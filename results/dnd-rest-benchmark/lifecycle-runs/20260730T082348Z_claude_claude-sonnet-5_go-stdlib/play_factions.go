package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playReputationEntry is an immutable history record of one reputation change
// for a character with a faction.
type playReputationEntry struct {
	FactionID   string `json:"faction_id"`
	CharacterID string `json:"character_id"`
	Reputation  int    `json:"reputation"`
	Delta       int    `json:"delta"`
	Reason      string `json:"reason"`
}

// playFaction is a DM-managed campaign faction record, tracking bounded
// reputation totals and an append-only history per character.
type playFaction struct {
	FactionID   string
	Name        string
	Reputations map[string]int
	History     []*playReputationEntry
}

func playFactionResponse(f *playFaction) map[string]interface{} {
	return map[string]interface{}{
		"faction_id": f.FactionID,
		"name":       f.Name,
	}
}

const (
	factionReputationMin      = -100
	factionReputationMax      = 100
	factionReputationDeltaMin = -25
	factionReputationDeltaMax = 25
)

func clampFactionReputation(v int) int {
	if v < factionReputationMin {
		return factionReputationMin
	}
	if v > factionReputationMax {
		return factionReputationMax
	}
	return v
}

// handlePlayCampaignFactionSub routes the "factions" and "factions/..."
// sub-paths of a play campaign. It returns false if rest does not name a
// faction path, so the caller can fall through to its own routing.
func handlePlayCampaignFactionSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "factions" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreatePlayFaction(w, r, campaignID)
		return true
	}
	if !strings.HasPrefix(rest, "factions/") {
		return false
	}
	factionRest := strings.TrimPrefix(rest, "factions/")

	if factionID, ok := strings.CutSuffix(factionRest, "/reputation"); ok && factionID != "" {
		switch r.Method {
		case http.MethodPost:
			handleCreateFactionReputation(w, r, campaignID, factionID)
		case http.MethodGet:
			handleGetFactionReputation(w, r, campaignID, factionID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	return false
}

// handleCreatePlayFaction lets the campaign dm create a new faction record.
// Only the dm may call this; faction_id and name must both be nonempty
// strings. Duplicate faction ids return 409.
func handleCreatePlayFaction(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		FactionID string `json:"faction_id"`
		Name      string `json:"name"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.FactionID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "faction_id and name are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create factions")
		return
	}
	if c.Factions == nil {
		c.Factions = make(map[string]*playFaction)
	}
	if _, exists := c.Factions[req.FactionID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "faction id already exists")
		return
	}

	f := &playFaction{
		FactionID:   req.FactionID,
		Name:        req.Name,
		Reputations: make(map[string]int),
	}
	c.Factions[req.FactionID] = f
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playFactionResponse(f))
}

// handleCreateFactionReputation lets the campaign dm record a reputation
// change for a campaign member character with a faction. Only the dm may
// call this; unknown factions return 404, and character_id must identify a
// campaign member character. delta must be a nonzero integer in [-25,25] and
// reason must be a nonempty string. The stored total is bounded to
// [-100,100] and each accepted change appends an immutable history record.
func handleCreateFactionReputation(w http.ResponseWriter, r *http.Request, campaignID, factionID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		CharacterID string `json:"character_id"`
		Delta       *int   `json:"delta"`
		Reason      string `json:"reason"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CharacterID == "" || req.Reason == "" || req.Delta == nil ||
		*req.Delta == 0 || *req.Delta < factionReputationDeltaMin || *req.Delta > factionReputationDeltaMax {
		writeError(w, http.StatusBadRequest, "character_id, a nonzero delta in [-25,25], and reason are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may change reputation")
		return
	}
	f := c.Factions[factionID]
	if f == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}
	if findPlayMemberByCharacterID(c, req.CharacterID) == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "character_id must identify a campaign member character")
		return
	}

	newTotal := clampFactionReputation(f.Reputations[req.CharacterID] + *req.Delta)
	f.Reputations[req.CharacterID] = newTotal

	entry := &playReputationEntry{
		FactionID:   factionID,
		CharacterID: req.CharacterID,
		Reputation:  newTotal,
		Delta:       *req.Delta,
		Reason:      req.Reason,
	}
	f.History = append(f.History, entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, entry)
}

// handleGetFactionReputation returns a faction's reputation history. Any
// authenticated campaign member may call this; unknown factions return 404.
// The dm sees every history entry in insertion order, while a player sees
// only entries for their own campaign character.
func handleGetFactionReputation(w http.ResponseWriter, r *http.Request, campaignID, factionID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view reputation")
		return
	}
	f := c.Factions[factionID]
	if f == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}

	var ownCharacterID string
	if c.Owner != username {
		for _, m := range c.Members {
			if m.Username == username {
				ownCharacterID = m.CharacterID
				break
			}
		}
	}

	entries := make([]*playReputationEntry, 0, len(f.History))
	for _, e := range f.History {
		if c.Owner == username || e.CharacterID == ownCharacterID {
			entries = append(entries, e)
		}
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"faction_id": factionID,
		"entries":    entries,
	})
}

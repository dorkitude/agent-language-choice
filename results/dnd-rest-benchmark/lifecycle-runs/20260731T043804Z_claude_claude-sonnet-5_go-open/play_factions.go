package main

import (
	"net/http"
	"sync"
)

const (
	minReputationDelta = -25
	maxReputationDelta = 25
	minReputationTotal = -100
	maxReputationTotal = 100
)

// playFaction is a DM-created campaign faction.
type playFaction struct {
	CampaignID string `json:"-"`
	FactionID  string `json:"faction_id"`
	Name       string `json:"name"`
}

// campaignFactionsMu guards campaignFactions, the in-memory index mirroring
// the play_factions table. Keyed by campaign id, then faction id.
var (
	campaignFactionsMu sync.Mutex
	campaignFactions   = map[string]map[string]*playFaction{}
)

// playReputationEntry is one immutable reputation change record for a
// faction/character pair.
type playReputationEntry struct {
	CampaignID  string `json:"-"`
	FactionID   string `json:"faction_id"`
	CharacterID string `json:"character_id"`
	Reputation  int    `json:"reputation"`
	Delta       int    `json:"delta"`
	Reason      string `json:"reason"`
}

// campaignReputationMu guards campaignReputation, the in-memory index
// mirroring the play_reputation table. Keyed by campaign id, then faction
// id, holding entries in insertion order.
var (
	campaignReputationMu sync.Mutex
	campaignReputation   = map[string]map[string][]*playReputationEntry{}
)

type createPlayFactionRequest struct {
	FactionID string `json:"faction_id"`
	Name      string `json:"name"`
}

// createPlayFactionHandler lets the campaign's owning dm create a new faction.
func createPlayFactionHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createPlayFactionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.FactionID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "faction_id and name are required")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may create factions")
		return
	}

	campaignFactionsMu.Lock()
	defer campaignFactionsMu.Unlock()

	if campaignFactions[campaignID] != nil {
		if _, exists := campaignFactions[campaignID][req.FactionID]; exists {
			writeError(w, http.StatusConflict, "faction_id already exists")
			return
		}
	}

	rec := &playFaction{
		CampaignID: campaignID,
		FactionID:  req.FactionID,
		Name:       req.Name,
	}
	if err := saveFactionToDB(rec); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save faction")
		return
	}
	if campaignFactions[campaignID] == nil {
		campaignFactions[campaignID] = map[string]*playFaction{}
	}
	campaignFactions[campaignID][req.FactionID] = rec

	writeJSON(w, http.StatusCreated, map[string]any{
		"faction_id": rec.FactionID,
		"name":       rec.Name,
	})
}

type createReputationRequest struct {
	CharacterID string `json:"character_id"`
	Delta       int    `json:"delta"`
	Reason      string `json:"reason"`
}

// createReputationHandler lets the campaign's owning dm apply a bounded
// reputation change for a character with a faction, storing an immutable
// history record.
func createReputationHandler(w http.ResponseWriter, r *http.Request, campaignID, factionID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createReputationRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may change reputation")
		return
	}

	campaignFactionsMu.Lock()
	defer campaignFactionsMu.Unlock()

	if campaignFactions[campaignID] == nil {
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}
	if _, exists := campaignFactions[campaignID][factionID]; !exists {
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}

	if req.Delta == 0 || req.Delta < minReputationDelta || req.Delta > maxReputationDelta {
		writeError(w, http.StatusBadRequest, "delta must be a nonzero integer in [-25,25]")
		return
	}
	if req.Reason == "" {
		writeError(w, http.StatusBadRequest, "reason is required")
		return
	}

	playMembersMu.Lock()
	_, exists := findMemberByCharacterID(campaignID, req.CharacterID)
	playMembersMu.Unlock()
	if !exists {
		writeError(w, http.StatusBadRequest, "character_id must identify a campaign member character")
		return
	}

	campaignReputationMu.Lock()
	defer campaignReputationMu.Unlock()

	current := currentReputation(campaignID, factionID, req.CharacterID)
	updated := current + req.Delta
	if updated < minReputationTotal {
		updated = minReputationTotal
	}
	if updated > maxReputationTotal {
		updated = maxReputationTotal
	}

	entry := &playReputationEntry{
		CampaignID:  campaignID,
		FactionID:   factionID,
		CharacterID: req.CharacterID,
		Reputation:  updated,
		Delta:       req.Delta,
		Reason:      req.Reason,
	}
	entryID := len(campaignReputation[campaignID][factionID]) + 1
	if err := saveReputationEntryToDB(entry, entryID); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save reputation entry")
		return
	}
	if campaignReputation[campaignID] == nil {
		campaignReputation[campaignID] = map[string][]*playReputationEntry{}
	}
	campaignReputation[campaignID][factionID] = append(campaignReputation[campaignID][factionID], entry)

	writeJSON(w, http.StatusCreated, map[string]any{
		"faction_id":   entry.FactionID,
		"character_id": entry.CharacterID,
		"reputation":   entry.Reputation,
		"delta":        entry.Delta,
		"reason":       entry.Reason,
	})
}

// currentReputation returns charID's current total reputation with
// factionID within campaignID. Callers must hold campaignReputationMu.
func currentReputation(campaignID, factionID, charID string) int {
	entries := campaignReputation[campaignID][factionID]
	for i := len(entries) - 1; i >= 0; i-- {
		if entries[i].CharacterID == charID {
			return entries[i].Reputation
		}
	}
	return 0
}

// getReputationHandler returns a faction's reputation history. The dm sees
// every entry; players see only entries for their own campaign character.
func getReputationHandler(w http.ResponseWriter, r *http.Request, campaignID, factionID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	campaignFactionsMu.Lock()
	if campaignFactions[campaignID] == nil {
		campaignFactionsMu.Unlock()
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}
	if _, exists := campaignFactions[campaignID][factionID]; !exists {
		campaignFactionsMu.Unlock()
		writeError(w, http.StatusNotFound, "faction not found")
		return
	}
	campaignFactionsMu.Unlock()

	var ownCharacterID string
	if !isDM {
		playMembersMu.Lock()
		if m, exists := playMembers[campaignID][actor.Username]; exists {
			ownCharacterID = m.CharacterID
		}
		playMembersMu.Unlock()
	}

	campaignReputationMu.Lock()
	defer campaignReputationMu.Unlock()

	entries := campaignReputation[campaignID][factionID]
	out := make([]map[string]any, 0, len(entries))
	for _, e := range entries {
		if !isDM && e.CharacterID != ownCharacterID {
			continue
		}
		out = append(out, map[string]any{
			"faction_id":   e.FactionID,
			"character_id": e.CharacterID,
			"reputation":   e.Reputation,
			"delta":        e.Delta,
			"reason":       e.Reason,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"faction_id": factionID,
		"entries":    out,
	})
}

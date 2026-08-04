package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayFactionHandler creates a new DM-managed faction for a play
// campaign. Only the campaign owner (DM) may create factions. faction_id and
// name are required nonempty strings. Duplicate faction_id values within the
// same campaign return 409.
func createPlayFactionHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create factions")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create factions")
		return
	}

	var req playFactionCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.FactionID) == "" {
		badRequest(w, "faction_id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}

	if err := dbCreatePlayFaction(id, req.FactionID, req.Name); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "faction_id already exists")
			return
		}
		log.Printf("create play faction: %v", err)
		badRequest(w, "failed to create faction")
		return
	}

	writeJSON(w, http.StatusCreated, playFaction{
		FactionID: req.FactionID,
		Name:      req.Name,
	})
}

// createPlayReputationHandler records a bounded reputation change for a
// campaign member character. Only the campaign owner (DM) may change
// reputation. Unknown factions return 404. character_id must identify a
// campaign member. delta must be a nonzero integer in [-25, 25]. reason is a
// required nonempty string. The stored total for each faction/character pair
// is clamped to [-100, 100].
func createPlayReputationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can change reputation")
		return
	}

	id := r.PathValue("id")
	factionID := r.PathValue("faction_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can change reputation")
		return
	}

	faction, err := dbGetPlayFaction(id, factionID)
	if err != nil {
		log.Printf("get play faction: %v", err)
		badRequest(w, "failed to read faction")
		return
	}
	if faction == nil {
		notFound(w, "faction not found")
		return
	}

	var req reputationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.CharacterID) == "" {
		badRequest(w, "character_id is required")
		return
	}
	if strings.TrimSpace(req.Reason) == "" {
		badRequest(w, "reason is required")
		return
	}
	if req.Delta == 0 || req.Delta < -25 || req.Delta > 25 {
		badRequest(w, "delta must be a nonzero integer between -25 and 25")
		return
	}

	member, err := dbGetPlayMembershipByCharacterID(id, req.CharacterID)
	if err != nil {
		log.Printf("get membership by character: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if member == nil {
		badRequest(w, "character_id must identify a campaign member")
		return
	}

	reputation, err := dbCreatePlayReputationChange(id, factionID, req.CharacterID, req.Delta, req.Reason)
	if err != nil {
		log.Printf("create reputation change: %v", err)
		badRequest(w, "failed to record reputation change")
		return
	}

	writeJSON(w, http.StatusCreated, reputationEntry{
		FactionID:   factionID,
		CharacterID: req.CharacterID,
		Reputation:  reputation,
		Delta:       req.Delta,
		Reason:      req.Reason,
	})
}

// getPlayReputationHandler reads a faction's reputation history. The DM sees
// all entries in insertion order. Players see only entries for their own
// campaign character.
func getPlayReputationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	factionID := r.PathValue("faction_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	faction, err := dbGetPlayFaction(id, factionID)
	if err != nil {
		log.Printf("get play faction: %v", err)
		badRequest(w, "failed to read faction")
		return
	}
	if faction == nil {
		notFound(w, "faction not found")
		return
	}

	var characterID string
	if p.Owner != u.Username {
		member, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err != nil {
			log.Printf("get membership: %v", err)
			badRequest(w, "failed to read membership")
			return
		}
		if member == nil {
			forbidden(w, "not a campaign member")
			return
		}
		characterID = member.CharacterID
	}

	entries, err := dbGetPlayReputationHistory(id, factionID, characterID)
	if err != nil {
		log.Printf("get reputation history: %v", err)
		badRequest(w, "failed to read reputation history")
		return
	}
	if entries == nil {
		entries = []reputationEntry{}
	}

	writeJSON(w, http.StatusOK, reputationResponse{
		FactionID: factionID,
		Entries:   entries,
	})
}

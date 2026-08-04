package main

import (
	"net/http"
	"sync"
)

// playConcentration tracks a character's currently active concentration
// spell, if any.
type playConcentration struct {
	CampaignID     string `json:"-"`
	CharacterID    string `json:"-"`
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	RemainingTurns int    `json:"remaining_turns"`
}

// concentrationMu guards concentrations, the in-memory index mirroring the
// play_concentration table. It is keyed by campaign id, then character id.
// A missing entry means no concentration is active.
var (
	concentrationMu sync.Mutex
	concentrations  = map[string]map[string]*playConcentration{}
)

type setConcentrationRequest struct {
	SpellID       string `json:"spell_id"`
	Target        string `json:"target"`
	DurationTurns int    `json:"duration_turns"`
}

func concentrationResponse(charID string, c *playConcentration) map[string]any {
	if c == nil {
		return map[string]any{"character_id": charID, "concentration": nil}
	}
	return map[string]any{
		"character_id": charID,
		"concentration": map[string]any{
			"spell_id":        c.SpellID,
			"target":          c.Target,
			"remaining_turns": c.RemainingTurns,
		},
	}
}

// setConcentrationHandler lets the character's owner start (or replace)
// concentration on a currently prepared spell, provided the character is a
// spellcaster and the requested duration is positive.
func setConcentrationHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req setConcentrationRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may set concentration")
		return
	}
	if !spellcastingClasses[member.Class] {
		writeError(w, http.StatusBadRequest, "character is not a spellcaster")
		return
	}
	if req.DurationTurns < 1 {
		writeError(w, http.StatusBadRequest, "duration_turns must be positive")
		return
	}

	if _, known := spellCompendium[req.SpellID]; !known {
		writeError(w, http.StatusBadRequest, "spell is not currently prepared")
		return
	}

	preparedSpellsMu.Lock()
	prepared := false
	if p, ok := preparedSpells[campaignID][charID]; ok {
		for _, id := range p.SpellIDs {
			if id == req.SpellID {
				prepared = true
				break
			}
		}
	}
	preparedSpellsMu.Unlock()
	if !prepared {
		writeError(w, http.StatusBadRequest, "spell is not currently prepared")
		return
	}

	concentrationMu.Lock()
	defer concentrationMu.Unlock()

	c := &playConcentration{
		CampaignID:     campaignID,
		CharacterID:    charID,
		SpellID:        req.SpellID,
		Target:         req.Target,
		RemainingTurns: req.DurationTurns,
	}
	if err := saveConcentrationToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save concentration")
		return
	}
	if concentrations[campaignID] == nil {
		concentrations[campaignID] = map[string]*playConcentration{}
	}
	concentrations[campaignID][charID] = c

	writeJSON(w, http.StatusOK, concentrationResponse(charID, c))
}

// getConcentrationHandler returns a character's active concentration state.
// Any campaign member (owner or player) may call this.
func getConcentrationHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the owner or a member of this campaign")
		return
	}

	playMembersMu.Lock()
	if _, exists := findMemberByCharacterID(campaignID, charID); !exists {
		playMembersMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	playMembersMu.Unlock()

	concentrationMu.Lock()
	defer concentrationMu.Unlock()

	writeJSON(w, http.StatusOK, concentrationResponse(charID, concentrations[campaignID][charID]))
}

// advanceConcentrationTurnHandler decrements the active concentration's
// remaining turns by one, clearing it when the count reaches zero. Any
// campaign member (owner or player) may call this.
func advanceConcentrationTurnHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
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
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the owner or a member of this campaign")
		return
	}

	playMembersMu.Lock()
	if _, exists := findMemberByCharacterID(campaignID, charID); !exists {
		playMembersMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	playMembersMu.Unlock()

	concentrationMu.Lock()
	defer concentrationMu.Unlock()

	active := concentrations[campaignID][charID]
	if active != nil {
		active.RemainingTurns--
		if active.RemainingTurns <= 0 {
			if err := deleteConcentrationFromDB(campaignID, charID); err != nil {
				writeError(w, http.StatusInternalServerError, "failed to advance concentration")
				return
			}
			delete(concentrations[campaignID], charID)
			active = nil
		} else {
			if err := saveConcentrationToDB(active); err != nil {
				writeError(w, http.StatusInternalServerError, "failed to advance concentration")
				return
			}
		}
	}

	writeJSON(w, http.StatusOK, concentrationResponse(charID, active))
}

// clearConcentrationHandler lets the character's owner clear any active
// concentration.
func clearConcentrationHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodDelete) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may clear concentration")
		return
	}

	concentrationMu.Lock()
	defer concentrationMu.Unlock()

	if err := deleteConcentrationFromDB(campaignID, charID); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to clear concentration")
		return
	}
	if concentrations[campaignID] != nil {
		delete(concentrations[campaignID], charID)
	}

	writeJSON(w, http.StatusOK, concentrationResponse(charID, nil))
}

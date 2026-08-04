package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// setCharacterConcentrationHandler starts or replaces a character's active
// concentration. Only the character owner may call it. The spell must be
// known, currently prepared, and the character must be a spellcaster; the
// duration must be positive.
func setCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may set concentration")
		return
	}

	var req concentrationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.SpellID) == "" {
		badRequest(w, "spell_id is required")
		return
	}
	if req.DurationTurns < 1 {
		badRequest(w, "duration_turns must be at least one")
		return
	}

	if !canCastSpells(m.Class) {
		badRequest(w, "character is not a spellcaster")
		return
	}

	known, err := dbGetCharacterSpells(id, charID)
	if err != nil {
		log.Printf("get character spells: %v", err)
		badRequest(w, "failed to read spellbook")
		return
	}
	spellKnown := false
	for _, s := range known {
		if s.SpellID == req.SpellID {
			spellKnown = true
			break
		}
	}
	if !spellKnown {
		badRequest(w, "unknown spell")
		return
	}

	prepared, err := dbGetCharacterPreparedSpells(id, charID)
	if err != nil {
		log.Printf("get prepared spells: %v", err)
		badRequest(w, "failed to read prepared spells")
		return
	}
	preparedSet := make(map[string]struct{}, len(prepared))
	for _, spellID := range prepared {
		preparedSet[spellID] = struct{}{}
	}
	if _, ok := preparedSet[req.SpellID]; !ok {
		badRequest(w, "spell not prepared")
		return
	}

	c := &concentration{
		SpellID:        req.SpellID,
		Target:         req.Target,
		RemainingTurns: req.DurationTurns,
	}
	if err := dbSetCharacterConcentration(id, charID, c); err != nil {
		log.Printf("set concentration: %v", err)
		badRequest(w, "failed to set concentration")
		return
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID:   charID,
		Concentration: c,
	})
}

// getCharacterConcentrationHandler returns the active concentration for a
// campaign character. Any campaign member may read it.
func getCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	c, err := dbGetCharacterConcentration(id, charID)
	if err != nil {
		log.Printf("get concentration: %v", err)
		badRequest(w, "failed to read concentration")
		return
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID:   charID,
		Concentration: c,
	})
}

// advanceCharacterConcentrationHandler decrements the active concentration's
// remaining turns by one and clears concentration when the count reaches zero.
// Any campaign member may call it.
func advanceCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	c, err := dbAdvanceCharacterConcentration(id, charID)
	if err != nil {
		log.Printf("advance concentration: %v", err)
		badRequest(w, "failed to advance concentration")
		return
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID:   charID,
		Concentration: c,
	})
}

// clearCharacterConcentrationHandler removes a character's active
// concentration. Only the character owner may call it.
func clearCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character membership: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may clear concentration")
		return
	}

	if err := dbClearCharacterConcentration(id, charID); err != nil {
		log.Printf("clear concentration: %v", err)
		badRequest(w, "failed to clear concentration")
		return
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID:   charID,
		Concentration: nil,
	})
}

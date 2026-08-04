package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// addCharacterSpellHandler records a new spell for a campaign character. Only
// the character's owner may call it. The spell is rejected if the character's
// class cannot learn it, or if the character already knows the spell.
func addCharacterSpellHandler(w http.ResponseWriter, r *http.Request) {
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

	var req spellCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.SpellID) == "" {
		badRequest(w, "spell_id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if req.Level < 0 {
		badRequest(w, "level must be non-negative")
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
		forbidden(w, "only the character owner may add spells")
		return
	}

	if !canLearnSpell(m.Class) {
		badRequest(w, "invalid class/spell combination")
		return
	}

	s := spell{SpellID: req.SpellID, Name: req.Name, Level: req.Level}
	if err := dbCreateCharacterSpell(id, charID, &s); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "spell already known")
			return
		}
		log.Printf("create character spell: %v", err)
		badRequest(w, "failed to add spell")
		return
	}

	writeJSON(w, http.StatusCreated, s)
}

// getCharacterSpellbookHandler returns the spellbook for a campaign character.
// Any member of the campaign (including the owner) may read it.
func getCharacterSpellbookHandler(w http.ResponseWriter, r *http.Request) {
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

	spells, err := dbGetCharacterSpells(id, charID)
	if err != nil {
		log.Printf("get character spells: %v", err)
		badRequest(w, "failed to read spellbook")
		return
	}

	writeJSON(w, http.StatusOK, spellbook{Spells: spells})
}

// prepareCharacterSpellsHandler sets a character's prepared spells. Only the
// character owner may call it. The character must be a spellcasting class,
// every spell must be known, and the count must not exceed the class's
// per-level maximum (for a wizard this equals their level).
func prepareCharacterSpellsHandler(w http.ResponseWriter, r *http.Request) {
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
		forbidden(w, "only the character owner may prepare spells")
		return
	}

	if !canPrepareSpells(m.Class) {
		badRequest(w, "invalid class/spell combination")
		return
	}

	var req preparedSpellsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.SpellIDs == nil {
		req.SpellIDs = []string{}
	}

	max := maxPreparedSpells(m.Class, m.Level)
	if len(req.SpellIDs) > max {
		badRequest(w, "too many prepared spells")
		return
	}

	known, err := dbGetCharacterSpells(id, charID)
	if err != nil {
		log.Printf("get character spells: %v", err)
		badRequest(w, "failed to read spellbook")
		return
	}
	knownSet := make(map[string]struct{}, len(known))
	for _, s := range known {
		knownSet[s.SpellID] = struct{}{}
	}
	for _, spellID := range req.SpellIDs {
		if _, ok := knownSet[spellID]; !ok {
			badRequest(w, "unknown spell")
			return
		}
	}

	if err := dbSetCharacterPreparedSpells(id, charID, req.SpellIDs); err != nil {
		if isForeignKeyViolation(err) || isUniqueViolation(err) {
			badRequest(w, "unknown spell")
			return
		}
		log.Printf("set prepared spells: %v", err)
		badRequest(w, "failed to prepare spells")
		return
	}

	writeJSON(w, http.StatusOK, preparedSpellsResponse{
		CharacterID:    charID,
		PreparedSpells: req.SpellIDs,
		MaxPrepared:    max,
	})
}

// getCharacterPreparedSpellsHandler returns a character's prepared spells. Any
// campaign member may read it.
func getCharacterPreparedSpellsHandler(w http.ResponseWriter, r *http.Request) {
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

	prepared, err := dbGetCharacterPreparedSpells(id, charID)
	if err != nil {
		log.Printf("get prepared spells: %v", err)
		badRequest(w, "failed to read prepared spells")
		return
	}

	max := maxPreparedSpells(m.Class, m.Level)

	writeJSON(w, http.StatusOK, preparedSpellsResponse{
		CharacterID:    charID,
		PreparedSpells: prepared,
		MaxPrepared:    max,
	})
}

// castSpellHandler records a spell cast for a campaign character. Only the
// character owner may call it. The spell must be known, prepared, and the
// character must have a remaining slot of the spell's level.
func castSpellHandler(w http.ResponseWriter, r *http.Request) {
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
		forbidden(w, "only the character owner may cast spells")
		return
	}

	if !canCastSpells(m.Class) {
		badRequest(w, "invalid class/spell combination")
		return
	}

	var req castSpellRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.SpellID) == "" {
		badRequest(w, "spell_id is required")
		return
	}

	known, err := dbGetCharacterSpells(id, charID)
	if err != nil {
		log.Printf("get character spells: %v", err)
		badRequest(w, "failed to read spellbook")
		return
	}
	var spellLevel int
	spellFound := false
	for _, s := range known {
		if s.SpellID == req.SpellID {
			spellLevel = s.Level
			spellFound = true
			break
		}
	}
	if !spellFound {
		badRequest(w, "spell not prepared")
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

	cast, ok, err := dbCastSpell(id, charID, req.SpellID, req.Target, spellLevel)
	if err != nil {
		log.Printf("cast spell: %v", err)
		badRequest(w, "failed to cast spell")
		return
	}
	if !ok {
		conflict(w, "no remaining spell slots")
		return
	}

	writeJSON(w, http.StatusCreated, cast)
}

// getCharacterCastsHandler returns a character's spell cast history. Any
// campaign member may read it.
func getCharacterCastsHandler(w http.ResponseWriter, r *http.Request) {
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

	casts, err := dbGetCharacterSpellCasts(id, charID)
	if err != nil {
		log.Printf("get character casts: %v", err)
		badRequest(w, "failed to read cast history")
		return
	}

	writeJSON(w, http.StatusOK, castHistoryResponse{Casts: casts})
}

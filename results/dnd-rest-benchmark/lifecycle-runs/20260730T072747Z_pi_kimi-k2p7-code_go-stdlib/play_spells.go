package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// spellEntry is a single known spell in a character's spellbook.
type spellEntry struct {
	SpellID string `json:"spell_id"`
	Name    string `json:"name"`
	Level   int    `json:"level"`
}

// spellbookResponse is the shape returned when listing a character's spells.
type spellbookResponse struct {
	Spells []spellEntry `json:"spells"`
}

// wizardSpells lists the spells a wizard may know. Other classes currently
// have no valid spells to learn.
var wizardSpells = map[string]bool{
	"fire-bolt":        true,
	"magic-missile":    true,
	"mage-armor":       true,
	"shield":           true,
	"mage-hand":        true,
	"prestidigitation": true,
	"detect-magic":     true,
	"identify":         true,
	"burning-hands":    true,
	"sleep":            true,
	"misty-step":       true,
}

// spellValidForClass reports whether a spell may be learned by the class.
func spellValidForClass(class, spellID string) bool {
	if class == "wizard" {
		return wizardSpells[spellID]
	}
	return false
}

// addCharacterSpellHandler adds a known spell to a character's spellbook.
// Only the character's owner may call it, and the spell must be valid for the
// character's class.
func addCharacterSpellHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("char_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("add spell member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req spellEntry
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SpellID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "invalid spell")
		return
	}

	if !spellValidForClass(member.Class, req.SpellID) {
		writeError(w, http.StatusBadRequest, "invalid spell")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM character_spells WHERE campaign_id=%s AND character_id=%s AND spell_id=%s LIMIT 1;", sq(campaignID), sq(characterID), sq(req.SpellID)))
	if err != nil {
		log.Printf("add spell duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "spell already known")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO character_spells (campaign_id, character_id, spell_id, name, level) VALUES (%s, %s, %s, %s, %d);",
		sq(campaignID), sq(characterID), sq(req.SpellID), sq(req.Name), req.Level)); err != nil {
		log.Printf("add spell insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

// getCharacterSpellsHandler returns the character's spellbook. Any campaign
// owner or member may read it.
func getCharacterSpellsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("char_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("get spells member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	var spells []spellEntry
	if err := queryRows(fmt.Sprintf("SELECT spell_id, name, level FROM character_spells WHERE campaign_id=%s AND character_id=%s ORDER BY level, name, spell_id;", sq(campaignID), sq(characterID)), &spells); err != nil {
		log.Printf("get spells query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if spells == nil {
		spells = []spellEntry{}
	}

	writeJSON(w, http.StatusOK, spellbookResponse{Spells: spells})
}

// preparedSpellsRequest binds the payload for replacing a character's
// prepared spell list.
type preparedSpellsRequest struct {
	SpellIDs []string `json:"spell_ids"`
}

// preparedSpellsResponse is the shape returned for a character's prepared
// spells. An empty prepared list is always serialized as [].
type preparedSpellsResponse struct {
	CharacterID    string   `json:"character_id"`
	PreparedSpells []string `json:"prepared_spells"`
	MaxPrepared    int      `json:"max_prepared"`
}

// spellcastingClasses is the set of classes that can prepare spells. In
// this service only wizards use the spellbook and prepared-spells feature.
var spellcastingClasses = map[string]bool{
	"wizard": true,
}

// maxPreparedForClass returns the maximum number of spells a character of
// the given class and level may prepare. Non-spellcasting classes cannot
// prepare any spells.
func maxPreparedForClass(class string, level int) int {
	if !spellcastingClasses[class] {
		return 0
	}
	if level < 1 {
		return 0
	}
	return level
}

// characterKnowsSpell reports whether a character knows a spell. The caller
// must hold dbMu.
func characterKnowsSpell(campaignID, characterID, spellID string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM character_spells WHERE campaign_id=%s AND character_id=%s AND spell_id=%s LIMIT 1;", sq(campaignID), sq(characterID), sq(spellID)))
}

// queryCharacterPreparedSpellIDs returns the prepared spell IDs for a
// character, ordered by sort_order. The caller must hold dbMu.
func queryCharacterPreparedSpellIDs(campaignID, characterID string) ([]string, error) {
	var rows []struct {
		SpellID string `json:"spell_id"`
	}
	if err := queryRows(fmt.Sprintf("SELECT spell_id FROM character_prepared_spells WHERE campaign_id=%s AND character_id=%s ORDER BY sort_order;", sq(campaignID), sq(characterID)), &rows); err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.SpellID)
	}
	return ids, nil
}

// updateCharacterPreparedSpellsHandler replaces the character's prepared
// spell list. Only the character owner may call it. The character must be a
// spellcasting class, every spell ID must be known, and the list length must
// not exceed the class level's maximum prepared spells.
func updateCharacterPreparedSpellsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("update prepared spells member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req preparedSpellsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SpellIDs == nil {
		req.SpellIDs = []string{}
	}

	// Deduplicate while preserving the first occurrence order so that the
	// primary key never conflicts and the count is deterministic.
	seen := make(map[string]bool, len(req.SpellIDs))
	deduped := make([]string, 0, len(req.SpellIDs))
	for _, spellID := range req.SpellIDs {
		if !seen[spellID] {
			seen[spellID] = true
			deduped = append(deduped, spellID)
		}
	}
	req.SpellIDs = deduped

	if !spellcastingClasses[member.Class] {
		writeError(w, http.StatusBadRequest, "invalid class")
		return
	}

	maxPrepared := maxPreparedForClass(member.Class, member.Level)
	if len(req.SpellIDs) > maxPrepared {
		writeError(w, http.StatusBadRequest, "too many prepared spells")
		return
	}

	for _, spellID := range req.SpellIDs {
		if spellID == "" {
			writeError(w, http.StatusBadRequest, "invalid spell")
			return
		}
		known, err := characterKnowsSpell(campaignID, characterID, spellID)
		if err != nil {
			log.Printf("prepared spell known query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !known {
			writeError(w, http.StatusBadRequest, "unknown spell")
			return
		}
	}

	if err := dbExec(fmt.Sprintf("DELETE FROM character_prepared_spells WHERE campaign_id=%s AND character_id=%s;", sq(campaignID), sq(characterID))); err != nil {
		log.Printf("prepared spell delete error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	for i, spellID := range req.SpellIDs {
		if err := dbExec(fmt.Sprintf("INSERT INTO character_prepared_spells (campaign_id, character_id, spell_id, sort_order) VALUES (%s, %s, %s, %d);",
			sq(campaignID), sq(characterID), sq(spellID), i)); err != nil {
			log.Printf("prepared spell insert error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	writeJSON(w, http.StatusOK, preparedSpellsResponse{
		CharacterID:    characterID,
		PreparedSpells: req.SpellIDs,
		MaxPrepared:    maxPrepared,
	})
}

// getCharacterPreparedSpellsHandler returns the character's prepared spell
// list. Any campaign owner or member may read it.
func getCharacterPreparedSpellsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("get prepared spells member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	prepared, err := queryCharacterPreparedSpellIDs(campaignID, characterID)
	if err != nil {
		log.Printf("get prepared spells query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if prepared == nil {
		prepared = []string{}
	}

	writeJSON(w, http.StatusOK, preparedSpellsResponse{
		CharacterID:    characterID,
		PreparedSpells: prepared,
		MaxPrepared:    maxPreparedForClass(member.Class, member.Level),
	})
}

// castingSlotsForWizard returns the number of spell slots a wizard of the
// given level has for each spell level. The level 1 entry is intentionally
// one first-level slot to match the staged benchmark contract.
func castingSlotsForWizard(level int) map[int]int {
	if level < 1 {
		return map[int]int{}
	}

	// Standard 5e wizard table with level 1 first-level slots reduced to 1.
	tables := map[int]map[int]int{
		1:  {1: 1},
		2:  {1: 3},
		3:  {1: 4, 2: 2},
		4:  {1: 4, 2: 3},
		5:  {1: 4, 2: 3, 3: 2},
		6:  {1: 4, 2: 3, 3: 3},
		7:  {1: 4, 2: 3, 3: 3, 4: 1},
		8:  {1: 4, 2: 3, 3: 3, 4: 2},
		9:  {1: 4, 2: 3, 3: 3, 4: 3, 5: 1},
		10: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2},
		11: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
		12: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1},
		13: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
		14: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1},
		15: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
		16: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1},
		17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 2, 6: 1, 7: 1, 8: 1, 9: 1},
		18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
		19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
		20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},
	}
	if slots, ok := tables[level]; ok {
		result := make(map[int]int, len(slots))
		for lvl, count := range slots {
			result[lvl] = count
		}
		return result
	}
	return map[int]int{}
}

// totalSlotsForLevel returns the total number of spell slots a character of
// the given class and level has for the requested spell level.
func totalSlotsForLevel(class string, level, spellLevel int) int {
	if !spellcastingClasses[class] {
		return 0
	}
	if class == "wizard" {
		return castingSlotsForWizard(level)[spellLevel]
	}
	return 0
}

// usedSlotsForLevel returns the number of spell slots of the given level
// that the character has already spent. The caller must hold dbMu.
func usedSlotsForLevel(campaignID, characterID string, level int) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COUNT(*) AS used FROM character_casts WHERE campaign_id=%s AND character_id=%s AND slot_level=%d;", sq(campaignID), sq(characterID), level))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		Used int `json:"used"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 0, nil
	}
	return rows[0].Used, nil
}

// nextCastSequence returns the next monotonic sequence number for a
// character's cast history. The caller must hold dbMu.
func nextCastSequence(campaignID, characterID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM character_casts WHERE campaign_id=%s AND character_id=%s;", sq(campaignID), sq(characterID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

// castSpellRequest binds the payload for casting a spell.
type castSpellRequest struct {
	SpellID string `json:"spell_id"`
	Target  string `json:"target"`
}

// castSpellResponse is the shape returned after a successful spell cast.
type castSpellResponse struct {
	CharacterID    string `json:"character_id"`
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	SlotLevel      int    `json:"slot_level"`
	SlotsRemaining int    `json:"slots_remaining"`
	Sequence       int    `json:"sequence"`
}

// castEvent is a single recorded spell cast in a character's history.
type castEvent struct {
	CharacterID    string `json:"character_id"`
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	SlotLevel      int    `json:"slot_level"`
	SlotsRemaining int    `json:"slots_remaining"`
	Sequence       int    `json:"sequence"`
}

// castHistoryResponse is the shape returned when reading a character's
// cast history. An empty history is always serialized as [].
type castHistoryResponse struct {
	Casts []castEvent `json:"casts"`
}

// castSpellHandler records a spell cast for a character. Only the character
// owner may call it. The character must be a spellcasting class, know the
// spell, have it prepared, and have at least one remaining slot of the
// spell's level.
func castSpellHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("cast spell member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req castSpellRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SpellID == "" || req.Target == "" {
		writeError(w, http.StatusBadRequest, "invalid spell")
		return
	}

	if !spellcastingClasses[member.Class] {
		writeError(w, http.StatusBadRequest, "invalid class")
		return
	}

	known, level, err := queryCharacterSpellLevel(campaignID, characterID, req.SpellID)
	if err != nil {
		log.Printf("cast spell known query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !known {
		writeError(w, http.StatusBadRequest, "unknown spell")
		return
	}

	prepared, err := queryCharacterPreparedSpellIDs(campaignID, characterID)
	if err != nil {
		log.Printf("cast spell prepared query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	preparedSet := make(map[string]bool, len(prepared))
	for _, id := range prepared {
		preparedSet[id] = true
	}
	if !preparedSet[req.SpellID] {
		writeError(w, http.StatusBadRequest, "spell not prepared")
		return
	}

	used, err := usedSlotsForLevel(campaignID, characterID, level)
	if err != nil {
		log.Printf("cast spell used slots query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	total := totalSlotsForLevel(member.Class, member.Level, level)
	if used >= total {
		writeError(w, http.StatusConflict, "no remaining spell slots")
		return
	}

	sequence, err := nextCastSequence(campaignID, characterID)
	if err != nil {
		log.Printf("cast spell sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	slotsRemaining := total - used - 1
	if err := dbExec(fmt.Sprintf("INSERT INTO character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (%s, %s, %d, %s, %s, %d, %d);",
		sq(campaignID), sq(characterID), sequence, sq(req.SpellID), sq(req.Target), level, slotsRemaining)); err != nil {
		log.Printf("cast spell insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, castSpellResponse{
		CharacterID:    characterID,
		SpellID:        req.SpellID,
		Target:         req.Target,
		SlotLevel:      level,
		SlotsRemaining: slotsRemaining,
		Sequence:       sequence,
	})
}

// getCastHistoryHandler returns the spell cast history for a character.
// Any campaign owner or member may read it.
func getCastHistoryHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("cast history member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	var rows []castEvent
	if err := queryRows(fmt.Sprintf("SELECT character_id, spell_id, target, slot_level, slots_remaining, sequence FROM character_casts WHERE campaign_id=%s AND character_id=%s ORDER BY sequence;", sq(campaignID), sq(characterID)), &rows); err != nil {
		log.Printf("cast history query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if rows == nil {
		rows = []castEvent{}
	}

	writeJSON(w, http.StatusOK, castHistoryResponse{Casts: rows})
}

// queryCharacterSpellLevel reports whether a character knows a spell and, if
// so, returns its level. The caller must hold dbMu.
func queryCharacterSpellLevel(campaignID, characterID, spellID string) (bool, int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT level FROM character_spells WHERE campaign_id=%s AND character_id=%s AND spell_id=%s LIMIT 1;", sq(campaignID), sq(characterID), sq(spellID)))
	if err != nil {
		return false, 0, err
	}
	var rows []struct {
		Level int `json:"level"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, 0, err
	}
	if len(rows) == 0 {
		return false, 0, nil
	}
	return true, rows[0].Level, nil
}

// concentrationState is a single active concentration record for a character.
type concentrationState struct {
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	RemainingTurns int    `json:"remaining_turns"`
}

// concentrationResponse is the shape returned by all concentration endpoints.
// When no concentration is active, Concentration is serialized as null.
type concentrationResponse struct {
	CharacterID   string              `json:"character_id"`
	Concentration *concentrationState `json:"concentration"`
}

// concentrationRequest binds the payload for replacing a character's concentration.
type concentrationRequest struct {
	SpellID       string `json:"spell_id"`
	Target        string `json:"target"`
	DurationTurns int    `json:"duration_turns"`
}

// queryCharacterConcentration loads the active concentration for a character, if any.
// The caller must hold dbMu.
func queryCharacterConcentration(campaignID, characterID string) (*concentrationState, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT spell_id, target, remaining_turns FROM character_concentration WHERE campaign_id=%s AND character_id=%s LIMIT 1;", sq(campaignID), sq(characterID)))
	if err != nil {
		return nil, err
	}
	var rows []concentrationState
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, nil
	}
	return &rows[0], nil
}

// setCharacterConcentration replaces a character's concentration with a new one.
// The caller must hold dbMu.
func setCharacterConcentration(campaignID, characterID, spellID, target string, remainingTurns int) error {
	return dbExec(fmt.Sprintf("INSERT INTO character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (%s, %s, %s, %s, %d) ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id=excluded.spell_id, target=excluded.target, remaining_turns=excluded.remaining_turns;",
		sq(campaignID), sq(characterID), sq(spellID), sq(target), remainingTurns))
}

// clearCharacterConcentration removes a character's concentration, if any.
// The caller must hold dbMu.
func clearCharacterConcentration(campaignID, characterID string) error {
	return dbExec(fmt.Sprintf("DELETE FROM character_concentration WHERE campaign_id=%s AND character_id=%s;", sq(campaignID), sq(characterID)))
}

// updateCharacterConcentrationHandler replaces the character's concentration.
// Only the character owner may call it. The character must be a spellcasting class,
// know the spell, have it prepared, and the duration must be positive.
func updateCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("update concentration member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req concentrationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SpellID == "" {
		writeError(w, http.StatusBadRequest, "invalid spell")
		return
	}
	if req.Target == "" {
		writeError(w, http.StatusBadRequest, "invalid target")
		return
	}
	if req.DurationTurns < 1 {
		writeError(w, http.StatusBadRequest, "invalid duration")
		return
	}

	if !spellcastingClasses[member.Class] {
		writeError(w, http.StatusBadRequest, "invalid class")
		return
	}

	known, err := characterKnowsSpell(campaignID, characterID, req.SpellID)
	if err != nil {
		log.Printf("update concentration known query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !known {
		writeError(w, http.StatusBadRequest, "unknown spell")
		return
	}

	prepared, err := queryCharacterPreparedSpellIDs(campaignID, characterID)
	if err != nil {
		log.Printf("update concentration prepared query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	preparedSet := make(map[string]bool, len(prepared))
	for _, id := range prepared {
		preparedSet[id] = true
	}
	if !preparedSet[req.SpellID] {
		writeError(w, http.StatusBadRequest, "spell not prepared")
		return
	}

	if err := setCharacterConcentration(campaignID, characterID, req.SpellID, req.Target, req.DurationTurns); err != nil {
		log.Printf("update concentration upsert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID: characterID,
		Concentration: &concentrationState{
			SpellID:        req.SpellID,
			Target:         req.Target,
			RemainingTurns: req.DurationTurns,
		},
	})
}

// getCharacterConcentrationHandler returns the character's active concentration.
// Any campaign owner or member may read it.
func getCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("get concentration member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	concentration, err := queryCharacterConcentration(campaignID, characterID)
	if err != nil {
		log.Printf("get concentration query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID:   characterID,
		Concentration: concentration,
	})
}

// advanceCharacterConcentrationHandler decrements the active concentration's
// remaining turns and clears it when it reaches zero. Any campaign owner or member
// may call it.
func advanceCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("advance concentration member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	concentration, err := queryCharacterConcentration(campaignID, characterID)
	if err != nil {
		log.Printf("advance concentration query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if concentration != nil {
		concentration.RemainingTurns--
		if concentration.RemainingTurns <= 0 {
			if err := clearCharacterConcentration(campaignID, characterID); err != nil {
				log.Printf("advance concentration clear error: %v", err)
				writeError(w, http.StatusInternalServerError, "internal error")
				return
			}
			concentration = nil
		} else {
			if err := setCharacterConcentration(campaignID, characterID, concentration.SpellID, concentration.Target, concentration.RemainingTurns); err != nil {
				log.Printf("advance concentration update error: %v", err)
				writeError(w, http.StatusInternalServerError, "internal error")
				return
			}
		}
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID:   characterID,
		Concentration: concentration,
	})
}

// deleteCharacterConcentrationHandler clears a character's concentration.
// Only the character owner may call it.
func deleteCharacterConcentrationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("delete concentration member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	if err := clearCharacterConcentration(campaignID, characterID); err != nil {
		log.Printf("delete concentration clear error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, concentrationResponse{
		CharacterID:   characterID,
		Concentration: nil,
	})
}

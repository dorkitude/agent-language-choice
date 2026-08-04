package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"sort"
)

func handlePlayCharacterDamage(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Amount *int `json:"amount"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Amount == nil {
		writeError(w, http.StatusBadRequest, "amount is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner may apply damage")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	hpBefore := member.HPCurrent
	hpAfter := hpBefore - *req.Amount
	if hpAfter < 0 {
		hpAfter = 0
	}
	member.HPCurrent = hpAfter
	if hpAfter == 0 && playMemberStatus(member) == "conscious" {
		member.Status = "unconscious"
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"target":    charID,
		"hp_before": hpBefore,
		"hp_after":  hpAfter,
		"damage":    *req.Amount,
	})
}

// handlePlayCharacterStatus returns a character's current hp and life
// status. Any campaign member (owner or player) may call this.
func handlePlayCharacterStatus(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only a campaign member may view character status")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	resp := map[string]interface{}{
		"character_id": charID,
		"hp_current":   member.HPCurrent,
		"hp_max":       member.HPMax,
		"status":       playMemberStatus(member),
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCharacterDeathSaves records a death save roll for an unconscious
// character. Only the character's owner may call this; rolling for a
// conscious, stable, or dead character returns 409. Three successes
// stabilize the character and three failures kill it; either outcome stops
// further rolls from being accepted.
func handlePlayCharacterDeathSaves(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Outcome string `json:"outcome"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Outcome != "success" && req.Outcome != "failure" {
		writeError(w, http.StatusBadRequest, "outcome must be \"success\" or \"failure\"")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Username != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may record death saves")
		return
	}
	if playMemberStatus(member) != "unconscious" {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "death saves may only be rolled for an unconscious character")
		return
	}

	if req.Outcome == "success" {
		member.DeathSaveSuccesses++
		if member.DeathSaveSuccesses >= 3 {
			member.Status = "stable"
		}
	} else {
		member.DeathSaveFailures++
		if member.DeathSaveFailures >= 3 {
			member.Status = "dead"
		}
	}
	resp := map[string]interface{}{
		"character_id": charID,
		"successes":    member.DeathSaveSuccesses,
		"failures":     member.DeathSaveFailures,
		"status":       playMemberStatus(member),
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handlePlayCharacterOwner returns a character's current owner. Any campaign
// member may call this.
func handlePlayCharacterOwner(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only a campaign member may view character ownership")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	resp := map[string]interface{}{
		"character_id": charID,
		"owner":        playMemberOwner(member),
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCharacterClaim allows the requesting player to claim an unowned
// character. A character already owned by another player cannot be claimed.
func handlePlayCharacterClaim(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}
	account := lookupPlayAccount(username)
	if account == nil || account.Role != "player" {
		writeError(w, http.StatusForbidden, "only a player may claim a character")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != "" && member.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "character is already owned by another player")
		return
	}
	member.Owner = username
	resp := map[string]interface{}{
		"character_id": charID,
		"owner":        member.Owner,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handlePlayCharacterTransfer lets a character's owner hand ownership to
// another campaign member.
func handlePlayCharacterTransfer(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		NewOwner string `json:"new_owner"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.NewOwner == "" {
		writeError(w, http.StatusBadRequest, "new_owner is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may transfer ownership")
		return
	}
	if !isPlayMember(c, req.NewOwner) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "new_owner must be a campaign member")
		return
	}
	member.Owner = req.NewOwner
	resp := map[string]interface{}{
		"character_id": charID,
		"owner":        member.Owner,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

var validPlayRaces = map[string]bool{
	"human": true, "elf": true, "dwarf": true, "halfling": true,
	"dragonborn": true, "gnome": true, "half-elf": true, "half-orc": true,
	"tiefling": true,
}

// playClassHitDie maps each valid class to its level-1 hit die size.
var playClassHitDie = map[string]int{
	"barbarian": 12,
	"fighter":   10,
	"paladin":   10,
	"ranger":    10,
	"bard":      8,
	"cleric":    8,
	"druid":     8,
	"monk":      8,
	"rogue":     8,
	"warlock":   8,
	"sorcerer":  6,
	"wizard":    6,
}

var validPlayBackgrounds = map[string]bool{
	"acolyte": true, "charlatan": true, "criminal": true, "entertainer": true,
	"folk-hero": true, "guild-artisan": true, "hermit": true, "noble": true,
	"outlander": true, "sage": true, "sailor": true, "soldier": true, "urchin": true,
}

// handlePlayCharacterBuild validates a character's race/class/background and
// ability scores, returning the character's derived level-1 defaults. Only
// the character's owner may call this.
func handlePlayCharacterBuild(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Race       string `json:"race"`
		Class      string `json:"class"`
		Background string `json:"background"`
		Abilities  *struct {
			Str *int `json:"str"`
			Dex *int `json:"dex"`
			Con *int `json:"con"`
			Int *int `json:"int"`
			Wis *int `json:"wis"`
			Cha *int `json:"cha"`
		} `json:"abilities"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validPlayRaces[req.Race] {
		writeError(w, http.StatusBadRequest, "invalid race")
		return
	}
	hitDie, validClass := playClassHitDie[req.Class]
	if !validClass {
		writeError(w, http.StatusBadRequest, "invalid class")
		return
	}
	if !validPlayBackgrounds[req.Background] {
		writeError(w, http.StatusBadRequest, "invalid background")
		return
	}
	if req.Abilities == nil {
		writeError(w, http.StatusBadRequest, "abilities are required")
		return
	}
	scores := []*int{req.Abilities.Str, req.Abilities.Dex, req.Abilities.Con, req.Abilities.Int, req.Abilities.Wis, req.Abilities.Cha}
	for _, v := range scores {
		if v == nil || *v < 1 || *v > 30 {
			writeError(w, http.StatusBadRequest, "ability scores must be integers from 1 through 30")
			return
		}
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may build the character")
		return
	}
	member.StrModifier = abilityModifier(*req.Abilities.Str)
	member.DexModifier = abilityModifier(*req.Abilities.Dex)
	member.ConModifier = abilityModifier(*req.Abilities.Con)
	member.IntModifier = abilityModifier(*req.Abilities.Int)
	member.WisModifier = abilityModifier(*req.Abilities.Wis)
	member.ChaModifier = abilityModifier(*req.Abilities.Cha)
	playMu.Unlock()
	persistState()

	hpMax := hitDie + abilityModifier(*req.Abilities.Con)

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"character_id":      charID,
		"race":              req.Race,
		"class":             req.Class,
		"background":        req.Background,
		"level":             1,
		"hp_max":            hpMax,
		"proficiency_bonus": proficiencyBonus(1),
	})
}

// handlePlayLevelUp advances a character by exactly one level, applying
// deterministic per-class hit-die HP growth. Only the character's owner may
// call this.
func handlePlayLevelUp(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Level *int `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may level up the character")
		return
	}
	currentLevel := playMemberLevel(member)
	if *req.Level != currentLevel+1 {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "level must be exactly one higher than the current level")
		return
	}
	hitDie, validClass := playClassHitDie[member.Class]
	if !validClass {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "character has no valid class")
		return
	}

	newLevel := *req.Level
	conMod := member.ConModifier
	level1HP := hitDie + conMod
	perLevelGain := hitDie/2 + 1 + conMod
	hpMax := level1HP + (newLevel-1)*perLevelGain

	member.Level = newLevel
	member.HPMax = hpMax
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"character_id":      charID,
		"level":             newLevel,
		"hp_max":            hpMax,
		"hit_dice":          fmt.Sprintf("1d%d", hitDie),
		"proficiency_bonus": proficiencyBonus(newLevel),
	})
}

// handlePlaySkillCheck resolves a skill check's modifier and total from a
// character's ability modifier and proficiency. Only the character's owner
// may call this.
func handlePlaySkillCheck(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Skill      string `json:"skill"`
		Ability    string `json:"ability"`
		Proficient bool   `json:"proficient"`
		Roll       *int   `json:"roll"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Roll == nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validPlaySkills[req.Skill] {
		writeError(w, http.StatusBadRequest, "unsupported skill")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may roll a skill check")
		return
	}
	abilityMod, validAbility := playAbilityModifier(member, req.Ability)
	if !validAbility {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "unsupported ability")
		return
	}
	modifier := abilityMod
	if req.Proficient {
		modifier += proficiencyBonus(playMemberLevel(member))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"character_id": charID,
		"skill":        req.Skill,
		"ability":      req.Ability,
		"modifier":     modifier,
		"total":        *req.Roll + modifier,
	})
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

// spellValidForClass reports whether spellID is a spell the given class may
// know.
func spellValidForClass(class, spellID string) bool {
	if class == "wizard" {
		return wizardSpells[spellID]
	}
	return false
}

// handlePlayCharacterSpells adds a spell to a character's spellbook (POST,
// owner only) or lists it (GET, any campaign member).
func handlePlayCharacterSpells(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	switch r.Method {
	case http.MethodPost:
		handlePlayCharacterLearnSpell(w, r, campaignID, charID)
	case http.MethodGet:
		handlePlayCharacterListSpells(w, r, campaignID, charID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

func handlePlayCharacterLearnSpell(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		SpellID string `json:"spell_id"`
		Name    string `json:"name"`
		Level   int    `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SpellID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "spell_id and name are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may learn a spell")
		return
	}
	if !spellValidForClass(member.Class, req.SpellID) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "spell is not valid for the character's class")
		return
	}
	for _, s := range member.Spells {
		if s.SpellID == req.SpellID {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "character already knows this spell")
			return
		}
	}
	spell := playSpell{SpellID: req.SpellID, Name: req.Name, Level: req.Level}
	member.Spells = append(member.Spells, spell)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"spell_id": spell.SpellID,
		"name":     spell.Name,
		"level":    spell.Level,
	})
}

// spellcastingClasses lists classes that may prepare spells.
var spellcastingClasses = map[string]bool{
	"wizard": true,
}

// maxPreparedSpells returns the maximum number of spells a character of the
// given class may prepare at the given level. Non-spellcasting classes
// return 0.
func maxPreparedSpells(class string, level int) int {
	if !spellcastingClasses[class] {
		return 0
	}
	if level < 1 {
		level = 1
	}
	return level
}

// memberKnowsSpell reports whether m's spellbook contains spellID.
func memberKnowsSpell(m *playMember, spellID string) bool {
	for _, s := range m.Spells {
		if s.SpellID == spellID {
			return true
		}
	}
	return false
}

// handlePlayCharacterPreparedSpells sets a character's prepared spells
// (PUT, owner only) or reads them (GET, any campaign member).
func handlePlayCharacterPreparedSpells(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	switch r.Method {
	case http.MethodPut:
		handlePlayCharacterSetPreparedSpells(w, r, campaignID, charID)
	case http.MethodGet:
		handlePlayCharacterGetPreparedSpells(w, r, campaignID, charID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

func handlePlayCharacterSetPreparedSpells(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		SpellIDs []string `json:"spell_ids"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may prepare spells")
		return
	}
	max := maxPreparedSpells(member.Class, playMemberLevel(member))
	if max == 0 {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "character's class cannot prepare spells")
		return
	}
	for _, spellID := range req.SpellIDs {
		if !memberKnowsSpell(member, spellID) {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "character does not know spell "+spellID)
			return
		}
	}
	if len(req.SpellIDs) > max {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "prepared spell list exceeds the maximum allowed")
		return
	}
	prepared := make([]string, len(req.SpellIDs))
	copy(prepared, req.SpellIDs)
	member.PreparedSpells = prepared
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"character_id":    charID,
		"prepared_spells": prepared,
		"max_prepared":    max,
	})
}

func handlePlayCharacterGetPreparedSpells(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
		writeError(w, http.StatusForbidden, "only a campaign member may view prepared spells")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	max := maxPreparedSpells(member.Class, playMemberLevel(member))
	prepared := make([]string, len(member.PreparedSpells))
	copy(prepared, member.PreparedSpells)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"character_id":    charID,
		"prepared_spells": prepared,
		"max_prepared":    max,
	})
}

// wizardSpellSlotsByLevel gives, for a character of the given level, the
// number of spell slots available at each spell level (1-9).
var wizardSpellSlotsByLevel = map[int]map[int]int{
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
	17: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
	18: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 1, 7: 1, 8: 1, 9: 1},
	19: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 1, 8: 1, 9: 1},
	20: {1: 4, 2: 3, 3: 3, 4: 3, 5: 3, 6: 2, 7: 2, 8: 1, 9: 1},
}

// spellSlotsForMember returns the total spell slots by spell level available
// to a character of the given class and level. Non-spellcasting classes get
// no slots.
func spellSlotsForMember(class string, level int) map[int]int {
	if !spellcastingClasses[class] {
		return nil
	}
	if level < 1 {
		level = 1
	}
	if level > 20 {
		level = 20
	}
	return wizardSpellSlotsByLevel[level]
}

// memberSpellLevel returns the known level of spellID on m, and whether m
// knows it.
func memberSpellLevel(m *playMember, spellID string) (int, bool) {
	for _, s := range m.Spells {
		if s.SpellID == spellID {
			return s.Level, true
		}
	}
	return 0, false
}

// memberHasPrepared reports whether spellID is currently prepared on m.
func memberHasPrepared(m *playMember, spellID string) bool {
	for _, s := range m.PreparedSpells {
		if s == spellID {
			return true
		}
	}
	return false
}

// handlePlayCharacterCasts records a spell cast (POST, owner only) or lists
// the character's cast history (GET, any campaign member).
func handlePlayCharacterCasts(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	switch r.Method {
	case http.MethodPost:
		handlePlayCharacterCastSpell(w, r, campaignID, charID)
	case http.MethodGet:
		handlePlayCharacterListCasts(w, r, campaignID, charID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

func handlePlayCharacterCastSpell(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		SpellID string `json:"spell_id"`
		Target  string `json:"target"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SpellID == "" {
		writeError(w, http.StatusBadRequest, "spell_id is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may cast a spell")
		return
	}
	if !spellcastingClasses[member.Class] {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "character's class cannot cast spells")
		return
	}
	if !memberHasPrepared(member, req.SpellID) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "spell is not currently prepared")
		return
	}
	spellLevel, known := memberSpellLevel(member, req.SpellID)
	if !known {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "spell is not currently prepared")
		return
	}
	slots := spellSlotsForMember(member.Class, playMemberLevel(member))
	total := slots[spellLevel]
	if member.SpellSlotsUsed == nil {
		member.SpellSlotsUsed = make(map[int]int)
	}
	used := member.SpellSlotsUsed[spellLevel]
	if used >= total {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "no remaining spell slots of the required level")
		return
	}
	member.SpellSlotsUsed[spellLevel] = used + 1
	remaining := total - member.SpellSlotsUsed[spellLevel]
	sequence := len(member.Casts) + 1
	cast := playCast{
		Sequence:       sequence,
		SpellID:        req.SpellID,
		Target:         req.Target,
		SlotLevel:      spellLevel,
		SlotsRemaining: remaining,
	}
	member.Casts = append(member.Casts, cast)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"character_id":    charID,
		"spell_id":        cast.SpellID,
		"target":          cast.Target,
		"slot_level":      cast.SlotLevel,
		"slots_remaining": cast.SlotsRemaining,
		"sequence":        cast.Sequence,
	})
}

func handlePlayCharacterListCasts(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
		writeError(w, http.StatusForbidden, "only a campaign member may view cast history")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	casts := make([]map[string]interface{}, 0, len(member.Casts))
	for _, cast := range member.Casts {
		casts = append(casts, map[string]interface{}{
			"character_id":    charID,
			"spell_id":        cast.SpellID,
			"target":          cast.Target,
			"slot_level":      cast.SlotLevel,
			"slots_remaining": cast.SlotsRemaining,
			"sequence":        cast.Sequence,
		})
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"casts": casts})
}

func handlePlayCharacterListSpells(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
		writeError(w, http.StatusForbidden, "only a campaign member may view the spellbook")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	spells := make([]map[string]interface{}, 0, len(member.Spells))
	for _, s := range member.Spells {
		spells = append(spells, map[string]interface{}{
			"spell_id": s.SpellID,
			"name":     s.Name,
			"level":    s.Level,
		})
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"spells": spells})
}

// concentrationResponse builds the standard concentration response body for
// charID given m's current concentration state (which may be nil).
func concentrationResponse(charID string, m *playMember) map[string]interface{} {
	if m.Concentration == nil {
		return map[string]interface{}{
			"character_id":  charID,
			"concentration": nil,
		}
	}
	return map[string]interface{}{
		"character_id": charID,
		"concentration": map[string]interface{}{
			"spell_id":        m.Concentration.SpellID,
			"target":          m.Concentration.Target,
			"remaining_turns": m.Concentration.RemainingTurns,
		},
	}
}

// handlePlayCharacterConcentration handles setting (PUT), reading (GET), and
// clearing (DELETE) a character's current concentration state.
func handlePlayCharacterConcentration(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	switch r.Method {
	case http.MethodPut:
		handlePlayCharacterSetConcentration(w, r, campaignID, charID)
	case http.MethodGet:
		handlePlayCharacterGetConcentration(w, r, campaignID, charID)
	case http.MethodDelete:
		handlePlayCharacterClearConcentration(w, r, campaignID, charID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

func handlePlayCharacterSetConcentration(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		SpellID       string `json:"spell_id"`
		Target        string `json:"target"`
		DurationTurns int    `json:"duration_turns"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may set concentration")
		return
	}
	if !spellcastingClasses[member.Class] {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "character's class cannot cast spells")
		return
	}
	if !memberKnowsSpell(member, req.SpellID) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "character does not know this spell")
		return
	}
	if !memberHasPrepared(member, req.SpellID) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "spell is not currently prepared")
		return
	}
	if req.DurationTurns < 1 {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "duration_turns must be positive")
		return
	}

	member.Concentration = &playConcentration{
		SpellID:        req.SpellID,
		Target:         req.Target,
		RemainingTurns: req.DurationTurns,
	}
	resp := concentrationResponse(charID, member)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

func handlePlayCharacterGetConcentration(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
		writeError(w, http.StatusForbidden, "only a campaign member may view concentration")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	resp := concentrationResponse(charID, member)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handlePlayCharacterClearConcentration(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may clear concentration")
		return
	}
	member.Concentration = nil
	resp := concentrationResponse(charID, member)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCharacterConcentrationAdvanceTurn decrements the character's
// active concentration by one turn, clearing it if it reaches zero. Allowed
// for any campaign member.
func handlePlayCharacterConcentrationAdvanceTurn(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
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
		writeError(w, http.StatusForbidden, "only a campaign member may advance concentration")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Concentration != nil {
		member.Concentration.RemainingTurns--
		if member.Concentration.RemainingTurns <= 0 {
			member.Concentration = nil
		}
	}
	resp := concentrationResponse(charID, member)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// encounterHasCombatant reports whether target names a monster or bound
// party member combatant within enc.

// validInventoryItems lists the catalog item IDs that may be stacked in a
// character's inventory.
var validInventoryItems = map[string]bool{
	"healing-potion":     true,
	"torch":              true,
	"leather-armor":      true,
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

// equipmentSlots lists the valid equipment slot names.
var equipmentSlots = map[string]bool{
	"armor":     true,
	"accessory": true,
}

// itemEquipmentSlot maps an equippable item ID to the slot it must be
// equipped in.
var itemEquipmentSlot = map[string]string{
	"leather-armor":      "armor",
	"ring-of-protection": "accessory",
	"amulet-of-health":   "accessory",
}

// attunableItems lists item IDs that may be attuned once equipped.
var attunableItems = map[string]bool{
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

// maxAttunements is the maximum number of items a character may have
// attuned at once.
const maxAttunements = 1

// consumableItems lists item IDs that may be consumed via the consume
// endpoint.
var consumableItems = map[string]bool{
	"healing-potion": true,
}

// consumableEffects maps a consumable item ID to the effect applied when it
// is consumed.
var consumableEffects = map[string]map[string]interface{}{
	"healing-potion": {
		"type":        "healing",
		"hp_restored": 5,
	},
}

// playCharacterItemsResponse builds the sorted items list response body for
// a character's held inventory stacks.
func playCharacterItemsResponse(charID string, items map[string]int) map[string]interface{} {
	ids := make([]string, 0, len(items))
	for itemID, qty := range items {
		if qty <= 0 {
			continue
		}
		ids = append(ids, itemID)
	}
	sort.Strings(ids)

	list := make([]map[string]interface{}, 0, len(ids))
	for _, itemID := range ids {
		list = append(list, map[string]interface{}{
			"item_id":  itemID,
			"quantity": items[itemID],
		})
	}

	return map[string]interface{}{
		"character_id": charID,
		"items":        list,
	}
}

// handlePlayCharacterInventoryItems adds an inventory item stack (POST,
// owner only) or lists held item stacks (GET, any campaign member).
func handlePlayCharacterInventoryItems(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	switch r.Method {
	case http.MethodPost:
		handlePlayCharacterAddInventoryItem(w, r, campaignID, charID)
	case http.MethodGet:
		handlePlayCharacterListInventoryItems(w, r, campaignID, charID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

func handlePlayCharacterAddInventoryItem(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ItemID   string `json:"item_id"`
		Quantity *int   `json:"quantity"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validInventoryItems[req.ItemID] || req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "item_id must be a valid catalog item and quantity must be positive")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may add inventory items")
		return
	}
	if member.Items == nil {
		member.Items = make(map[string]int)
	}
	member.Items[req.ItemID] += *req.Quantity
	total := member.Items[req.ItemID]
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"character_id":   charID,
		"item_id":        req.ItemID,
		"quantity":       *req.Quantity,
		"total_quantity": total,
	})
}

func handlePlayCharacterListInventoryItems(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
		writeError(w, http.StatusForbidden, "only a campaign member may view the inventory")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	resp := playCharacterItemsResponse(charID, member.Items)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCharacterInventoryItemRemove decrements an inventory item stack.
// Only the character's owner may remove items.
func handlePlayCharacterInventoryItemRemove(w http.ResponseWriter, r *http.Request, campaignID, charID, itemID string) {
	if r.Method != http.MethodDelete {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Quantity *int `json:"quantity"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validInventoryItems[itemID] || req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "item_id must be a valid catalog item and quantity must be positive")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may remove inventory items")
		return
	}
	held := member.Items[itemID]
	if *req.Quantity > held {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "cannot remove more than the held quantity")
		return
	}
	held -= *req.Quantity
	if member.Items == nil {
		member.Items = make(map[string]int)
	}
	member.Items[itemID] = held
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"character_id":   charID,
		"item_id":        itemID,
		"quantity":       *req.Quantity,
		"total_quantity": held,
	})
}

// handlePlayCharacterInventoryItemConsume consumes one unit of a held
// consumable inventory item. Only the character's owner may consume items.
func handlePlayCharacterInventoryItemConsume(w http.ResponseWriter, r *http.Request, campaignID, charID, itemID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	if !validInventoryItems[itemID] || !consumableItems[itemID] {
		writeError(w, http.StatusBadRequest, "item_id must be a consumable catalog item")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may consume inventory items")
		return
	}
	if member.Items[itemID] <= 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "no held quantity of this item")
		return
	}
	member.Items[itemID]--
	total := member.Items[itemID]
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"character_id":      charID,
		"item_id":           itemID,
		"quantity_consumed": 1,
		"total_quantity":    total,
		"effect":            consumableEffects[itemID],
	})
}

// equipmentSlotResponse builds the response body for an equipment slot,
// treating a nil slot as empty.
func equipmentSlotResponse(charID, slot string, es *playEquipmentSlot) map[string]interface{} {
	itemID := ""
	attuned := false
	if es != nil {
		itemID = es.ItemID
		attuned = es.Attuned
	}
	return map[string]interface{}{
		"character_id": charID,
		"slot":         slot,
		"item_id":      itemID,
		"attuned":      attuned,
	}
}

// handlePlayCharacterEquipmentSlot equips an item into a slot (PUT, owner
// only) or reads the currently equipped item for a slot (GET, any campaign
// member).
func handlePlayCharacterEquipmentSlot(w http.ResponseWriter, r *http.Request, campaignID, charID, slot string) {
	switch r.Method {
	case http.MethodPut:
		handlePlayCharacterEquipItem(w, r, campaignID, charID, slot)
	case http.MethodGet:
		handlePlayCharacterGetEquipment(w, r, campaignID, charID, slot)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

func handlePlayCharacterEquipItem(w http.ResponseWriter, r *http.Request, campaignID, charID, slot string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ItemID string `json:"item_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !equipmentSlots[slot] {
		writeError(w, http.StatusBadRequest, "invalid equipment slot")
		return
	}
	requiredSlot, known := itemEquipmentSlot[req.ItemID]
	if !known {
		writeError(w, http.StatusBadRequest, "unknown item id")
		return
	}
	if requiredSlot != slot {
		writeError(w, http.StatusBadRequest, "item does not belong in the requested slot")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may equip items")
		return
	}
	if member.Items[req.ItemID] <= 0 {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "item is not held in the character inventory")
		return
	}
	if member.Equipment == nil {
		member.Equipment = make(map[string]*playEquipmentSlot)
	}
	if prev := member.Equipment[slot]; prev != nil && prev.Attuned && member.AttunementCount > 0 {
		member.AttunementCount--
	}
	member.Equipment[slot] = &playEquipmentSlot{ItemID: req.ItemID}
	resp := equipmentSlotResponse(charID, slot, member.Equipment[slot])
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

func handlePlayCharacterGetEquipment(w http.ResponseWriter, r *http.Request, campaignID, charID, slot string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}
	if !equipmentSlots[slot] {
		writeError(w, http.StatusBadRequest, "invalid equipment slot")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a campaign member may view equipment")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	resp := equipmentSlotResponse(charID, slot, member.Equipment[slot])
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCharacterAttune attunes the item currently equipped in slot.
// Only the character's owner may attune, and only one item may be attuned
// per character at a time.
func handlePlayCharacterAttune(w http.ResponseWriter, r *http.Request, campaignID, charID, slot string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}
	if !equipmentSlots[slot] {
		writeError(w, http.StatusBadRequest, "invalid equipment slot")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(member) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the character's owner may attune items")
		return
	}
	es := member.Equipment[slot]
	if es == nil || !attunableItems[es.ItemID] {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "slot does not contain an attunable item")
		return
	}
	if es.Attuned {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "item is already attuned")
		return
	}
	if member.AttunementCount >= maxAttunements {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "maximum attunements reached")
		return
	}
	es.Attuned = true
	member.AttunementCount++
	resp := map[string]interface{}{
		"character_id":     charID,
		"slot":             slot,
		"item_id":          es.ItemID,
		"attuned":          true,
		"attunement_count": member.AttunementCount,
		"max_attunements":  maxAttunements,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCharacterCurrency returns a character's current gold balance.
// Any authenticated campaign member may call this.
func handlePlayCharacterCurrency(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

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
		writeError(w, http.StatusForbidden, "only a campaign member may view character currency")
		return
	}
	member := findPlayMemberByCharacterID(c, charID)
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	resp := map[string]interface{}{
		"character_id": charID,
		"gold":         member.Gold,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayCharacterCurrencyTransfer atomically transfers gold from charID
// to another character in the same campaign. Only the source character's
// owner may initiate the transfer.
func handlePlayCharacterCurrencyTransfer(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ToCharacterID string `json:"to_character_id"`
		Gold          *int   `json:"gold"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	source := findPlayMemberByCharacterID(c, charID)
	if source == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if playMemberOwner(source) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the source character's owner may transfer gold")
		return
	}
	if req.ToCharacterID == "" || req.ToCharacterID == charID || req.Gold == nil || *req.Gold <= 0 {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "to_character_id must name a different campaign character and gold must be positive")
		return
	}
	dest := findPlayMemberByCharacterID(c, req.ToCharacterID)
	if dest == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "to_character_id must name a different campaign character and gold must be positive")
		return
	}
	if source.Gold < *req.Gold {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "insufficient gold for transfer")
		return
	}

	source.Gold -= *req.Gold
	dest.Gold += *req.Gold
	c.TransferSeq++
	resp := map[string]interface{}{
		"from_character_id": charID,
		"to_character_id":   req.ToCharacterID,
		"gold":              *req.Gold,
		"from_gold":         source.Gold,
		"to_gold":           dest.Gold,
		"transfer_id":       c.TransferSeq,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

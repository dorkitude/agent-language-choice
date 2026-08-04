package main

import (
	"net/http"
	"sync"
)

// spellDef describes a known spell's canonical name/level and the classes
// permitted to learn it.
type spellDef struct {
	Name    string
	Level   int
	Classes map[string]bool
}

func classSet(classes ...string) map[string]bool {
	s := make(map[string]bool, len(classes))
	for _, c := range classes {
		s[c] = true
	}
	return s
}

// spellCompendium is the fixed set of spells characters may learn, keyed by
// spell_id. A class may learn a spell only if it appears in that spell's
// Classes set; classes with no entries in any spell (e.g. rogue, fighter,
// barbarian, monk) cannot learn spells at all.
var spellCompendium = map[string]spellDef{
	"fire-bolt":       {Name: "Fire Bolt", Level: 0, Classes: classSet("wizard", "sorcerer")},
	"ray-of-frost":    {Name: "Ray of Frost", Level: 0, Classes: classSet("wizard", "sorcerer")},
	"minor-illusion":  {Name: "Minor Illusion", Level: 0, Classes: classSet("wizard", "sorcerer", "bard", "warlock")},
	"mage-armor":      {Name: "Mage Armor", Level: 1, Classes: classSet("wizard", "sorcerer")},
	"magic-missile":   {Name: "Magic Missile", Level: 1, Classes: classSet("wizard", "sorcerer")},
	"shield":          {Name: "Shield", Level: 1, Classes: classSet("wizard", "sorcerer")},
	"sacred-flame":    {Name: "Sacred Flame", Level: 0, Classes: classSet("cleric")},
	"guidance":        {Name: "Guidance", Level: 0, Classes: classSet("cleric", "druid")},
	"cure-wounds":     {Name: "Cure Wounds", Level: 1, Classes: classSet("cleric", "druid", "bard", "paladin", "ranger")},
	"bless":           {Name: "Bless", Level: 1, Classes: classSet("cleric", "paladin")},
	"produce-flame":   {Name: "Produce Flame", Level: 0, Classes: classSet("druid")},
	"thorn-whip":      {Name: "Thorn Whip", Level: 0, Classes: classSet("druid")},
	"vicious-mockery": {Name: "Vicious Mockery", Level: 0, Classes: classSet("bard")},
	"healing-word":    {Name: "Healing Word", Level: 1, Classes: classSet("bard", "cleric", "druid")},
	"eldritch-blast":  {Name: "Eldritch Blast", Level: 0, Classes: classSet("warlock")},
	"hex":             {Name: "Hex", Level: 1, Classes: classSet("warlock")},
	"hunters-mark":    {Name: "Hunter's Mark", Level: 1, Classes: classSet("ranger")},
	"goodberry":       {Name: "Goodberry", Level: 1, Classes: classSet("ranger", "druid")},
}

type playSpell struct {
	CampaignID  string `json:"-"`
	CharacterID string `json:"-"`
	SpellID     string `json:"spell_id"`
	Name        string `json:"name"`
	Level       int    `json:"level"`
}

// playSpellsMu guards playSpells, the in-memory index mirroring the
// play_spells table. It is keyed by campaign id, then character id.
var (
	playSpellsMu sync.Mutex
	playSpells   = map[string]map[string][]*playSpell{}
)

type addSpellRequest struct {
	SpellID string `json:"spell_id"`
	Name    string `json:"name"`
	Level   int    `json:"level"`
}

// addSpellHandler lets the character's owner add a known spell to their
// spellbook, provided the spell is valid for the character's class. Only
// the owner may call this; a duplicate spell_id returns 409.
func addSpellHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req addSpellRequest
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
		writeError(w, http.StatusForbidden, "only the character's owner may add a spell")
		return
	}

	def, known := spellCompendium[req.SpellID]
	if !known || def.Name != req.Name || def.Level != req.Level || !def.Classes[member.Class] {
		writeError(w, http.StatusBadRequest, "invalid class/spell combination")
		return
	}

	playSpellsMu.Lock()
	defer playSpellsMu.Unlock()

	for _, s := range playSpells[campaignID][charID] {
		if s.SpellID == req.SpellID {
			writeError(w, http.StatusConflict, "character already knows this spell")
			return
		}
	}

	spell := &playSpell{
		CampaignID:  campaignID,
		CharacterID: charID,
		SpellID:     req.SpellID,
		Name:        req.Name,
		Level:       req.Level,
	}
	if err := savePlaySpellToDB(spell); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save spell")
		return
	}
	if playSpells[campaignID] == nil {
		playSpells[campaignID] = map[string][]*playSpell{}
	}
	playSpells[campaignID][charID] = append(playSpells[campaignID][charID], spell)

	writeJSON(w, http.StatusCreated, map[string]any{
		"spell_id": spell.SpellID,
		"name":     spell.Name,
		"level":    spell.Level,
	})
}

// listSpellsHandler returns a character's spellbook. Any campaign member
// (owner or player) may call this.
func listSpellsHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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

	playSpellsMu.Lock()
	defer playSpellsMu.Unlock()

	spells := make([]map[string]any, 0, len(playSpells[campaignID][charID]))
	for _, s := range playSpells[campaignID][charID] {
		spells = append(spells, map[string]any{
			"spell_id": s.SpellID,
			"name":     s.Name,
			"level":    s.Level,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{"spells": spells})
}

// spellcastingClasses are the classes that may prepare spells at all;
// classes absent here (e.g. rogue, fighter, barbarian, monk) can never
// learn a spell in the first place (see spellCompendium above).
var spellcastingClasses = classSet("wizard", "sorcerer", "cleric", "druid", "bard", "paladin", "warlock", "ranger")

// maxPreparedSpells returns the maximum number of prepared spells allowed
// for a character of the given class and level. Non-spellcasting classes
// may prepare none. At level 1 a wizard may prepare at most one spell.
func maxPreparedSpells(class string, level int) int {
	if !spellcastingClasses[class] {
		return 0
	}
	if level < 1 {
		level = 1
	}
	return level
}

type playPreparedSpells struct {
	CampaignID  string   `json:"-"`
	CharacterID string   `json:"-"`
	SpellIDs    []string `json:"-"`
}

// preparedSpellsMu guards preparedSpells, the in-memory index mirroring the
// play_prepared_spells table. It is keyed by campaign id, then character id.
var (
	preparedSpellsMu sync.Mutex
	preparedSpells   = map[string]map[string]*playPreparedSpells{}
)

type preparedSpellsRequest struct {
	SpellIDs []string `json:"spell_ids"`
}

func preparedSpellsResponse(charID string, spellIDs []string, maxPrepared int) map[string]any {
	if spellIDs == nil {
		spellIDs = []string{}
	}
	return map[string]any{
		"character_id":    charID,
		"prepared_spells": spellIDs,
		"max_prepared":    maxPrepared,
	}
}

// setPreparedSpellsHandler lets the character's owner set the character's
// full prepared-spells list, provided the character's class can prepare
// spells, every requested spell is already known, and the list does not
// exceed the class/level's maximum prepared spells.
func setPreparedSpellsHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req preparedSpellsRequest
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
		writeError(w, http.StatusForbidden, "only the character's owner may prepare spells")
		return
	}

	maxPrepared := maxPreparedSpells(member.Class, member.Level)
	if maxPrepared == 0 || len(req.SpellIDs) > maxPrepared {
		writeError(w, http.StatusBadRequest, "invalid prepared spells list")
		return
	}

	playSpellsMu.Lock()
	known := map[string]bool{}
	for _, s := range playSpells[campaignID][charID] {
		known[s.SpellID] = true
	}
	playSpellsMu.Unlock()

	for _, id := range req.SpellIDs {
		if !known[id] {
			writeError(w, http.StatusBadRequest, "invalid prepared spells list")
			return
		}
	}

	spellIDs := append([]string{}, req.SpellIDs...)

	preparedSpellsMu.Lock()
	defer preparedSpellsMu.Unlock()

	p := &playPreparedSpells{
		CampaignID:  campaignID,
		CharacterID: charID,
		SpellIDs:    spellIDs,
	}
	if err := savePreparedSpellsToDB(p); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save prepared spells")
		return
	}
	if preparedSpells[campaignID] == nil {
		preparedSpells[campaignID] = map[string]*playPreparedSpells{}
	}
	preparedSpells[campaignID][charID] = p

	writeJSON(w, http.StatusOK, preparedSpellsResponse(charID, spellIDs, maxPrepared))
}

// getPreparedSpellsHandler returns a character's prepared spells. Any
// campaign member (owner or player) may call this.
func getPreparedSpellsHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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
	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		playMembersMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	maxPrepared := maxPreparedSpells(member.Class, member.Level)
	playMembersMu.Unlock()

	preparedSpellsMu.Lock()
	defer preparedSpellsMu.Unlock()

	var spellIDs []string
	if p, ok := preparedSpells[campaignID][charID]; ok {
		spellIDs = append([]string{}, p.SpellIDs...)
	}

	writeJSON(w, http.StatusOK, preparedSpellsResponse(charID, spellIDs, maxPrepared))
}

// spellSlotTable maps a spellcasting character's level to the number of
// slots available at each spell level. At level 1 a full spellcaster has
// exactly one first-level slot.
var spellSlotTable = map[int]map[int]int{
	1: {1: 1},
	5: {1: 4, 2: 3, 3: 2},
}

// totalSpellSlotsOfLevel returns the number of spell slots of slotLevel a
// character of the given class/level has in total. Non-spellcasting
// classes, or levels not present in spellSlotTable, have none.
func totalSpellSlotsOfLevel(class string, charLevel, slotLevel int) int {
	if !spellcastingClasses[class] {
		return 0
	}
	slots, ok := spellSlotTable[charLevel]
	if !ok {
		return 0
	}
	return slots[slotLevel]
}

type playSpellCast struct {
	CampaignID     string `json:"-"`
	CharacterID    string `json:"character_id"`
	SpellID        string `json:"spell_id"`
	Target         string `json:"target"`
	SlotLevel      int    `json:"slot_level"`
	SlotsRemaining int    `json:"slots_remaining"`
	Sequence       int    `json:"sequence"`
}

// spellCastsMu guards spellCasts (a character's ordered cast history) and
// spellSlotsUsed (spent slots per spell level), both mirroring the
// play_casts table. Each is keyed by campaign id, then character id.
var (
	spellCastsMu   sync.Mutex
	spellCasts     = map[string]map[string][]*playSpellCast{}
	spellSlotsUsed = map[string]map[string]map[int]int{}
)

type castSpellRequest struct {
	SpellID string `json:"spell_id"`
	Target  string `json:"target"`
}

// castSpellHandler lets the character's owner cast a currently prepared
// spell, provided the character is a spellcaster with a remaining slot of
// the spell's level.
func castSpellHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req castSpellRequest
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
		writeError(w, http.StatusForbidden, "only the character's owner may cast a spell")
		return
	}
	if !spellcastingClasses[member.Class] {
		writeError(w, http.StatusBadRequest, "character is not a spellcaster")
		return
	}

	def, known := spellCompendium[req.SpellID]
	if !known || req.Target == "" {
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

	slotLevel := def.Level
	total := totalSpellSlotsOfLevel(member.Class, member.Level, slotLevel)

	spellCastsMu.Lock()
	defer spellCastsMu.Unlock()

	used := spellSlotsUsed[campaignID][charID][slotLevel]
	if used >= total {
		writeError(w, http.StatusConflict, "no remaining spell slots of that level")
		return
	}
	used++
	remaining := total - used

	if spellSlotsUsed[campaignID] == nil {
		spellSlotsUsed[campaignID] = map[string]map[int]int{}
	}
	if spellSlotsUsed[campaignID][charID] == nil {
		spellSlotsUsed[campaignID][charID] = map[int]int{}
	}
	spellSlotsUsed[campaignID][charID][slotLevel] = used

	cast := &playSpellCast{
		CampaignID:     campaignID,
		CharacterID:    charID,
		SpellID:        req.SpellID,
		Target:         req.Target,
		SlotLevel:      slotLevel,
		SlotsRemaining: remaining,
		Sequence:       len(spellCasts[campaignID][charID]) + 1,
	}
	if err := saveSpellCastToDB(cast); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save cast")
		return
	}
	if spellCasts[campaignID] == nil {
		spellCasts[campaignID] = map[string][]*playSpellCast{}
	}
	spellCasts[campaignID][charID] = append(spellCasts[campaignID][charID], cast)

	writeJSON(w, http.StatusCreated, cast)
}

// listCastsHandler returns a character's cast history. Any campaign member
// (owner or player) may call this.
func listCastsHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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

	spellCastsMu.Lock()
	defer spellCastsMu.Unlock()

	casts := make([]*playSpellCast, 0, len(spellCasts[campaignID][charID]))
	casts = append(casts, spellCasts[campaignID][charID]...)

	writeJSON(w, http.StatusOK, map[string]any{"casts": casts})
}

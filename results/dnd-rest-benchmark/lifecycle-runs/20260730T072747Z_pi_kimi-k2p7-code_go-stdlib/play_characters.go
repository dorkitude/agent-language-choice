package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

type characterDamageRequest struct {
	Amount int `json:"amount"`
}

// characterDamageResponse is the shape returned after applying damage to a
// character. HP floors at 0 and reaching 0 makes the character unconscious.
type characterDamageResponse struct {
	Target   string `json:"target"`
	HPBefore int    `json:"hp_before"`
	HPAfter  int    `json:"hp_after"`
	Damage   int    `json:"damage"`
}

// damageCharacterHandler lets the campaign owner apply deterministic damage to
// a bound party member. HP floors at 0; reaching 0 transitions the character to
// unconscious.
func damageCharacterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("char_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req characterDamageRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Amount <= 0 {
		writeError(w, http.StatusBadRequest, "invalid amount")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("damage character query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	before := member.HPCurrent
	after := before - req.Amount
	if after < 0 {
		after = 0
	}
	status := member.Status
	successes := member.DeathSavesSuccesses
	failures := member.DeathSavesFailures
	if after > 0 {
		status = "conscious"
		successes = 0
		failures = 0
	} else if after == 0 && status == "conscious" {
		status = "unconscious"
		successes = 0
		failures = 0
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET hp_current=%d, status=%s, death_saves_successes=%d, death_saves_failures=%d WHERE campaign_id=%s AND character_id=%s;",
		after, sq(status), successes, failures, sq(campaignID), sq(characterID))); err != nil {
		log.Printf("damage character update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, characterDamageResponse{
		Target:   characterID,
		HPBefore: before,
		HPAfter:  after,
		Damage:   req.Amount,
	})
}

// deathSavesRequest binds the payload for a death-saving throw.
type deathSavesRequest struct {
	Outcome string `json:"outcome"`
}

// deathSavesResponse is the shape returned after recording a death save.
type deathSavesResponse struct {
	CharacterID string `json:"character_id"`
	Successes   int    `json:"successes"`
	Failures    int    `json:"failures"`
	Status      string `json:"status"`
}

// deathSavesHandler lets the owner of a bound character record a death-saving
// throw. Only the character's owner may call it, and only while the character
// is unconscious. Three successes make the character stable; three failures
// make the character dead. Further rolls on a stable or dead character are
// rejected with 409.
func deathSavesHandler(w http.ResponseWriter, r *http.Request) {
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
		log.Printf("death saves member query error: %v", err)
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

	if member.Status != "unconscious" {
		writeError(w, http.StatusConflict, "character is not unconscious")
		return
	}

	var req deathSavesRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Outcome != "success" && req.Outcome != "failure" {
		writeError(w, http.StatusBadRequest, "invalid outcome")
		return
	}

	successes := member.DeathSavesSuccesses
	failures := member.DeathSavesFailures
	status := member.Status

	if req.Outcome == "success" {
		successes++
		if successes >= 3 {
			successes = 3
			status = "stable"
		}
	} else {
		failures++
		if failures >= 3 {
			failures = 3
			status = "dead"
		}
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET status=%s, death_saves_successes=%d, death_saves_failures=%d WHERE campaign_id=%s AND character_id=%s;",
		sq(status), successes, failures, sq(campaignID), sq(characterID))); err != nil {
		log.Printf("death saves update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, deathSavesResponse{
		CharacterID: characterID,
		Successes:   successes,
		Failures:    failures,
		Status:      status,
	})
}

// characterStatusResponse is the shape returned for a bound character's
// current health and life-state.
type characterStatusResponse struct {
	CharacterID string `json:"character_id"`
	HPCurrent   int    `json:"hp_current"`
	HPMax       int    `json:"hp_max"`
	Status      string `json:"status"`
}

// getCharacterStatusHandler returns the current HP and life-state of a bound
// party character. Any campaign owner or member may read it.
func getCharacterStatusHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("char_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("character status query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, characterStatusResponse{
		CharacterID: characterID,
		HPCurrent:   member.HPCurrent,
		HPMax:       member.HPMax,
		Status:      member.Status,
	})
}

// characterOwnerResponse is the shape returned by the character ownership
// endpoints. It links a campaign character to exactly one player identity.
type characterOwnerResponse struct {
	CharacterID string `json:"character_id"`
	Owner       string `json:"owner"`
}

// transferCharacterRequest binds the payload for an ownership transfer.
type transferCharacterRequest struct {
	NewOwner string `json:"new_owner"`
}

// getCharacterOwnerHandler returns the player identity that owns a campaign
// character. Any campaign owner or member may read it.
func getCharacterOwnerHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("char_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	if _, ok, err := queryPlayCampaign(campaignID); err != nil {
		log.Printf("character owner campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("character owner member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, characterOwnerResponse{
		CharacterID: characterID,
		Owner:       member.Owner,
	})
}

// claimCharacterHandler lets an authenticated player claim an unowned campaign
// character. If the character is already owned by another player, it returns
// 409. If the caller already owns the character, the current owner is
// returned with 200.
func claimCharacterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	characterID := r.PathValue("char_id")

	if _, ok, err := queryPlayCampaign(campaignID); err != nil {
		log.Printf("claim character campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isMember := false
	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("claim character members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for _, m := range members {
		if m.Username == username {
			isMember = true
			break
		}
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("claim character member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	if member.Owner != "" && member.Owner != username {
		writeError(w, http.StatusConflict, "character already owned")
		return
	}
	if member.Owner == username {
		writeJSON(w, http.StatusOK, characterOwnerResponse{
			CharacterID: characterID,
			Owner:       member.Owner,
		})
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET owner=%s WHERE campaign_id=%s AND character_id=%s;",
		sq(username), sq(campaignID), sq(characterID))); err != nil {
		log.Printf("claim character update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, characterOwnerResponse{
		CharacterID: characterID,
		Owner:       username,
	})
}

// transferCharacterHandler lets the current owner transfer a campaign character
// to another campaign member. Only the owner may transfer, and the new owner
// must already be a member.
func transferCharacterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	characterID := r.PathValue("char_id")

	if _, ok, err := queryPlayCampaign(campaignID); err != nil {
		log.Printf("transfer character campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	var req transferCharacterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.NewOwner == "" {
		writeError(w, http.StatusBadRequest, "invalid new_owner")
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("transfer character member query error: %v", err)
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

	isMember := false
	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("transfer character members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for _, m := range members {
		if m.Username == req.NewOwner {
			isMember = true
			break
		}
	}
	if !isMember {
		writeError(w, http.StatusConflict, "new owner is not a member")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET owner=%s WHERE campaign_id=%s AND character_id=%s;",
		sq(req.NewOwner), sq(campaignID), sq(characterID))); err != nil {
		log.Printf("transfer character update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, characterOwnerResponse{
		CharacterID: characterID,
		Owner:       req.NewOwner,
	})
}

// validRaces is the set of supported character races for build validation.
var validRaces = map[string]bool{
	"dragonborn": true,
	"dwarf":      true,
	"elf":        true,
	"gnome":      true,
	"half-elf":   true,
	"half-orc":   true,
	"halfling":   true,
	"human":      true,
	"tiefling":   true,
}

// classHitDice maps supported classes to their first-level hit die.
var classHitDice = map[string]int{
	"barbarian": 12,
	"bard":      8,
	"cleric":    8,
	"druid":     8,
	"fighter":   10,
	"monk":      8,
	"paladin":   10,
	"ranger":    10,
	"rogue":     8,
	"sorcerer":  6,
	"warlock":   8,
	"wizard":    6,
}

// validBackgrounds is the set of supported character backgrounds for build
// validation. Both spaced and hyphenated forms are accepted for multi-word
// backgrounds.
var validBackgrounds = map[string]bool{
	"acolyte":       true,
	"charlatan":     true,
	"criminal":      true,
	"entertainer":   true,
	"folk hero":     true,
	"folk-hero":     true,
	"guild artisan": true,
	"guild-artisan": true,
	"hermit":        true,
	"noble":         true,
	"outlander":     true,
	"sage":          true,
	"sailor":        true,
	"soldier":       true,
	"urchin":        true,
}

// buildCharacterRequest binds the payload for finalizing a campaign
// character's race, class, background, and ability scores.
type buildCharacterRequest struct {
	Race       string         `json:"race"`
	Class      string         `json:"class"`
	Background string         `json:"background"`
	Abilities  abilitiesInput `json:"abilities"`
}

// buildCharacterResponse is the shape returned after a successful character
// build. It echoes the validated choices and reports derived level-1 stats.
type buildCharacterResponse struct {
	CharacterID      string `json:"character_id"`
	Race             string `json:"race"`
	Class            string `json:"class"`
	Background       string `json:"background"`
	Level            int    `json:"level"`
	HPMax            int    `json:"hp_max"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
}

// buildCharacterHandler validates a campaign character's creation choices and
// returns derived level-1 statistics. Only the character's owner may call it.
// Invalid race/class/background or ability scores outside 1..30 return 400.
func buildCharacterHandler(w http.ResponseWriter, r *http.Request) {
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
		log.Printf("build character member query error: %v", err)
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

	var req buildCharacterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if _, classOK := classHitDice[req.Class]; !classOK || !validRaces[req.Race] || !validBackgrounds[req.Background] {
		writeError(w, http.StatusBadRequest, "invalid race, class, or background")
		return
	}
	if !validateAbilityScore(req.Abilities.Str) ||
		!validateAbilityScore(req.Abilities.Dex) ||
		!validateAbilityScore(req.Abilities.Con) ||
		!validateAbilityScore(req.Abilities.Int) ||
		!validateAbilityScore(req.Abilities.Wis) ||
		!validateAbilityScore(req.Abilities.Cha) {
		writeError(w, http.StatusBadRequest, "ability scores must be between 1 and 30")
		return
	}

	conMod := abilityModifier(req.Abilities.Con)
	hpMax := classHitDice[req.Class] + conMod
	level := 1

	if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET class=%s, hp_max=%d, hp_current=%d, level=%d, con_modifier=%d, str_score=%d, dex_score=%d, con_score=%d, int_score=%d, wis_score=%d, cha_score=%d WHERE campaign_id=%s AND character_id=%s;",
		sq(req.Class), hpMax, hpMax, level, conMod,
		req.Abilities.Str, req.Abilities.Dex, req.Abilities.Con, req.Abilities.Int, req.Abilities.Wis, req.Abilities.Cha,
		sq(campaignID), sq(characterID))); err != nil {
		log.Printf("build character update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, buildCharacterResponse{
		CharacterID:      characterID,
		Race:             req.Race,
		Class:            req.Class,
		Background:       req.Background,
		Level:            level,
		HPMax:            hpMax,
		ProficiencyBonus: proficiencyBonus(level),
	})
}

// levelUpRequest binds the payload for leveling up a campaign character.
type levelUpRequest struct {
	Level int `json:"level"`
}

// levelUpResponse is the shape returned after a successful level-up.
type levelUpResponse struct {
	CharacterID      string `json:"character_id"`
	Level            int    `json:"level"`
	HPMax            int    `json:"hp_max"`
	HitDice          string `json:"hit_dice"`
	ProficiencyBonus int    `json:"proficiency_bonus"`
}

// levelUpHandler advances a campaign character by exactly one level. Only the
// character's owner may call it. The request level must be one higher than the
// current level. HP max increases by the deterministic average of the class hit
// die (rounded up) plus the stored constitution modifier. Missing requests or
// invalid levels return 400; non-owner requests return 403.
func levelUpHandler(w http.ResponseWriter, r *http.Request) {
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
		log.Printf("level up member query error: %v", err)
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

	var req levelUpRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level != member.Level+1 {
		writeError(w, http.StatusBadRequest, "invalid level")
		return
	}

	hitDie, classOK := classHitDice[member.Class]
	if !classOK {
		writeError(w, http.StatusBadRequest, "invalid class")
		return
	}

	// Deterministic average of the hit die (half the die max, rounded up)
	// plus the stored constitution modifier.
	gain := hitDie/2 + 1 + member.ConModifier
	if gain < 1 {
		gain = 1
	}
	newHPMax := member.HPMax + gain
	newLevel := req.Level

	if err := dbExec(fmt.Sprintf("UPDATE play_campaign_members SET level=%d, hp_max=%d WHERE campaign_id=%s AND character_id=%s;",
		newLevel, newHPMax, sq(campaignID), sq(characterID))); err != nil {
		log.Printf("level up update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, levelUpResponse{
		CharacterID:      characterID,
		Level:            newLevel,
		HPMax:            newHPMax,
		HitDice:          fmt.Sprintf("1d%d", hitDie),
		ProficiencyBonus: proficiencyBonus(newLevel),
	})
}

// validAbilities is the set of ability names supported by skill checks.
var validAbilities = map[string]bool{
	"str": true,
	"dex": true,
	"con": true,
	"int": true,
	"wis": true,
	"cha": true,
}

// validSkills is the set of skill names supported by skill checks.
var validSkills = map[string]bool{
	"acrobatics":      true,
	"animal-handling": true,
	"arcana":          true,
	"athletics":       true,
	"deception":       true,
	"history":         true,
	"insight":         true,
	"intimidation":    true,
	"investigation":   true,
	"medicine":        true,
	"nature":          true,
	"perception":      true,
	"performance":     true,
	"persuasion":      true,
	"religion":        true,
	"sleight-of-hand": true,
	"stealth":         true,
	"survival":        true,
}

// memberAbilityScore returns the stored ability score for a party member.
func memberAbilityScore(member *playCampaignMember, ability string) int {
	switch ability {
	case "str":
		return member.StrScore
	case "dex":
		return member.DexScore
	case "con":
		return member.ConScore
	case "int":
		return member.IntScore
	case "wis":
		return member.WisScore
	case "cha":
		return member.ChaScore
	default:
		return 10
	}
}

// skillCheckRequest binds the payload for a campaign character skill check.
type skillCheckRequest struct {
	Skill      string `json:"skill"`
	Ability    string `json:"ability"`
	Proficient bool   `json:"proficient"`
	Roll       int    `json:"roll"`
}

// skillCheckResponse is the shape returned after resolving a skill check.
type skillCheckResponse struct {
	CharacterID string `json:"character_id"`
	Skill       string `json:"skill"`
	Ability     string `json:"ability"`
	Modifier    int    `json:"modifier"`
	Total       int    `json:"total"`
}

// skillCheckHandler resolves a skill check for a campaign character using the
// character's stored ability score and level. Only the character's owner may
// call it. Unsupported skills or abilities return 400; non-owner requests
// return 403.
func skillCheckHandler(w http.ResponseWriter, r *http.Request) {
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
		log.Printf("skill check member query error: %v", err)
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

	var req skillCheckRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validSkills[req.Skill] || !validAbilities[req.Ability] {
		writeError(w, http.StatusBadRequest, "invalid skill or ability")
		return
	}

	score := memberAbilityScore(member, req.Ability)
	modifier := abilityModifier(score)
	if req.Proficient {
		modifier += proficiencyBonus(member.Level)
	}

	writeJSON(w, http.StatusOK, skillCheckResponse{
		CharacterID: characterID,
		Skill:       req.Skill,
		Ability:     req.Ability,
		Modifier:    modifier,
		Total:       req.Roll + modifier,
	})
}

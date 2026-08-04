package main

import (
	"encoding/json"
	"net/http"
)

// abilityModifier converts a raw ability score to its 5e modifier. Scores
// below 10 floor the half-value downward (e.g. 9 -> -1, 7 -> -2).
func abilityModifier(score int) int {
	diff := score - 10
	if diff < 0 && diff%2 != 0 {
		diff--
	}
	return diff / 2
}

// proficiencyBonus returns the proficiency bonus for a character level between
// 1 and 20, using the standard 5e progression.
func proficiencyBonus(level int) int {
	switch {
	case level <= 4:
		return 2
	case level <= 8:
		return 3
	case level <= 12:
		return 4
	case level <= 16:
		return 5
	default:
		return 6
	}
}

type abilityModifierRequest struct {
	Score int `json:"score"`
}

type abilityModifierResponse struct {
	Score    int `json:"score"`
	Modifier int `json:"modifier"`
}

// abilityModifierHandler validates a score in the 1..30 range and returns its
// modifier. Scores outside that range are rejected with a 400 error.
func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	var req abilityModifierRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Score < 1 || req.Score > 30 {
		writeError(w, http.StatusBadRequest, "score must be between 1 and 30")
		return
	}
	writeJSON(w, http.StatusOK, abilityModifierResponse{
		Score:    req.Score,
		Modifier: abilityModifier(req.Score),
	})
}

type proficiencyRequest struct {
	Level int `json:"level"`
}

type proficiencyResponse struct {
	Level            int `json:"level"`
	ProficiencyBonus int `json:"proficiency_bonus"`
}

// proficiencyHandler validates a level in the 1..20 range and returns the
// corresponding proficiency bonus.
func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	var req proficiencyRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be between 1 and 20")
		return
	}
	writeJSON(w, http.StatusOK, proficiencyResponse{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
	})
}

type abilitiesInput struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

type armorInput struct {
	Base   int  `json:"base"`
	Shield bool `json:"shield"`
	DexCap int  `json:"dex_cap"`
}

type derivedStatsRequest struct {
	Level     int            `json:"level"`
	Abilities abilitiesInput `json:"abilities"`
	Armor     armorInput     `json:"armor"`
}

type derivedStatsResponse struct {
	Level            int            `json:"level"`
	ProficiencyBonus int            `json:"proficiency_bonus"`
	HPMax            int            `json:"hp_max"`
	ArmorClass       int            `json:"armor_class"`
	Modifiers        map[string]int `json:"modifiers"`
}

// validateAbilityScore checks whether a score is within the 1..30 range used
// by this simplified stat calculator.
func validateAbilityScore(score int) bool {
	return score >= 1 && score <= 30
}

// derivedStatsHandler combines level, ability scores, and armor into a simple
// set of derived statistics. HP is calculated as level * (6 + con modifier),
// and AC is base + capped dex modifier + an optional shield bonus of 2.
func derivedStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req derivedStatsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be between 1 and 20")
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
	if req.Armor.Base <= 0 || req.Armor.DexCap < 0 {
		writeError(w, http.StatusBadRequest, "invalid armor")
		return
	}

	modifiers := map[string]int{
		"str": abilityModifier(req.Abilities.Str),
		"dex": abilityModifier(req.Abilities.Dex),
		"con": abilityModifier(req.Abilities.Con),
		"int": abilityModifier(req.Abilities.Int),
		"wis": abilityModifier(req.Abilities.Wis),
		"cha": abilityModifier(req.Abilities.Cha),
	}

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}

	conMod := modifiers["con"]
	dexMod := modifiers["dex"]
	if dexMod > req.Armor.DexCap {
		dexMod = req.Armor.DexCap
	}

	hpMax := req.Level * (6 + conMod)
	armorClass := req.Armor.Base + dexMod + shieldBonus

	writeJSON(w, http.StatusOK, derivedStatsResponse{
		Level:            req.Level,
		ProficiencyBonus: proficiencyBonus(req.Level),
		HPMax:            hpMax,
		ArmorClass:       armorClass,
		Modifiers:        modifiers,
	})
}

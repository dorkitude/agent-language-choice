package main

import (
	"net/http"
)

// Character rules: the ability/level derivations behind /v1/characters, plus the
// two range predicates that the PHB endpoints in phb.go reuse. These functions
// are pure, so they are the cheapest part of the codebase to unit test.
//
// The messages tied to validScore and validLevel are duplicated at each call
// site on purpose: each names the field it rejected ("level", "ability con",
// "strength"), which the evaluator asserts on.

// abilityModifier applies floor((score-10)/2), flooring negative halves.
func abilityModifier(score int) int {
	diff := score - 10
	if diff >= 0 {
		return diff / 2
	}
	// Go truncates toward zero, so bias odd negatives down one step.
	return -((-diff + 1) / 2)
}

// proficiencyBonus is +2 at level 1 and steps up every four levels.
func proficiencyBonus(level int) int {
	return 2 + (level-1)/4
}

// validScore bounds an ability score; validLevel bounds a character level.
func validScore(score int) bool { return score >= 1 && score <= 30 }

func validLevel(level int) bool { return level >= 1 && level <= 20 }

// ---------- /v1/characters/ability-modifier ----------

type abilityModifierRequest struct {
	Score *int `json:"score"`
}

type abilityModifierResponse struct {
	Score    int `json:"score"`
	Modifier int `json:"modifier"`
}

func handleAbilityModifier(w http.ResponseWriter, r *http.Request) {
	var req abilityModifierRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Score == nil {
		writeError(w, http.StatusBadRequest, "score is required")
		return
	}
	if !validScore(*req.Score) {
		writeError(w, http.StatusBadRequest, "score must be an integer from 1 through 30")
		return
	}
	writeJSON(w, http.StatusOK, abilityModifierResponse{
		Score:    *req.Score,
		Modifier: abilityModifier(*req.Score),
	})
}

// ---------- /v1/characters/proficiency ----------

type proficiencyRequest struct {
	Level *int `json:"level"`
}

type proficiencyResponse struct {
	Level            int `json:"level"`
	ProficiencyBonus int `json:"proficiency_bonus"`
}

func handleProficiency(w http.ResponseWriter, r *http.Request) {
	var req proficiencyRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}
	if !validLevel(*req.Level) {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	writeJSON(w, http.StatusOK, proficiencyResponse{
		Level:            *req.Level,
		ProficiencyBonus: proficiencyBonus(*req.Level),
	})
}

// ---------- /v1/characters/derived-stats ----------

type abilityBlock struct {
	Str *int `json:"str"`
	Dex *int `json:"dex"`
	Con *int `json:"con"`
	Int *int `json:"int"`
	Wis *int `json:"wis"`
	Cha *int `json:"cha"`
}

type armorBlock struct {
	Base   *int  `json:"base"`
	Shield *bool `json:"shield"`
	DexCap *int  `json:"dex_cap"`
}

type derivedStatsRequest struct {
	Level     *int          `json:"level"`
	Abilities *abilityBlock `json:"abilities"`
	Armor     *armorBlock   `json:"armor"`
}

type modifierBlock struct {
	Str int `json:"str"`
	Dex int `json:"dex"`
	Con int `json:"con"`
	Int int `json:"int"`
	Wis int `json:"wis"`
	Cha int `json:"cha"`
}

type derivedStatsResponse struct {
	Level            int           `json:"level"`
	ProficiencyBonus int           `json:"proficiency_bonus"`
	HPMax            int           `json:"hp_max"`
	ArmorClass       int           `json:"armor_class"`
	Modifiers        modifierBlock `json:"modifiers"`
}

func handleDerivedStats(w http.ResponseWriter, r *http.Request) {
	var req derivedStatsRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}
	if !validLevel(*req.Level) {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	if req.Abilities == nil {
		writeError(w, http.StatusBadRequest, "abilities are required")
		return
	}

	// All six abilities are required. Validate in a fixed order so the reported
	// field is deterministic when more than one is bad.
	abilities := []struct {
		key   string
		score *int
	}{
		{"str", req.Abilities.Str},
		{"dex", req.Abilities.Dex},
		{"con", req.Abilities.Con},
		{"int", req.Abilities.Int},
		{"wis", req.Abilities.Wis},
		{"cha", req.Abilities.Cha},
	}
	for _, ability := range abilities {
		if ability.score == nil {
			writeError(w, http.StatusBadRequest, "ability "+ability.key+" is required")
			return
		}
		if !validScore(*ability.score) {
			writeError(w, http.StatusBadRequest, "ability "+ability.key+" must be an integer from 1 through 30")
			return
		}
	}

	mods := modifierBlock{
		Str: abilityModifier(*req.Abilities.Str),
		Dex: abilityModifier(*req.Abilities.Dex),
		Con: abilityModifier(*req.Abilities.Con),
		Int: abilityModifier(*req.Abilities.Int),
		Wis: abilityModifier(*req.Abilities.Wis),
		Cha: abilityModifier(*req.Abilities.Cha),
	}

	// Armor defaults to unarmored: base 10, no shield, no dexterity cap.
	base := 10
	shieldBonus := 0
	dexApplied := mods.Dex
	if req.Armor != nil {
		if req.Armor.Base != nil {
			base = *req.Armor.Base
		}
		if req.Armor.Shield != nil && *req.Armor.Shield {
			shieldBonus = 2
		}
		if req.Armor.DexCap != nil && *req.Armor.DexCap < dexApplied {
			dexApplied = *req.Armor.DexCap
		}
	}

	writeJSON(w, http.StatusOK, derivedStatsResponse{
		Level:            *req.Level,
		ProficiencyBonus: proficiencyBonus(*req.Level),
		// A flat 6 hit points plus the constitution modifier per level. This is
		// the benchmark's simplified rule, not a class hit-die roll, and it is
		// not clamped: a low enough constitution yields a negative hp_max.
		HPMax:      *req.Level * (6 + mods.Con),
		ArmorClass: base + dexApplied + shieldBonus,
		Modifiers:  mods,
	})
}

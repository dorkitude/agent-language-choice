package main

import (
	"net/http"
)

// floorDiv computes floor(numerator / 2), rounding toward negative infinity
// (Go's integer division truncates toward zero, so odd negatives need an
// explicit adjustment). Used for the 5e ability-modifier formula.
func floorDiv(numerator int) int {
	if numerator >= 0 {
		return numerator / 2
	}
	if numerator%2 == 0 {
		return numerator / 2
	}
	return numerator/2 - 1
}

type abilityModifierRequest struct {
	Score *int `json:"score"`
}

func abilityModifierHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req abilityModifierRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Score == nil || *req.Score < 1 || *req.Score > 30 {
		writeError(w, http.StatusBadRequest, "score must be an integer from 1 through 30")
		return
	}
	modifier := floorDiv(*req.Score - 10)
	writeJSON(w, http.StatusOK, map[string]any{
		"score":    *req.Score,
		"modifier": modifier,
	})
}

// proficiencyBonusForLevel implements the 5e level -> proficiency bonus table.
func proficiencyBonusForLevel(level int) int {
	switch {
	case level >= 1 && level <= 4:
		return 2
	case level >= 5 && level <= 8:
		return 3
	case level >= 9 && level <= 12:
		return 4
	case level >= 13 && level <= 16:
		return 5
	default:
		return 6
	}
}

type proficiencyRequest struct {
	Level *int `json:"level"`
}

func proficiencyHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req proficiencyRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"level":             *req.Level,
		"proficiency_bonus": proficiencyBonusForLevel(*req.Level),
	})
}

type abilityScores struct {
	Str *int `json:"str"`
	Dex *int `json:"dex"`
	Con *int `json:"con"`
	Int *int `json:"int"`
	Wis *int `json:"wis"`
	Cha *int `json:"cha"`
}

type armorInfo struct {
	Base   *int `json:"base"`
	Shield bool `json:"shield"`
	DexCap *int `json:"dex_cap"`
}

type derivedStatsRequest struct {
	Level     *int          `json:"level"`
	Abilities abilityScores `json:"abilities"`
	Armor     armorInfo     `json:"armor"`
}

func derivedStatsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req derivedStatsRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	scores := map[string]*int{
		"str": req.Abilities.Str,
		"dex": req.Abilities.Dex,
		"con": req.Abilities.Con,
		"int": req.Abilities.Int,
		"wis": req.Abilities.Wis,
		"cha": req.Abilities.Cha,
	}
	for _, v := range scores {
		if v == nil || *v < 1 || *v > 30 {
			writeError(w, http.StatusBadRequest, "abilities must be integers from 1 through 30")
			return
		}
	}
	if req.Armor.Base == nil {
		writeError(w, http.StatusBadRequest, "armor.base is required")
		return
	}
	if req.Armor.DexCap == nil {
		writeError(w, http.StatusBadRequest, "armor.dex_cap is required")
		return
	}

	modifiers := map[string]int{}
	for k, v := range scores {
		modifiers[k] = floorDiv(*v - 10)
	}

	proficiencyBonus := proficiencyBonusForLevel(*req.Level)
	hpMax := *req.Level * (6 + modifiers["con"])

	dexMod := modifiers["dex"]
	dexBonus := dexMod
	if dexBonus > *req.Armor.DexCap {
		dexBonus = *req.Armor.DexCap
	}
	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	armorClass := *req.Armor.Base + dexBonus + shieldBonus

	writeJSON(w, http.StatusOK, map[string]any{
		"level":             *req.Level,
		"proficiency_bonus": proficiencyBonus,
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers":         modifiers,
	})
}

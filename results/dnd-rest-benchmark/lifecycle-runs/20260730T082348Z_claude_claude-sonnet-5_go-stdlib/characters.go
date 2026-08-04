package main

import (
	"encoding/json"
	"net/http"
)

// abilityModifier converts a raw ability score into its D&D modifier.
func abilityModifier(score int) int {
	diff := score - 10
	if diff >= 0 {
		return diff / 2
	}
	return -(((-diff) + 1) / 2)
}

// proficiencyBonus returns the proficiency bonus for a given character level.
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

func handleAbilityModifier(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Score *int `json:"score"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Score == nil || *req.Score < 1 || *req.Score > 30 {
		writeError(w, http.StatusBadRequest, "score must be an integer from 1 through 30")
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"score":    *req.Score,
		"modifier": abilityModifier(*req.Score),
	})
}

func handleProficiency(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level *int `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"level":             *req.Level,
		"proficiency_bonus": proficiencyBonus(*req.Level),
	})
}

func handleDerivedStats(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level     *int `json:"level"`
		Abilities *struct {
			Str *int `json:"str"`
			Dex *int `json:"dex"`
			Con *int `json:"con"`
			Int *int `json:"int"`
			Wis *int `json:"wis"`
			Cha *int `json:"cha"`
		} `json:"abilities"`
		Armor *struct {
			Base   *int `json:"base"`
			Shield bool `json:"shield"`
			DexCap *int `json:"dex_cap"`
		} `json:"armor"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	if req.Abilities == nil {
		writeError(w, http.StatusBadRequest, "abilities are required")
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
	for _, key := range []string{"str", "dex", "con", "int", "wis", "cha"} {
		v := scores[key]
		if v == nil || *v < 1 || *v > 30 {
			writeError(w, http.StatusBadRequest, "ability scores must be integers from 1 through 30")
			return
		}
	}
	if req.Armor == nil || req.Armor.Base == nil || req.Armor.DexCap == nil {
		writeError(w, http.StatusBadRequest, "armor is required")
		return
	}

	strMod := abilityModifier(*req.Abilities.Str)
	dexMod := abilityModifier(*req.Abilities.Dex)
	conMod := abilityModifier(*req.Abilities.Con)
	intMod := abilityModifier(*req.Abilities.Int)
	wisMod := abilityModifier(*req.Abilities.Wis)
	chaMod := abilityModifier(*req.Abilities.Cha)

	hpMax := *req.Level * (6 + conMod)

	shieldBonus := 0
	if req.Armor.Shield {
		shieldBonus = 2
	}
	dexApplied := dexMod
	if dexApplied > *req.Armor.DexCap {
		dexApplied = *req.Armor.DexCap
	}
	armorClass := *req.Armor.Base + dexApplied + shieldBonus

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"level":             *req.Level,
		"proficiency_bonus": proficiencyBonus(*req.Level),
		"hp_max":            hpMax,
		"armor_class":       armorClass,
		"modifiers": map[string]int{
			"str": strMod,
			"dex": dexMod,
			"con": conMod,
			"int": intMod,
			"wis": wisMod,
			"cha": chaMod,
		},
	})
}

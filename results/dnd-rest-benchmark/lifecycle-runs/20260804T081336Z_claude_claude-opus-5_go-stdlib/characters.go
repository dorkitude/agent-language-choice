package main

import (
	"encoding/json"
	"net/http"
)

// Character build rules: ability modifiers, proficiency bonus, and the derived
// statistics that combine them. Stateless and deterministic.

const (
	minAbilityScore = 1
	maxAbilityScore = 30
	minLevel        = 1
	maxLevel        = 20
)

// abilityKeys is the fixed set of abilities a derived-stats request must supply,
// and also fixes the key set of the response's modifiers object.
var abilityKeys = []string{"str", "dex", "con", "int", "wis", "cha"}

// abilityModifier floors (score-10)/2. The arithmetic shift is deliberate:
// integer division in Go truncates toward zero, which would round -1.5 to -1
// instead of the required -2.
func abilityModifier(score int) int {
	return (score - 10) >> 1
}

// proficiencyBonus is +2 at levels 1-4 and rises by one every four levels.
func proficiencyBonus(level int) int {
	return (level-1)/4 + 2
}

// readLevel reads and range-checks a character level, writing the 400 itself.
func readLevel(w http.ResponseWriter, raw *json.RawMessage) (int, bool) {
	level, ok := asInt(raw)
	if !ok {
		writeError(w, http.StatusBadRequest, "level must be an integer")
		return 0, false
	}
	if level < minLevel || level > maxLevel {
		writeError(w, http.StatusBadRequest, "level must be between 1 and 20")
		return 0, false
	}
	return level, true
}

// ---------- POST /v1/characters/ability-modifier ----------

type abilityModifierRequest struct {
	Score *json.RawMessage `json:"score"`
}

type abilityModifierResponse struct {
	Score    int `json:"score"`
	Modifier int `json:"modifier"`
}

func handleAbilityModifier(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req abilityModifierRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	score, ok := asInt(req.Score)
	if !ok {
		writeError(w, http.StatusBadRequest, "score must be an integer")
		return
	}
	if score < minAbilityScore || score > maxAbilityScore {
		writeError(w, http.StatusBadRequest, "score must be between 1 and 30")
		return
	}
	writeJSON(w, http.StatusOK, abilityModifierResponse{Score: score, Modifier: abilityModifier(score)})
}

// ---------- POST /v1/characters/proficiency ----------

type proficiencyRequest struct {
	Level *json.RawMessage `json:"level"`
}

type proficiencyResponse struct {
	Level            int `json:"level"`
	ProficiencyBonus int `json:"proficiency_bonus"`
}

func handleProficiency(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req proficiencyRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	level, ok := readLevel(w, req.Level)
	if !ok {
		return
	}
	writeJSON(w, http.StatusOK, proficiencyResponse{Level: level, ProficiencyBonus: proficiencyBonus(level)})
}

// ---------- POST /v1/characters/derived-stats ----------

type armorInput struct {
	Base   *json.RawMessage `json:"base"`
	Shield *bool            `json:"shield"`
	DexCap *json.RawMessage `json:"dex_cap"`
}

type derivedStatsRequest struct {
	Level     *json.RawMessage            `json:"level"`
	Abilities map[string]*json.RawMessage `json:"abilities"`
	Armor     *armorInput                 `json:"armor"`
}

type derivedStatsResponse struct {
	Level            int            `json:"level"`
	ProficiencyBonus int            `json:"proficiency_bonus"`
	HPMax            int            `json:"hp_max"`
	ArmorClass       int            `json:"armor_class"`
	Modifiers        map[string]int `json:"modifiers"`
}

// hitDieAverage is the fixed per-level hit point gain before the CON modifier.
const hitDieAverage = 6

// shieldBonus is the AC granted by a shield.
const shieldBonus = 2

func handleDerivedStats(w http.ResponseWriter, r *http.Request) {
	if !requirePost(w, r) {
		return
	}
	var req derivedStatsRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}

	level, ok := readLevel(w, req.Level)
	if !ok {
		return
	}
	if req.Abilities == nil {
		writeError(w, http.StatusBadRequest, "abilities are required")
		return
	}

	modifiers := make(map[string]int, len(abilityKeys))
	for _, key := range abilityKeys {
		score, ok := asInt(req.Abilities[key])
		if !ok {
			writeError(w, http.StatusBadRequest, "ability "+key+" must be an integer")
			return
		}
		if score < minAbilityScore || score > maxAbilityScore {
			writeError(w, http.StatusBadRequest, "ability "+key+" must be between 1 and 30")
			return
		}
		modifiers[key] = abilityModifier(score)
	}

	armorClass, ok := armorClassOf(w, req.Armor, modifiers["dex"])
	if !ok {
		return
	}

	writeJSON(w, http.StatusOK, derivedStatsResponse{
		Level:            level,
		ProficiencyBonus: proficiencyBonus(level),
		HPMax:            level * (hitDieAverage + modifiers["con"]),
		ArmorClass:       armorClass,
		Modifiers:        modifiers,
	})
}

// armorClassOf computes AC from the optional armor block. Omitted armor means
// unarmored: base 10, no shield, and the full DEX modifier applied (an absent
// dex_cap is an uncapped cap, not a zero one). It writes the 400 itself.
func armorClassOf(w http.ResponseWriter, armor *armorInput, dexModifier int) (int, bool) {
	base := 10
	shield := 0
	dexCap := dexModifier

	if armor != nil {
		if armor.Base != nil {
			v, ok := asInt(armor.Base)
			if !ok {
				writeError(w, http.StatusBadRequest, "armor base must be an integer")
				return 0, false
			}
			base = v
		}
		if armor.Shield != nil && *armor.Shield {
			shield = shieldBonus
		}
		if armor.DexCap != nil {
			v, ok := asInt(armor.DexCap)
			if !ok {
				writeError(w, http.StatusBadRequest, "armor dex_cap must be an integer")
				return 0, false
			}
			dexCap = v
		}
	}

	dexBonus := min(dexModifier, dexCap)
	return base + dexBonus + shield, true
}

package main

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
)

// Selected Player's Handbook-style rules: spell slots, long rests, and carrying
// capacity. All results are deterministic table lookups or arithmetic; nothing
// here reads or writes persistent state.

// fullCasterSlots is the standard full-caster spell slot table, indexed by
// character level (1-20). Each row lists slots for spell levels 1-9.
var fullCasterSlots = [21][9]int{
	1:  {2},
	2:  {3},
	3:  {4, 2},
	4:  {4, 3},
	5:  {4, 3, 2},
	6:  {4, 3, 3},
	7:  {4, 3, 3, 1},
	8:  {4, 3, 3, 2},
	9:  {4, 3, 3, 3, 1},
	10: {4, 3, 3, 3, 2},
	11: {4, 3, 3, 3, 2, 1},
	12: {4, 3, 3, 3, 2, 1},
	13: {4, 3, 3, 3, 2, 1, 1},
	14: {4, 3, 3, 3, 2, 1, 1},
	15: {4, 3, 3, 3, 2, 1, 1, 1},
	16: {4, 3, 3, 3, 2, 1, 1, 1},
	17: {4, 3, 3, 3, 2, 1, 1, 1, 1},
	18: {4, 3, 3, 3, 3, 1, 1, 1, 1},
	19: {4, 3, 3, 3, 3, 2, 1, 1, 1},
	20: {4, 3, 3, 3, 3, 2, 2, 1, 1},
}

// fullCasterClasses are the classes this endpoint supports; half-casters and
// warlocks use different tables and are rejected rather than approximated.
var fullCasterClasses = map[string]bool{
	"wizard":   true,
	"sorcerer": true,
	"bard":     true,
	"cleric":   true,
	"druid":    true,
}

type spellSlotRequest struct {
	Class *string          `json:"class"`
	Level *json.RawMessage `json:"level"`
}

type spellSlotResponse struct {
	Class string         `json:"class"`
	Level int            `json:"level"`
	Slots map[string]int `json:"slots"`
}

// ---------- POST /v1/phb/spell-slots ----------

func handleSpellSlots(w http.ResponseWriter, r *http.Request) {
	var req spellSlotRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	name, ok := requiredString(req.Class)
	if !ok {
		writeError(w, http.StatusBadRequest, "class is required")
		return
	}
	class := strings.ToLower(name)
	if !fullCasterClasses[class] {
		writeError(w, http.StatusBadRequest, "unsupported class")
		return
	}
	level, ok := asInt(req.Level)
	if !ok {
		writeError(w, http.StatusBadRequest, "level must be an integer")
		return
	}
	if level < 1 || level > 20 {
		writeError(w, http.StatusBadRequest, "level must be between 1 and 20")
		return
	}

	slots := map[string]int{}
	for i, count := range fullCasterSlots[level] {
		if count > 0 {
			slots[strconv.Itoa(i+1)] = count
		}
	}
	writeJSON(w, http.StatusOK, spellSlotResponse{Class: class, Level: level, Slots: slots})
}

// ---------- POST /v1/phb/rests/long ----------

type longRestRequest struct {
	Level           *json.RawMessage `json:"level"`
	HPCurrent       *json.RawMessage `json:"hp_current"`
	HPMax           *json.RawMessage `json:"hp_max"`
	HitDiceSpent    *json.RawMessage `json:"hit_dice_spent"`
	ExhaustionLevel *json.RawMessage `json:"exhaustion_level"`
}

type longRestResponse struct {
	HPCurrent       int `json:"hp_current"`
	HitDiceSpent    int `json:"hit_dice_spent"`
	ExhaustionLevel int `json:"exhaustion_level"`
}

func handleLongRest(w http.ResponseWriter, r *http.Request) {
	var req longRestRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	level, ok := asInt(req.Level)
	if !ok || level < 1 || level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer between 1 and 20")
		return
	}
	if _, ok := asInt(req.HPCurrent); !ok {
		writeError(w, http.StatusBadRequest, "hp_current must be an integer")
		return
	}
	hpMax, ok := asInt(req.HPMax)
	if !ok || hpMax < 1 {
		writeError(w, http.StatusBadRequest, "hp_max must be a positive integer")
		return
	}
	spent, ok := asInt(req.HitDiceSpent)
	if !ok || spent < 0 {
		writeError(w, http.StatusBadRequest, "hit_dice_spent must be a non-negative integer")
		return
	}
	exhaustion, ok := asInt(req.ExhaustionLevel)
	if !ok || exhaustion < 0 {
		writeError(w, http.StatusBadRequest, "exhaustion_level must be a non-negative integer")
		return
	}

	// A long rest restores all hit points, recovers half the character level in
	// spent hit dice (rounded down, at least one), and removes one level of
	// exhaustion. hp_current is validated but unused: the result is always hp_max.
	recovered := level / 2
	if recovered < 1 {
		recovered = 1
	}
	remaining := spent - recovered
	if remaining < 0 {
		remaining = 0
	}
	if exhaustion > 0 {
		exhaustion--
	}

	writeJSON(w, http.StatusOK, longRestResponse{
		HPCurrent:       hpMax,
		HitDiceSpent:    remaining,
		ExhaustionLevel: exhaustion,
	})
}

// ---------- POST /v1/phb/equipment-load ----------

type equipmentLoadRequest struct {
	Strength *json.RawMessage `json:"strength"`
	Weight   *json.RawMessage `json:"weight"`
}

type equipmentLoadResponse struct {
	Capacity   int  `json:"capacity"`
	Weight     int  `json:"weight"`
	Encumbered bool `json:"encumbered"`
}

func handleEquipmentLoad(w http.ResponseWriter, r *http.Request) {
	var req equipmentLoadRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	strength, ok := asInt(req.Strength)
	if !ok || strength < 1 {
		writeError(w, http.StatusBadRequest, "strength must be a positive integer")
		return
	}
	weight, ok := asInt(req.Weight)
	if !ok || weight < 0 {
		writeError(w, http.StatusBadRequest, "weight must be a non-negative integer")
		return
	}

	capacity := strength * 15
	writeJSON(w, http.StatusOK, equipmentLoadResponse{
		Capacity:   capacity,
		Weight:     weight,
		Encumbered: weight > capacity,
	})
}

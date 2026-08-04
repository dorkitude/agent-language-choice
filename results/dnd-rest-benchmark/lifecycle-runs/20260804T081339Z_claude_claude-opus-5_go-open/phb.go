package main

import (
	"net/http"
	"strconv"
	"strings"
)

// Player's Handbook table lookups: spell slots, long-rest recovery and carrying
// capacity. All three are stateless and reuse the range predicates from
// characters.go, so a level or score rejected here is rejected there too.

// ---------- POST /v1/phb/spell-slots ----------

// wizardSlots is the full-caster slot progression, indexed by character level.
// Each row lists slots for spell levels 1..9 in order and is truncated after the
// highest level the character can cast, so a row's length is meaningful.
var wizardSlots = map[int][]int{
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

type spellSlotsRequest struct {
	Class *string `json:"class"`
	Level *int    `json:"level"`
}

type spellSlotsResponse struct {
	Class string         `json:"class"`
	Level int            `json:"level"`
	Slots map[string]int `json:"slots"`
}

func handleSpellSlots(w http.ResponseWriter, r *http.Request) {
	var req spellSlotsRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Class == nil || req.Level == nil {
		writeError(w, http.StatusBadRequest, "class and level are required")
		return
	}
	// Only the full-caster wizard table is implemented. The echoed class is the
	// normalized form, but the rejection message quotes the caller's spelling.
	class := strings.ToLower(strings.TrimSpace(*req.Class))
	if class != "wizard" {
		writeError(w, http.StatusBadRequest, "unsupported class: "+*req.Class)
		return
	}
	if !validLevel(*req.Level) {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	row := wizardSlots[*req.Level]
	slots := make(map[string]int, len(row))
	for i, count := range row {
		slots[strconv.Itoa(i+1)] = count
	}
	writeJSON(w, http.StatusOK, spellSlotsResponse{
		Class: class,
		Level: *req.Level,
		Slots: slots,
	})
}

// ---------- POST /v1/phb/rests/long ----------

type longRestRequest struct {
	Level           *int `json:"level"`
	HPCurrent       *int `json:"hp_current"`
	HPMax           *int `json:"hp_max"`
	HitDiceSpent    *int `json:"hit_dice_spent"`
	ExhaustionLevel *int `json:"exhaustion_level"`
}

type longRestResponse struct {
	HPCurrent       int `json:"hp_current"`
	HitDiceSpent    int `json:"hit_dice_spent"`
	ExhaustionLevel int `json:"exhaustion_level"`
}

func handleLongRest(w http.ResponseWriter, r *http.Request) {
	var req longRestRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Level == nil || req.HPMax == nil {
		writeError(w, http.StatusBadRequest, "level and hp_max are required")
		return
	}
	if !validLevel(*req.Level) {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	if *req.HPMax < 0 {
		writeError(w, http.StatusBadRequest, "hp_max must not be negative")
		return
	}
	if req.HPCurrent != nil && *req.HPCurrent < 0 {
		writeError(w, http.StatusBadRequest, "hp_current must not be negative")
		return
	}

	spent := 0
	if req.HitDiceSpent != nil {
		spent = *req.HitDiceSpent
	}
	if spent < 0 {
		writeError(w, http.StatusBadRequest, "hit_dice_spent must not be negative")
		return
	}
	exhaustion := 0
	if req.ExhaustionLevel != nil {
		exhaustion = *req.ExhaustionLevel
	}
	if exhaustion < 0 {
		writeError(w, http.StatusBadRequest, "exhaustion_level must not be negative")
		return
	}

	// A long rest regains half the character's level in hit dice, rounded down,
	// but never fewer than one.
	regained := *req.Level / 2
	if regained < 1 {
		regained = 1
	}
	spent -= regained
	if spent < 0 {
		spent = 0
	}
	if exhaustion > 0 {
		exhaustion--
	}

	writeJSON(w, http.StatusOK, longRestResponse{
		HPCurrent:       *req.HPMax,
		HitDiceSpent:    spent,
		ExhaustionLevel: exhaustion,
	})
}

// ---------- POST /v1/phb/equipment-load ----------

type equipmentLoadRequest struct {
	Strength *int     `json:"strength"`
	Weight   *float64 `json:"weight"`
}

type equipmentLoadResponse struct {
	Capacity   int     `json:"capacity"`
	Weight     float64 `json:"weight"`
	Encumbered bool    `json:"encumbered"`
}

func handleEquipmentLoad(w http.ResponseWriter, r *http.Request) {
	var req equipmentLoadRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Strength == nil || req.Weight == nil {
		writeError(w, http.StatusBadRequest, "strength and weight are required")
		return
	}
	if !validScore(*req.Strength) {
		writeError(w, http.StatusBadRequest, "strength must be an integer from 1 through 30")
		return
	}
	if *req.Weight < 0 {
		writeError(w, http.StatusBadRequest, "weight must not be negative")
		return
	}
	// Carrying capacity is strength times 15 pounds; a load exactly at capacity
	// is not encumbered.
	capacity := *req.Strength * 15
	writeJSON(w, http.StatusOK, equipmentLoadResponse{
		Capacity:   capacity,
		Weight:     *req.Weight,
		Encumbered: *req.Weight > float64(capacity),
	})
}

package main

import (
	"encoding/json"
	"net/http"
	"strconv"
)

// --- Selected PHB rules (Maintenance Stage 7) ---

// spellSlotTable maps a class to per-level slot layouts. For this benchmark we
// support wizard level 5.
var spellSlotTable = map[string]map[int]map[int]int{
	"wizard": {
		5: {1: 4, 2: 3, 3: 2},
	},
}

func handleSpellSlots(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Class string `json:"class"`
		Level *int   `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Level == nil {
		badRequest(w)
		return
	}
	byLevel, ok := spellSlotTable[req.Class]
	if !ok {
		badRequest(w)
		return
	}
	slots, ok := byLevel[*req.Level]
	if !ok {
		badRequest(w)
		return
	}
	// JSON object keys must be strings; emit slot levels as string keys.
	slotView := map[string]int{}
	for lvl, count := range slots {
		slotView[strconv.Itoa(lvl)] = count
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"class": req.Class,
		"level": *req.Level,
		"slots": slotView,
	})
}

func handleLongRest(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level           *int `json:"level"`
		HPCurrent       *int `json:"hp_current"`
		HPMax           *int `json:"hp_max"`
		HitDiceSpent    *int `json:"hit_dice_spent"`
		ExhaustionLevel *int `json:"exhaustion_level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.Level == nil || req.HPMax == nil || req.HitDiceSpent == nil || req.ExhaustionLevel == nil {
		badRequest(w)
		return
	}
	if *req.Level < 1 || *req.HPMax < 0 || *req.HitDiceSpent < 0 || *req.ExhaustionLevel < 0 {
		badRequest(w)
		return
	}

	// Restore hit dice: recover up to half level (rounded down), minimum 1.
	recovered := *req.Level / 2
	if recovered < 1 {
		recovered = 1
	}
	hitDiceSpent := *req.HitDiceSpent - recovered
	if hitDiceSpent < 0 {
		hitDiceSpent = 0
	}

	exhaustion := *req.ExhaustionLevel - 1
	if exhaustion < 0 {
		exhaustion = 0
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"hp_current":       *req.HPMax,
		"hit_dice_spent":   hitDiceSpent,
		"exhaustion_level": exhaustion,
	})
}

func handleEquipmentLoad(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Strength *int `json:"strength"`
		Weight   *int `json:"weight"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.Strength == nil || req.Weight == nil {
		badRequest(w)
		return
	}
	if *req.Strength < 0 || *req.Weight < 0 {
		badRequest(w)
		return
	}
	capacity := *req.Strength * 15
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"capacity":   capacity,
		"weight":     *req.Weight,
		"encumbered": *req.Weight > capacity,
	})
}

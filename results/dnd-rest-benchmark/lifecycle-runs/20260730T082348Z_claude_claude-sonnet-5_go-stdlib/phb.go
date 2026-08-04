package main

import (
	"encoding/json"
	"net/http"
)

var wizardSlotsByLevel = map[int]map[string]int{
	5: {"1": 4, "2": 3, "3": 2},
}

func handleSpellSlots(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Class string `json:"class"`
		Level int    `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Class != "wizard" {
		writeError(w, http.StatusBadRequest, "unsupported class")
		return
	}
	slots, ok := wizardSlotsByLevel[req.Level]
	if !ok {
		writeError(w, http.StatusBadRequest, "unsupported level")
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"class": req.Class,
		"level": req.Level,
		"slots": slots,
	})
}

func handleLongRest(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level           int `json:"level"`
		HPCurrent       int `json:"hp_current"`
		HPMax           int `json:"hp_max"`
		HitDiceSpent    int `json:"hit_dice_spent"`
		ExhaustionLevel int `json:"exhaustion_level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level <= 0 || req.HPMax < 0 || req.HPCurrent < 0 || req.HitDiceSpent < 0 || req.ExhaustionLevel < 0 {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	maxRecoverable := req.Level / 2
	if maxRecoverable < 1 {
		maxRecoverable = 1
	}

	hitDiceSpent := req.HitDiceSpent - maxRecoverable
	if hitDiceSpent < 0 {
		hitDiceSpent = 0
	}

	exhaustionLevel := req.ExhaustionLevel - 1
	if exhaustionLevel < 0 {
		exhaustionLevel = 0
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"hp_current":       req.HPMax,
		"hit_dice_spent":   hitDiceSpent,
		"exhaustion_level": exhaustionLevel,
	})
}

func handleEquipmentLoad(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Strength int `json:"strength"`
		Weight   int `json:"weight"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Strength < 0 || req.Weight < 0 {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	capacity := req.Strength * 15

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"capacity":   capacity,
		"weight":     req.Weight,
		"encumbered": req.Weight > capacity,
	})
}

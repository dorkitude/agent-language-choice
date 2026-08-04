package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

func spellSlotsHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Class string `json:"class"`
		Level int    `json:"level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if strings.ToLower(req.Class) != "wizard" {
		badRequest(w, "unsupported class")
		return
	}
	if req.Level < 1 || req.Level > 20 {
		badRequest(w, "level must be between 1 and 20")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"class": req.Class,
		"level": req.Level,
		"slots": wizardSpellSlots[req.Level],
	})
}

func longRestHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Level           int `json:"level"`
		HPCurrent       int `json:"hp_current"`
		HPMax           int `json:"hp_max"`
		HitDiceSpent    int `json:"hit_dice_spent"`
		ExhaustionLevel int `json:"exhaustion_level"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if req.Level < 1 {
		badRequest(w, "level must be at least 1")
		return
	}
	if req.HPMax < 1 {
		badRequest(w, "hp_max must be at least 1")
		return
	}
	if req.HPCurrent < 0 || req.HPCurrent > req.HPMax {
		badRequest(w, "hp_current must be between 0 and hp_max")
		return
	}
	if req.HitDiceSpent < 0 || req.HitDiceSpent > req.Level {
		badRequest(w, "hit_dice_spent must be between 0 and level")
		return
	}
	if req.ExhaustionLevel < 0 {
		badRequest(w, "exhaustion_level must be non-negative")
		return
	}

	restored := req.Level / 2
	if restored < 1 {
		restored = 1
	}
	if restored > req.HitDiceSpent {
		restored = req.HitDiceSpent
	}

	exhaustion := req.ExhaustionLevel - 1
	if exhaustion < 0 {
		exhaustion = 0
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"hp_current":       req.HPMax,
		"hit_dice_spent":   req.HitDiceSpent - restored,
		"exhaustion_level": exhaustion,
	})
}

func equipmentLoadHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Strength int `json:"strength"`
		Weight   int `json:"weight"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if req.Strength < 1 {
		badRequest(w, "strength must be at least 1")
		return
	}
	if req.Weight < 0 {
		badRequest(w, "weight must be non-negative")
		return
	}

	capacity := req.Strength * 15

	writeJSON(w, http.StatusOK, map[string]any{
		"capacity":   capacity,
		"weight":     req.Weight,
		"encumbered": req.Weight > capacity,
	})
}

package main

import (
	"net/http"
)

type spellSlotsRequest struct {
	Class *string `json:"class"`
	Level *int    `json:"level"`
}

// wizardSpellSlots maps wizard level to spell-level -> slot-count.
var wizardSpellSlots = map[int]map[string]int{
	5: {"1": 4, "2": 3, "3": 2},
}

func spellSlotsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req spellSlotsRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Class == nil || *req.Class != "wizard" {
		writeError(w, http.StatusBadRequest, "unsupported class")
		return
	}
	if req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}
	slots, ok := wizardSpellSlots[*req.Level]
	if !ok {
		writeError(w, http.StatusBadRequest, "unsupported level")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"class": *req.Class,
		"level": *req.Level,
		"slots": slots,
	})
}

type longRestRequest struct {
	Level           *int `json:"level"`
	HPCurrent       *int `json:"hp_current"`
	HPMax           *int `json:"hp_max"`
	HitDiceSpent    *int `json:"hit_dice_spent"`
	ExhaustionLevel *int `json:"exhaustion_level"`
}

func longRestHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req longRestRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Level == nil || *req.Level < 1 || *req.Level > 20 {
		writeError(w, http.StatusBadRequest, "level must be an integer from 1 through 20")
		return
	}
	if req.HPCurrent == nil {
		writeError(w, http.StatusBadRequest, "hp_current is required")
		return
	}
	if req.HPMax == nil || *req.HPMax < 0 {
		writeError(w, http.StatusBadRequest, "hp_max is required")
		return
	}
	if req.HitDiceSpent == nil || *req.HitDiceSpent < 0 {
		writeError(w, http.StatusBadRequest, "hit_dice_spent must be a non-negative integer")
		return
	}
	if req.ExhaustionLevel == nil || *req.ExhaustionLevel < 0 {
		writeError(w, http.StatusBadRequest, "exhaustion_level must be a non-negative integer")
		return
	}

	maxRecoverable := *req.Level / 2
	if maxRecoverable < 1 {
		maxRecoverable = 1
	}
	hitDiceSpent := *req.HitDiceSpent - maxRecoverable
	if hitDiceSpent < 0 {
		hitDiceSpent = 0
	}

	exhaustionLevel := *req.ExhaustionLevel - 1
	if exhaustionLevel < 0 {
		exhaustionLevel = 0
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"hp_current":       *req.HPMax,
		"hit_dice_spent":   hitDiceSpent,
		"exhaustion_level": exhaustionLevel,
	})
}

type equipmentLoadRequest struct {
	Strength *int `json:"strength"`
	Weight   *int `json:"weight"`
}

func equipmentLoadHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req equipmentLoadRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Strength == nil || *req.Strength < 0 {
		writeError(w, http.StatusBadRequest, "strength must be a non-negative integer")
		return
	}
	if req.Weight == nil || *req.Weight < 0 {
		writeError(w, http.StatusBadRequest, "weight must be a non-negative integer")
		return
	}
	capacity := *req.Strength * 15
	writeJSON(w, http.StatusOK, map[string]any{
		"capacity":   capacity,
		"weight":     *req.Weight,
		"encumbered": *req.Weight > capacity,
	})
}

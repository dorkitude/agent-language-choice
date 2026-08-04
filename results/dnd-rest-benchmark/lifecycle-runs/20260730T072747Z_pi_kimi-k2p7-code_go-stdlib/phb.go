package main

import (
	"encoding/json"
	"net/http"
)

type spellSlotsRequest struct {
	Class string `json:"class"`
	Level int    `json:"level"`
}

type spellSlotsResponse struct {
	Class string         `json:"class"`
	Level int            `json:"level"`
	Slots map[string]int `json:"slots"`
}

// spellSlotsHandler returns the fixed spell slot table for a level 5 wizard.
// Other classes and levels are rejected to match the original scope.
func spellSlotsHandler(w http.ResponseWriter, r *http.Request) {
	var req spellSlotsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Class != "wizard" || req.Level != 5 {
		writeError(w, http.StatusBadRequest, "unsupported class or level")
		return
	}
	writeJSON(w, http.StatusOK, spellSlotsResponse{
		Class: "wizard",
		Level: 5,
		Slots: map[string]int{"1": 4, "2": 3, "3": 2},
	})
}

type longRestRequest struct {
	Level           int `json:"level"`
	HPCurrent       int `json:"hp_current"`
	HPMax           int `json:"hp_max"`
	HitDiceSpent    int `json:"hit_dice_spent"`
	ExhaustionLevel int `json:"exhaustion_level"`
}

type longRestResponse struct {
	HPCurrent       int `json:"hp_current"`
	HitDiceSpent    int `json:"hit_dice_spent"`
	ExhaustionLevel int `json:"exhaustion_level"`
}

// longRestHandler restores HP to maximum and recovers a portion of spent hit
// dice. It also reduces exhaustion by one level, but never below zero.
func longRestHandler(w http.ResponseWriter, r *http.Request) {
	var req longRestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Level < 1 || req.HPMax < 1 || req.HitDiceSpent < 0 || req.ExhaustionLevel < 0 {
		writeError(w, http.StatusBadRequest, "invalid request")
		return
	}

	hpCurrent := req.HPMax

	restored := req.Level / 2
	if restored < 1 {
		restored = 1
	}
	hitDiceSpent := req.HitDiceSpent - restored
	if hitDiceSpent < 0 {
		hitDiceSpent = 0
	}

	exhaustionLevel := req.ExhaustionLevel - 1
	if exhaustionLevel < 0 {
		exhaustionLevel = 0
	}

	writeJSON(w, http.StatusOK, longRestResponse{
		HPCurrent:       hpCurrent,
		HitDiceSpent:    hitDiceSpent,
		ExhaustionLevel: exhaustionLevel,
	})
}

type equipmentLoadRequest struct {
	Strength int `json:"strength"`
	Weight   int `json:"weight"`
}

type equipmentLoadResponse struct {
	Capacity   int  `json:"capacity"`
	Weight     int  `json:"weight"`
	Encumbered bool `json:"encumbered"`
}

// equipmentLoadHandler calculates carrying capacity as strength * 15 pounds and
// reports whether the carried weight exceeds that capacity.
func equipmentLoadHandler(w http.ResponseWriter, r *http.Request) {
	var req equipmentLoadRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Strength < 1 || req.Weight < 0 {
		writeError(w, http.StatusBadRequest, "invalid request")
		return
	}
	capacity := req.Strength * 15
	writeJSON(w, http.StatusOK, equipmentLoadResponse{
		Capacity:   capacity,
		Weight:     req.Weight,
		Encumbered: req.Weight > capacity,
	})
}

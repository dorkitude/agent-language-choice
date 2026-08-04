package main

import (
	"encoding/json"
	"net/http"
	"regexp"
	"strconv"
)

// diceRe matches dice expressions such as "2d6", "1d20+3", and "3d8-1".
// The capturing groups are: count, sides, optional sign, and optional modifier.
var diceRe = regexp.MustCompile(`^(\d+)d(\d+)(?:([+-])(\d+))?$`)

type diceStatsRequest struct {
	Expression string `json:"expression"`
}

type diceStatsResponse struct {
	DiceCount int     `json:"dice_count"`
	Sides     int     `json:"sides"`
	Modifier  int     `json:"modifier"`
	Min       int     `json:"min"`
	Max       int     `json:"max"`
	Average   float64 `json:"average"`
}

// diceStatsHandler parses a dice expression and returns deterministic statistics.
// It does not roll dice; it computes the range and average for the expression.
func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	var req diceStatsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	matches := diceRe.FindStringSubmatch(req.Expression)
	if matches == nil {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}

	count, _ := strconv.Atoi(matches[1])
	sides, _ := strconv.Atoi(matches[2])
	modifier := 0
	if matches[3] != "" && matches[4] != "" {
		m, _ := strconv.Atoi(matches[4])
		if matches[3] == "-" {
			m = -m
		}
		modifier = m
	}

	if count <= 0 || sides <= 0 {
		writeError(w, http.StatusBadRequest, "invalid expression")
		return
	}

	min := count + modifier
	max := count*sides + modifier
	average := float64(count*(1+sides)+2*modifier) / 2.0

	writeJSON(w, http.StatusOK, diceStatsResponse{
		DiceCount: count,
		Sides:     sides,
		Modifier:  modifier,
		Min:       min,
		Max:       max,
		Average:   average,
	})
}

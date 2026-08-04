package main

import (
	"net/http"
	"regexp"
	"strconv"
)

var diceExprRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

type diceStatsRequest struct {
	Expression string `json:"expression"`
}

// diceStatsHandler reports min/max/average for a dice expression like "3d6+2".
func diceStatsHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req diceStatsRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	matches := diceExprRe.FindStringSubmatch(req.Expression)
	if matches == nil {
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}
	count, err1 := strconv.Atoi(matches[1])
	sides, err2 := strconv.Atoi(matches[2])
	if err1 != nil || err2 != nil || count <= 0 || sides <= 0 {
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}
	modifier := 0
	if matches[3] != "" {
		mod, err := strconv.Atoi(matches[3])
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid dice expression")
			return
		}
		modifier = mod
	}

	min := count*1 + modifier
	max := count*sides + modifier
	average := float64(count)*(float64(sides)+1)/2 + float64(modifier)

	writeJSON(w, http.StatusOK, map[string]any{
		"dice_count": count,
		"sides":      sides,
		"modifier":   modifier,
		"min":        min,
		"max":        max,
		"average":    average,
	})
}

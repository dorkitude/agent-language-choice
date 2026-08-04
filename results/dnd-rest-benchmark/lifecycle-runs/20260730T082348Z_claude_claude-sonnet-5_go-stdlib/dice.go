package main

import (
	"encoding/json"
	"net/http"
	"regexp"
	"strconv"
)

// diceExprRe matches expressions like "2d6", "1d20+5", or "3d8-2".
var diceExprRe = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

func handleDiceStats(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Expression string `json:"expression"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	m := diceExprRe.FindStringSubmatch(req.Expression)
	if m == nil {
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}

	count, err1 := strconv.Atoi(m[1])
	sides, err2 := strconv.Atoi(m[2])
	if err1 != nil || err2 != nil || count <= 0 || sides <= 0 {
		writeError(w, http.StatusBadRequest, "invalid dice expression")
		return
	}

	modifier := 0
	if m[3] != "" {
		mod, err := strconv.Atoi(m[3])
		if err != nil {
			writeError(w, http.StatusBadRequest, "invalid dice expression")
			return
		}
		modifier = mod
	}

	min := count*1 + modifier
	max := count*sides + modifier
	average := float64(min+max) / 2

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"dice_count": count,
		"sides":      sides,
		"modifier":   modifier,
		"min":        min,
		"max":        max,
		"average":    average,
	})
}

func handleAbilityCheck(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Roll     int `json:"roll"`
		Modifier int `json:"modifier"`
		DC       int `json:"dc"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	total := req.Roll + req.Modifier
	success := total >= req.DC
	margin := total - req.DC

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"total":   total,
		"success": success,
		"margin":  margin,
	})
}

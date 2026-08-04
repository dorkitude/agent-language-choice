package main

import (
	"encoding/json"
	"net/http"
)

type abilityCheckRequest struct {
	Roll     int `json:"roll"`
	Modifier int `json:"modifier"`
	DC       int `json:"dc"`
}

type abilityCheckResponse struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

// abilityCheckHandler adds a modifier to a roll and compares it against a DC.
// The margin is positive on success and negative on failure.
func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	var req abilityCheckRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	total := req.Roll + req.Modifier
	margin := total - req.DC
	writeJSON(w, http.StatusOK, abilityCheckResponse{
		Total:   total,
		Success: total >= req.DC,
		Margin:  margin,
	})
}

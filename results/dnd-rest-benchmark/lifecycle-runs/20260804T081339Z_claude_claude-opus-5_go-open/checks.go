package main

import "net/http"

// ---------- POST /v1/checks/ability ----------

type abilityRequest struct {
	Roll     *int `json:"roll"`
	Modifier *int `json:"modifier"`
	DC       *int `json:"dc"`
}

type abilityResponse struct {
	Total   int  `json:"total"`
	Success bool `json:"success"`
	Margin  int  `json:"margin"`
}

// handleAbilityCheck resolves roll+modifier against a DC. A check succeeds when
// the total meets the DC, so margin 0 is a success.
func handleAbilityCheck(w http.ResponseWriter, r *http.Request) {
	var req abilityRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Roll == nil || req.DC == nil {
		writeError(w, http.StatusBadRequest, "roll and dc are required")
		return
	}
	modifier := 0
	if req.Modifier != nil {
		modifier = *req.Modifier
	}
	total := *req.Roll + modifier
	writeJSON(w, http.StatusOK, abilityResponse{
		Total:   total,
		Success: total >= *req.DC,
		Margin:  total - *req.DC,
	})
}

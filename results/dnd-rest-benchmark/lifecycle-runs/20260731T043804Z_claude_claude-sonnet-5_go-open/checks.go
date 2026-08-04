package main

import (
	"net/http"
)

type abilityCheckRequest struct {
	Roll     int `json:"roll"`
	Modifier int `json:"modifier"`
	DC       int `json:"dc"`
}

func abilityCheckHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req abilityCheckRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	total := req.Roll + req.Modifier
	success := total >= req.DC
	margin := total - req.DC
	writeJSON(w, http.StatusOK, map[string]any{
		"total":   total,
		"success": success,
		"margin":  margin,
	})
}

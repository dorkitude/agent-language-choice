package main

import (
	"encoding/json"
	"net/http"
	"sync"
)

var (
	serviceModeMu          sync.Mutex
	serviceMaintenanceMode bool
)

func handleLiveness(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func handleReadiness(w http.ResponseWriter, r *http.Request) {
	serviceModeMu.Lock()
	maintenance := serviceMaintenanceMode
	serviceModeMu.Unlock()

	if maintenance {
		writeJSON(w, http.StatusServiceUnavailable, map[string]interface{}{
			"status":         "maintenance",
			"schema_version": 2,
		})
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"status":         "ready",
		"schema_version": 2,
	})
}

// handlePlayCampaignServiceModeSub routes the "service-mode" sub-path of a
// play campaign.
func handlePlayCampaignServiceModeSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest != "service-mode" {
		return false
	}
	handlePlayCampaignServiceMode(w, r, id)
	return true
}

func handlePlayCampaignServiceMode(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Maintenance bool `json:"maintenance"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be the campaign dm")
		return
	}
	playMu.Unlock()

	serviceModeMu.Lock()
	serviceMaintenanceMode = req.Maintenance
	mode := serviceMaintenanceMode
	serviceModeMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"maintenance": mode})
}

package main

import (
	"net/http"
	"sync"
)

// serviceModeMu guards serviceMaintenance, the process-global reference
// service mode flag. It is not campaign-local: any DM enabling maintenance
// through their campaign puts the whole test-run server into maintenance
// until a DM disables it again.
var (
	serviceModeMu      sync.Mutex
	serviceMaintenance bool
)

// isServiceMaintenance reports the current process-global maintenance mode.
func isServiceMaintenance() bool {
	serviceModeMu.Lock()
	defer serviceModeMu.Unlock()
	return serviceMaintenance
}

// livezHandler is the public liveness probe. It always reports ok,
// regardless of maintenance mode.
func livezHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

// readyzHandler is the public readiness probe. It reports 503 while the
// process-global maintenance flag is set.
func readyzHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	if isServiceMaintenance() {
		writeJSON(w, http.StatusServiceUnavailable, map[string]any{
			"status":         "maintenance",
			"schema_version": 2,
		})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"status":         "ready",
		"schema_version": 2,
	})
}

type serviceModeRequest struct {
	Maintenance *bool `json:"maintenance"`
}

// serviceModeHandler lets the campaign owner (DM) flip the process-global
// maintenance switch. Any authenticated non-owner gets 403; unknown
// campaigns get 404; unauthenticated requests get 401.
func serviceModeHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		playCampaignsMu.Unlock()
		return
	}
	owner := c.Owner
	playCampaignsMu.Unlock()

	if actor.Username != owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may change service mode")
		return
	}

	var req serviceModeRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Maintenance == nil {
		writeError(w, http.StatusBadRequest, "maintenance is required")
		return
	}

	serviceModeMu.Lock()
	serviceMaintenance = *req.Maintenance
	serviceModeMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]bool{"maintenance": *req.Maintenance})
}

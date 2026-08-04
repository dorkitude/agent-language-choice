package main

import (
	"encoding/json"
	"log"
	"net/http"
	"sync/atomic"
)

// globalMaintenance is the process-global service-mode switch. It is controlled
// by any authenticated DM via POST /v1/play/campaigns/{id}/service-mode and is
// read by the public readiness endpoint.
var globalMaintenance atomic.Bool

type livenessResponse struct {
	Status string `json:"status"`
}

type readinessResponse struct {
	Status        string `json:"status"`
	SchemaVersion int    `json:"schema_version"`
}

type serviceModeRequest struct {
	Maintenance bool `json:"maintenance"`
}

type serviceModeResponse struct {
	Maintenance bool `json:"maintenance"`
}

// healthzHandler is the public liveness endpoint. It always returns HTTP 200,
// even when the service is in maintenance mode.
func healthzHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, livenessResponse{Status: "ok"})
}

// readyzHandler is the public readiness endpoint. It returns HTTP 200 when the
// service is not in maintenance mode and HTTP 503 when it is.
func readyzHandler(w http.ResponseWriter, r *http.Request) {
	if globalMaintenance.Load() {
		writeJSON(w, http.StatusServiceUnavailable, readinessResponse{Status: "maintenance", SchemaVersion: 2})
		return
	}
	writeJSON(w, http.StatusOK, readinessResponse{Status: "ready", SchemaVersion: 2})
}

// serviceModeHandler lets any authenticated DM set the process-global
// maintenance switch. Player requests receive 403, unknown campaigns receive
// 404, and unauthenticated requests receive 401.
func serviceModeHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	if _, ok := requireDM(w, r); !ok {
		return
	}

	campaignID := r.PathValue("id")
	if _, ok, err := queryPlayCampaign(campaignID); err != nil {
		log.Printf("service-mode campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	var req serviceModeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	globalMaintenance.Store(req.Maintenance)
	writeJSON(w, http.StatusOK, serviceModeResponse{Maintenance: req.Maintenance})
}

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// campaignImportState is the stored result of a successful campaign import.
type campaignImportState struct {
	Version int    `json:"version"`
	Story   string `json:"story"`
	Status  string `json:"status"`
}

// importSnapshotRequest is the exact shape of a compatible version 1 snapshot.
type importSnapshotRequest struct {
	Version int    `json:"version"`
	Story   string `json:"story"`
	Status  string `json:"status"`
}

// createPlayCampaignImportHandler imports a version 1 snapshot into the
// campaign. Only the campaign owner (DM) may call it. The snapshot's story
// replaces the campaign document's public story, and the snapshot's status
// replaces the campaign's status atomically. Invalid snapshots return 400
// without modifying any state.
func createPlayCampaignImportHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req importSnapshotRequest
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid import snapshot")
		return
	}

	if req.Version != 1 {
		writeError(w, http.StatusBadRequest, "invalid import snapshot")
		return
	}
	if req.Story == "" {
		writeError(w, http.StatusBadRequest, "invalid import snapshot")
		return
	}
	if req.Status != "lobby" && req.Status != "started" {
		writeError(w, http.StatusBadRequest, "invalid import snapshot")
		return
	}

	// Apply the imported story to the campaign document while preserving any
	// existing DM notes.
	if err := dbExec(fmt.Sprintf("INSERT OR REPLACE INTO campaign_documents (campaign_id, story, dm_notes) VALUES (%s, %s, COALESCE((SELECT dm_notes FROM campaign_documents WHERE campaign_id=%s), ''));",
		sq(campaignID), sq(req.Story), sq(campaignID))); err != nil {
		log.Printf("import document update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	// Apply the imported status to the campaign header.
	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET status=%s WHERE id=%s;",
		sq(req.Status), sq(campaignID))); err != nil {
		log.Printf("import status update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	// Record the imported snapshot so the import-state endpoint can return it.
	if err := dbExec(fmt.Sprintf("INSERT OR REPLACE INTO campaign_imports (campaign_id, version, story, status) VALUES (%s, %d, %s, %s);",
		sq(campaignID), req.Version, sq(req.Story), sq(req.Status))); err != nil {
		log.Printf("import state insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, campaignImportState{
		Version: req.Version,
		Story:   req.Story,
		Status:  req.Status,
	})
}

// getPlayCampaignImportStateHandler returns the most recently imported
// snapshot for the campaign. Only the campaign owner (DM) may call it. Before
// the first successful import, it returns 404.
func getPlayCampaignImportStateHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var states []campaignImportState
	if err := queryRows(fmt.Sprintf("SELECT version, story, status FROM campaign_imports WHERE campaign_id=%s LIMIT 1;", sq(campaignID)), &states); err != nil {
		log.Printf("import state query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(states) == 0 {
		writeError(w, http.StatusNotFound, "no import state")
		return
	}

	writeJSON(w, http.StatusOK, states[0])
}

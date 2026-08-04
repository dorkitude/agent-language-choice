package main

import (
	"encoding/json"
	"net/http"
)

// playImport is the applied snapshot of a campaign's story and status, set
// only by a compatible version 1 import created by the campaign DM.
type playImport struct {
	Version int    `json:"version"`
	Story   string `json:"story"`
	Status  string `json:"status"`
}

// handlePlayCampaignImportsSub routes the "imports" and "import-state"
// sub-paths of a play campaign.
func handlePlayCampaignImportsSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest == "imports" {
		handleCreatePlayImport(w, r, id)
		return true
	}

	if rest == "import-state" {
		handleGetPlayImportState(w, r, id)
		return true
	}

	return false
}

func handleCreatePlayImport(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		Version int    `json:"version"`
		Story   string `json:"story"`
		Status  string `json:"status"`
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create an import")
		return
	}

	if req.Version != 1 || req.Story == "" || (req.Status != "lobby" && req.Status != "started") {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "invalid import snapshot")
		return
	}

	c.Story = req.Story
	c.Status = req.Status
	c.Import = &playImport{
		Version: 1,
		Story:   req.Story,
		Status:  req.Status,
	}
	resp := map[string]interface{}{
		"version": c.Import.Version,
		"story":   c.Import.Story,
		"status":  c.Import.Status,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

func handleGetPlayImportState(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}

	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign dm may read imported state")
		return
	}

	if c.Import == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "no import has been applied")
		return
	}

	resp := map[string]interface{}{
		"version": c.Import.Version,
		"story":   c.Import.Story,
		"status":  c.Import.Status,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

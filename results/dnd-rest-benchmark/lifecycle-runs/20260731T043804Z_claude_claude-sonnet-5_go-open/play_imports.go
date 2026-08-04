package main

import (
	"net/http"
	"sync"
)

// campaignImportState is the current imported snapshot applied to one
// campaign, if any.
type campaignImportState struct {
	CampaignID string
	Version    int
	Story      string
	Status     string
}

// campaignImportsMu guards campaignImports, the in-memory index mirroring the
// play_campaign_imports table. Keyed by campaign id; a campaign has at most
// one imported state, representing its most recently applied import.
var (
	campaignImportsMu sync.Mutex
	campaignImports   = map[string]*campaignImportState{}
)

func importStateJSON(s *campaignImportState) map[string]any {
	return map[string]any{
		"version": s.Version,
		"story":   s.Story,
		"status":  s.Status,
	}
}

type importSnapshotRequest struct {
	Version int    `json:"version"`
	Story   string `json:"story"`
	Status  string `json:"status"`
}

// createImportHandler lets only the campaign DM import a compatible version 1
// snapshot, atomically applying its story and status to the campaign and
// recording the imported state.
func createImportHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req importSnapshotRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may create imports")
		return
	}

	if req.Version != 1 {
		writeError(w, http.StatusBadRequest, "unsupported snapshot version")
		return
	}
	if req.Story == "" {
		writeError(w, http.StatusBadRequest, "story must be nonempty")
		return
	}
	if req.Status != "lobby" && req.Status != "started" {
		writeError(w, http.StatusBadRequest, "status must be lobby or started")
		return
	}

	campaignImportsMu.Lock()
	defer campaignImportsMu.Unlock()

	state := &campaignImportState{
		CampaignID: campaignID,
		Version:    req.Version,
		Story:      req.Story,
		Status:     req.Status,
	}
	if err := saveCampaignImportToDB(state); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save import")
		return
	}

	c.Story = req.Story
	c.Status = req.Status
	if err := savePlayCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save campaign")
		return
	}

	campaignImports[campaignID] = state

	writeJSON(w, http.StatusOK, importStateJSON(state))
}

// getImportStateHandler lets only the campaign DM read the campaign's current
// imported state.
func getImportStateHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may read imported state")
		return
	}

	campaignImportsMu.Lock()
	defer campaignImportsMu.Unlock()

	state, exists := campaignImports[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "no imported state")
		return
	}

	writeJSON(w, http.StatusOK, importStateJSON(state))
}

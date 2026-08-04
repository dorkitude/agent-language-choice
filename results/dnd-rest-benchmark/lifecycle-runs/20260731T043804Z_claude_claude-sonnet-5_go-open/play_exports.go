package main

import (
	"net/http"
	"strconv"
	"sync"
)

// campaignExport is one immutable DM-only campaign export snapshot.
type campaignExport struct {
	CampaignID string
	Version    int
	Story      string
	Status     string
}

// campaignExportsMu guards campaignExports, the in-memory index mirroring the
// play_campaign_exports table. Keyed by campaign id, holding exports in
// version order starting at 1.
var (
	campaignExportsMu sync.Mutex
	campaignExports   = map[string][]*campaignExport{}
)

func exportJSON(e *campaignExport) map[string]any {
	return map[string]any{
		"version": e.Version,
		"story":   e.Story,
		"status":  e.Status,
	}
}

// createExportHandler lets only the campaign DM snapshot the campaign's
// current public story and status into a new immutable, sequential export
// version.
func createExportHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create exports")
		return
	}

	campaignExportsMu.Lock()
	defer campaignExportsMu.Unlock()

	entry := &campaignExport{
		CampaignID: campaignID,
		Version:    len(campaignExports[campaignID]) + 1,
		Story:      c.Story,
		Status:     c.Status,
	}
	if err := saveCampaignExportToDB(entry); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save export")
		return
	}
	campaignExports[campaignID] = append(campaignExports[campaignID], entry)

	writeJSON(w, http.StatusCreated, exportJSON(entry))
}

// listExportsHandler lets only the campaign DM list the campaign's exports in
// ascending version order.
func listExportsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may list exports")
		return
	}

	campaignExportsMu.Lock()
	defer campaignExportsMu.Unlock()

	exports := make([]map[string]any, 0, len(campaignExports[campaignID]))
	for _, e := range campaignExports[campaignID] {
		exports = append(exports, exportJSON(e))
	}

	writeJSON(w, http.StatusOK, map[string]any{"exports": exports})
}

// getExportHandler lets only the campaign DM read one immutable export
// snapshot by version.
func getExportHandler(w http.ResponseWriter, r *http.Request, campaignID string, versionStr string) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may read exports")
		return
	}

	version, err := strconv.Atoi(versionStr)
	if err != nil {
		writeError(w, http.StatusNotFound, "export not found")
		return
	}

	campaignExportsMu.Lock()
	defer campaignExportsMu.Unlock()

	for _, e := range campaignExports[campaignID] {
		if e.Version == version {
			writeJSON(w, http.StatusOK, exportJSON(e))
			return
		}
	}
	writeError(w, http.StatusNotFound, "export not found")
}

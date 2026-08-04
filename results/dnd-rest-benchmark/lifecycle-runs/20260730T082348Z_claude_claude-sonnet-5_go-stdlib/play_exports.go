package main

import (
	"net/http"
	"strconv"
	"strings"
)

// playExport is an immutable, sequentially versioned snapshot of a
// campaign's public story and status, created only by the campaign DM.
type playExport struct {
	Version int    `json:"version"`
	Story   string `json:"story"`
	Status  string `json:"status"`
}

// handlePlayCampaignExportsSub routes the "exports" sub-path of a play
// campaign.
func handlePlayCampaignExportsSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest == "exports" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayExport(w, r, id)
		case http.MethodGet:
			handleListPlayExports(w, r, id)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}

	if versionStr, ok := strings.CutPrefix(rest, "exports/"); ok && versionStr != "" {
		handleGetPlayExport(w, r, id, versionStr)
		return true
	}

	return false
}

func handleCreatePlayExport(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create an export")
		return
	}

	exp := &playExport{
		Version: len(c.Exports) + 1,
		Story:   c.Story,
		Status:  c.Status,
	}
	c.Exports = append(c.Exports, exp)
	resp := map[string]interface{}{
		"version": exp.Version,
		"story":   exp.Story,
		"status":  exp.Status,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleListPlayExports(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may list exports")
		return
	}

	exports := make([]map[string]interface{}, 0, len(c.Exports))
	for _, exp := range c.Exports {
		exports = append(exports, map[string]interface{}{
			"version": exp.Version,
			"story":   exp.Story,
			"status":  exp.Status,
		})
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"exports": exports})
}

func handleGetPlayExport(w http.ResponseWriter, r *http.Request, campaignID, versionStr string) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may read exports")
		return
	}

	version, err := strconv.Atoi(versionStr)
	if err != nil || version < 1 || version > len(c.Exports) {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "export version not found")
		return
	}
	exp := c.Exports[version-1]
	resp := map[string]interface{}{
		"version": exp.Version,
		"story":   exp.Story,
		"status":  exp.Status,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

package main

import (
	"encoding/json"
	"net/http"
)

// playMigration is the applied, deterministically upgraded state produced by
// migrating a compatible legacy schema version 1 snapshot, set only by the
// campaign DM.
type playMigration struct {
	SchemaVersion int    `json:"schema_version"`
	Story         string `json:"story"`
	CampaignName  string `json:"campaign_name"`
}

// handlePlayCampaignMigrationsSub routes the "migrations" and
// "migration-state" sub-paths of a play campaign.
func handlePlayCampaignMigrationsSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest == "migrations" {
		handleCreatePlayMigration(w, r, id)
		return true
	}

	if rest == "migration-state" {
		handleGetPlayMigrationState(w, r, id)
		return true
	}

	return false
}

func handleCreatePlayMigration(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		SchemaVersion int    `json:"schema_version"`
		Story         string `json:"story"`
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create a migration")
		return
	}

	if req.SchemaVersion != 1 || req.Story == "" {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "invalid legacy schema snapshot")
		return
	}

	status := http.StatusCreated
	if c.Migration != nil && c.Migration.Story == req.Story {
		status = http.StatusOK
	} else {
		c.Migration = &playMigration{
			SchemaVersion: 2,
			Story:         req.Story,
			CampaignName:  c.Name,
		}
	}
	resp := map[string]interface{}{
		"schema_version": c.Migration.SchemaVersion,
		"story":          c.Migration.Story,
		"campaign_name":  c.Migration.CampaignName,
	}
	playMu.Unlock()
	if status == http.StatusCreated {
		persistState()
	}

	writeJSON(w, status, resp)
}

func handleGetPlayMigrationState(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may read migrated state")
		return
	}

	if c.Migration == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "no migration has been applied")
		return
	}

	resp := map[string]interface{}{
		"schema_version": c.Migration.SchemaVersion,
		"story":          c.Migration.Story,
		"campaign_name":  c.Migration.CampaignName,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

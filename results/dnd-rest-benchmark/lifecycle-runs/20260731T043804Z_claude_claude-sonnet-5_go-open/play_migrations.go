package main

import (
	"net/http"
	"sync"
)

// campaignMigrationState is the current migrated (schema version 2) state
// applied to one campaign, if any.
type campaignMigrationState struct {
	CampaignID   string
	SchemaVer    int
	Story        string
	CampaignName string
}

// campaignMigrationsMu guards campaignMigrations, the in-memory index
// mirroring the play_campaign_migrations table. Keyed by campaign id; a
// campaign has at most one migrated state, representing its most recently
// applied migration.
var (
	campaignMigrationsMu sync.Mutex
	campaignMigrations   = map[string]*campaignMigrationState{}
)

func migrationStateJSON(s *campaignMigrationState) map[string]any {
	return map[string]any{
		"schema_version": s.SchemaVer,
		"story":          s.Story,
		"campaign_name":  s.CampaignName,
	}
}

type migrateSnapshotRequest struct {
	SchemaVersion int    `json:"schema_version"`
	Story         string `json:"story"`
}

// createMigrationHandler lets only the campaign DM migrate a legacy schema
// version 1 snapshot, deterministically producing schema version 2 state.
func createMigrationHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req migrateSnapshotRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create migrations")
		return
	}

	if req.SchemaVersion != 1 {
		writeError(w, http.StatusBadRequest, "unsupported schema version")
		return
	}
	if req.Story == "" {
		writeError(w, http.StatusBadRequest, "story must be nonempty")
		return
	}

	campaignMigrationsMu.Lock()
	defer campaignMigrationsMu.Unlock()

	state := &campaignMigrationState{
		CampaignID:   campaignID,
		SchemaVer:    2,
		Story:        req.Story,
		CampaignName: c.Name,
	}

	existing, hadExisting := campaignMigrations[campaignID]
	if hadExisting && existing.Story == state.Story && existing.CampaignName == state.CampaignName {
		writeJSON(w, http.StatusOK, migrationStateJSON(existing))
		return
	}

	if err := saveCampaignMigrationToDB(state); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save migration")
		return
	}

	campaignMigrations[campaignID] = state

	writeJSON(w, http.StatusCreated, migrationStateJSON(state))
}

// getMigrationStateHandler lets only the campaign DM read the campaign's
// current migrated state.
func getMigrationStateHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the campaign dm may read migrated state")
		return
	}

	campaignMigrationsMu.Lock()
	defer campaignMigrationsMu.Unlock()

	state, exists := campaignMigrations[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "no migrated state")
		return
	}

	writeJSON(w, http.StatusOK, migrationStateJSON(state))
}

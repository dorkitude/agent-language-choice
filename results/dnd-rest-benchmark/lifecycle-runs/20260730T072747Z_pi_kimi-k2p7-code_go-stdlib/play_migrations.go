package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// migrationRequest is the exact shape of a compatible version 1 snapshot.
type migrationRequest struct {
	SchemaVersion int    `json:"schema_version"`
	Story         string `json:"story"`
}

// migrationState is the deterministic migrated state stored at schema version 2.
type migrationState struct {
	SchemaVersion int    `json:"schema_version"`
	Story         string `json:"story"`
	CampaignName  string `json:"campaign_name"`
}

// createPlayCampaignMigrationHandler migrates a legacy version 1 snapshot into
// the campaign's schema version 2 state. Only the campaign owner (DM) may call
// it. The story is preserved, the schema version is set to 2, and the campaign
// name is filled in from the campaign header. Repeating the exact same version
// 1 snapshot is idempotent and returns 200; invalid migrations return 400 and do
// not change stored state.
func createPlayCampaignMigrationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var campaigns []playCampaign
	if err := queryRows(fmt.Sprintf("SELECT id, name, owner, status, max_players, turn_number, turn_actor, nudge_count, current_scene_id, current_location_id, phase, pre_combat_actor FROM play_campaigns WHERE id=%s LIMIT 1;", sq(campaignID)), &campaigns); err != nil {
		log.Printf("migration campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	campaign := campaigns[0]

	var req migrationRequest
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid migration")
		return
	}

	if req.SchemaVersion != 1 || req.Story == "" {
		writeError(w, http.StatusBadRequest, "invalid migration")
		return
	}

	var states []migrationState
	if err := queryRows(fmt.Sprintf("SELECT schema_version, story, campaign_name FROM campaign_migrations WHERE campaign_id=%s LIMIT 1;", sq(campaignID)), &states); err != nil {
		log.Printf("migration state query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	state := migrationState{
		SchemaVersion: 2,
		Story:         req.Story,
		CampaignName:  campaign.Name,
	}

	if len(states) > 0 {
		if states[0].Story != req.Story {
			writeError(w, http.StatusBadRequest, "invalid migration")
			return
		}
		writeJSON(w, http.StatusOK, states[0])
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (%s, %d, %s, %s);",
		sq(campaignID), state.SchemaVersion, sq(req.Story), sq(campaign.Name))); err != nil {
		log.Printf("migration state insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, state)
}

// getPlayCampaignMigrationStateHandler returns the current migrated state for
// the campaign. Only the campaign owner (DM) may call it. Before the first
// successful migration, it returns 404.
func getPlayCampaignMigrationStateHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var states []migrationState
	if err := queryRows(fmt.Sprintf("SELECT schema_version, story, campaign_name FROM campaign_migrations WHERE campaign_id=%s LIMIT 1;", sq(campaignID)), &states); err != nil {
		log.Printf("migration state query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(states) == 0 {
		writeError(w, http.StatusNotFound, "no migration state")
		return
	}

	writeJSON(w, http.StatusOK, states[0])
}

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// campaign represents the core campaign header.
type campaign struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

// campaignCharacter is a player character attached to a campaign.
type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

// campaignEvent is a campaign log entry.
type campaignEvent struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Summary string `json:"summary"`
}

// campaignEventResponse is the reduced shape returned when an event is created.
type campaignEventResponse struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
}

// campaignState aggregates a campaign header, its characters, and a count of
// log entries.
type campaignState struct {
	ID         string              `json:"id"`
	Name       string              `json:"name"`
	DM         string              `json:"dm"`
	Characters []campaignCharacter `json:"characters"`
	LogCount   int                 `json:"log_count"`
}

// campaignAuditResponse is the deterministic audit summary for a campaign.
type campaignAuditResponse struct {
	CampaignID string `json:"campaign_id"`
	Events     int    `json:"events"`
	Quests     int    `json:"quests"`
	NPCs       int    `json:"npcs"`
	Sessions   int    `json:"sessions"`
}

// campaignExportResponse is the deterministic JSON summary export for a campaign.
type campaignExportResponse struct {
	CampaignID     string `json:"campaign_id"`
	Name           string `json:"name"`
	Characters     int    `json:"characters"`
	Quests         int    `json:"quests"`
	NPCs           int    `json:"npcs"`
	InventoryItems int    `json:"inventory_items"`
	Sessions       int    `json:"sessions"`
	SchemaVersion  int    `json:"schema_version"`
}

// queryCampaignExists returns true when a campaign with the given ID exists.
func queryCampaignExists(id string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM campaigns WHERE id=%s LIMIT 1;", sq(id)))
}

// createCampaignHandler creates a new campaign with a unique ID.
func createCampaignHandler(w http.ResponseWriter, r *http.Request) {
	var req campaign
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.DM == "" {
		writeError(w, http.StatusBadRequest, "invalid campaign")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(req.ID)
	if err != nil {
		log.Printf("campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "campaign already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaigns (id, name, dm) VALUES (%s, %s, %s);",
		sq(req.ID), sq(req.Name), sq(req.DM))); err != nil {
		log.Printf("campaign insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

// addCampaignCharacterHandler attaches a player character to a campaign. Both
// the campaign ID and the character ID must exist, and the character ID must be
// unique across all campaigns.
func addCampaignCharacterHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req campaignCharacter
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.Class == "" || req.Level < 1 {
		writeError(w, http.StatusBadRequest, "invalid character")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("add character campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_characters WHERE id=%s LIMIT 1;", sq(req.ID)))
	if err != nil {
		log.Printf("add character duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "character already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (%s, %s, %s, %d, %s);",
		sq(req.ID), sq(campaignID), sq(req.Name), req.Level, sq(req.Class))); err != nil {
		log.Printf("add character insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

// addCampaignEventHandler appends a log event to a campaign. Event IDs are
// unique across all campaigns, and the campaign must exist.
func addCampaignEventHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req campaignEvent
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Kind == "" || req.Summary == "" {
		writeError(w, http.StatusBadRequest, "invalid event")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("add event campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_events WHERE id=%s LIMIT 1;", sq(req.ID)))
	if err != nil {
		log.Printf("add event duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "event already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (%s, %s, %s, %s);",
		sq(req.ID), sq(campaignID), sq(req.Kind), sq(req.Summary))); err != nil {
		log.Printf("add event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, campaignEventResponse{ID: req.ID, Kind: req.Kind})
}

// getCampaignStateHandler returns the campaign header, its characters (ordered
// by ID), and a count of log events.
func getCampaignStateHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	var campaigns []campaign
	if err := queryRows(fmt.Sprintf("SELECT id, name, dm FROM campaigns WHERE id=%s LIMIT 1;", sq(campaignID)), &campaigns); err != nil {
		log.Printf("campaign state query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(campaigns) == 0 {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	camp := campaigns[0]

	var characters []campaignCharacter
	if err := queryRows(fmt.Sprintf("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id=%s ORDER BY id;", sq(campaignID)), &characters); err != nil {
		log.Printf("campaign state characters query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if characters == nil {
		characters = []campaignCharacter{}
	}

	var counts []struct {
		LogCount int `json:"log_count"`
	}
	if err := queryRows(fmt.Sprintf("SELECT COUNT(*) AS log_count FROM campaign_events WHERE campaign_id=%s;", sq(campaignID)), &counts); err != nil {
		log.Printf("campaign state log count query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	logCount := 0
	if len(counts) > 0 {
		logCount = counts[0].LogCount
	}

	writeJSON(w, http.StatusOK, campaignState{
		ID:         camp.ID,
		Name:       camp.Name,
		DM:         camp.DM,
		Characters: characters,
		LogCount:   logCount,
	})
}

// countCampaignTable returns the number of rows in the named table for a campaign.
func countCampaignTable(campaignID, table, column string) (int, error) {
	var rows []struct {
		Cnt int `json:"cnt"`
	}
	if err := queryRows(fmt.Sprintf("SELECT COUNT(*) AS cnt FROM %s WHERE %s=%s;", table, column, sq(campaignID)), &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 0, nil
	}
	return rows[0].Cnt, nil
}

// getCampaignAuditHandler returns deterministic audit counts for a campaign.
func getCampaignAuditHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("campaign audit exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	events, err := countCampaignTable(campaignID, "campaign_events", "campaign_id")
	if err != nil {
		log.Printf("campaign audit events count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	quests, err := countCampaignTable(campaignID, "quests", "campaign_id")
	if err != nil {
		log.Printf("campaign audit quests count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	npcs, err := countCampaignTable(campaignID, "npcs", "campaign_id")
	if err != nil {
		log.Printf("campaign audit npcs count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	sessions, err := countCampaignTable(campaignID, "campaign_sessions", "campaign_id")
	if err != nil {
		log.Printf("campaign audit sessions count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, campaignAuditResponse{
		CampaignID: campaignID,
		Events:     events,
		Quests:     quests,
		NPCs:       npcs,
		Sessions:   sessions,
	})
}

// getCampaignExportHandler returns a deterministic JSON summary export for a campaign.
func getCampaignExportHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	var campaigns []struct {
		ID   string `json:"id"`
		Name string `json:"name"`
	}
	if err := queryRows(fmt.Sprintf("SELECT id, name FROM campaigns WHERE id=%s LIMIT 1;", sq(campaignID)), &campaigns); err != nil {
		log.Printf("campaign export query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(campaigns) == 0 {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	camp := campaigns[0]

	characters, err := countCampaignTable(campaignID, "campaign_characters", "campaign_id")
	if err != nil {
		log.Printf("campaign export characters count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	quests, err := countCampaignTable(campaignID, "quests", "campaign_id")
	if err != nil {
		log.Printf("campaign export quests count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	npcs, err := countCampaignTable(campaignID, "npcs", "campaign_id")
	if err != nil {
		log.Printf("campaign export npcs count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	inventoryItems, err := countCampaignTable(campaignID, "campaign_inventory", "campaign_id")
	if err != nil {
		log.Printf("campaign export inventory count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	sessions, err := countCampaignTable(campaignID, "campaign_sessions", "campaign_id")
	if err != nil {
		log.Printf("campaign export sessions count error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	schemaVersion, _, err := queryVersion()
	if err != nil {
		log.Printf("campaign export schema version error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if schemaVersion == 0 {
		schemaVersion = 1
	}

	writeJSON(w, http.StatusOK, campaignExportResponse{
		CampaignID:     camp.ID,
		Name:           camp.Name,
		Characters:     characters,
		Quests:         quests,
		NPCs:           npcs,
		InventoryItems: inventoryItems,
		Sessions:       sessions,
		SchemaVersion:  schemaVersion,
	})
}

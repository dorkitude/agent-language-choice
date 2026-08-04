package main

import (
	"database/sql"
	"errors"
	"log"
	"net/http"
)

// Campaign state is the running table record: the campaign itself, its roster of
// characters, and an append-only event log. All three live in SQLite and survive
// for the life of the process, the same way the compendium does.
//
// Both child collections are ordered by an integer position assigned at insert
// time, so GET /state replays them in the order the DM added them rather than in
// id order. Assigning that position is a read-then-write, which is why every
// handler here holds storeMu across the whole sequence.

// ---------- POST /v1/campaigns ----------

type campaignRequest struct {
	ID   *string `json:"id"`
	Name *string `json:"name"`
	DM   *string `json:"dm"`
}

type campaignResponse struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

func handleCampaigns(w http.ResponseWriter, r *http.Request) {
	var req campaignRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	if _, ok := requireField(w, req.Name, "name"); !ok {
		return
	}
	out := campaignResponse{ID: id, Name: *req.Name}
	if req.DM != nil {
		out.DM = *req.DM
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if exists, err := campaignExists(id); err != nil {
		writeStorageFailure(w, "campaign lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "campaign id already exists")
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)`, out.ID, out.Name, out.DM,
	); err != nil {
		// A primary-key collision that raced the check above; still a conflict.
		log.Printf("campaign insert failed: %v", err)
		writeError(w, http.StatusConflict, "campaign id already exists")
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

// ---------- POST /v1/campaigns/{id}/characters ----------

type campaignCharacterRequest struct {
	ID    *string `json:"id"`
	Name  *string `json:"name"`
	Level *int    `json:"level"`
	Class *string `json:"class"`
}

// campaignCharacterResponse is both the create response and one roster entry in
// the campaign state read.
type campaignCharacterResponse struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

func handleCampaignCharacters(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req campaignCharacterRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	if _, ok := requireField(w, req.Name, "name"); !ok {
		return
	}
	out := campaignCharacterResponse{ID: id, Name: *req.Name}
	if req.Level != nil {
		out.Level = *req.Level
	}
	if req.Class != nil {
		out.Class = *req.Class
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?`, campaignID, id,
	); err != nil {
		writeStorageFailure(w, "character lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "character id already exists")
		return
	}

	position, err := nextPosition(`campaign_characters`, campaignID)
	if err != nil {
		writeStorageFailure(w, "character position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_characters (campaign_id, id, position, name, level, class)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		campaignID, out.ID, position, out.Name, out.Level, out.Class,
	); err != nil {
		log.Printf("character insert failed: %v", err)
		writeError(w, http.StatusConflict, "character id already exists")
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

// ---------- POST /v1/campaigns/{id}/events ----------

type campaignEventRequest struct {
	ID      *string `json:"id"`
	Kind    *string `json:"kind"`
	Summary *string `json:"summary"`
}

// campaignEventResponse omits the summary: the event log is written here and
// only ever read back in aggregate by GET /state and the DM session recap.
type campaignEventResponse struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
}

func handleCampaignEvents(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req campaignEventRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	out := campaignEventResponse{ID: id}
	if req.Kind != nil {
		out.Kind = *req.Kind
	}
	summary := ""
	if req.Summary != nil {
		summary = *req.Summary
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?`, campaignID, id,
	); err != nil {
		writeStorageFailure(w, "event lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "event id already exists")
		return
	}

	position, err := nextPosition(`campaign_events`, campaignID)
	if err != nil {
		writeStorageFailure(w, "event position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_events (campaign_id, id, position, kind, summary) VALUES (?, ?, ?, ?, ?)`,
		campaignID, out.ID, position, out.Kind, summary,
	); err != nil {
		log.Printf("event insert failed: %v", err)
		writeError(w, http.StatusConflict, "event id already exists")
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

// ---------- GET /v1/campaigns/{id}/state ----------

type campaignStateResponse struct {
	ID         string                      `json:"id"`
	Name       string                      `json:"name"`
	DM         string                      `json:"dm"`
	Characters []campaignCharacterResponse `json:"characters"`
	LogCount   int                         `json:"log_count"`
}

func handleCampaignState(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	// Characters starts as an empty slice so a roster-less campaign renders [].
	out := campaignStateResponse{Characters: []campaignCharacterResponse{}}
	err := db.QueryRow(`SELECT id, name, dm FROM campaigns WHERE id = ?`, campaignID).
		Scan(&out.ID, &out.Name, &out.DM)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "campaign read failed", err)
		return
	}

	rows, err := db.Query(
		`SELECT id, name, level, class FROM campaign_characters
		 WHERE campaign_id = ? ORDER BY position`, campaignID,
	)
	if err != nil {
		writeStorageFailure(w, "character list failed", err)
		return
	}
	defer rows.Close()
	for rows.Next() {
		var c campaignCharacterResponse
		if err := rows.Scan(&c.ID, &c.Name, &c.Level, &c.Class); err != nil {
			writeStorageFailure(w, "character scan failed", err)
			return
		}
		out.Characters = append(out.Characters, c)
	}
	if err := rows.Err(); err != nil {
		writeStorageFailure(w, "character list failed", err)
		return
	}

	// The log is summarized as a count; the events themselves are only exposed
	// through the DM session recap.
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?`, campaignID,
	).Scan(&out.LogCount); err != nil {
		writeStorageFailure(w, "event count failed", err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

// ---------- shared helpers ----------

func campaignExists(id string) (bool, error) {
	return rowExists(`SELECT 1 FROM campaigns WHERE id = ?`, id)
}

// requireCampaign resolves the parent campaign for a nested write, writing the
// 404 or 500 itself. Callers must already hold storeMu.
func requireCampaign(w http.ResponseWriter, campaignID string) bool {
	exists, err := campaignExists(campaignID)
	if err != nil {
		writeStorageFailure(w, "campaign lookup failed", err)
		return false
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return false
	}
	return true
}

// nextPosition returns the position to give the next row appended to one of the
// campaign's ordered child tables, starting at 1. table is a literal from this
// file only, never request data.
func nextPosition(table, campaignID string) (int, error) {
	var position int
	err := db.QueryRow(
		`SELECT COALESCE(MAX(position), 0) + 1 FROM `+table+` WHERE campaign_id = ?`, campaignID,
	).Scan(&position)
	return position, err
}

// rowExists runs an existence query written in this package and reports whether
// it matched. The query must select a single column.
func rowExists(query string, args ...any) (bool, error) {
	var found int
	err := db.QueryRow(query, args...).Scan(&found)
	if errors.Is(err, sql.ErrNoRows) {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	return true, nil
}

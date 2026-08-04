package main

import (
	"database/sql"
	"errors"
	"log"
	"net/http"
	"strings"
	"time"
)

// Scheduled play sessions are another ordered child of a campaign, alongside
// quests, inventory and crafting. A session owns an agenda list and, once it
// has been played, an attendance record; both responses report counts derived
// from those child rows rather than storing a tally.
//
// starts_at is echoed back exactly as the caller wrote it, so an offset like
// +02:00 survives the round trip. Ordering uses a separate normalized UTC key
// computed at write time, which keeps "next session" independent of how each
// caller spelled its timestamp — and independent of the wall clock, which no
// response in this program consults.

// Attendance buckets. These are the two states a named character can be in for
// a session; anything else is not modelled.
const (
	attendancePresent = "present"
	attendanceAbsent  = "absent"
)

// sessionTimeLayouts are the timestamp spellings accepted for starts_at. The
// first is the spec's form; the second allows a local time without a zone,
// which is then read as UTC so ordering stays total.
var sessionTimeLayouts = []string{time.RFC3339, "2006-01-02T15:04:05"}

// parseSessionStart validates starts_at and returns the sort key used to order
// sessions: the instant in UTC, formatted so string comparison matches time
// comparison.
func parseSessionStart(value string) (string, bool) {
	for _, layout := range sessionTimeLayouts {
		if parsed, err := time.Parse(layout, value); err == nil {
			return parsed.UTC().Format("2006-01-02T15:04:05.000000000Z"), true
		}
	}
	return "", false
}

// ---------- POST /v1/campaigns/{id}/sessions ----------

type sessionRequest struct {
	ID              *string  `json:"id"`
	StartsAt        *string  `json:"starts_at"`
	DurationMinutes *int     `json:"duration_minutes"`
	Agenda          []string `json:"agenda"`
}

type sessionResponse struct {
	ID              string `json:"id"`
	StartsAt        string `json:"starts_at"`
	DurationMinutes int    `json:"duration_minutes"`
	AgendaCount     int    `json:"agenda_count"`
}

func handleCampaignSessions(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req sessionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	startsAt, ok := requireField(w, req.StartsAt, "starts_at")
	if !ok {
		return
	}
	sortKey, ok := parseSessionStart(startsAt)
	if !ok {
		writeError(w, http.StatusBadRequest, "starts_at is invalid")
		return
	}
	if req.DurationMinutes == nil {
		writeError(w, http.StatusBadRequest, "duration_minutes is required")
		return
	}
	duration := *req.DurationMinutes
	if duration <= 0 {
		writeError(w, http.StatusBadRequest, "duration_minutes must be positive")
		return
	}
	// Blank agenda entries carry no information and would inflate the count, so
	// they are dropped the way quest milestones are.
	agenda := make([]string, 0, len(req.Agenda))
	for _, entry := range req.Agenda {
		if trimmed := strings.TrimSpace(entry); trimmed != "" {
			agenda = append(agenda, trimmed)
		}
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?`, campaignID, id,
	); err != nil {
		writeStorageFailure(w, "session lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "session id already exists")
		return
	}

	position, err := nextPosition(`campaign_sessions`, campaignID)
	if err != nil {
		writeStorageFailure(w, "session position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_sessions
		   (campaign_id, id, position, starts_at, starts_at_key, duration_minutes)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		campaignID, id, position, startsAt, sortKey, duration,
	); err != nil {
		log.Printf("session insert failed: %v", err)
		writeError(w, http.StatusConflict, "session id already exists")
		return
	}
	for index, entry := range agenda {
		if _, err := db.Exec(
			`INSERT INTO campaign_session_agenda (campaign_id, session_id, position, entry)
			 VALUES (?, ?, ?, ?)`,
			campaignID, id, index+1, entry,
		); err != nil {
			writeStorageFailure(w, "agenda insert failed", err)
			return
		}
	}

	writeJSON(w, http.StatusCreated, sessionResponse{
		ID:              id,
		StartsAt:        startsAt,
		DurationMinutes: duration,
		AgendaCount:     len(agenda),
	})
}

// ---------- POST /v1/campaigns/{id}/sessions/{session_id}/attendance ----------

type attendanceRequest struct {
	Present []string `json:"present"`
	Absent  []string `json:"absent"`
}

type attendanceResponse struct {
	SessionID    string `json:"session_id"`
	PresentCount int    `json:"present_count"`
	AbsentCount  int    `json:"absent_count"`
}

func handleCampaignSessionAttendance(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	sessionID, ok := requirePathValue(w, r, "session_id", "session id")
	if !ok {
		return
	}
	var req attendanceRequest
	if !decodeBody(w, r, &req) {
		return
	}
	// A character named in both lists cannot be in two places at once. Present
	// wins for that name, and it is counted once.
	present := dedupeNames(req.Present, nil)
	absent := dedupeNames(req.Absent, present)

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?`, campaignID, sessionID,
	); err != nil {
		writeStorageFailure(w, "session lookup failed", err)
		return
	} else if !exists {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	// Recording attendance replaces the whole record, so a correction call
	// reports exactly what it was given rather than merging with an earlier take.
	if _, err := db.Exec(
		`DELETE FROM campaign_session_attendance WHERE campaign_id = ? AND session_id = ?`,
		campaignID, sessionID,
	); err != nil {
		writeStorageFailure(w, "attendance clear failed", err)
		return
	}
	for _, group := range []struct {
		status string
		names  []string
	}{{attendancePresent, present}, {attendanceAbsent, absent}} {
		for _, name := range group.names {
			if _, err := db.Exec(
				`INSERT INTO campaign_session_attendance (campaign_id, session_id, character_id, status)
				 VALUES (?, ?, ?, ?)`,
				campaignID, sessionID, name, group.status,
			); err != nil {
				writeStorageFailure(w, "attendance insert failed", err)
				return
			}
		}
	}

	writeJSON(w, http.StatusOK, attendanceResponse{
		SessionID:    sessionID,
		PresentCount: len(present),
		AbsentCount:  len(absent),
	})
}

// dedupeNames trims and de-duplicates a list of character ids, dropping blanks
// and anything already claimed by an earlier list.
func dedupeNames(names []string, taken []string) []string {
	seen := make(map[string]bool, len(names)+len(taken))
	for _, name := range taken {
		seen[name] = true
	}
	out := make([]string, 0, len(names))
	for _, name := range names {
		trimmed := strings.TrimSpace(name)
		if trimmed == "" || seen[trimmed] {
			continue
		}
		seen[trimmed] = true
		out = append(out, trimmed)
	}
	return out
}

// ---------- GET /v1/campaigns/{id}/sessions/next ----------

type nextSessionResponse struct {
	ID          string `json:"id"`
	StartsAt    string `json:"starts_at"`
	AgendaCount int    `json:"agenda_count"`
}

// handleCampaignNextSession returns the earliest scheduled session. It does not
// compare against the current time: responses in this program are deterministic,
// so "next" means first on the calendar, with the insert order breaking ties
// between two sessions that start at the same instant.
func handleCampaignNextSession(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	var out nextSessionResponse
	err := db.QueryRow(
		`SELECT id, starts_at FROM campaign_sessions WHERE campaign_id = ?
		 ORDER BY starts_at_key, position LIMIT 1`, campaignID,
	).Scan(&out.ID, &out.StartsAt)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "no scheduled sessions")
		return
	}
	if err != nil {
		writeStorageFailure(w, "session read failed", err)
		return
	}
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM campaign_session_agenda WHERE campaign_id = ? AND session_id = ?`,
		campaignID, out.ID,
	).Scan(&out.AgendaCount); err != nil {
		writeStorageFailure(w, "agenda count failed", err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

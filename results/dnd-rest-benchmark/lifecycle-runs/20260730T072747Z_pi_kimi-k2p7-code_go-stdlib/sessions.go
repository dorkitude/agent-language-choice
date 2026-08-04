package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sort"
	"time"
)

// campaignSessionRequest is the payload for scheduling a campaign session.
type campaignSessionRequest struct {
	ID              string   `json:"id"`
	StartsAt        string   `json:"starts_at"`
	DurationMinutes int      `json:"duration_minutes"`
	Agenda          []string `json:"agenda"`
}

// campaignSessionResponse is the reduced shape returned when a session is scheduled.
type campaignSessionResponse struct {
	ID              string `json:"id"`
	StartsAt        string `json:"starts_at"`
	DurationMinutes int    `json:"duration_minutes"`
	AgendaCount     int    `json:"agenda_count"`
}

// sessionAttendanceRequest records who was present or absent for a session.
type sessionAttendanceRequest struct {
	Present []string `json:"present"`
	Absent  []string `json:"absent"`
}

// sessionAttendanceResponse reports the attendance tally for a session.
type sessionAttendanceResponse struct {
	SessionID    string `json:"session_id"`
	PresentCount int    `json:"present_count"`
	AbsentCount  int    `json:"absent_count"`
}

// nextCampaignSessionResponse is the summary returned for the upcoming session.
type nextCampaignSessionResponse struct {
	ID          string `json:"id"`
	StartsAt    string `json:"starts_at"`
	AgendaCount int    `json:"agenda_count"`
}

// queryCampaignSessionExists returns true when a session with the given ID exists.
func queryCampaignSessionExists(id string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM campaign_sessions WHERE id=%s LIMIT 1;", sq(id)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// createCampaignSessionHandler schedules a new session under a campaign.
func createCampaignSessionHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req campaignSessionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.StartsAt == "" || req.DurationMinutes <= 0 {
		writeError(w, http.StatusBadRequest, "invalid session")
		return
	}
	if _, err := time.Parse(time.RFC3339, req.StartsAt); err != nil {
		writeError(w, http.StatusBadRequest, "invalid session")
		return
	}

	agendaJSON, err := json.Marshal(req.Agenda)
	if err != nil {
		log.Printf("session agenda marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("create session campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	dup, err := queryCampaignSessionExists(req.ID)
	if err != nil {
		log.Printf("create session duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "session already exists")
		return
	}

	if err := dbExec(fmt.Sprintf(
		"INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda) VALUES (%s, %s, %s, %d, %s);",
		sq(req.ID), sq(campaignID), sq(req.StartsAt), req.DurationMinutes, sq(string(agendaJSON)))); err != nil {
		log.Printf("create session insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, campaignSessionResponse{
		ID:              req.ID,
		StartsAt:        req.StartsAt,
		DurationMinutes: req.DurationMinutes,
		AgendaCount:     len(req.Agenda),
	})
}

// recordCampaignSessionAttendanceHandler records who attended a campaign session.
func recordCampaignSessionAttendanceHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	sessionID := r.PathValue("session_id")

	var req sessionAttendanceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Present == nil {
		req.Present = []string{}
	}
	if req.Absent == nil {
		req.Absent = []string{}
	}

	presentJSON, err := json.Marshal(req.Present)
	if err != nil {
		log.Printf("attendance present marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	absentJSON, err := json.Marshal(req.Absent)
	if err != nil {
		log.Printf("attendance absent marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("record attendance campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf(
		"SELECT id FROM campaign_sessions WHERE id=%s AND campaign_id=%s LIMIT 1;",
		sq(sessionID), sq(campaignID)))
	if err != nil {
		log.Printf("record attendance session query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var sessions []struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(out, &sessions); err != nil {
		log.Printf("record attendance session unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(sessions) == 0 {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	if err := dbExec(fmt.Sprintf(
		"INSERT OR REPLACE INTO session_attendance (session_id, present, absent) VALUES (%s, %s, %s);",
		sq(sessionID), sq(string(presentJSON)), sq(string(absentJSON)))); err != nil {
		log.Printf("record attendance insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, sessionAttendanceResponse{
		SessionID:    sessionID,
		PresentCount: len(req.Present),
		AbsentCount:  len(req.Absent),
	})
}

// getNextCampaignSessionHandler returns the earliest scheduled session for a campaign.
func getNextCampaignSessionHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("next session campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf(
		"SELECT id, starts_at, agenda FROM campaign_sessions WHERE campaign_id=%s;",
		sq(campaignID)))
	if err != nil {
		log.Printf("next session query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		ID       string `json:"id"`
		StartsAt string `json:"starts_at"`
		Agenda   string `json:"agenda"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("next session unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	type candidate struct {
		id       string
		startsAt time.Time
		agenda   []string
	}
	var candidates []candidate
	for _, row := range rows {
		t, err := time.Parse(time.RFC3339, row.StartsAt)
		if err != nil {
			log.Printf("next session parse error for %s: %v", row.ID, err)
			continue
		}
		var agenda []string
		if err := json.Unmarshal([]byte(row.Agenda), &agenda); err != nil {
			agenda = []string{}
		}
		candidates = append(candidates, candidate{id: row.ID, startsAt: t, agenda: agenda})
	}
	if len(candidates) == 0 {
		writeError(w, http.StatusNotFound, "no session found")
		return
	}

	sort.Slice(candidates, func(i, j int) bool {
		if !candidates[i].startsAt.Equal(candidates[j].startsAt) {
			return candidates[i].startsAt.Before(candidates[j].startsAt)
		}
		return candidates[i].id < candidates[j].id
	})
	next := candidates[0]

	writeJSON(w, http.StatusOK, nextCampaignSessionResponse{
		ID:          next.id,
		StartsAt:    next.startsAt.Format(time.RFC3339),
		AgendaCount: len(next.agenda),
	})
}

package main

import (
	"net/http"
	"strings"
	"time"
)

type campaignSession struct {
	ID                 string   `json:"id"`
	StartsAt           string   `json:"starts_at"`
	DurationMinutes    int      `json:"duration_minutes"`
	Agenda             []string `json:"agenda"`
	Present            []string `json:"present"`
	Absent             []string `json:"absent"`
	AttendanceRecorded bool     `json:"-"`
}

func sessionScheduleResponse(s *campaignSession) map[string]any {
	return map[string]any{
		"id":               s.ID,
		"starts_at":        s.StartsAt,
		"duration_minutes": s.DurationMinutes,
		"agenda_count":     len(s.Agenda),
	}
}

func sessionAttendanceResponse(s *campaignSession) map[string]any {
	return map[string]any{
		"session_id":    s.ID,
		"present_count": len(s.Present),
		"absent_count":  len(s.Absent),
	}
}

func sessionNextResponse(s *campaignSession) map[string]any {
	return map[string]any{
		"id":           s.ID,
		"starts_at":    s.StartsAt,
		"agenda_count": len(s.Agenda),
	}
}

type scheduleSessionRequest struct {
	ID              string   `json:"id"`
	StartsAt        string   `json:"starts_at"`
	DurationMinutes *int     `json:"duration_minutes"`
	Agenda          []string `json:"agenda"`
}

func scheduleSessionHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req scheduleSessionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.StartsAt == "" {
		writeError(w, http.StatusBadRequest, "starts_at is required")
		return
	}
	if _, err := time.Parse(time.RFC3339, req.StartsAt); err != nil {
		writeError(w, http.StatusBadRequest, "starts_at must be an RFC3339 timestamp")
		return
	}
	if req.DurationMinutes == nil || *req.DurationMinutes <= 0 {
		writeError(w, http.StatusBadRequest, "duration_minutes must be a positive integer")
		return
	}
	agenda := req.Agenda
	if agenda == nil {
		agenda = []string{}
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	for _, s := range c.Sessions {
		if s.ID == req.ID {
			writeError(w, http.StatusConflict, "session id already exists")
			return
		}
	}

	s := &campaignSession{
		ID:              req.ID,
		StartsAt:        req.StartsAt,
		DurationMinutes: *req.DurationMinutes,
		Agenda:          agenda,
		Present:         []string{},
		Absent:          []string{},
	}
	if err := saveCampaignSessionToDB(c.ID, s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save session")
		return
	}
	c.Sessions = append(c.Sessions, s)

	writeJSON(w, http.StatusCreated, sessionScheduleResponse(s))
}

type sessionAttendanceRequest struct {
	Present []string `json:"present"`
	Absent  []string `json:"absent"`
}

func sessionAttendanceHandler(w http.ResponseWriter, r *http.Request, campaignID, sessionID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req sessionAttendanceRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	var s *campaignSession
	for _, existing := range c.Sessions {
		if existing.ID == sessionID {
			s = existing
			break
		}
	}
	if s == nil {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}

	present := req.Present
	if present == nil {
		present = []string{}
	}
	absent := req.Absent
	if absent == nil {
		absent = []string{}
	}
	s.Present = present
	s.Absent = absent
	s.AttendanceRecorded = true

	if err := saveCampaignSessionToDB(c.ID, s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save session")
		return
	}

	writeJSON(w, http.StatusOK, sessionAttendanceResponse(s))
}

func nextSessionHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	var next *campaignSession
	var nextTime time.Time
	for _, s := range c.Sessions {
		t, err := time.Parse(time.RFC3339, s.StartsAt)
		if err != nil {
			continue
		}
		if next == nil || t.Before(nextTime) {
			next = s
			nextTime = t
		}
	}
	if next == nil {
		writeError(w, http.StatusNotFound, "no upcoming session")
		return
	}

	writeJSON(w, http.StatusOK, sessionNextResponse(next))
}

// campaignSessionsRouter dispatches /v1/campaigns/{id}/sessions... routes.
// rest is the path segment after "/v1/campaigns/{id}/". Returns true if it
// handled the request.
func campaignSessionsRouter(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "sessions" {
		scheduleSessionHandler(w, r, campaignID)
		return true
	}
	if rest == "sessions/next" {
		nextSessionHandler(w, r, campaignID)
		return true
	}
	if strings.HasPrefix(rest, "sessions/") && strings.HasSuffix(rest, "/attendance") {
		sessionID := strings.TrimSuffix(strings.TrimPrefix(rest, "sessions/"), "/attendance")
		if sessionID == "" {
			return false
		}
		sessionAttendanceHandler(w, r, campaignID, sessionID)
		return true
	}
	return false
}

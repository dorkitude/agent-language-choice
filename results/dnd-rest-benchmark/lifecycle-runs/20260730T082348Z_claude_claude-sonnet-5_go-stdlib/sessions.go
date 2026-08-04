package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"
)

type campaignSession struct {
	ID              string   `json:"id"`
	StartsAt        string   `json:"starts_at"`
	DurationMinutes int      `json:"duration_minutes"`
	Agenda          []string `json:"agenda"`
	Present         []string `json:"present"`
	Absent          []string `json:"absent"`
}

func sessionResponse(s *campaignSession) map[string]interface{} {
	return map[string]interface{}{
		"id":               s.ID,
		"starts_at":        s.StartsAt,
		"duration_minutes": s.DurationMinutes,
		"agenda_count":     len(s.Agenda),
	}
}

func sessionNextResponse(s *campaignSession) map[string]interface{} {
	return map[string]interface{}{
		"id":           s.ID,
		"starts_at":    s.StartsAt,
		"agenda_count": len(s.Agenda),
	}
}

func handleScheduleSession(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ID              string   `json:"id"`
		StartsAt        string   `json:"starts_at"`
		DurationMinutes *int     `json:"duration_minutes"`
		Agenda          []string `json:"agenda"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.StartsAt == "" || req.DurationMinutes == nil || *req.DurationMinutes <= 0 {
		writeError(w, http.StatusBadRequest, "id, starts_at, and duration_minutes are required")
		return
	}
	if _, err := time.Parse(time.RFC3339, req.StartsAt); err != nil {
		writeError(w, http.StatusBadRequest, "starts_at must be an RFC3339 timestamp")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, s := range c.Sessions {
		if s.ID == req.ID {
			campaignMu.Unlock()
			writeError(w, http.StatusConflict, "session id already exists")
			return
		}
	}
	agenda := req.Agenda
	if agenda == nil {
		agenda = []string{}
	}
	s := &campaignSession{
		ID:              req.ID,
		StartsAt:        req.StartsAt,
		DurationMinutes: *req.DurationMinutes,
		Agenda:          agenda,
		Present:         []string{},
		Absent:          []string{},
	}
	c.Sessions = append(c.Sessions, s)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, sessionResponse(s))
}

func handleRecordAttendance(w http.ResponseWriter, r *http.Request, campaignID, sessionID string) {
	var req struct {
		Present []string `json:"present"`
		Absent  []string `json:"absent"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	var s *campaignSession
	for _, sess := range c.Sessions {
		if sess.ID == sessionID {
			s = sess
			break
		}
	}
	if s == nil {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "session not found")
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
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"session_id":    s.ID,
		"present_count": len(s.Present),
		"absent_count":  len(s.Absent),
	})
}

func handleNextSession(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
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
	campaignMu.Unlock()

	if next == nil {
		writeError(w, http.StatusNotFound, "no sessions scheduled")
		return
	}

	writeJSON(w, http.StatusOK, sessionNextResponse(next))
}

func handleCampaignSessionsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "sessions" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleScheduleSession(w, r, campaignID)
		return true
	}
	if rest == "sessions/next" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleNextSession(w, r, campaignID)
		return true
	}
	if strings.HasPrefix(rest, "sessions/") && strings.HasSuffix(rest, "/attendance") {
		sessionID := strings.TrimSuffix(strings.TrimPrefix(rest, "sessions/"), "/attendance")
		if sessionID == "" {
			return false
		}
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleRecordAttendance(w, r, campaignID, sessionID)
		return true
	}
	return false
}

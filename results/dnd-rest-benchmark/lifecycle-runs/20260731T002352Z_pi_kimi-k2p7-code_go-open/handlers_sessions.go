package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func createCampaignSessionHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req campaignSession
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.StartsAt) == "" {
		badRequest(w, "starts_at is required")
		return
	}
	if req.DurationMinutes <= 0 {
		badRequest(w, "duration_minutes must be a positive integer")
		return
	}

	session := &campaignSession{
		ID:              req.ID,
		CampaignID:      campaignID,
		StartsAt:        req.StartsAt,
		DurationMinutes: req.DurationMinutes,
		Agenda:          req.Agenda,
	}
	if session.Agenda == nil {
		session.Agenda = []string{}
	}

	if err := dbCreateCampaignSession(campaignID, session); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "session id already exists")
			return
		}
		log.Printf("create campaign session: %v", err)
		badRequest(w, "failed to create session")
		return
	}

	writeJSON(w, http.StatusCreated, sessionResponse{
		ID:              session.ID,
		StartsAt:        session.StartsAt,
		DurationMinutes: session.DurationMinutes,
		AgendaCount:     len(session.Agenda),
	})
}

func recordAttendanceHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	sessionID := r.PathValue("session_id")
	if sessionID == "" {
		notFound(w, "session not found")
		return
	}

	s, err := dbGetCampaignSession(sessionID)
	if err != nil {
		log.Printf("get campaign session: %v", err)
		notFound(w, "session not found")
		return
	}
	if s == nil || s.CampaignID != campaignID {
		notFound(w, "session not found")
		return
	}

	var req attendanceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Present == nil {
		req.Present = []string{}
	}
	if req.Absent == nil {
		req.Absent = []string{}
	}

	if err := dbRecordAttendance(sessionID, req.Present, req.Absent); err != nil {
		log.Printf("record attendance: %v", err)
		badRequest(w, "failed to record attendance")
		return
	}

	writeJSON(w, http.StatusOK, attendanceResponse{
		SessionID:    sessionID,
		PresentCount: len(req.Present),
		AbsentCount:  len(req.Absent),
	})
}

func getNextSessionHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	sessions, err := dbGetSessionsByCampaign(campaignID)
	if err != nil {
		log.Printf("get campaign sessions: %v", err)
		badRequest(w, "failed to read sessions")
		return
	}
	if len(sessions) == 0 {
		notFound(w, "no sessions scheduled")
		return
	}

	next, err := dbGetCampaignSession(sessions[0].ID)
	if err != nil {
		log.Printf("get campaign session: %v", err)
		badRequest(w, "failed to read session")
		return
	}
	if next == nil {
		notFound(w, "session not found")
		return
	}

	writeJSON(w, http.StatusOK, nextSessionResponse{
		ID:          next.ID,
		StartsAt:    next.StartsAt,
		AgendaCount: len(next.Agenda),
	})
}

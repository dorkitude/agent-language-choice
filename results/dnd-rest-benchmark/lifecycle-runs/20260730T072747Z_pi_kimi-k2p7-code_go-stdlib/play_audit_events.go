package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// actorAuditEventRequest binds the payload for creating an audit event.
type actorAuditEventRequest struct {
	Kind          string `json:"kind"`
	CorrelationID string `json:"correlation_id"`
}

// actorAuditEvent is the immutable audit record shape returned by the API.
type actorAuditEvent struct {
	Kind          string `json:"kind"`
	Actor         string `json:"actor"`
	Role          string `json:"role"`
	Timestamp     int    `json:"timestamp"`
	CorrelationID string `json:"correlation_id"`
}

// actorAuditEventsResponse is the shape returned when listing audit events.
type actorAuditEventsResponse struct {
	Entries []actorAuditEvent `json:"entries"`
}

// nextAuditTimestamp returns the next monotonic timestamp for a campaign's
// audit trail. The caller must hold dbMu.
func nextAuditTimestamp(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(timestamp), 0) + 1 AS next_ts FROM campaign_audit_events WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextTs int `json:"next_ts"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextTs, nil
}

// createAuditEventHandler lets authenticated campaign members (including the
// owner) create an audit event. Unknown campaigns return 404; non-members
// receive 403; invalid payloads return 400; duplicate correlation_ids return 409.
func createAuditEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("audit event auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("audit event campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isOwner := campaign.Owner == username
	isMember := isOwner
	if !isMember {
		out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
		if err != nil {
			log.Printf("audit event member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		var memberRows []struct {
			One int `json:"1"`
		}
		if err := json.Unmarshal(out, &memberRows); err != nil {
			log.Printf("audit event member unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		isMember = len(memberRows) > 0
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req actorAuditEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Kind == "" || req.CorrelationID == "" {
		writeError(w, http.StatusBadRequest, "invalid audit event")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_audit_events WHERE campaign_id=%s AND correlation_id=%s LIMIT 1;", sq(campaignID), sq(req.CorrelationID)))
	if err != nil {
		log.Printf("audit event duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "correlation_id already exists")
		return
	}

	role := "player"
	if isOwner {
		role = "DM"
	}

	nextTs, err := nextAuditTimestamp(campaignID)
	if err != nil {
		log.Printf("audit event timestamp query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (%s, %s, %s, %s, %d, %s);",
		sq(campaignID), sq(req.Kind), sq(username), sq(role), nextTs, sq(req.CorrelationID))); err != nil {
		log.Printf("audit event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, actorAuditEvent{
		Kind:          req.Kind,
		Actor:         username,
		Role:          role,
		Timestamp:     nextTs,
		CorrelationID: req.CorrelationID,
	})
}

// listAuditEventsHandler returns the immutable audit trail for a campaign.
// Only the campaign owner may read it. Unknown campaigns return 404; non-owner
// members and non-members receive 403.
func listAuditEventsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("audit events list auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("audit events list campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT kind, actor, role, timestamp, correlation_id FROM campaign_audit_events WHERE campaign_id=%s ORDER BY timestamp;", sq(campaignID)))
	if err != nil {
		log.Printf("audit events list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		Kind          string `json:"kind"`
		Actor         string `json:"actor"`
		Role          string `json:"role"`
		Timestamp     int    `json:"timestamp"`
		CorrelationID string `json:"correlation_id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("audit events list unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	entries := make([]actorAuditEvent, 0, len(rows))
	for _, row := range rows {
		entries = append(entries, actorAuditEvent{
			Kind:          row.Kind,
			Actor:         row.Actor,
			Role:          row.Role,
			Timestamp:     row.Timestamp,
			CorrelationID: row.CorrelationID,
		})
	}
	if entries == nil {
		entries = []actorAuditEvent{}
	}

	writeJSON(w, http.StatusOK, actorAuditEventsResponse{Entries: entries})
}

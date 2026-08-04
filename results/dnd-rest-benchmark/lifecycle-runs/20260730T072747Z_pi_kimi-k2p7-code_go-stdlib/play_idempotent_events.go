package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// idempotentEventRequest binds the payload for creating an idempotent event.
type idempotentEventRequest struct {
	EventID string `json:"event_id"`
	Value   string `json:"value"`
}

// idempotentEventResponse is the immutable event shape returned by the create
// endpoint. The field order matches the exact JSON required by the stage
// contract.
type idempotentEventResponse struct {
	EventID        string `json:"event_id"`
	Value          string `json:"value"`
	Sequence       int    `json:"sequence"`
	IdempotencyKey string `json:"idempotency_key"`
}

// idempotentEventsListResponse is the ordered list returned by the read
// endpoint.
type idempotentEventsListResponse struct {
	Events []idempotentEventResponse `json:"events"`
}

// idempotentEventRow is the durable shape stored in the database.
type idempotentEventRow struct {
	CampaignID     string `json:"campaign_id"`
	Sequence       int    `json:"sequence"`
	EventID        string `json:"event_id"`
	Value          string `json:"value"`
	IdempotencyKey string `json:"idempotency_key"`
}

// nextIdempotentEventSequence returns the next monotonic sequence number for a
// campaign's idempotent event log. The caller must hold dbMu.
func nextIdempotentEventSequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_idempotent_events WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

// queryIdempotentEventByKey loads the stored event for a campaign and
// idempotency key, if any. The caller must hold dbMu.
func queryIdempotentEventByKey(campaignID, key string) (*idempotentEventRow, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT campaign_id, sequence, event_id, value, idempotency_key FROM campaign_idempotent_events WHERE campaign_id=%s AND idempotency_key=%s LIMIT 1;", sq(campaignID), sq(key)))
	if err != nil {
		return nil, false, err
	}
	var rows []idempotentEventRow
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// queryIdempotentEvents loads all idempotent events for a campaign ordered by
// sequence. The caller must hold dbMu.
func queryIdempotentEvents(campaignID string) ([]idempotentEventRow, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT campaign_id, sequence, event_id, value, idempotency_key FROM campaign_idempotent_events WHERE campaign_id=%s ORDER BY sequence;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var rows []idempotentEventRow
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	if rows == nil {
		return []idempotentEventRow{}, nil
	}
	return rows, nil
}

// createIdempotentEventHandler creates a campaign-scoped idempotent event.
// Authenticated campaign members (including the owner) may create. Duplicate
// mutating requests with the same idempotency key have exactly one public
// effect.
func createIdempotentEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("idempotent event auth query error: %v", err)
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
		log.Printf("idempotent event campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isMember := campaign.Owner == username
	if !isMember {
		isMember, err = isPlayCampaignMember(campaignID, username)
		if err != nil {
			log.Printf("idempotent event member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	idempotencyKey := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
	if idempotencyKey == "" {
		writeError(w, http.StatusBadRequest, "invalid idempotency key")
		return
	}

	var req idempotentEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Value == "" {
		writeError(w, http.StatusBadRequest, "invalid idempotent event")
		return
	}

	stored, exists, err := queryIdempotentEventByKey(campaignID, idempotencyKey)
	if err != nil {
		log.Printf("idempotent event key query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		if stored.EventID == req.EventID && stored.Value == req.Value {
			writeJSON(w, http.StatusOK, idempotentEventResponse{
				EventID:        stored.EventID,
				Value:          stored.Value,
				Sequence:       stored.Sequence,
				IdempotencyKey: stored.IdempotencyKey,
			})
			return
		}
		writeError(w, http.StatusConflict, "idempotency conflict")
		return
	}

	exists, err = queryExists(fmt.Sprintf("SELECT 1 FROM campaign_idempotent_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;", sq(campaignID), sq(req.EventID)))
	if err != nil {
		log.Printf("idempotent event duplicate event_id query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "event_id already exists")
		return
	}

	sequence, err := nextIdempotentEventSequence(campaignID)
	if err != nil {
		log.Printf("idempotent event sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (%s, %d, %s, %s, %s);",
		sq(campaignID), sequence, sq(req.EventID), sq(req.Value), sq(idempotencyKey))); err != nil {
		log.Printf("idempotent event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, idempotentEventResponse{
		EventID:        req.EventID,
		Value:          req.Value,
		Sequence:       sequence,
		IdempotencyKey: idempotencyKey,
	})
}

// listIdempotentEventsHandler returns the ordered idempotent event log for a
// campaign. The campaign owner and members may read it.
func listIdempotentEventsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("idempotent events list auth query error: %v", err)
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
		log.Printf("idempotent events list campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isReader := campaign.Owner == username
	if !isReader {
		isReader, err = isPlayCampaignMember(campaignID, username)
		if err != nil {
			log.Printf("idempotent events list member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isReader {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	rows, err := queryIdempotentEvents(campaignID)
	if err != nil {
		log.Printf("idempotent events list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	events := make([]idempotentEventResponse, 0, len(rows))
	for _, row := range rows {
		events = append(events, idempotentEventResponse{
			EventID:        row.EventID,
			Value:          row.Value,
			Sequence:       row.Sequence,
			IdempotencyKey: row.IdempotencyKey,
		})
	}

	writeJSON(w, http.StatusOK, idempotentEventsListResponse{Events: events})
}

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

const rateEventLimit = 2

// createRateEventRequest binds the payload for creating a rate event.
type createRateEventRequest struct {
	EventID string `json:"event_id"`
}

// rateEvent is the accepted rate event shape returned in lists.
type rateEvent struct {
	EventID string `json:"event_id"`
	Actor   string `json:"actor"`
}

// createRateEventResponse is the shape returned after a successful rate event
// creation. The field order matches the exact JSON required by the stage
// contract.
type createRateEventResponse struct {
	EventID   string `json:"event_id"`
	Actor     string `json:"actor"`
	Remaining int    `json:"remaining"`
}

// rateLimitResponse is the shape returned when the actor's allowance is
// exhausted.
type rateLimitResponse struct {
	Limit     int `json:"limit"`
	Remaining int `json:"remaining"`
}

// rateEventsListResponse is the shape returned when listing rate events.
type rateEventsListResponse struct {
	Events    []rateEvent `json:"events"`
	Remaining int         `json:"remaining"`
}

// countAcceptedRateEvents returns the number of accepted rate events for the
// actor in the campaign. The caller must hold dbMu.
func countAcceptedRateEvents(campaignID, actor string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COUNT(*) AS cnt FROM campaign_rate_events WHERE campaign_id=%s AND actor=%s;", sq(campaignID), sq(actor)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		Cnt int `json:"cnt"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 0, nil
	}
	return rows[0].Cnt, nil
}

// nextRateEventOrder returns the next monotonic acceptance order number for a
// campaign's rate event log. The caller must hold dbMu.
func nextRateEventOrder(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sort_order), 0) + 1 AS next_order FROM campaign_rate_events WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextOrder int `json:"next_order"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextOrder, nil
}

// queryRateEvents loads all accepted rate events for a campaign in acceptance
// order. The caller must hold dbMu.
func queryRateEvents(campaignID string) ([]rateEvent, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT event_id, actor FROM campaign_rate_events WHERE campaign_id=%s ORDER BY sort_order;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var events []rateEvent
	if err := json.Unmarshal(out, &events); err != nil {
		return nil, err
	}
	if events == nil {
		return []rateEvent{}, nil
	}
	return events, nil
}

// createRateEventHandler creates a campaign-scoped rate event. Authenticated
// campaign members (including the owner) may create. Each username has a fixed
// allowance of two accepted events per campaign; exhausted requests return 429
// without recording an event.
func createRateEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("rate event auth query error: %v", err)
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
		log.Printf("rate event campaign query error: %v", err)
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
			log.Printf("rate event member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req createRateEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" {
		writeError(w, http.StatusBadRequest, "invalid rate event")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_rate_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;", sq(campaignID), sq(req.EventID)))
	if err != nil {
		log.Printf("rate event duplicate event_id query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusBadRequest, "event_id already exists")
		return
	}

	acceptedCount, err := countAcceptedRateEvents(campaignID, username)
	if err != nil {
		log.Printf("rate event count query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	remaining := rateEventLimit - acceptedCount
	if remaining <= 0 {
		if err := incrementRejectedRateEvents(campaignID); err != nil {
			log.Printf("rate event rejected counter error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		writeJSON(w, http.StatusTooManyRequests, rateLimitResponse{
			Limit:     rateEventLimit,
			Remaining: 0,
		})
		return
	}

	nextOrder, err := nextRateEventOrder(campaignID)
	if err != nil {
		log.Printf("rate event order query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_rate_events (campaign_id, event_id, actor, sort_order) VALUES (%s, %s, %s, %d);",
		sq(campaignID), sq(req.EventID), sq(username), nextOrder)); err != nil {
		log.Printf("rate event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := incrementAcceptedRateEvents(campaignID); err != nil {
		log.Printf("rate event accepted counter error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, createRateEventResponse{
		EventID:   req.EventID,
		Actor:     username,
		Remaining: remaining - 1,
	})
}

// listRateEventsHandler returns the accepted rate events for a campaign in
// creation order plus the caller's remaining allowance. The campaign owner and
// members may read it.
func listRateEventsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("rate events list auth query error: %v", err)
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
		log.Printf("rate events list campaign query error: %v", err)
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
			log.Printf("rate events list member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isReader {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	events, err := queryRateEvents(campaignID)
	if err != nil {
		log.Printf("rate events list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	acceptedCount, err := countAcceptedRateEvents(campaignID, username)
	if err != nil {
		log.Printf("rate events list count query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	remaining := rateEventLimit - acceptedCount
	if remaining < 0 {
		remaining = 0
	}

	writeJSON(w, http.StatusOK, rateEventsListResponse{
		Events:    events,
		Remaining: remaining,
	})
}

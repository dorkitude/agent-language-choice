package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
)

// feedEventRequest binds the payload for a new feed event.
type feedEventRequest struct {
	EventID string `json:"event_id"`
	Text    string `json:"text"`
}

// feedEvent is the exact shape of an accepted feed event.
type feedEvent struct {
	EventID  string `json:"event_id"`
	Text     string `json:"text"`
	Sequence int    `json:"sequence"`
}

// feedEventListResponse is the exact shape returned when reading the feed.
type feedEventListResponse struct {
	Events     []feedEvent `json:"events"`
	NextCursor int         `json:"next_cursor"`
}

// createFeedEventHandler appends an event to the campaign's load-safe feed.
// Only authenticated campaign members (including the DM owner) may append.
func createFeedEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	var req feedEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid event")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_feed_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;", sq(campaignID), sq(req.EventID)))
	if err != nil {
		log.Printf("feed event duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "event_id already exists")
		return
	}

	seq, err := nextFeedEventSequence(campaignID)
	if err != nil {
		log.Printf("feed event sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_feed_events (campaign_id, event_id, text, sequence) VALUES (%s, %s, %s, %d);",
		sq(campaignID), sq(req.EventID), sq(req.Text), seq)); err != nil {
		log.Printf("feed event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, feedEvent{
		EventID:  req.EventID,
		Text:     req.Text,
		Sequence: seq,
	})
}

// nextFeedEventSequence returns the next one-based sequence number for a
// campaign's feed. The caller must hold dbMu.
func nextFeedEventSequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_feed_events WHERE campaign_id=%s;", sq(campaignID)))
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

// listFeedEventsHandler returns a stable cursor-paginated slice of the
// campaign's feed. Reads never mutate the feed. Only authenticated campaign
// members (including the DM owner) may read.
func listFeedEventsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	cursor := 0
	if c := r.URL.Query().Get("cursor"); c != "" {
		var err error
		cursor, err = strconv.Atoi(c)
		if err != nil || cursor < 0 {
			writeError(w, http.StatusBadRequest, "invalid pagination")
			return
		}
	}

	limit := 2
	if l := r.URL.Query().Get("limit"); l != "" {
		var err error
		limit, err = strconv.Atoi(l)
		if err != nil || limit < 1 || limit > 3 {
			writeError(w, http.StatusBadRequest, "invalid pagination")
			return
		}
	}

	out, err := dbQuery(fmt.Sprintf("SELECT event_id, text, sequence FROM campaign_feed_events WHERE campaign_id=%s ORDER BY sequence ASC LIMIT %d OFFSET %d;",
		sq(campaignID), limit, cursor))
	if err != nil {
		log.Printf("feed event list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var events []feedEvent
	if err := json.Unmarshal(out, &events); err != nil {
		log.Printf("feed event list unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if events == nil {
		events = []feedEvent{}
	}

	writeJSON(w, http.StatusOK, feedEventListResponse{
		Events:     events,
		NextCursor: cursor + len(events),
	})
}

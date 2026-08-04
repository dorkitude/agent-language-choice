package main

import (
	"encoding/json"
	"net/http"
	"strconv"
)

// playFeedEvent is a campaign-scoped, append-only feed event, accepted in
// append order and never mutated once recorded.
type playFeedEvent struct {
	EventID  string
	Text     string
	Sequence int
}

func playFeedEventResponse(evt *playFeedEvent) map[string]interface{} {
	return map[string]interface{}{
		"event_id": evt.EventID,
		"text":     evt.Text,
		"sequence": evt.Sequence,
	}
}

// handlePlayCampaignFeedEventsSub routes the "feed-events" and "event-feed"
// sub-paths of a play campaign. It returns false if rest does not name a
// recognized feed path, so the caller can fall through to its own routing.
func handlePlayCampaignFeedEventsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "feed-events" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAppendPlayFeedEvent(w, r, campaignID)
		return true
	}
	if rest == "event-feed" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleReadPlayFeedEvents(w, r, campaignID)
		return true
	}
	return false
}

// handleAppendPlayFeedEvent lets an authenticated campaign member (dm owner
// or joined player) append a new event to the campaign's event feed.
func handleAppendPlayFeedEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		EventID string `json:"event_id"`
		Text    string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "event_id and text are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may append feed events")
		return
	}
	for _, evt := range c.FeedEvents {
		if evt.EventID == req.EventID {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "event_id already exists")
			return
		}
	}

	evt := &playFeedEvent{
		EventID:  req.EventID,
		Text:     req.Text,
		Sequence: len(c.FeedEvents) + 1,
	}
	c.FeedEvents = append(c.FeedEvents, evt)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playFeedEventResponse(evt))
}

// handleReadPlayFeedEvents returns a cursor-paginated page of the campaign's
// event feed in append order. Reads never mutate the feed, so pagination
// stays stable even when new events are appended between reads.
func handleReadPlayFeedEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	query := r.URL.Query()

	cursor := 0
	if v := query.Get("cursor"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 {
			writeError(w, http.StatusBadRequest, "cursor must be a nonnegative integer")
			return
		}
		cursor = n
	}

	limit := 2
	if v := query.Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > 3 {
			writeError(w, http.StatusBadRequest, "limit must be an integer from 1 through 3")
			return
		}
		limit = n
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may read the event feed")
		return
	}

	events := make([]map[string]interface{}, 0, limit)
	nextCursor := cursor
	if cursor < len(c.FeedEvents) {
		end := cursor + limit
		if end > len(c.FeedEvents) {
			end = len(c.FeedEvents)
		}
		for _, evt := range c.FeedEvents[cursor:end] {
			events = append(events, playFeedEventResponse(evt))
		}
		nextCursor = end
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"events":      events,
		"next_cursor": nextCursor,
	})
}

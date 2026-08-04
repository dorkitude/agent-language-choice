package main

import (
	"net/http"
	"strconv"
	"sync"
)

// playFeedEvent is an append-only campaign event feed entry.
type playFeedEvent struct {
	CampaignID string
	EventID    string
	Text       string
	Sequence   int
}

// campaignFeedEventsMu guards campaignFeedEvents, the in-memory index
// mirroring the play_feed_events table. Keyed by campaign id, holding events
// in accepted append order.
var (
	campaignFeedEventsMu sync.Mutex
	campaignFeedEvents   = map[string][]*playFeedEvent{}
)

func feedEventJSON(e *playFeedEvent) map[string]any {
	return map[string]any{
		"event_id": e.EventID,
		"text":     e.Text,
		"sequence": e.Sequence,
	}
}

type createFeedEventRequest struct {
	EventID string `json:"event_id"`
	Text    string `json:"text"`
}

// createFeedEventHandler lets an authenticated campaign member or the dm
// append an event to the campaign's event feed.
func createFeedEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createFeedEventRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if _, ok := requireCampaignAccess(w, c, actor); !ok {
		return
	}

	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "event_id and text are required nonempty strings")
		return
	}

	campaignFeedEventsMu.Lock()
	defer campaignFeedEventsMu.Unlock()

	for _, existing := range campaignFeedEvents[campaignID] {
		if existing.EventID == req.EventID {
			writeError(w, http.StatusConflict, "event_id already exists in this campaign feed")
			return
		}
	}

	e := &playFeedEvent{
		CampaignID: campaignID,
		EventID:    req.EventID,
		Text:       req.Text,
		Sequence:   len(campaignFeedEvents[campaignID]) + 1,
	}
	if err := saveFeedEventToDB(e); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save feed event")
		return
	}
	campaignFeedEvents[campaignID] = append(campaignFeedEvents[campaignID], e)

	writeJSON(w, http.StatusCreated, feedEventJSON(e))
}

// listFeedEventsHandler returns a cursor-paginated slice of the campaign's
// event feed. It never mutates the feed, so it stays stable when events are
// appended between reads: a cursor always refers to "events consumed so
// far," not an index into a possibly-resized slice.
func listFeedEventsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if _, ok := requireCampaignAccess(w, c, actor); !ok {
		return
	}

	query := r.URL.Query()

	cursor := 0
	if raw := query.Get("cursor"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil || v < 0 {
			writeError(w, http.StatusBadRequest, "cursor must be a nonnegative integer")
			return
		}
		cursor = v
	}

	limit := 2
	if raw := query.Get("limit"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil || v < 1 || v > 3 {
			writeError(w, http.StatusBadRequest, "limit must be an integer from 1 through 3")
			return
		}
		limit = v
	}

	campaignFeedEventsMu.Lock()
	defer campaignFeedEventsMu.Unlock()

	feed := campaignFeedEvents[campaignID]

	events := make([]map[string]any, 0, limit)
	if cursor < len(feed) {
		end := cursor + limit
		if end > len(feed) {
			end = len(feed)
		}
		for _, e := range feed[cursor:end] {
			events = append(events, feedEventJSON(e))
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"events":      events,
		"next_cursor": cursor + len(events),
	})
}

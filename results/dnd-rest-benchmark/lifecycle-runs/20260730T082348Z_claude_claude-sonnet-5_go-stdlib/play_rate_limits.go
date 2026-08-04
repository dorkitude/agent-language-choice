package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playRateEventLimit is the fixed number of rate events each username may
// have accepted per campaign.
const playRateEventLimit = 2

// playRateEvent is an accepted campaign-scoped rate-limited event.
type playRateEvent struct {
	EventID string
	Actor   string
}

// handlePlayCampaignRateEventsSub routes the "rate-events" sub-path of a
// play campaign.
func handlePlayCampaignRateEventsSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest != "rate-events" {
		return false
	}
	switch r.Method {
	case http.MethodPost:
		handleCreatePlayRateEvent(w, r, id)
	case http.MethodGet:
		handleListPlayRateEvents(w, r, id)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
	return true
}

func handleCreatePlayRateEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		EventID string `json:"event_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if strings.TrimSpace(req.EventID) == "" {
		writeError(w, http.StatusBadRequest, "event_id is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign dm or member")
		return
	}

	if c.RateEventIDs != nil && c.RateEventIDs[req.EventID] {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "event_id already used in this campaign")
		return
	}

	used := c.RateEventCounts[username]
	if used >= playRateEventLimit {
		c.MetricsRejectedRateEvents++
		playMu.Unlock()
		persistState()
		writeJSON(w, http.StatusTooManyRequests, map[string]interface{}{
			"limit":     playRateEventLimit,
			"remaining": 0,
		})
		return
	}

	entry := &playRateEvent{
		EventID: req.EventID,
		Actor:   username,
	}
	c.RateEvents = append(c.RateEvents, entry)
	if c.RateEventIDs == nil {
		c.RateEventIDs = make(map[string]bool)
	}
	c.RateEventIDs[req.EventID] = true
	if c.RateEventCounts == nil {
		c.RateEventCounts = make(map[string]int)
	}
	c.RateEventCounts[username] = used + 1
	c.MetricsAcceptedRateEvents++
	remaining := playRateEventLimit - c.RateEventCounts[username]
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"event_id":  entry.EventID,
		"actor":     entry.Actor,
		"remaining": remaining,
	})
}

func handleListPlayRateEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign dm or member")
		return
	}

	events := make([]map[string]interface{}, 0, len(c.RateEvents))
	for _, e := range c.RateEvents {
		events = append(events, map[string]interface{}{
			"event_id": e.EventID,
			"actor":    e.Actor,
		})
	}
	remaining := playRateEventLimit - c.RateEventCounts[username]
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"events":    events,
		"remaining": remaining,
	})
}

package main

import (
	"encoding/json"
	"net/http"
	"sort"
	"strings"
)

// playWorldEventResolution is the immutable resolution recorded when a world
// event is resolved.
type playWorldEventResolution struct {
	TurnNumber int
	Text       string
}

// playWorldEvent is a campaign-level world event scheduled by the dm to
// resolve exactly once when the campaign reaches its turn number.
type playWorldEvent struct {
	EventID    string
	TurnNumber int
	Title      string
	Text       string
	Resolution *playWorldEventResolution
}

func playWorldEventResponse(e *playWorldEvent) map[string]interface{} {
	status := "scheduled"
	resp := map[string]interface{}{
		"event_id":    e.EventID,
		"turn_number": e.TurnNumber,
		"title":       e.Title,
		"text":        e.Text,
	}
	if e.Resolution != nil {
		status = "resolved"
		resp["resolution"] = map[string]interface{}{
			"turn_number": e.Resolution.TurnNumber,
			"text":        e.Resolution.Text,
		}
	}
	resp["status"] = status
	return resp
}

// findPlayWorldEvent locates a world event by id within c.
func findPlayWorldEvent(c *playCampaign, eventID string) *playWorldEvent {
	for _, e := range c.WorldEvents {
		if e.EventID == eventID {
			return e
		}
	}
	return nil
}

// handlePlayCampaignWorldEventSub routes the "world-events" and
// "world-events/..." sub-paths of a play campaign. It returns false if rest
// does not name a world-events path, so the caller can fall through to its
// own routing.
func handlePlayCampaignWorldEventSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "world-events" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayWorldEvent(w, r, campaignID)
		case http.MethodGet:
			handleListPlayWorldEvents(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if !strings.HasPrefix(rest, "world-events/") {
		return false
	}
	eventRest := strings.TrimPrefix(rest, "world-events/")
	if eventID, ok := strings.CutSuffix(eventRest, "/resolve"); ok && eventID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleResolvePlayWorldEvent(w, r, campaignID, eventID)
		return true
	}
	return false
}

// handleCreatePlayWorldEvent lets the campaign dm schedule a new world event
// for a future or current campaign turn.
func handleCreatePlayWorldEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		EventID    string `json:"event_id"`
		TurnNumber *int   `json:"turn_number"`
		Title      string `json:"title"`
		Text       string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Title == "" || req.Text == "" || req.TurnNumber == nil {
		writeError(w, http.StatusBadRequest, "event_id, turn_number, title, and text are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may schedule world events")
		return
	}
	if *req.TurnNumber < c.TurnNumber {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "turn_number must be greater than or equal to the campaign's current turn number")
		return
	}
	if findPlayWorldEvent(c, req.EventID) != nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "event_id already exists")
		return
	}

	e := &playWorldEvent{
		EventID:    req.EventID,
		TurnNumber: *req.TurnNumber,
		Title:      req.Title,
		Text:       req.Text,
	}
	c.WorldEvents = append(c.WorldEvents, e)
	resp := playWorldEventResponse(e)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleResolvePlayWorldEvent lets the campaign dm resolve a scheduled world
// event exactly once, on the exact turn it was scheduled for.
func handleResolvePlayWorldEvent(w http.ResponseWriter, r *http.Request, campaignID, eventID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Text string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may resolve world events")
		return
	}
	e := findPlayWorldEvent(c, eventID)
	if e == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "world event not found")
		return
	}
	if e.Resolution != nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "world event is already resolved")
		return
	}
	if c.TurnNumber != e.TurnNumber {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "world event may only be resolved on its scheduled turn")
		return
	}

	e.Resolution = &playWorldEventResolution{TurnNumber: e.TurnNumber, Text: req.Text}
	resp := playWorldEventResponse(e)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayWorldEvents returns every campaign world event, ordered by
// turn_number ascending then creation order, to any authenticated campaign
// member.
func handleListPlayWorldEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view world events")
		return
	}

	events := make([]*playWorldEvent, len(c.WorldEvents))
	copy(events, c.WorldEvents)
	sort.SliceStable(events, func(i, j int) bool {
		return events[i].TurnNumber < events[j].TurnNumber
	})
	resp := make([]map[string]interface{}, 0, len(events))
	for _, e := range events {
		resp = append(resp, playWorldEventResponse(e))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"events": resp,
	})
}

package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playIdempotentEvent is an immutable campaign-scoped idempotent event.
type playIdempotentEvent struct {
	Sequence       int
	EventID        string
	Value          string
	IdempotencyKey string
}

func playIdempotentEventResponse(e *playIdempotentEvent) map[string]interface{} {
	return map[string]interface{}{
		"event_id":        e.EventID,
		"value":           e.Value,
		"sequence":        e.Sequence,
		"idempotency_key": e.IdempotencyKey,
	}
}

// handlePlayCampaignIdempotentEventsSub routes the "idempotent-events"
// sub-path of a play campaign.
func handlePlayCampaignIdempotentEventsSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest != "idempotent-events" {
		return false
	}
	switch r.Method {
	case http.MethodPost:
		handleCreatePlayIdempotentEvent(w, r, id)
	case http.MethodGet:
		handleListPlayIdempotentEvents(w, r, id)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
	return true
}

func handleCreatePlayIdempotentEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	key := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
	if key == "" {
		writeError(w, http.StatusBadRequest, "Idempotency-Key header is required")
		return
	}

	var req struct {
		EventID string `json:"event_id"`
		Value   string `json:"value"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Value == "" {
		writeError(w, http.StatusBadRequest, "event_id and value are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign member")
		return
	}

	if existing, exists := c.IdempotencyKeys[key]; exists {
		playMu.Unlock()
		if existing.EventID == req.EventID && existing.Value == req.Value {
			writeJSON(w, http.StatusOK, playIdempotentEventResponse(existing))
			return
		}
		writeError(w, http.StatusConflict, "idempotency key already used with a different request")
		return
	}

	if _, exists := c.IdempotentEventIDs[req.EventID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "event_id already used in this campaign")
		return
	}

	c.IdempotentEventSeq++
	entry := &playIdempotentEvent{
		Sequence:       c.IdempotentEventSeq,
		EventID:        req.EventID,
		Value:          req.Value,
		IdempotencyKey: key,
	}
	c.IdempotentEvents = append(c.IdempotentEvents, entry)
	if c.IdempotentEventIDs == nil {
		c.IdempotentEventIDs = make(map[string]bool)
	}
	c.IdempotentEventIDs[req.EventID] = true
	if c.IdempotencyKeys == nil {
		c.IdempotencyKeys = make(map[string]*playIdempotentEvent)
	}
	c.IdempotencyKeys[key] = entry
	resp := playIdempotentEventResponse(entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleListPlayIdempotentEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	events := make([]map[string]interface{}, 0, len(c.IdempotentEvents))
	for _, e := range c.IdempotentEvents {
		events = append(events, playIdempotentEventResponse(e))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"events": events})
}

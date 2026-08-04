package main

import (
	"net/http"
	"strings"
	"sync"
)

// idempotentEvent is one immutable campaign idempotent-event record.
type idempotentEvent struct {
	CampaignID     string
	Sequence       int
	EventID        string
	Value          string
	IdempotencyKey string
}

// campaignIdempotentEventsMu guards campaignIdempotentEvents, the in-memory
// index mirroring the play_idempotent_events table. Keyed by campaign id,
// holding events in sequence order starting at 1.
var (
	campaignIdempotentEventsMu sync.Mutex
	campaignIdempotentEvents   = map[string][]*idempotentEvent{}
)

func idempotentEventJSON(e *idempotentEvent) map[string]any {
	return map[string]any{
		"event_id":        e.EventID,
		"value":           e.Value,
		"sequence":        e.Sequence,
		"idempotency_key": e.IdempotencyKey,
	}
}

type createIdempotentEventRequest struct {
	EventID string `json:"event_id"`
	Value   string `json:"value"`
}

// createIdempotentEventHandler lets authenticated campaign members, including
// the owner, create idempotent events. Repeating an Idempotency-Key with the
// same body replays the stored result; repeating it with a different body,
// or reusing an event_id under a different key, is rejected.
func createIdempotentEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	key := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
	if key == "" {
		writeError(w, http.StatusBadRequest, "Idempotency-Key header is required")
		return
	}

	var req createIdempotentEventRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a campaign member to create idempotent events")
		return
	}

	if req.EventID == "" || req.Value == "" {
		writeError(w, http.StatusBadRequest, "event_id and value must be nonempty strings")
		return
	}

	campaignIdempotentEventsMu.Lock()
	defer campaignIdempotentEventsMu.Unlock()

	for _, existing := range campaignIdempotentEvents[campaignID] {
		if existing.IdempotencyKey == key {
			if existing.EventID == req.EventID && existing.Value == req.Value {
				writeJSON(w, http.StatusOK, idempotentEventJSON(existing))
				return
			}
			writeError(w, http.StatusConflict, "idempotency key already used with a different request")
			return
		}
	}

	for _, existing := range campaignIdempotentEvents[campaignID] {
		if existing.EventID == req.EventID {
			writeError(w, http.StatusConflict, "event_id already exists in this campaign")
			return
		}
	}

	entry := &idempotentEvent{
		CampaignID:     campaignID,
		Sequence:       len(campaignIdempotentEvents[campaignID]) + 1,
		EventID:        req.EventID,
		Value:          req.Value,
		IdempotencyKey: key,
	}
	if err := saveIdempotentEventToDB(entry); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save idempotent event")
		return
	}
	campaignIdempotentEvents[campaignID] = append(campaignIdempotentEvents[campaignID], entry)

	writeJSON(w, http.StatusCreated, idempotentEventJSON(entry))
}

// listIdempotentEventsHandler lets the campaign DM and members read the
// campaign's idempotent events in sequence order.
func listIdempotentEventsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a campaign member to read idempotent events")
		return
	}

	campaignIdempotentEventsMu.Lock()
	defer campaignIdempotentEventsMu.Unlock()

	events := make([]map[string]any, 0, len(campaignIdempotentEvents[campaignID]))
	for _, e := range campaignIdempotentEvents[campaignID] {
		events = append(events, idempotentEventJSON(e))
	}

	writeJSON(w, http.StatusOK, map[string]any{"events": events})
}

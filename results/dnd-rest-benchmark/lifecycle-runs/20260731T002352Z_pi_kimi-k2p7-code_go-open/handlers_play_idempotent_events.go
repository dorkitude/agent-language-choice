package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createIdempotentEventHandler creates a campaign-scoped idempotent event.
// Any campaign member, including the owner, may create an event. Duplicate
// mutating requests with the same idempotency key have exactly one public
// effect.
func createIdempotentEventHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	idempotencyKey := strings.TrimSpace(r.Header.Get("Idempotency-Key"))
	if idempotencyKey == "" {
		badRequest(w, "idempotency key is required")
		return
	}

	var req idempotentEventCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.EventID) == "" {
		badRequest(w, "event_id is required")
		return
	}
	if strings.TrimSpace(req.Value) == "" {
		badRequest(w, "value is required")
		return
	}

	e := &idempotentEvent{
		EventID:        strings.TrimSpace(req.EventID),
		Value:          strings.TrimSpace(req.Value),
		IdempotencyKey: idempotencyKey,
	}

	e, created, err := dbCreateIdempotentEvent(id, e)
	if err != nil {
		if err == errIdempotentEventDuplicate || err == errIdempotentKeyConflict {
			conflict(w, "duplicate or conflicting idempotent event")
			return
		}
		log.Printf("create idempotent event: %v", err)
		badRequest(w, "failed to create idempotent event")
		return
	}

	statusCode := http.StatusCreated
	if !created {
		statusCode = http.StatusOK
	}
	writeJSON(w, statusCode, e)
}

// listIdempotentEventsHandler returns the campaign-scoped idempotent events in
// sequence order. The campaign owner and any member may read them.
func listIdempotentEventsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	events, err := dbListIdempotentEvents(id)
	if err != nil {
		log.Printf("list idempotent events: %v", err)
		badRequest(w, "failed to read idempotent events")
		return
	}

	writeJSON(w, http.StatusOK, idempotentEventsResponse{Events: events})
}

package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayAuditEventHandler creates an immutable campaign audit event. Any
// campaign member, including the owner, may create an event. Duplicate
// correlation_ids within the same campaign are rejected with 409.
func createPlayAuditEventHandler(w http.ResponseWriter, r *http.Request) {
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

	var req auditEventCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Kind) == "" {
		badRequest(w, "kind is required")
		return
	}
	if strings.TrimSpace(req.CorrelationID) == "" {
		badRequest(w, "correlation_id is required")
		return
	}

	role := "player"
	if p.Owner == u.Username {
		role = "DM"
	}

	e := &auditEvent{
		Kind:          req.Kind,
		Actor:         u.Username,
		Role:          role,
		CorrelationID: req.CorrelationID,
	}
	e, err := dbCreatePlayAuditEvent(id, e)
	if err != nil {
		if err == errAuditEventDuplicate {
			conflict(w, "duplicate correlation_id")
			return
		}
		log.Printf("create play audit event: %v", err)
		badRequest(w, "failed to create audit event")
		return
	}

	writeJSON(w, http.StatusCreated, e)
}

// listPlayAuditEventsHandler returns the immutable campaign audit trail in
// timestamp order. Only the campaign owner may read it.
func listPlayAuditEventsHandler(w http.ResponseWriter, r *http.Request) {
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
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can read audit events")
		return
	}

	entries, err := dbListPlayAuditEvents(id)
	if err != nil {
		log.Printf("list play audit events: %v", err)
		badRequest(w, "failed to read audit events")
		return
	}

	writeJSON(w, http.StatusOK, auditEventsResponse{Entries: entries})
}

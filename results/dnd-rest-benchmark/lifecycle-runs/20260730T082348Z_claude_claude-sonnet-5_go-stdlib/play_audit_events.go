package main

import (
	"encoding/json"
	"net/http"
)

// playAuditEvent is an immutable campaign-scoped audit trail entry recorded
// for a mutating campaign play event.
type playAuditEvent struct {
	Kind          string
	Actor         string
	Role          string
	Timestamp     int
	CorrelationID string
}

func playAuditEventResponse(e *playAuditEvent) map[string]interface{} {
	return map[string]interface{}{
		"kind":           e.Kind,
		"actor":          e.Actor,
		"role":           e.Role,
		"timestamp":      e.Timestamp,
		"correlation_id": e.CorrelationID,
	}
}

// handlePlayCampaignAuditEvents routes the "audit-events" sub-path of a play
// campaign.
func handlePlayCampaignAuditEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
	switch r.Method {
	case http.MethodPost:
		handleCreatePlayAuditEvent(w, r, campaignID)
	case http.MethodGet:
		handleListPlayAuditEvents(w, r, campaignID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
}

// handleCreatePlayAuditEvent lets any authenticated campaign member,
// including the owner, record an immutable audit entry.
func handleCreatePlayAuditEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Kind          string `json:"kind"`
		CorrelationID string `json:"correlation_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
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
	if req.Kind == "" || req.CorrelationID == "" {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "kind and correlation_id are required")
		return
	}
	if c.AuditCorrelationIDs != nil && c.AuditCorrelationIDs[req.CorrelationID] {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "correlation_id already used in this campaign")
		return
	}

	role := "player"
	if c.Owner == username {
		role = "DM"
	}
	c.AuditSeq++
	entry := &playAuditEvent{
		Kind:          req.Kind,
		Actor:         username,
		Role:          role,
		Timestamp:     c.AuditSeq,
		CorrelationID: req.CorrelationID,
	}
	c.AuditEvents = append(c.AuditEvents, entry)
	if c.AuditCorrelationIDs == nil {
		c.AuditCorrelationIDs = make(map[string]bool)
	}
	c.AuditCorrelationIDs[req.CorrelationID] = true
	resp := playAuditEventResponse(entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayAuditEvents lets only the campaign owner read the full audit
// trail, in timestamp order.
func handleListPlayAuditEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign owner may read the audit trail")
		return
	}

	entries := make([]map[string]interface{}, 0, len(c.AuditEvents))
	for _, e := range c.AuditEvents {
		entries = append(entries, playAuditEventResponse(e))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"entries": entries})
}

package main

import (
	"net/http"
	"sync"
)

// playAuditEntry is one immutable campaign play-event audit record.
type playAuditEntry struct {
	CampaignID    string
	Kind          string
	Actor         string
	Role          string
	Timestamp     int
	CorrelationID string
}

// campaignAuditMu guards campaignAudit, the in-memory index mirroring the
// play_audit_events table. Keyed by campaign id, holding entries in
// timestamp order starting at 1.
var (
	campaignAuditMu sync.Mutex
	campaignAudit   = map[string][]*playAuditEntry{}
)

func auditEntryJSON(e *playAuditEntry) map[string]any {
	return map[string]any{
		"kind":           e.Kind,
		"actor":          e.Actor,
		"role":           e.Role,
		"timestamp":      e.Timestamp,
		"correlation_id": e.CorrelationID,
	}
}

type createAuditEventRequest struct {
	Kind          string `json:"kind"`
	CorrelationID string `json:"correlation_id"`
}

// createAuditEventHandler lets any authenticated campaign member, including
// the owner, append an immutable audit entry to the campaign's audit trail.
func createAuditEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createAuditEventRequest
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
		writeError(w, http.StatusForbidden, "must be a campaign member to create audit events")
		return
	}

	if req.Kind == "" || req.CorrelationID == "" {
		writeError(w, http.StatusBadRequest, "kind and correlation_id must be nonempty strings")
		return
	}

	role := "player"
	if actor.Username == c.Owner {
		role = "DM"
	}

	campaignAuditMu.Lock()
	defer campaignAuditMu.Unlock()

	for _, existing := range campaignAudit[campaignID] {
		if existing.CorrelationID == req.CorrelationID {
			writeError(w, http.StatusConflict, "correlation_id already exists in this campaign")
			return
		}
	}

	entry := &playAuditEntry{
		CampaignID:    campaignID,
		Kind:          req.Kind,
		Actor:         actor.Username,
		Role:          role,
		Timestamp:     len(campaignAudit[campaignID]) + 1,
		CorrelationID: req.CorrelationID,
	}
	if err := saveAuditEventToDB(entry); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save audit event")
		return
	}
	campaignAudit[campaignID] = append(campaignAudit[campaignID], entry)

	writeJSON(w, http.StatusCreated, auditEntryJSON(entry))
}

// listAuditEventsHandler lets only the campaign owner read the campaign's
// audit trail.
func listAuditEventsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign owner may read the audit trail")
		return
	}

	campaignAuditMu.Lock()
	defer campaignAuditMu.Unlock()

	entries := make([]map[string]any, 0, len(campaignAudit[campaignID]))
	for _, e := range campaignAudit[campaignID] {
		entries = append(entries, auditEntryJSON(e))
	}

	writeJSON(w, http.StatusOK, map[string]any{"entries": entries})
}

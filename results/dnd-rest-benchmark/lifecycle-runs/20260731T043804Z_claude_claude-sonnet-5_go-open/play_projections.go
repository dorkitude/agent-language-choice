package main

import (
	"net/http"
	"sync"
)

// projectionEvent is one immutable campaign projection-event record.
type projectionEvent struct {
	CampaignID string
	Sequence   int
	EventID    string
	Kind       string
	Value      string
	HasValue   bool
}

// campaignProjectionsMu guards campaignProjectionEvents, the in-memory index
// mirroring the play_projection_events table. Keyed by campaign id, holding
// events in sequence order starting at 1.
var (
	campaignProjectionsMu    sync.Mutex
	campaignProjectionEvents = map[string][]*projectionEvent{}
)

func projectionEventJSON(e *projectionEvent) map[string]any {
	out := map[string]any{
		"sequence": e.Sequence,
		"event_id": e.EventID,
		"kind":     e.Kind,
	}
	if e.HasValue {
		out["value"] = e.Value
	}
	return out
}

// buildProjection rebuilds the deterministic projection solely from the
// ordered event log for a campaign.
func buildProjection(campaignID string) map[string]any {
	story := ""
	danger := 0
	appliedIDs := []string{}

	for _, e := range campaignProjectionEvents[campaignID] {
		switch e.Kind {
		case "set-story":
			story = e.Value
		case "increment-danger":
			danger++
		}
		appliedIDs = append(appliedIDs, e.EventID)
	}

	return map[string]any{
		"story":             story,
		"danger":            danger,
		"applied_event_ids": appliedIDs,
	}
}

type createProjectionEventRequest struct {
	EventID string  `json:"event_id"`
	Kind    string  `json:"kind"`
	Value   *string `json:"value"`
}

// createProjectionEventHandler lets authenticated campaign player members
// append immutable projection events. The campaign DM may not append.
func createProjectionEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createProjectionEventRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	isMember := isPlayMember(campaignID, actor.Username)
	if actor.Username != c.Owner && !isMember {
		writeError(w, http.StatusForbidden, "must be a campaign member to append projection events")
		return
	}
	if actor.Username == c.Owner {
		writeError(w, http.StatusForbidden, "the campaign DM may not append projection events")
		return
	}

	if req.EventID == "" {
		writeError(w, http.StatusBadRequest, "event_id must be a nonempty string")
		return
	}
	if req.Kind != "set-story" && req.Kind != "increment-danger" {
		writeError(w, http.StatusBadRequest, "kind must be exactly 'set-story' or 'increment-danger'")
		return
	}
	if req.Kind == "set-story" {
		if req.Value == nil || *req.Value == "" {
			writeError(w, http.StatusBadRequest, "value is required and must be a nonempty string for set-story")
			return
		}
	} else {
		if req.Value != nil {
			writeError(w, http.StatusBadRequest, "value must be omitted for increment-danger")
			return
		}
	}

	campaignProjectionsMu.Lock()
	defer campaignProjectionsMu.Unlock()

	for _, existing := range campaignProjectionEvents[campaignID] {
		if existing.EventID == req.EventID {
			writeError(w, http.StatusConflict, "event_id already exists in this campaign")
			return
		}
	}

	entry := &projectionEvent{
		CampaignID: campaignID,
		Sequence:   len(campaignProjectionEvents[campaignID]) + 1,
		EventID:    req.EventID,
		Kind:       req.Kind,
	}
	if req.Kind == "set-story" {
		entry.Value = *req.Value
		entry.HasValue = true
	}

	if err := saveProjectionEventToDB(entry); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save projection event")
		return
	}
	campaignProjectionEvents[campaignID] = append(campaignProjectionEvents[campaignID], entry)

	writeJSON(w, http.StatusCreated, projectionEventJSON(entry))
}

// getProjectionHandler lets the campaign DM and members read the current
// projection, rebuilt from the ordered event log.
func getProjectionHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "must be a campaign member to read the projection")
		return
	}

	campaignProjectionsMu.Lock()
	defer campaignProjectionsMu.Unlock()

	writeJSON(w, http.StatusOK, buildProjection(campaignID))
}

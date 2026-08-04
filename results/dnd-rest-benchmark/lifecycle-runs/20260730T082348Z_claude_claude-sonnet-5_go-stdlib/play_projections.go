package main

import (
	"encoding/json"
	"net/http"
)

// playProjectionEvent is an immutable campaign-scoped projection event.
type playProjectionEvent struct {
	Sequence int
	EventID  string
	Kind     string
	Value    string
	HasValue bool
}

func playProjectionEventResponse(e *playProjectionEvent) map[string]interface{} {
	resp := map[string]interface{}{
		"sequence": e.Sequence,
		"event_id": e.EventID,
		"kind":     e.Kind,
	}
	if e.HasValue {
		resp["value"] = e.Value
	}
	return resp
}

// playProjection is the deterministic state rebuilt from a campaign's ordered
// projection events.
type playProjection struct {
	Story           string
	Danger          int
	AppliedEventIDs []string
}

func playProjectionResponse(p *playProjection) map[string]interface{} {
	ids := p.AppliedEventIDs
	if ids == nil {
		ids = []string{}
	}
	return map[string]interface{}{
		"story":             p.Story,
		"danger":            p.Danger,
		"applied_event_ids": ids,
	}
}

// buildPlayProjection rebuilds a projection solely from the ordered event
// log. It must be called with playMu already held.
func buildPlayProjection(c *playCampaign) *playProjection {
	p := &playProjection{AppliedEventIDs: []string{}}
	for _, e := range c.ProjectionEvents {
		switch e.Kind {
		case "set-story":
			p.Story = e.Value
		case "increment-danger":
			p.Danger++
		}
		p.AppliedEventIDs = append(p.AppliedEventIDs, e.EventID)
	}
	return p
}

// handlePlayCampaignProjectionSub routes the "projection-events", "projection",
// and "projection/rebuild" sub-paths of a play campaign.
func handlePlayCampaignProjectionSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest == "projection-events" {
		handlePlayCampaignProjectionEvents(w, r, id)
		return true
	}
	if rest == "projection/rebuild" {
		handleGetPlayCampaignProjection(w, r, id)
		return true
	}
	if rest == "projection" {
		handleGetPlayCampaignProjection(w, r, id)
		return true
	}
	return false
}

func handlePlayCampaignProjectionEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	handleCreatePlayProjectionEvent(w, r, campaignID)
}

func handleCreatePlayProjectionEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		EventID string  `json:"event_id"`
		Kind    string  `json:"kind"`
		Value   *string `json:"value"`
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
	if c.Owner == username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "the campaign dm may not append projection events")
		return
	}
	if !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign member")
		return
	}

	if req.EventID == "" {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "event_id is required")
		return
	}
	if req.Kind != "set-story" && req.Kind != "increment-danger" {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "kind must be set-story or increment-danger")
		return
	}
	if req.Kind == "set-story" {
		if req.Value == nil || *req.Value == "" {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "value is required for set-story")
			return
		}
	} else {
		if req.Value != nil {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "value must be omitted for increment-danger")
			return
		}
	}
	if c.ProjectionEventIDs != nil && c.ProjectionEventIDs[req.EventID] {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "event_id already used in this campaign")
		return
	}

	c.ProjectionSeq++
	entry := &playProjectionEvent{
		Sequence: c.ProjectionSeq,
		EventID:  req.EventID,
		Kind:     req.Kind,
	}
	if req.Kind == "set-story" {
		entry.Value = *req.Value
		entry.HasValue = true
	}
	c.ProjectionEvents = append(c.ProjectionEvents, entry)
	if c.ProjectionEventIDs == nil {
		c.ProjectionEventIDs = make(map[string]bool)
	}
	c.ProjectionEventIDs[req.EventID] = true
	c.MetricsProjectionEvents++
	buildPlayProjection(c)
	resp := playProjectionEventResponse(entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleGetPlayCampaignProjection(w http.ResponseWriter, r *http.Request, campaignID string) {
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
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

	p := buildPlayProjection(c)
	resp := playProjectionResponse(p)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

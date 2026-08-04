package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createProjectionEventHandler appends an immutable projection event. Only
// campaign player members may append; the campaign owner (DM) may read
// projections but may not append.
func createProjectionEventHandler(w http.ResponseWriter, r *http.Request) {
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
	if p.Owner == u.Username {
		forbidden(w, "DM may not append projection events")
		return
	}

	var req projectionEventCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if strings.TrimSpace(req.EventID) == "" {
		badRequest(w, "event_id is required")
		return
	}
	if req.Kind != projectionKindSetStory && req.Kind != projectionKindIncrementDanger {
		badRequest(w, "kind must be set-story or increment-danger")
		return
	}

	if req.Kind == projectionKindSetStory {
		if req.Value == nil {
			badRequest(w, "value is required for set-story")
			return
		}
		if strings.TrimSpace(*req.Value) == "" {
			badRequest(w, "value must be a non-empty string")
			return
		}
	} else {
		if req.Value != nil {
			badRequest(w, "value must be omitted for increment-danger")
			return
		}
	}

	e := &projectionEvent{
		EventID: req.EventID,
		Kind:    req.Kind,
	}
	if req.Value != nil {
		e.Value = strings.TrimSpace(*req.Value)
	}

	e, err := dbCreateProjectionEvent(id, e)
	if err != nil {
		if err == errProjectionEventDuplicate {
			conflict(w, "duplicate event_id")
			return
		}
		log.Printf("create projection event: %v", err)
		badRequest(w, "failed to create projection event")
		return
	}

	writeJSON(w, http.StatusCreated, e)
}

// getProjectionHandler returns the deterministic projection rebuilt from
// the campaign's ordered projection event log. The campaign owner and any
// member may read it.
func getProjectionHandler(w http.ResponseWriter, r *http.Request) {
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

	proj, err := buildProjection(id)
	if err != nil {
		log.Printf("build projection: %v", err)
		badRequest(w, "failed to build projection")
		return
	}

	writeJSON(w, http.StatusOK, proj)
}

// rebuildProjectionHandler returns the same projection as getProjectionHandler,
// rebuilt solely from the ordered event log. This explicit rebuild endpoint is
// useful for verifying deterministic replayability.
func rebuildProjectionHandler(w http.ResponseWriter, r *http.Request) {
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

	proj, err := buildProjection(id)
	if err != nil {
		log.Printf("build projection: %v", err)
		badRequest(w, "failed to build projection")
		return
	}

	writeJSON(w, http.StatusOK, proj)
}

// buildProjection rebuilds the deterministic projection from the ordered
// projection event log for the given campaign.
func buildProjection(campaignID string) (*projectionResponse, error) {
	events, err := dbListProjectionEvents(campaignID)
	if err != nil {
		return nil, err
	}

	proj := &projectionResponse{
		Story:           "",
		Danger:          0,
		AppliedEventIDs: make([]string, 0, len(events)),
	}

	for _, e := range events {
		proj.AppliedEventIDs = append(proj.AppliedEventIDs, e.EventID)
		switch e.Kind {
		case projectionKindSetStory:
			proj.Story = e.Value
		case projectionKindIncrementDanger:
			proj.Danger++
		}
	}

	return proj, nil
}

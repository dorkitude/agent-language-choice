package main

import (
	"net/http"
	"sync"
)

// rateEventLimit is the fixed number of accepted rate events allowed per
// username per campaign.
const rateEventLimit = 2

// rateEvent is one accepted campaign rate event.
type rateEvent struct {
	CampaignID string
	EntryID    int
	EventID    string
	Actor      string
}

// campaignRateEventsMu guards campaignRateEvents, the in-memory index
// mirroring the play_rate_events table. Keyed by campaign id, holding
// accepted events in acceptance order.
var (
	campaignRateEventsMu sync.Mutex
	campaignRateEvents   = map[string][]*rateEvent{}
)

func rateEventJSON(e *rateEvent) map[string]any {
	return map[string]any{
		"event_id": e.EventID,
		"actor":    e.Actor,
	}
}

// remainingRateAllowance returns how many more events username may accept in
// this campaign, given the events already recorded.
func remainingRateAllowance(campaignID, username string) int {
	used := 0
	for _, e := range campaignRateEvents[campaignID] {
		if e.Actor == username {
			used++
		}
	}
	remaining := rateEventLimit - used
	if remaining < 0 {
		remaining = 0
	}
	return remaining
}

type createRateEventRequest struct {
	EventID string `json:"event_id"`
}

// createRateEventHandler lets the campaign DM or any campaign member create
// a rate event, subject to a fixed per-username allowance of two accepted
// events per campaign.
func createRateEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createRateEventRequest
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
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	if req.EventID == "" {
		writeError(w, http.StatusBadRequest, "event_id is required and must be nonempty")
		return
	}

	campaignRateEventsMu.Lock()
	defer campaignRateEventsMu.Unlock()

	for _, existing := range campaignRateEvents[campaignID] {
		if existing.EventID == req.EventID {
			writeError(w, http.StatusBadRequest, "event_id already exists in this campaign")
			return
		}
	}

	remaining := remainingRateAllowance(campaignID, actor.Username)
	if remaining <= 0 {
		recordRejectedRateEvent(campaignID)
		writeJSON(w, http.StatusTooManyRequests, map[string]any{
			"limit":     rateEventLimit,
			"remaining": 0,
		})
		return
	}

	e := &rateEvent{
		CampaignID: campaignID,
		EntryID:    len(campaignRateEvents[campaignID]),
		EventID:    req.EventID,
		Actor:      actor.Username,
	}
	if err := saveRateEventToDB(e); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save rate event")
		return
	}
	campaignRateEvents[campaignID] = append(campaignRateEvents[campaignID], e)

	writeJSON(w, http.StatusCreated, map[string]any{
		"event_id":  e.EventID,
		"actor":     e.Actor,
		"remaining": remaining - 1,
	})
}

// listRateEventsHandler lets the campaign DM and members list accepted rate
// events in creation order, along with the caller's remaining allowance.
func listRateEventsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	campaignRateEventsMu.Lock()
	defer campaignRateEventsMu.Unlock()

	events := make([]map[string]any, 0, len(campaignRateEvents[campaignID]))
	for _, e := range campaignRateEvents[campaignID] {
		events = append(events, rateEventJSON(e))
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"events":    events,
		"remaining": remainingRateAllowance(campaignID, actor.Username),
	})
}

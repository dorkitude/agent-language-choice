package main

import (
	"net/http"
	"sort"
	"sync"
)

// worldEvent is a deterministic campaign-level event scheduled for a future
// turn and resolved exactly once when that turn is reached.
type worldEvent struct {
	CampaignID           string
	EventID              string
	TurnNumber           int
	Title                string
	Text                 string
	Resolved             bool
	ResolutionTurnNumber int
	ResolutionText       string
}

// worldEventsMu guards worldEvents, the in-memory index mirroring the
// play_world_events table. Keyed by campaign id, holding events in creation
// order.
var (
	worldEventsMu sync.Mutex
	worldEvents   = map[string][]*worldEvent{}
)

func worldEventJSON(e *worldEvent) map[string]any {
	status := "scheduled"
	out := map[string]any{
		"event_id":    e.EventID,
		"turn_number": e.TurnNumber,
		"title":       e.Title,
		"text":        e.Text,
	}
	if e.Resolved {
		status = "resolved"
		out["resolution"] = map[string]any{
			"turn_number": e.ResolutionTurnNumber,
			"text":        e.ResolutionText,
		}
	}
	out["status"] = status
	return out
}

// findWorldEvent returns the world event with the given id in campaignID, or
// nil. Callers must already hold worldEventsMu.
func findWorldEvent(campaignID, eventID string) *worldEvent {
	for _, e := range worldEvents[campaignID] {
		if e.EventID == eventID {
			return e
		}
	}
	return nil
}

type createWorldEventRequest struct {
	EventID    string `json:"event_id"`
	TurnNumber int    `json:"turn_number"`
	Title      string `json:"title"`
	Text       string `json:"text"`
}

// createWorldEventHandler lets the campaign's owning dm schedule a
// deterministic world event for a future (or current) campaign turn.
func createWorldEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createWorldEventRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may schedule world events")
		return
	}

	if req.EventID == "" || req.Title == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "event_id, title, and text are required nonempty strings")
		return
	}
	if req.TurnNumber < c.TurnNumber {
		writeError(w, http.StatusBadRequest, "turn_number must be greater than or equal to the campaign's current turn number")
		return
	}

	worldEventsMu.Lock()
	defer worldEventsMu.Unlock()

	if findWorldEvent(campaignID, req.EventID) != nil {
		writeError(w, http.StatusConflict, "event_id already exists in this campaign")
		return
	}

	e := &worldEvent{
		CampaignID: campaignID,
		EventID:    req.EventID,
		TurnNumber: req.TurnNumber,
		Title:      req.Title,
		Text:       req.Text,
	}
	if err := saveWorldEventToDB(e); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save world event")
		return
	}
	worldEvents[campaignID] = append(worldEvents[campaignID], e)

	writeJSON(w, http.StatusCreated, worldEventJSON(e))
}

type resolveWorldEventRequest struct {
	Text string `json:"text"`
}

// resolveWorldEventHandler lets the campaign's owning dm resolve a scheduled
// world event, exactly once, when the campaign's current turn matches the
// event's scheduled turn.
func resolveWorldEventHandler(w http.ResponseWriter, r *http.Request, campaignID, eventID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req resolveWorldEventRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may resolve world events")
		return
	}

	worldEventsMu.Lock()
	defer worldEventsMu.Unlock()

	e := findWorldEvent(campaignID, eventID)
	if e == nil {
		writeError(w, http.StatusNotFound, "unknown world event id")
		return
	}

	if req.Text == "" {
		writeError(w, http.StatusBadRequest, "text is a required nonempty string")
		return
	}

	if e.Resolved {
		writeError(w, http.StatusConflict, "world event has already been resolved")
		return
	}
	if c.TurnNumber != e.TurnNumber {
		writeError(w, http.StatusConflict, "campaign turn number must exactly match the event's scheduled turn number")
		return
	}

	e.Resolved = true
	e.ResolutionTurnNumber = e.TurnNumber
	e.ResolutionText = req.Text
	if err := saveWorldEventToDB(e); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save world event")
		return
	}

	writeJSON(w, http.StatusCreated, worldEventJSON(e))
}

// listWorldEventsHandler returns a campaign's world events ordered by turn
// number ascending, then creation order for events scheduled on the same
// turn. Any authenticated campaign member (including the dm) may call this.
func listWorldEventsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	worldEventsMu.Lock()
	defer worldEventsMu.Unlock()

	ordered := make([]*worldEvent, len(worldEvents[campaignID]))
	copy(ordered, worldEvents[campaignID])
	sort.SliceStable(ordered, func(i, j int) bool {
		return ordered[i].TurnNumber < ordered[j].TurnNumber
	})

	events := make([]map[string]any, 0, len(ordered))
	for _, e := range ordered {
		events = append(events, worldEventJSON(e))
	}

	writeJSON(w, http.StatusOK, map[string]any{"events": events})
}

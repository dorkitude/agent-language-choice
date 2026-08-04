package main

import (
	"net/http"
	"sort"
	"sync"
)

// safetyBoundary holds a campaign's current blocked-tags list, replaced
// atomically by the campaign dm.
type safetyBoundary struct {
	CampaignID  string
	BlockedTags []string
}

// safetyEvent is an accepted safety check, appended in submission order.
type safetyEvent struct {
	CampaignID string
	EventID    string
	Kind       string
	Text       string
	Tags       []string
	Sequence   int
}

// safetyBoundariesMu guards safetyBoundaries, the in-memory index mirroring
// the play_safety_boundaries table. Keyed by campaign id.
var (
	safetyBoundariesMu sync.Mutex
	safetyBoundaries    = map[string]*safetyBoundary{}
)

// safetyEventsMu guards safetyEvents, the in-memory index mirroring the
// play_safety_events table. Keyed by campaign id, holding events in append
// order.
var (
	safetyEventsMu sync.Mutex
	safetyEvents    = map[string][]*safetyEvent{}
)

func sortedTagsCopy(tags []string) []string {
	out := append([]string(nil), tags...)
	sort.Strings(out)
	return out
}

func safetyBoundaryJSON(b *safetyBoundary) map[string]any {
	tags := []string{}
	if b != nil {
		tags = sortedTagsCopy(b.BlockedTags)
	}
	return map[string]any{"blocked_tags": tags}
}

func safetyEventJSON(ev *safetyEvent) map[string]any {
	return map[string]any{
		"event_id": ev.EventID,
		"kind":     ev.Kind,
		"text":     ev.Text,
		"tags":     ev.Tags,
		"sequence": ev.Sequence,
	}
}

// findSafetyEvent returns the event with the given id in campaignID, or nil.
// Callers must already hold safetyEventsMu.
func findSafetyEvent(campaignID, eventID string) *safetyEvent {
	for _, ev := range safetyEvents[campaignID] {
		if ev.EventID == eventID {
			return ev
		}
	}
	return nil
}

type replaceSafetyBoundariesRequest struct {
	BlockedTags []string `json:"blocked_tags"`
}

// replaceSafetyBoundariesHandler lets only the campaign dm atomically
// replace the campaign's blocked-tags list.
func replaceSafetyBoundariesHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req replaceSafetyBoundariesRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may replace safety boundaries")
		return
	}

	if len(req.BlockedTags) == 0 || !uniqueNonEmptyStrings(req.BlockedTags) {
		writeError(w, http.StatusBadRequest, "blocked_tags must be a nonempty array of unique nonempty strings")
		return
	}

	safetyBoundariesMu.Lock()
	defer safetyBoundariesMu.Unlock()

	b := &safetyBoundary{CampaignID: campaignID, BlockedTags: req.BlockedTags}
	if err := saveSafetyBoundaryToDB(b); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save safety boundaries")
		return
	}
	safetyBoundaries[campaignID] = b

	writeJSON(w, http.StatusOK, safetyBoundaryJSON(b))
}

// getSafetyBoundariesHandler lets any authenticated campaign member,
// including the dm, read the campaign's current safety boundaries.
func getSafetyBoundariesHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	safetyBoundariesMu.Lock()
	defer safetyBoundariesMu.Unlock()

	writeJSON(w, http.StatusOK, safetyBoundaryJSON(safetyBoundaries[campaignID]))
}

type createSafetyCheckRequest struct {
	EventID string   `json:"event_id"`
	Kind    string   `json:"kind"`
	Text    string   `json:"text"`
	Tags    []string `json:"tags"`
}

// createSafetyCheckHandler lets any authenticated campaign member, including
// the dm, submit a safety check that is accepted unless it duplicates an
// already-accepted event id or touches a currently blocked tag.
func createSafetyCheckHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createSafetyCheckRequest
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

	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "event_id and text are required nonempty strings")
		return
	}
	if req.Kind != "narration" && req.Kind != "chat" {
		writeError(w, http.StatusBadRequest, "kind must be exactly narration or chat")
		return
	}
	if len(req.Tags) == 0 || !uniqueNonEmptyStrings(req.Tags) {
		writeError(w, http.StatusBadRequest, "tags must be a nonempty array of unique nonempty strings")
		return
	}

	safetyBoundariesMu.Lock()
	defer safetyBoundariesMu.Unlock()
	safetyEventsMu.Lock()
	defer safetyEventsMu.Unlock()

	if findSafetyEvent(campaignID, req.EventID) != nil {
		writeError(w, http.StatusConflict, "event_id already accepted in this campaign")
		return
	}

	if b, present := safetyBoundaries[campaignID]; present {
		blocked := map[string]bool{}
		for _, t := range b.BlockedTags {
			blocked[t] = true
		}
		for _, t := range req.Tags {
			if blocked[t] {
				writeError(w, http.StatusConflict, "submitted tags include a currently blocked tag")
				return
			}
		}
	}

	sequence := len(safetyEvents[campaignID]) + 1
	ev := &safetyEvent{
		CampaignID: campaignID,
		EventID:    req.EventID,
		Kind:       req.Kind,
		Text:       req.Text,
		Tags:       req.Tags,
		Sequence:   sequence,
	}
	if err := saveSafetyEventToDB(ev); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save safety event")
		return
	}
	safetyEvents[campaignID] = append(safetyEvents[campaignID], ev)

	writeJSON(w, http.StatusCreated, safetyEventJSON(ev))
}

// listSafetyEventsHandler returns a campaign's accepted safety events in
// stable append order. Any authenticated campaign member, including the dm,
// may call this.
func listSafetyEventsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	safetyEventsMu.Lock()
	defer safetyEventsMu.Unlock()

	events := make([]map[string]any, 0, len(safetyEvents[campaignID]))
	for _, ev := range safetyEvents[campaignID] {
		events = append(events, safetyEventJSON(ev))
	}

	writeJSON(w, http.StatusOK, map[string]any{"events": events})
}

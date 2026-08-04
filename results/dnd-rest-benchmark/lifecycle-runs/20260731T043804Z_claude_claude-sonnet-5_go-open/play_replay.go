package main

import (
	"net/http"
	"strings"
	"sync"
)

// replayEvent is one immutable campaign replay-stream event.
type replayEvent struct {
	CampaignID string
	Sequence   int
	EventID    string
	Kind       string
	Text       string
}

// campaignReplayEventsMu guards campaignReplayEvents, the in-memory index
// mirroring the play_replay_events table. Keyed by campaign id, holding
// events in successful append order starting at sequence 1.
var (
	campaignReplayEventsMu sync.Mutex
	campaignReplayEvents   = map[string][]*replayEvent{}
)

func replayEventJSON(e *replayEvent) map[string]any {
	return map[string]any{
		"event_id": e.EventID,
		"kind":     e.Kind,
		"text":     e.Text,
		"sequence": e.Sequence,
	}
}

func replayStateJSON(campaignID string) map[string]any {
	events := campaignReplayEvents[campaignID]
	eventIDs := make([]string, 0, len(events))
	var story strings.Builder
	for _, e := range events {
		eventIDs = append(eventIDs, e.EventID)
		story.WriteString(e.Text)
	}
	digest := strings.Join(eventIDs, ",") + "|" + story.String()
	return map[string]any{
		"story":     story.String(),
		"event_ids": eventIDs,
		"digest":    digest,
	}
}

type createReplayEventRequest struct {
	EventID string `json:"event_id"`
	Kind    string `json:"kind"`
	Text    string `json:"text"`
}

func requireReplayMember(w http.ResponseWriter, actor *user, c *playCampaign, campaignID string) bool {
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a campaign member to access replay")
		return false
	}
	return true
}

// createReplayEventHandler lets the campaign DM and members append
// deterministic replay events. event_id must be unique within the campaign
// replay stream; duplicates return 409 without mutating state.
func createReplayEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createReplayEventRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !requireReplayMember(w, actor, c, campaignID) {
		return
	}

	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "event_id and text must be nonempty strings")
		return
	}
	if req.Kind != "append" {
		writeError(w, http.StatusBadRequest, "kind must be exactly 'append'")
		return
	}

	campaignReplayEventsMu.Lock()
	defer campaignReplayEventsMu.Unlock()

	for _, existing := range campaignReplayEvents[campaignID] {
		if existing.EventID == req.EventID {
			writeError(w, http.StatusConflict, "event_id already exists in this campaign replay stream")
			return
		}
	}

	entry := &replayEvent{
		CampaignID: campaignID,
		Sequence:   len(campaignReplayEvents[campaignID]) + 1,
		EventID:    req.EventID,
		Kind:       req.Kind,
		Text:       req.Text,
	}
	if err := saveReplayEventToDB(entry); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save replay event")
		return
	}
	campaignReplayEvents[campaignID] = append(campaignReplayEvents[campaignID], entry)

	writeJSON(w, http.StatusCreated, replayEventJSON(entry))
}

// getReplayHandler lets the campaign DM and members read the deterministic
// replay state rebuilt from successfully appended events.
func getReplayHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if !requireReplayMember(w, actor, c, campaignID) {
		return
	}

	campaignReplayEventsMu.Lock()
	defer campaignReplayEventsMu.Unlock()

	writeJSON(w, http.StatusOK, replayStateJSON(campaignID))
}

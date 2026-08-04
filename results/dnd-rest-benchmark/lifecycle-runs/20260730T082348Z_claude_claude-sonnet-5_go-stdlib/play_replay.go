package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playReplayEvent is an immutable campaign-scoped replay event.
type playReplayEvent struct {
	Sequence int
	EventID  string
	Kind     string
	Text     string
}

func playReplayEventResponse(e *playReplayEvent) map[string]interface{} {
	return map[string]interface{}{
		"event_id": e.EventID,
		"kind":     e.Kind,
		"text":     e.Text,
		"sequence": e.Sequence,
	}
}

// playReplayState computes the deterministic public replay state for c.
func playReplayState(c *playCampaign) map[string]interface{} {
	eventIDs := make([]string, 0, len(c.ReplayEvents))
	var story strings.Builder
	for _, e := range c.ReplayEvents {
		eventIDs = append(eventIDs, e.EventID)
		story.WriteString(e.Text)
	}
	storyStr := story.String()
	digest := strings.Join(eventIDs, ",") + "|" + storyStr
	return map[string]interface{}{
		"story":     storyStr,
		"event_ids": eventIDs,
		"digest":    digest,
	}
}

// handlePlayCampaignReplaySub routes the "replay-events", "replay", and
// "replay/check" sub-paths of a play campaign. It returns false if rest does
// not name a replay path, so the caller can fall through to its own routing.
func handlePlayCampaignReplaySub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	switch rest {
	case "replay-events":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAppendPlayReplayEvent(w, r, campaignID)
		return true
	case "replay", "replay/check":
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleReadPlayReplay(w, r, campaignID)
		return true
	}
	return false
}

func handleAppendPlayReplayEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		EventID string `json:"event_id"`
		Kind    string `json:"kind"`
		Text    string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "event_id and text are required")
		return
	}
	if req.Kind != "append" {
		writeError(w, http.StatusBadRequest, "kind must be append")
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

	if c.ReplayEventIDs != nil && c.ReplayEventIDs[req.EventID] {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "event_id already used in this campaign")
		return
	}

	c.ReplayEventSeq++
	entry := &playReplayEvent{
		Sequence: c.ReplayEventSeq,
		EventID:  req.EventID,
		Kind:     req.Kind,
		Text:     req.Text,
	}
	c.ReplayEvents = append(c.ReplayEvents, entry)
	if c.ReplayEventIDs == nil {
		c.ReplayEventIDs = make(map[string]bool)
	}
	c.ReplayEventIDs[req.EventID] = true
	resp := playReplayEventResponse(entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleReadPlayReplay(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	resp := playReplayState(c)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

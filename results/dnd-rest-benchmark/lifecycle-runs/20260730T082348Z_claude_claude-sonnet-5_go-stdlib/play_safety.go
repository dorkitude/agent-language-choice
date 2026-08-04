package main

import (
	"encoding/json"
	"net/http"
	"sort"
)

// playSafetyEvent is an immutable campaign-scoped accepted safety check
// event.
type playSafetyEvent struct {
	EventID  string
	Kind     string
	Text     string
	Tags     []string
	Sequence int
}

func playSafetyEventResponse(ev *playSafetyEvent) map[string]interface{} {
	return map[string]interface{}{
		"event_id": ev.EventID,
		"kind":     ev.Kind,
		"text":     ev.Text,
		"tags":     ev.Tags,
		"sequence": ev.Sequence,
	}
}

// playSortedTags returns a sorted copy of tags.
func playSortedTags(tags []string) []string {
	sorted := make([]string, len(tags))
	copy(sorted, tags)
	sort.Strings(sorted)
	return sorted
}

func playSafetyBoundariesResponse(c *playCampaign) map[string]interface{} {
	return map[string]interface{}{
		"blocked_tags": playSortedTags(c.SafetyBlockedTags),
	}
}

// playValidateUniqueNonemptyStrings reports whether tags is a nonempty array
// of unique nonempty strings.
func playValidateUniqueNonemptyStrings(tags []string, present bool) bool {
	if !present || len(tags) == 0 {
		return false
	}
	seen := make(map[string]bool, len(tags))
	for _, t := range tags {
		if t == "" || seen[t] {
			return false
		}
		seen[t] = true
	}
	return true
}

// handlePlayCampaignSafetySub routes the "safety-boundaries",
// "safety-checks", and "safety-events" sub-paths of a play campaign. It
// returns false if rest does not name a safety path, so the caller can fall
// through to its own routing.
func handlePlayCampaignSafetySub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	switch rest {
	case "safety-boundaries":
		switch r.Method {
		case http.MethodPut:
			handleReplacePlaySafetyBoundaries(w, r, campaignID)
		case http.MethodGet:
			handleReadPlaySafetyBoundaries(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	case "safety-checks":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleSubmitPlaySafetyCheck(w, r, campaignID)
		return true
	case "safety-events":
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleReadPlaySafetyEvents(w, r, campaignID)
		return true
	}
	return false
}

func handleReplacePlaySafetyBoundaries(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var raw struct {
		BlockedTags *[]string `json:"blocked_tags"`
	}
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	var blockedTags []string
	hasTags := raw.BlockedTags != nil
	if hasTags {
		blockedTags = *raw.BlockedTags
	}
	if !playValidateUniqueNonemptyStrings(blockedTags, hasTags) {
		writeError(w, http.StatusBadRequest, "blocked_tags must be a nonempty array of unique nonempty strings")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be the campaign dm")
		return
	}

	tags := make([]string, len(blockedTags))
	copy(tags, blockedTags)
	c.SafetyBlockedTags = tags
	resp := playSafetyBoundariesResponse(c)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

func handleReadPlaySafetyBoundaries(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	resp := playSafetyBoundariesResponse(c)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handleSubmitPlaySafetyCheck(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var raw struct {
		EventID *string   `json:"event_id"`
		Kind    *string   `json:"kind"`
		Text    *string   `json:"text"`
		Tags    *[]string `json:"tags"`
	}
	if err := json.NewDecoder(r.Body).Decode(&raw); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if raw.EventID == nil || *raw.EventID == "" {
		writeError(w, http.StatusBadRequest, "event_id is required")
		return
	}
	if raw.Text == nil || *raw.Text == "" {
		writeError(w, http.StatusBadRequest, "text is required")
		return
	}
	if raw.Kind == nil || (*raw.Kind != "narration" && *raw.Kind != "chat") {
		writeError(w, http.StatusBadRequest, "kind must be narration or chat")
		return
	}
	var tags []string
	hasTags := raw.Tags != nil
	if hasTags {
		tags = *raw.Tags
	}
	if !playValidateUniqueNonemptyStrings(tags, hasTags) {
		writeError(w, http.StatusBadRequest, "tags must be a nonempty array of unique nonempty strings")
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
	if c.SafetyEventIDs != nil && c.SafetyEventIDs[*raw.EventID] {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "event_id already accepted in this campaign")
		return
	}
	blocked := make(map[string]bool, len(c.SafetyBlockedTags))
	for _, t := range c.SafetyBlockedTags {
		blocked[t] = true
	}
	for _, t := range tags {
		if blocked[t] {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "tag is blocked by campaign safety boundaries")
			return
		}
	}

	c.SafetyEventSeq++
	entryTags := make([]string, len(tags))
	copy(entryTags, tags)
	entry := &playSafetyEvent{
		EventID:  *raw.EventID,
		Kind:     *raw.Kind,
		Text:     *raw.Text,
		Tags:     entryTags,
		Sequence: c.SafetyEventSeq,
	}
	c.SafetyEvents = append(c.SafetyEvents, entry)
	if c.SafetyEventIDs == nil {
		c.SafetyEventIDs = make(map[string]bool)
	}
	c.SafetyEventIDs[entry.EventID] = true
	resp := playSafetyEventResponse(entry)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleReadPlaySafetyEvents(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	events := make([]map[string]interface{}, 0, len(c.SafetyEvents))
	for _, ev := range c.SafetyEvents {
		events = append(events, playSafetyEventResponse(ev))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"events": events})
}

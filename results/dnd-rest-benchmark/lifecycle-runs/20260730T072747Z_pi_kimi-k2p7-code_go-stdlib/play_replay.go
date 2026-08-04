package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// appendReplayEventRequest binds the payload for appending a replay event.
type appendReplayEventRequest struct {
	EventID string `json:"event_id"`
	Kind    string `json:"kind"`
	Text    string `json:"text"`
}

// appendReplayEventResponse is the immutable event shape returned by a
// successful append. The field order matches the stage contract.
type appendReplayEventResponse struct {
	EventID  string `json:"event_id"`
	Kind     string `json:"kind"`
	Text     string `json:"text"`
	Sequence int    `json:"sequence"`
}

// replayResponse is the deterministic read model rebuilt from the ordered
// replay event log.
type replayResponse struct {
	Story    string   `json:"story"`
	EventIDs []string `json:"event_ids"`
	Digest   string   `json:"digest"`
}

// nextReplaySequence returns the next monotonic sequence number for a
// campaign's replay event log. The caller must hold dbMu.
func nextReplaySequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_replay_events WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

// queryReplayEvents loads all replay events for a campaign ordered by sequence.
// The caller must hold dbMu.
func queryReplayEvents(campaignID string) ([]struct {
	Sequence int    `json:"sequence"`
	EventID  string `json:"event_id"`
	Kind     string `json:"kind"`
	Text     string `json:"text"`
}, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT sequence, event_id, kind, text FROM campaign_replay_events WHERE campaign_id=%s ORDER BY sequence;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		Sequence int    `json:"sequence"`
		EventID  string `json:"event_id"`
		Kind     string `json:"kind"`
		Text     string `json:"text"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	if rows == nil {
		return []struct {
			Sequence int    `json:"sequence"`
			EventID  string `json:"event_id"`
			Kind     string `json:"kind"`
			Text     string `json:"text"`
		}{}, nil
	}
	return rows, nil
}

// buildReplayState deterministically rebuilds the campaign replay state from
// the ordered event log. The caller must hold dbMu.
func buildReplayState(campaignID string) (replayResponse, error) {
	events, err := queryReplayEvents(campaignID)
	if err != nil {
		return replayResponse{}, err
	}

	var story strings.Builder
	eventIDs := make([]string, 0, len(events))
	for _, ev := range events {
		if ev.Kind == "append" {
			story.WriteString(ev.Text)
			eventIDs = append(eventIDs, ev.EventID)
		}
	}

	resp := replayResponse{
		Story:    story.String(),
		EventIDs: eventIDs,
		Digest:   strings.Join(eventIDs, ",") + "|" + story.String(),
	}
	if resp.EventIDs == nil {
		resp.EventIDs = []string{}
	}
	return resp, nil
}

// appendReplayEventHandler lets the campaign DM or campaign members append a
// deterministic replay event. Duplicate event IDs per campaign return 409;
// invalid payloads return 400; unknown campaigns return 404; non-members
// return 403.
func appendReplayEventHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("replay event auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")
	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("replay event campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isMember := campaign.Owner == username
	if !isMember {
		isMember, err = isPlayCampaignMember(campaignID, username)
		if err != nil {
			log.Printf("replay event member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req appendReplayEventRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid replay event")
		return
	}
	if req.Kind != "append" {
		writeError(w, http.StatusBadRequest, "invalid replay event")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_replay_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;", sq(campaignID), sq(req.EventID)))
	if err != nil {
		log.Printf("replay event duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "event_id already exists")
		return
	}

	sequence, err := nextReplaySequence(campaignID)
	if err != nil {
		log.Printf("replay event sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (%s, %d, %s, %s, %s);",
		sq(campaignID), sequence, sq(req.EventID), sq(req.Kind), sq(req.Text))); err != nil {
		log.Printf("replay event insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, appendReplayEventResponse{
		EventID:  req.EventID,
		Kind:     req.Kind,
		Text:     req.Text,
		Sequence: sequence,
	})
}

// getReplayHandler returns the deterministic replay state for a campaign.
// The campaign DM and campaign members may read replay state.
func getReplayHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("replay read auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")
	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("replay read campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isReader := campaign.Owner == username
	if !isReader {
		isReader, err = isPlayCampaignMember(campaignID, username)
		if err != nil {
			log.Printf("replay read member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isReader {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	state, err := buildReplayState(campaignID)
	if err != nil {
		log.Printf("replay read build state error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, state)
}

// checkReplayHandler returns the same deterministic replay state as
// getReplayHandler via an explicit verification path. It does not mutate state.
func checkReplayHandler(w http.ResponseWriter, r *http.Request) {
	getReplayHandler(w, r)
}

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sort"
	"strings"
)

// replaceSafetyBoundariesRequest binds the PUT safety-boundaries payload.
type replaceSafetyBoundariesRequest struct {
	BlockedTags []string `json:"blocked_tags"`
}

// safetyBoundariesResponse is the exact current boundary state.
type safetyBoundariesResponse struct {
	BlockedTags []string `json:"blocked_tags"`
}

// submitSafetyCheckRequest binds the submit-safety-check payload.
type submitSafetyCheckRequest struct {
	EventID string   `json:"event_id"`
	Kind    string   `json:"kind"`
	Text    string   `json:"text"`
	Tags    []string `json:"tags"`
}

// safetyEvent is one accepted safety event.
type safetyEvent struct {
	EventID  string   `json:"event_id"`
	Kind     string   `json:"kind"`
	Text     string   `json:"text"`
	Tags     []string `json:"tags"`
	Sequence int      `json:"sequence"`
}

// safetyEventRow mirrors the durable row for an accepted safety event.
type safetyEventRow struct {
	EventID  string `json:"event_id"`
	Kind     string `json:"kind"`
	Text     string `json:"text"`
	Tags     string `json:"tags"`
	Sequence int    `json:"sequence"`
}

// safetyEventsResponse is the list returned by the read endpoint.
type safetyEventsResponse struct {
	Events []safetyEvent `json:"events"`
}

// validateNonemptyUniqueStrings checks that tags is non-empty (when required),
// contains only non-blank strings, and has no duplicates.
func validateNonemptyUniqueStrings(tags []string, required bool) bool {
	if required && len(tags) == 0 {
		return false
	}
	seen := make(map[string]struct{}, len(tags))
	for _, t := range tags {
		if strings.TrimSpace(t) == "" {
			return false
		}
		if _, ok := seen[t]; ok {
			return false
		}
		seen[t] = struct{}{}
	}
	return true
}

// replaceSafetyBoundariesHandler lets only the campaign DM replace the
// campaign's blocked tags. Invalid requests do not mutate state.
func replaceSafetyBoundariesHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req replaceSafetyBoundariesRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validateNonemptyUniqueStrings(req.BlockedTags, true) {
		writeError(w, http.StatusBadRequest, "invalid blocked_tags")
		return
	}

	sortedTags := make([]string, len(req.BlockedTags))
	copy(sortedTags, req.BlockedTags)
	sort.Strings(sortedTags)

	tagsJSON, err := json.Marshal(sortedTags)
	if err != nil {
		log.Printf("marshal blocked tags error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf(
		"INSERT INTO campaign_safety_boundaries (campaign_id, blocked_tags) VALUES (%s, %s) ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags=%s;",
		sq(campaignID), sq(string(tagsJSON)), sq(string(tagsJSON)))); err != nil {
		log.Printf("replace safety boundaries error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, safetyBoundariesResponse{BlockedTags: sortedTags})
}

// getSafetyBoundariesHandler lets any authenticated campaign member or the DM
// read the current blocked tags in lexicographic order.
func getSafetyBoundariesHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignMemberOrDM(w, r, campaignID); !ok {
		return
	}

	blockedTags, err := loadSafetyBoundaries(campaignID)
	if err != nil {
		log.Printf("load safety boundaries error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, safetyBoundariesResponse{BlockedTags: blockedTags})
}

// loadSafetyBoundaries returns the stored blocked tags for a campaign, or an
// empty slice if none have been set. The caller must hold dbMu.
func loadSafetyBoundaries(campaignID string) ([]string, error) {
	var rows []struct {
		BlockedTags string `json:"blocked_tags"`
	}
	if err := queryRows(fmt.Sprintf(
		"SELECT blocked_tags FROM campaign_safety_boundaries WHERE campaign_id=%s LIMIT 1;",
		sq(campaignID)), &rows); err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return []string{}, nil
	}
	var tags []string
	if err := json.Unmarshal([]byte(rows[0].BlockedTags), &tags); err != nil {
		return nil, err
	}
	return tags, nil
}

// submitSafetyCheckHandler lets any authenticated campaign member or the DM
// submit a safety check. Duplicate or blocked-tag checks return 409 without
// mutating state.
func submitSafetyCheckHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignMemberOrDM(w, r, campaignID); !ok {
		return
	}

	var req submitSafetyCheckRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.EventID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid safety check")
		return
	}
	if req.Kind != "narration" && req.Kind != "chat" {
		writeError(w, http.StatusBadRequest, "invalid kind")
		return
	}
	if !validateNonemptyUniqueStrings(req.Tags, true) {
		writeError(w, http.StatusBadRequest, "invalid tags")
		return
	}

	exists, err := queryExists(fmt.Sprintf(
		"SELECT 1 FROM campaign_safety_events WHERE campaign_id=%s AND event_id=%s LIMIT 1;",
		sq(campaignID), sq(req.EventID)))
	if err != nil {
		log.Printf("safety check duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "event already accepted")
		return
	}

	blockedTags, err := loadSafetyBoundaries(campaignID)
	if err != nil {
		log.Printf("load safety boundaries for check error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	blockedSet := make(map[string]struct{}, len(blockedTags))
	for _, tag := range blockedTags {
		blockedSet[tag] = struct{}{}
	}
	for _, tag := range req.Tags {
		if _, ok := blockedSet[tag]; ok {
			writeError(w, http.StatusConflict, "blocked tag")
			return
		}
	}

	nextSeq := 1
	out, err := dbQuery(fmt.Sprintf(
		"SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_safety_events WHERE campaign_id=%s;",
		sq(campaignID)))
	if err != nil {
		log.Printf("safety check sequence query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var seqRows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &seqRows); err != nil {
		log.Printf("safety check sequence unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(seqRows) > 0 {
		nextSeq = seqRows[0].NextSeq
	}

	tagsJSON, err := json.Marshal(req.Tags)
	if err != nil {
		log.Printf("marshal safety check tags error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf(
		"INSERT INTO campaign_safety_events (campaign_id, event_id, kind, text, tags, sequence) VALUES (%s, %s, %s, %s, %s, %d);",
		sq(campaignID), sq(req.EventID), sq(req.Kind), sq(req.Text), sq(string(tagsJSON)), nextSeq)); err != nil {
		log.Printf("safety check insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, safetyEvent{
		EventID:  req.EventID,
		Kind:     req.Kind,
		Text:     req.Text,
		Tags:     req.Tags,
		Sequence: nextSeq,
	})
}

// listSafetyEventsHandler lets any authenticated campaign member or the DM read
// accepted safety events in stable append order.
func listSafetyEventsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignMemberOrDM(w, r, campaignID); !ok {
		return
	}

	var rows []safetyEventRow
	if err := queryRows(fmt.Sprintf(
		"SELECT event_id, kind, text, tags, sequence FROM campaign_safety_events WHERE campaign_id=%s ORDER BY sequence;",
		sq(campaignID)), &rows); err != nil {
		log.Printf("safety events list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	events := make([]safetyEvent, 0, len(rows))
	for _, row := range rows {
		tags := []string{}
		if row.Tags != "" && row.Tags != "null" {
			if err := json.Unmarshal([]byte(row.Tags), &tags); err != nil {
				log.Printf("unmarshal safety event tags error: %v", err)
				writeError(w, http.StatusInternalServerError, "internal error")
				return
			}
		}
		events = append(events, safetyEvent{
			EventID:  row.EventID,
			Kind:     row.Kind,
			Text:     row.Text,
			Tags:     tags,
			Sequence: row.Sequence,
		})
	}

	writeJSON(w, http.StatusOK, safetyEventsResponse{Events: events})
}

package main

import (
	"encoding/json"
	"net/http"
	"strconv"
	"strings"
)

// playSearchRecord is a campaign-scoped, DM-authored search record used for
// text search across campaign notes. Records preserve creation order.
type playSearchRecord struct {
	RecordID string
	Text     string
}

func playSearchRecordResponse(rec *playSearchRecord) map[string]interface{} {
	return map[string]interface{}{
		"record_id": rec.RecordID,
		"text":      rec.Text,
	}
}

// handlePlayCampaignSearchRecordsSub routes the "search-records" sub-path of
// a play campaign. It returns false if rest does not name that path, so the
// caller can fall through to its own routing.
func handlePlayCampaignSearchRecordsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest != "search-records" {
		return false
	}
	switch r.Method {
	case http.MethodPost:
		handleCreatePlaySearchRecord(w, r, campaignID)
	case http.MethodGet:
		handleListPlaySearchRecords(w, r, campaignID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
	return true
}

// handleCreatePlaySearchRecord lets the campaign dm create a new search
// record.
func handleCreatePlaySearchRecord(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		RecordID string `json:"record_id"`
		Text     string `json:"text"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.RecordID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "record_id and text are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create search records")
		return
	}
	for _, rec := range c.SearchRecords {
		if rec.RecordID == req.RecordID {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "record_id already exists")
			return
		}
		if rec.Text == req.Text {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "text already exists")
			return
		}
	}

	rec := &playSearchRecord{
		RecordID: req.RecordID,
		Text:     req.Text,
	}
	c.SearchRecords = append(c.SearchRecords, rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playSearchRecordResponse(rec))
}

// handleListPlaySearchRecords returns campaign search records, optionally
// filtered by a case-insensitive substring match over text, paginated by
// cursor/limit.
func handleListPlaySearchRecords(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	query := r.URL.Query()

	limit := 2
	if v := query.Get("limit"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 1 || n > 3 {
			writeError(w, http.StatusBadRequest, "limit must be an integer from 1 through 3")
			return
		}
		limit = n
	}

	cursor := 0
	if v := query.Get("cursor"); v != "" {
		n, err := strconv.Atoi(v)
		if err != nil || n < 0 {
			writeError(w, http.StatusBadRequest, "cursor must be a nonnegative integer")
			return
		}
		cursor = n
	}

	q := query.Get("q")

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm or a member may view search records")
		return
	}

	filtered := make([]*playSearchRecord, 0, len(c.SearchRecords))
	for _, rec := range c.SearchRecords {
		if q != "" && !strings.Contains(strings.ToLower(rec.Text), strings.ToLower(q)) {
			continue
		}
		filtered = append(filtered, rec)
	}
	playMu.Unlock()

	records := make([]map[string]interface{}, 0, limit)
	var nextCursor interface{}
	if cursor < len(filtered) {
		end := cursor + limit
		if end > len(filtered) {
			end = len(filtered)
		}
		for _, rec := range filtered[cursor:end] {
			records = append(records, playSearchRecordResponse(rec))
		}
		if end < len(filtered) {
			nextCursor = end
		}
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"records":     records,
		"next_cursor": nextCursor,
	})
}

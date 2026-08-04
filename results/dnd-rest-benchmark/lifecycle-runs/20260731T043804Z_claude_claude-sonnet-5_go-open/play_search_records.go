package main

import (
	"net/http"
	"strconv"
	"strings"
	"sync"
)

// playSearchRecord is a campaign-scoped search record created by the dm.
type playSearchRecord struct {
	CampaignID string `json:"-"`
	RecordID   string `json:"record_id"`
	Text       string `json:"text"`
}

// campaignSearchRecordsMu guards campaignSearchRecords, the in-memory index
// mirroring the play_search_records table. Keyed by campaign id, holding
// records in insertion order.
var (
	campaignSearchRecordsMu sync.Mutex
	campaignSearchRecords   = map[string][]*playSearchRecord{}
)

func searchRecordJSON(rec *playSearchRecord) map[string]any {
	return map[string]any{
		"record_id": rec.RecordID,
		"text":      rec.Text,
	}
}

type createSearchRecordRequest struct {
	RecordID string `json:"record_id"`
	Text     string `json:"text"`
}

// createSearchRecordHandler lets the campaign's owning dm create a search
// record with a unique record_id within the campaign.
func createSearchRecordHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createSearchRecordRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create search records")
		return
	}

	if req.RecordID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "record_id and text are required nonempty strings")
		return
	}

	campaignSearchRecordsMu.Lock()
	defer campaignSearchRecordsMu.Unlock()

	for _, existing := range campaignSearchRecords[campaignID] {
		if existing.RecordID == req.RecordID {
			writeError(w, http.StatusBadRequest, "record_id already exists in this campaign")
			return
		}
		if existing.Text == req.Text {
			writeError(w, http.StatusBadRequest, "text already exists in this campaign")
			return
		}
	}

	rec := &playSearchRecord{
		CampaignID: campaignID,
		RecordID:   req.RecordID,
		Text:       req.Text,
	}
	if err := saveSearchRecordToDB(rec); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save search record")
		return
	}
	campaignSearchRecords[campaignID] = append(campaignSearchRecords[campaignID], rec)

	writeJSON(w, http.StatusCreated, searchRecordJSON(rec))
}

// listSearchRecordsHandler returns search records visible to the dm or any
// campaign member, filtered by an optional case-insensitive substring match
// over text, and paginated by cursor/limit.
func listSearchRecordsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	query := r.URL.Query()

	limit := 2
	if raw := query.Get("limit"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil || v < 1 || v > 3 {
			writeError(w, http.StatusBadRequest, "limit must be an integer from 1 through 3")
			return
		}
		limit = v
	}

	cursor := 0
	if raw := query.Get("cursor"); raw != "" {
		v, err := strconv.Atoi(raw)
		if err != nil || v < 0 {
			writeError(w, http.StatusBadRequest, "cursor must be a nonnegative integer")
			return
		}
		cursor = v
	}

	q := strings.ToLower(query.Get("q"))

	campaignSearchRecordsMu.Lock()
	defer campaignSearchRecordsMu.Unlock()

	filtered := make([]*playSearchRecord, 0, len(campaignSearchRecords[campaignID]))
	for _, rec := range campaignSearchRecords[campaignID] {
		if q == "" || strings.Contains(strings.ToLower(rec.Text), q) {
			filtered = append(filtered, rec)
		}
	}

	records := make([]map[string]any, 0, limit)
	var nextCursor any
	if cursor < len(filtered) {
		end := cursor + limit
		if end > len(filtered) {
			end = len(filtered)
		}
		for _, rec := range filtered[cursor:end] {
			records = append(records, searchRecordJSON(rec))
		}
		if end < len(filtered) {
			nextCursor = end
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"records":     records,
		"next_cursor": nextCursor,
	})
}

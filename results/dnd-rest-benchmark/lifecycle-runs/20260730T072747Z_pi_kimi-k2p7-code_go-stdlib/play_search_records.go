package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
)

// searchRecord is the exact shape returned for a single search record.
type searchRecord struct {
	RecordID string `json:"record_id"`
	Text     string `json:"text"`
}

// searchRecordListResponse is the shape returned when listing search records.
type searchRecordListResponse struct {
	Records    []searchRecord `json:"records"`
	NextCursor *int           `json:"next_cursor"`
}

// createSearchRecordRequest binds the payload for a new search record.
type createSearchRecordRequest struct {
	RecordID string `json:"record_id"`
	Text     string `json:"text"`
}

// createSearchRecordHandler lets the campaign DM create a search record.
// Only the campaign owner (DM) may create; authenticated non-DM actors receive
// 403. Unknown campaigns return 404, and invalid creation requests return 400
// without creating a record.
func createSearchRecordHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createSearchRecordRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.RecordID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid search record")
		return
	}

	dupRecordID, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_search_records WHERE campaign_id=%s AND record_id=%s LIMIT 1;", sq(campaignID), sq(req.RecordID)))
	if err != nil {
		log.Printf("search record duplicate record_id query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dupRecordID {
		writeError(w, http.StatusBadRequest, "duplicate record_id")
		return
	}

	dupText, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_search_records WHERE campaign_id=%s AND lower(text)=lower(%s) LIMIT 1;", sq(campaignID), sq(req.Text)))
	if err != nil {
		log.Printf("search record duplicate text query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dupText {
		writeError(w, http.StatusBadRequest, "duplicate text")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_search_records (campaign_id, record_id, text) VALUES (%s, %s, %s);",
		sq(campaignID), sq(req.RecordID), sq(req.Text))); err != nil {
		log.Printf("search record insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, searchRecord{
		RecordID: req.RecordID,
		Text:     req.Text,
	})
}

// listSearchRecordsHandler returns campaign search records visible to the
// caller. The campaign DM and members may list; other authenticated users
// receive 403. Query parameters support optional case-insensitive substring
// filtering (q), a limit of 1-3 (default 2), and a nonnegative cursor offset
// (default 0). The response preserves creation order.
func listSearchRecordsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("search records list auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("search records list campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != username {
		out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
		if err != nil {
			log.Printf("search records list member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		var memberRows []struct {
			One int `json:"1"`
		}
		if err := json.Unmarshal(out, &memberRows); err != nil {
			log.Printf("search records list member unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if len(memberRows) == 0 {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
	}

	q := strings.ToLower(r.URL.Query().Get("q"))
	limitStr := r.URL.Query().Get("limit")
	cursorStr := r.URL.Query().Get("cursor")

	limit := 2
	if limitStr != "" {
		parsed, err := strconv.Atoi(limitStr)
		if err != nil || parsed < 1 || parsed > 3 {
			writeError(w, http.StatusBadRequest, "invalid limit")
			return
		}
		limit = parsed
	}

	cursor := 0
	if cursorStr != "" {
		parsed, err := strconv.Atoi(cursorStr)
		if err != nil || parsed < 0 {
			writeError(w, http.StatusBadRequest, "invalid cursor")
			return
		}
		cursor = parsed
	}

	var rows []searchRecord
	if err := queryRows(fmt.Sprintf("SELECT record_id, text FROM campaign_search_records WHERE campaign_id=%s ORDER BY id;", sq(campaignID)), &rows); err != nil {
		log.Printf("search records list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	filtered := rows
	if q != "" {
		filtered = make([]searchRecord, 0, len(rows))
		for _, row := range rows {
			if strings.Contains(strings.ToLower(row.Text), q) {
				filtered = append(filtered, row)
			}
		}
	}

	if cursor > len(filtered) {
		cursor = len(filtered)
	}
	end := cursor + limit
	if end > len(filtered) {
		end = len(filtered)
	}

	page := filtered[cursor:end]
	if page == nil {
		page = []searchRecord{}
	}

	var nextCursor *int
	if end < len(filtered) {
		nc := end
		nextCursor = &nc
	}

	writeJSON(w, http.StatusOK, searchRecordListResponse{
		Records:    page,
		NextCursor: nextCursor,
	})
}

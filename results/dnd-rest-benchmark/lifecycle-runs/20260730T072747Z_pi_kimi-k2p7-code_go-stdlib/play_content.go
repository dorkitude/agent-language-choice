package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// contentRecord is the response shape for a campaign content entry.
type contentRecord struct {
	ContentID string   `json:"content_id"`
	Kind      string   `json:"kind"`
	Text      string   `json:"text"`
	Tags      []string `json:"tags"`
}

// createContentRequest binds the payload for creating a content record.
type createContentRequest struct {
	ContentID string   `json:"content_id"`
	Kind      string   `json:"kind"`
	Text      string   `json:"text"`
	Tags      []string `json:"tags"`
}

// updateContentTagsRequest binds the payload for replacing a content record's tags.
type updateContentTagsRequest struct {
	Tags []string `json:"tags"`
}

// contentListResponse is the shape returned by the content list endpoint.
type contentListResponse struct {
	Content []contentRecord `json:"content"`
}

// validateContentTags ensures the supplied tags are a nonempty array of unique
// nonempty strings. It is used for creation, where tags are mandatory.
func validateContentTags(tags []string) bool {
	if len(tags) == 0 {
		return false
	}
	seen := make(map[string]bool, len(tags))
	for _, t := range tags {
		if t == "" {
			return false
		}
		if seen[t] {
			return false
		}
		seen[t] = true
	}
	return true
}

// validateContentUpdateTags ensures the supplied tags, when present, are unique
// nonempty strings. An empty list is explicitly allowed for tag replacement.
func validateContentUpdateTags(tags []string) bool {
	seen := make(map[string]bool, len(tags))
	for _, t := range tags {
		if t == "" {
			return false
		}
		if seen[t] {
			return false
		}
		seen[t] = true
	}
	return true
}

// normalizeContentTags returns a non-nil slice, preserving the exact order of
// the input. This guarantees that empty tag lists serialize as [] rather than null.
func normalizeContentTags(tags []string) []string {
	if tags == nil {
		return []string{}
	}
	return tags
}

// createContentHandler lets the campaign DM create a content record for a
// campaign. Players receive 403, unauthenticated requests receive 401, and
// unknown campaigns return 404. Duplicate content IDs within the campaign
// return 409.
func createContentHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createContentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ContentID == "" || req.Kind == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid content")
		return
	}
	if !validateContentTags(req.Tags) {
		writeError(w, http.StatusBadRequest, "invalid tags")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_content WHERE campaign_id=%s AND content_id=%s LIMIT 1;", sq(campaignID), sq(req.ContentID)))
	if err != nil {
		log.Printf("content duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "content already exists")
		return
	}

	tagsJSON, err := json.Marshal(req.Tags)
	if err != nil {
		log.Printf("content tags marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_content (campaign_id, content_id, kind, text, tags, sort_order) VALUES (%s, %s, %s, %s, %s, COALESCE((SELECT MAX(sort_order) FROM campaign_content WHERE campaign_id=%s), 0) + 1);",
		sq(campaignID), sq(req.ContentID), sq(req.Kind), sq(req.Text), sq(string(tagsJSON)), sq(campaignID))); err != nil {
		log.Printf("content insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, contentRecord{
		ContentID: req.ContentID,
		Kind:      req.Kind,
		Text:      req.Text,
		Tags:      normalizeContentTags(req.Tags),
	})
}

// updateContentTagsHandler lets the campaign DM replace a content record's tags.
// Players receive 403, unauthenticated requests receive 401, and unknown
// campaigns or content IDs return 404. The replacement tag list may be empty.
func updateContentTagsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	contentID := r.PathValue("content_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	existing, err := queryContentRecord(campaignID, contentID)
	if err != nil {
		log.Printf("content tags record query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if existing == nil {
		writeError(w, http.StatusNotFound, "content not found")
		return
	}

	var req updateContentTagsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validateContentUpdateTags(req.Tags) {
		writeError(w, http.StatusBadRequest, "invalid tags")
		return
	}

	tagsJSON, err := json.Marshal(req.Tags)
	if err != nil {
		log.Printf("content tags update marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_content SET tags=%s WHERE campaign_id=%s AND content_id=%s;",
		sq(string(tagsJSON)), sq(campaignID), sq(contentID))); err != nil {
		log.Printf("content tags update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, contentRecord{
		ContentID: existing.ContentID,
		Kind:      existing.Kind,
		Text:      existing.Text,
		Tags:      normalizeContentTags(req.Tags),
	})
}

// listContentHandler returns campaign content records in creation order. The DM
// always sees every record. Players see all records unless an exclude_tag query
// parameter is provided, in which case records containing that tag are omitted.
func listContentHandler(w http.ResponseWriter, r *http.Request) {
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
		log.Printf("content list auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("content list campaign query error: %v", err)
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
			log.Printf("content list member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		var memberRows []struct {
			One int `json:"1"`
		}
		if err := json.Unmarshal(out, &memberRows); err != nil {
			log.Printf("content list member unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if len(memberRows) == 0 {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
	}

	excludeTag := r.URL.Query().Get("exclude_tag")
	hasExcludeTag := r.URL.Query().Has("exclude_tag")
	if hasExcludeTag && excludeTag == "" {
		writeError(w, http.StatusBadRequest, "invalid exclude_tag")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT content_id, kind, text, tags FROM campaign_content WHERE campaign_id=%s ORDER BY sort_order;", sq(campaignID)))
	if err != nil {
		log.Printf("content list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		ContentID string `json:"content_id"`
		Kind      string `json:"kind"`
		Text      string `json:"text"`
		Tags      string `json:"tags"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("content list unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	isDM := campaign.Owner == username
	records := make([]contentRecord, 0, len(rows))
	for _, row := range rows {
		var tags []string
		if err := json.Unmarshal([]byte(row.Tags), &tags); err != nil {
			log.Printf("content tags unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !isDM && hasExcludeTag {
			if tagSliceContains(tags, excludeTag) {
				continue
			}
		}
		records = append(records, contentRecord{
			ContentID: row.ContentID,
			Kind:      row.Kind,
			Text:      row.Text,
			Tags:      normalizeContentTags(tags),
		})
	}
	if records == nil {
		records = []contentRecord{}
	}

	writeJSON(w, http.StatusOK, contentListResponse{Content: records})
}

// queryContentRecord loads a single campaign content record by campaign and
// content id. The caller must hold dbMu. It returns nil if the record does not exist.
func queryContentRecord(campaignID, contentID string) (*contentRecord, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT content_id, kind, text, tags FROM campaign_content WHERE campaign_id=%s AND content_id=%s LIMIT 1;", sq(campaignID), sq(contentID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		ContentID string `json:"content_id"`
		Kind      string `json:"kind"`
		Text      string `json:"text"`
		Tags      string `json:"tags"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, nil
	}
	var tags []string
	if err := json.Unmarshal([]byte(rows[0].Tags), &tags); err != nil {
		return nil, err
	}
	return &contentRecord{
		ContentID: rows[0].ContentID,
		Kind:      rows[0].Kind,
		Text:      rows[0].Text,
		Tags:      normalizeContentTags(tags),
	}, nil
}

// tagSliceContains reports whether tag appears in tags.
func tagSliceContains(tags []string, tag string) bool {
	for _, t := range tags {
		if t == tag {
			return true
		}
	}
	return false
}

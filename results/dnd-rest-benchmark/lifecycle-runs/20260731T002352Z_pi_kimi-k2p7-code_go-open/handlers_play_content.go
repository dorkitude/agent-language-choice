package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayContentHandler creates a campaign content record. Only the
// campaign owner (DM) may create content. Players receive 403, unauthenticated
// requests receive 401, and unknown campaigns return 404. Duplicate content_id
// values within the campaign return 409. Invalid payloads return 400.
func createPlayContentHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create content")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create content")
		return
	}

	var req content
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ContentID) == "" {
		badRequest(w, "content_id is required")
		return
	}
	if strings.TrimSpace(req.Kind) == "" {
		badRequest(w, "kind is required")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}
	if len(req.Tags) == 0 {
		badRequest(w, "tags must be a non-empty array")
		return
	}
	seen := make(map[string]bool, len(req.Tags))
	for _, tag := range req.Tags {
		if strings.TrimSpace(tag) == "" {
			badRequest(w, "tags must be non-empty strings")
			return
		}
		if seen[tag] {
			badRequest(w, "tags must be unique")
			return
		}
		seen[tag] = true
	}

	if err := dbCreatePlayContent(id, &req); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "content already exists")
			return
		}
		log.Printf("create play content: %v", err)
		badRequest(w, "failed to create content")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

// updatePlayContentTagsHandler replaces the tags of a content record. Only the
// campaign owner (DM) may update tags. Players receive 403, unauthenticated
// requests receive 401, and unknown campaigns or content IDs return 404.
// Invalid payloads return 400. The replacement tag list may be empty.
func updatePlayContentTagsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can update content tags")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can update content tags")
		return
	}

	contentID := r.PathValue("content_id")
	if strings.TrimSpace(contentID) == "" {
		notFound(w, "content not found")
		return
	}
	existing, err := dbGetPlayContent(id, contentID)
	if err != nil {
		log.Printf("get play content: %v", err)
		badRequest(w, "failed to read content")
		return
	}
	if existing == nil {
		notFound(w, "content not found")
		return
	}

	var req contentUpdateTagsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Tags == nil {
		badRequest(w, "tags is required")
		return
	}
	seen := make(map[string]bool, len(req.Tags))
	for _, tag := range req.Tags {
		if strings.TrimSpace(tag) == "" {
			badRequest(w, "tags must be non-empty strings")
			return
		}
		if seen[tag] {
			badRequest(w, "tags must be unique")
			return
		}
		seen[tag] = true
	}

	if err := dbUpdatePlayContentTags(id, contentID, req.Tags); err != nil {
		log.Printf("update play content tags: %v", err)
		badRequest(w, "failed to update content tags")
		return
	}

	updated := &content{
		ContentID: existing.ContentID,
		Kind:      existing.Kind,
		Text:      existing.Text,
		Tags:      req.Tags,
	}
	writeJSON(w, http.StatusOK, updated)
}

// listPlayContentHandler lists campaign content records. Authenticated campaign
// members may list content. Unknown campaigns return 404. The optional
// exclude_tag query parameter excludes matching tagged content from player
// responses; the DM always receives all content records.
func listPlayContentHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	q := r.URL.Query()
	excludeTag := q.Get("exclude_tag")
	if q.Has("exclude_tag") && strings.TrimSpace(excludeTag) == "" {
		badRequest(w, "exclude_tag must be a non-empty string")
		return
	}

	contents, err := dbListPlayContent(id)
	if err != nil {
		log.Printf("list play content: %v", err)
		badRequest(w, "failed to read content")
		return
	}

	resp := struct {
		Content []content `json:"content"`
	}{Content: contents}

	if p.Owner == u.Username || !q.Has("exclude_tag") {
		writeJSON(w, http.StatusOK, resp)
		return
	}

	filtered := make([]content, 0, len(contents))
	for _, c := range contents {
		if !containsTag(c.Tags, excludeTag) {
			filtered = append(filtered, c)
		}
	}
	resp.Content = filtered
	writeJSON(w, http.StatusOK, resp)
}

// containsTag reports whether the tag list contains the given tag exactly.
func containsTag(tags []string, tag string) bool {
	for _, t := range tags {
		if t == tag {
			return true
		}
	}
	return false
}

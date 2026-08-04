package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playContent is a DM-authored campaign content record with deterministic
// tags used for role-appropriate filtering.
type playContent struct {
	ContentID string
	Kind      string
	Text      string
	Tags      []string
}

func playContentResponse(rec *playContent) map[string]interface{} {
	return map[string]interface{}{
		"content_id": rec.ContentID,
		"kind":       rec.Kind,
		"text":       rec.Text,
		"tags":       rec.Tags,
	}
}

// handlePlayCampaignContentSub routes the "content" and "content/..."
// sub-paths of a play campaign. It returns false if rest does not name a
// recognized content path, so the caller can fall through to its own routing.
func handlePlayCampaignContentSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "content" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayContent(w, r, campaignID)
		case http.MethodGet:
			handleListPlayContent(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if !strings.HasPrefix(rest, "content/") {
		return false
	}
	contentRest := strings.TrimPrefix(rest, "content/")
	if contentID, ok := strings.CutSuffix(contentRest, "/tags"); ok && contentID != "" {
		if r.Method != http.MethodPut {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleUpdatePlayContentTags(w, r, campaignID, contentID)
		return true
	}
	return false
}

func uniqueNonemptyStrings(items []string) bool {
	seen := map[string]bool{}
	for _, item := range items {
		if item == "" || seen[item] {
			return false
		}
		seen[item] = true
	}
	return true
}

type playContentRequest struct {
	ContentID string   `json:"content_id"`
	Kind      string   `json:"kind"`
	Text      string   `json:"text"`
	Tags      []string `json:"tags"`
}

// handleCreatePlayContent lets the campaign dm create a new content record.
// Only the dm may call this; unknown campaigns return 404, invalid payloads
// return 400, and duplicate content ids within the campaign return 409.
func handleCreatePlayContent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playContentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ContentID == "" || req.Kind == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "content_id, kind, and text are required")
		return
	}
	if len(req.Tags) == 0 || !uniqueNonemptyStrings(req.Tags) {
		writeError(w, http.StatusBadRequest, "tags must be a nonempty array of unique nonempty strings")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create content")
		return
	}
	if c.Content == nil {
		c.Content = make(map[string]*playContent)
	}
	if _, exists := c.Content[req.ContentID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "content_id already exists")
		return
	}

	rec := &playContent{
		ContentID: req.ContentID,
		Kind:      req.Kind,
		Text:      req.Text,
		Tags:      append([]string{}, req.Tags...),
	}
	c.Content[req.ContentID] = rec
	c.ContentOrder = append(c.ContentOrder, req.ContentID)
	resp := playContentResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayContent returns campaign content in creation order.
// Authenticated campaign members (owner or player) may list content. The
// campaign dm always sees every record; players may exclude records tagged
// with the optional exclude_tag query parameter.
func handleListPlayContent(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	excludeTag := ""
	if r.URL.Query().Has("exclude_tag") {
		excludeTag = r.URL.Query().Get("exclude_tag")
		if excludeTag == "" {
			writeError(w, http.StatusBadRequest, "exclude_tag must be a nonempty string")
			return
		}
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view content")
		return
	}

	isDM := c.Owner == username
	content := make([]map[string]interface{}, 0, len(c.ContentOrder))
	for _, contentID := range c.ContentOrder {
		rec := c.Content[contentID]
		if !isDM && excludeTag != "" && containsString(rec.Tags, excludeTag) {
			continue
		}
		content = append(content, playContentResponse(rec))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"content": content})
}

func containsString(items []string, target string) bool {
	for _, item := range items {
		if item == target {
			return true
		}
	}
	return false
}

type playContentTagsRequest struct {
	Tags []string `json:"tags"`
}

// handleUpdatePlayContentTags lets the campaign dm replace a content
// record's tags. Only the dm may call this; unknown campaigns or content ids
// return 404, and invalid payloads return 400.
func handleUpdatePlayContentTags(w http.ResponseWriter, r *http.Request, campaignID, contentID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playContentTagsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Tags == nil {
		writeError(w, http.StatusBadRequest, "tags is required")
		return
	}
	if !uniqueNonemptyStrings(req.Tags) {
		writeError(w, http.StatusBadRequest, "tags must contain unique nonempty strings")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may replace content tags")
		return
	}
	rec := c.Content[contentID]
	if rec == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "content not found")
		return
	}

	rec.Tags = append([]string{}, req.Tags...)
	resp := playContentResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

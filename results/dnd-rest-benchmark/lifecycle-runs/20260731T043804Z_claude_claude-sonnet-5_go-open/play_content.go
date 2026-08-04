package main

import (
	"net/http"
	"sync"
)

// playContent is a campaign content record (scene text, handouts, etc) with
// deterministic tags used for role-based filtering.
type playContent struct {
	CampaignID string
	ContentID  string
	Kind       string
	Text       string
	Tags       []string
}

// campaignContentMu guards campaignContent, the in-memory index mirroring the
// play_content table. Keyed by campaign id, holding content in insertion order.
var (
	campaignContentMu sync.Mutex
	campaignContent   = map[string][]*playContent{}
)

func contentJSON(c *playContent) map[string]any {
	return map[string]any{
		"content_id": c.ContentID,
		"kind":       c.Kind,
		"text":       c.Text,
		"tags":       c.Tags,
	}
}

func uniqueNonEmptyStrings(tags []string) bool {
	seen := make(map[string]bool, len(tags))
	for _, t := range tags {
		if t == "" || seen[t] {
			return false
		}
		seen[t] = true
	}
	return true
}

type createContentRequest struct {
	ContentID string   `json:"content_id"`
	Kind      string   `json:"kind"`
	Text      string   `json:"text"`
	Tags      []string `json:"tags"`
}

// createContentHandler lets the campaign's owning dm create a content record
// with deterministic, unique tags.
func createContentHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createContentRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create content")
		return
	}

	if req.ContentID == "" || req.Kind == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "content_id, kind, and text are required nonempty strings")
		return
	}
	if len(req.Tags) == 0 || !uniqueNonEmptyStrings(req.Tags) {
		writeError(w, http.StatusBadRequest, "tags must be a nonempty array of unique nonempty strings")
		return
	}

	campaignContentMu.Lock()
	defer campaignContentMu.Unlock()

	for _, existing := range campaignContent[campaignID] {
		if existing.ContentID == req.ContentID {
			writeError(w, http.StatusConflict, "content_id already exists in this campaign")
			return
		}
	}

	content := &playContent{
		CampaignID: campaignID,
		ContentID:  req.ContentID,
		Kind:       req.Kind,
		Text:       req.Text,
		Tags:       req.Tags,
	}
	if err := saveContentToDB(content); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save content")
		return
	}
	campaignContent[campaignID] = append(campaignContent[campaignID], content)

	writeJSON(w, http.StatusCreated, contentJSON(content))
}

type updateContentTagsRequest struct {
	Tags []string `json:"tags"`
}

// updateContentTagsHandler lets the campaign's owning dm replace a content
// record's tags outright.
func updateContentTagsHandler(w http.ResponseWriter, r *http.Request, campaignID, contentID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req updateContentTagsRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may replace content tags")
		return
	}

	if !uniqueNonEmptyStrings(req.Tags) {
		writeError(w, http.StatusBadRequest, "tags must be unique nonempty strings")
		return
	}

	campaignContentMu.Lock()
	defer campaignContentMu.Unlock()

	var content *playContent
	for _, existing := range campaignContent[campaignID] {
		if existing.ContentID == contentID {
			content = existing
			break
		}
	}
	if content == nil {
		writeError(w, http.StatusNotFound, "content not found")
		return
	}

	content.Tags = req.Tags
	if err := saveContentToDB(content); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save content")
		return
	}

	writeJSON(w, http.StatusOK, contentJSON(content))
}

// listContentHandler returns campaign content. The dm always receives every
// record. Players receive every record except those tagged with exclude_tag.
func listContentHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	excludeTag := ""
	if raw, present := r.URL.Query()["exclude_tag"]; present {
		if len(raw) != 1 || raw[0] == "" {
			writeError(w, http.StatusBadRequest, "exclude_tag must be a nonempty string")
			return
		}
		excludeTag = raw[0]
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

	campaignContentMu.Lock()
	defer campaignContentMu.Unlock()

	records := make([]map[string]any, 0, len(campaignContent[campaignID]))
	for _, content := range campaignContent[campaignID] {
		if !isDM && excludeTag != "" && hasTag(content.Tags, excludeTag) {
			continue
		}
		records = append(records, contentJSON(content))
	}

	writeJSON(w, http.StatusOK, map[string]any{"content": records})
}

func hasTag(tags []string, tag string) bool {
	for _, t := range tags {
		if t == tag {
			return true
		}
	}
	return false
}

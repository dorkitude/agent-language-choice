package main

import (
	"net/http"
	"strings"
)

type campaignQuest struct {
	ID         string          `json:"id"`
	Title      string          `json:"title"`
	Status     string          `json:"status"`
	Milestones []string        `json:"milestones"`
	Done       map[string]bool `json:"-"`
}

func questDoneCount(q *campaignQuest) int {
	count := 0
	for _, m := range q.Milestones {
		if q.Done[m] {
			count++
		}
	}
	return count
}

func questCreateResponse(q *campaignQuest) map[string]any {
	return map[string]any{
		"id":               q.ID,
		"title":            q.Title,
		"status":           q.Status,
		"milestones_total": len(q.Milestones),
		"milestones_done":  questDoneCount(q),
	}
}

func questProgressResponse(q *campaignQuest) map[string]any {
	return map[string]any{
		"id":               q.ID,
		"status":           q.Status,
		"milestones_total": len(q.Milestones),
		"milestones_done":  questDoneCount(q),
	}
}

type createQuestRequest struct {
	ID         string   `json:"id"`
	Title      string   `json:"title"`
	Status     string   `json:"status"`
	Milestones []string `json:"milestones"`
}

func createQuestHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createQuestRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Title == "" {
		writeError(w, http.StatusBadRequest, "title is required")
		return
	}
	status := req.Status
	if status == "" {
		status = "active"
	}
	milestones := req.Milestones
	if milestones == nil {
		milestones = []string{}
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	for _, q := range c.Quests {
		if q.ID == req.ID {
			writeError(w, http.StatusConflict, "quest id already exists")
			return
		}
	}

	q := &campaignQuest{ID: req.ID, Title: req.Title, Status: status, Milestones: milestones, Done: map[string]bool{}}
	if err := saveCampaignQuestToDB(c.ID, q); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save quest")
		return
	}
	c.Quests = append(c.Quests, q)

	writeJSON(w, http.StatusCreated, questCreateResponse(q))
}

type questProgressRequest struct {
	Completed []string `json:"completed"`
}

func questProgressHandler(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req questProgressRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	var q *campaignQuest
	for _, existing := range c.Quests {
		if existing.ID == questID {
			q = existing
			break
		}
	}
	if q == nil {
		writeError(w, http.StatusNotFound, "unknown quest id")
		return
	}

	for _, name := range req.Completed {
		found := false
		for _, m := range q.Milestones {
			if m == name {
				found = true
				break
			}
		}
		if !found {
			writeError(w, http.StatusBadRequest, "completed milestone not found on quest")
			return
		}
	}

	for _, name := range req.Completed {
		q.Done[name] = true
	}
	if len(q.Milestones) > 0 && questDoneCount(q) == len(q.Milestones) {
		q.Status = "completed"
	}

	if err := saveCampaignQuestToDB(c.ID, q); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save quest")
		return
	}

	writeJSON(w, http.StatusOK, questProgressResponse(q))
}

func questSummaryHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	counts := map[string]int{"active": 0, "completed": 0, "blocked": 0}
	for _, q := range c.Quests {
		counts[q.Status]++
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id": c.ID,
		"active":      counts["active"],
		"completed":   counts["completed"],
		"blocked":     counts["blocked"],
	})
}

// campaignQuestsRouter dispatches /v1/campaigns/{id}/quests... routes. rest
// is the path segment after "/v1/campaigns/{id}/". Returns true if it
// handled the request.
func campaignQuestsRouter(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "quests" {
		createQuestHandler(w, r, campaignID)
		return true
	}
	if rest == "quests/summary" {
		questSummaryHandler(w, r, campaignID)
		return true
	}
	if strings.HasPrefix(rest, "quests/") && strings.HasSuffix(rest, "/progress") {
		questID := strings.TrimSuffix(strings.TrimPrefix(rest, "quests/"), "/progress")
		if questID == "" {
			return false
		}
		questProgressHandler(w, r, campaignID, questID)
		return true
	}
	return false
}

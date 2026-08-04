package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

type quest struct {
	ID         string          `json:"id"`
	Title      string          `json:"title"`
	Status     string          `json:"status"`
	Milestones []string        `json:"milestones"`
	Done       map[string]bool `json:"done"`
}

func questDoneCount(q *quest) int {
	count := 0
	for _, m := range q.Milestones {
		if q.Done[m] {
			count++
		}
	}
	return count
}

func questResponse(q *quest) map[string]interface{} {
	return map[string]interface{}{
		"id":               q.ID,
		"title":            q.Title,
		"status":           q.Status,
		"milestones_total": len(q.Milestones),
		"milestones_done":  questDoneCount(q),
	}
}

func questProgressResponse(q *quest) map[string]interface{} {
	return map[string]interface{}{
		"id":               q.ID,
		"status":           q.Status,
		"milestones_total": len(q.Milestones),
		"milestones_done":  questDoneCount(q),
	}
}

func handleCreateQuest(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ID         string   `json:"id"`
		Title      string   `json:"title"`
		Status     string   `json:"status"`
		Milestones []string `json:"milestones"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Title == "" {
		writeError(w, http.StatusBadRequest, "id and title are required")
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

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, q := range c.Quests {
		if q.ID == req.ID {
			campaignMu.Unlock()
			writeError(w, http.StatusConflict, "quest id already exists")
			return
		}
	}
	q := &quest{
		ID:         req.ID,
		Title:      req.Title,
		Status:     status,
		Milestones: milestones,
		Done:       map[string]bool{},
	}
	c.Quests = append(c.Quests, q)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, questResponse(q))
}

func handleQuestProgress(w http.ResponseWriter, r *http.Request, campaignID, questID string) {
	var req struct {
		Completed []string `json:"completed"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	var q *quest
	for _, existing := range c.Quests {
		if existing.ID == questID {
			q = existing
			break
		}
	}
	if q == nil {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "quest not found")
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
			campaignMu.Unlock()
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
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, questProgressResponse(q))
}

func handleQuestSummary(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	counts := map[string]int{"active": 0, "completed": 0, "blocked": 0}
	for _, q := range c.Quests {
		counts[q.Status]++
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id": campaignID,
		"active":      counts["active"],
		"completed":   counts["completed"],
		"blocked":     counts["blocked"],
	})
}

func handleCampaignQuestsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "quests" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreateQuest(w, r, campaignID)
		return true
	}
	if rest == "quests/summary" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleQuestSummary(w, r, campaignID)
		return true
	}
	if strings.HasPrefix(rest, "quests/") && strings.HasSuffix(rest, "/progress") {
		questID := strings.TrimSuffix(strings.TrimPrefix(rest, "quests/"), "/progress")
		if questID == "" {
			return false
		}
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleQuestProgress(w, r, campaignID, questID)
		return true
	}
	return false
}

package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func createQuestHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req questCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Title) == "" {
		badRequest(w, "title is required")
		return
	}
	req.Status = strings.TrimSpace(req.Status)
	if req.Status == "" {
		badRequest(w, "status is required")
		return
	}
	if req.Status != questStatusActive && req.Status != questStatusCompleted && req.Status != questStatusBlocked {
		badRequest(w, "status must be active, completed, or blocked")
		return
	}

	if err := dbCreateQuest(campaignID, &req); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "quest id already exists")
			return
		}
		log.Printf("create quest: %v", err)
		badRequest(w, "failed to create quest")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":               req.ID,
		"title":            req.Title,
		"status":           req.Status,
		"milestones_total": len(req.Milestones),
		"milestones_done":  0,
	})
}

func updateQuestProgressHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	questID := r.PathValue("quest_id")
	if campaignID == "" || questID == "" {
		notFound(w, "campaign not found")
		return
	}
	if requireCampaign(w, campaignID) == nil {
		return
	}

	q, err := dbGetQuest(questID)
	if err != nil {
		log.Printf("get quest: %v", err)
		notFound(w, "quest not found")
		return
	}
	if q == nil || q.CampaignID != campaignID {
		notFound(w, "quest not found")
		return
	}

	var req struct {
		Completed []string `json:"completed"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if err := dbUpdateQuestProgress(questID, req.Completed); err != nil {
		log.Printf("update quest progress: %v", err)
		badRequest(w, "failed to update quest progress")
		return
	}

	q, err = dbGetQuest(questID)
	if err != nil {
		log.Printf("get quest after update: %v", err)
		badRequest(w, "failed to read quest")
		return
	}
	if q == nil {
		notFound(w, "quest not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":               q.ID,
		"status":           q.Status,
		"milestones_total": q.Total,
		"milestones_done":  q.Done,
	})
}

func getQuestSummaryHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	counts, err := dbCountQuestsByStatus(campaignID)
	if err != nil {
		log.Printf("count quests: %v", err)
		badRequest(w, "failed to read quest summary")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":        campaignID,
		questStatusActive:    counts[questStatusActive],
		questStatusCompleted: counts[questStatusCompleted],
		questStatusBlocked:   counts[questStatusBlocked],
	})
}

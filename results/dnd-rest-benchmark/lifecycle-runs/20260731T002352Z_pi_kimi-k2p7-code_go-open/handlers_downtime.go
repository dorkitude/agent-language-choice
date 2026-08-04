package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func createCraftingProjectHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req craftingProject
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.CharacterID) == "" {
		badRequest(w, "character_id is required")
		return
	}
	if strings.TrimSpace(req.ItemSlug) == "" {
		badRequest(w, "item_slug is required")
		return
	}
	if req.DaysRequired <= 0 {
		badRequest(w, "days_required must be a positive integer")
		return
	}
	if req.CostGP < 0 {
		badRequest(w, "cost_gp must be a non-negative integer")
		return
	}

	char, err := dbGetCharacter(req.CharacterID, campaignID)
	if err != nil {
		log.Printf("get character: %v", err)
		notFound(w, "character not found")
		return
	}
	if char == nil {
		notFound(w, "character not found")
		return
	}

	item, err := dbGetItem(req.ItemSlug)
	if err != nil {
		log.Printf("get item: %v", err)
		notFound(w, "item not found")
		return
	}
	if item == nil {
		notFound(w, "item not found")
		return
	}

	p := &craftingProject{
		ID:            req.ID,
		CampaignID:    campaignID,
		CharacterID:   req.CharacterID,
		ItemSlug:      req.ItemSlug,
		DaysRequired:  req.DaysRequired,
		DaysCompleted: 0,
		CostGP:        req.CostGP,
		Status:        craftingStatusActive,
	}

	if err := dbCreateCraftingProject(p); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "project id already exists")
			return
		}
		if isForeignKeyViolation(err) {
			notFound(w, "character or item not found")
			return
		}
		log.Printf("create crafting project: %v", err)
		badRequest(w, "failed to create crafting project")
		return
	}

	writeJSON(w, http.StatusCreated, craftingProjectResponse{
		ID:            p.ID,
		CharacterID:   p.CharacterID,
		ItemSlug:      p.ItemSlug,
		DaysRequired:  p.DaysRequired,
		DaysCompleted: p.DaysCompleted,
		Status:        p.Status,
	})
}

func advanceCraftingProjectHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	projectID := r.PathValue("project_id")
	if campaignID == "" || projectID == "" {
		notFound(w, "campaign or project not found")
		return
	}
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req struct {
		Days int `json:"days"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Days <= 0 {
		badRequest(w, "days must be a positive integer")
		return
	}

	p, err := dbGetCraftingProject(projectID)
	if err != nil {
		log.Printf("get crafting project: %v", err)
		notFound(w, "project not found")
		return
	}
	if p == nil || p.CampaignID != campaignID {
		notFound(w, "project not found")
		return
	}

	if p.Status != craftingStatusActive {
		badRequest(w, "project is not active")
		return
	}

	p, err = dbAdvanceCraftingProject(projectID, req.Days)
	if err != nil {
		log.Printf("advance crafting project: %v", err)
		badRequest(w, "failed to advance crafting project")
		return
	}
	if p == nil {
		notFound(w, "project not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":             p.ID,
		"days_completed": p.DaysCompleted,
		"status":         p.Status,
	})
}

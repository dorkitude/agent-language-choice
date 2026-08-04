package main

import (
	"net/http"
	"strings"
)

type campaignCraftingProject struct {
	ID            string `json:"id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	CostGP        int    `json:"cost_gp"`
	Status        string `json:"status"`
}

func craftingCreateResponse(p *campaignCraftingProject) map[string]any {
	return map[string]any{
		"id":             p.ID,
		"character_id":   p.CharacterID,
		"item_slug":      p.ItemSlug,
		"days_required":  p.DaysRequired,
		"days_completed": p.DaysCompleted,
		"status":         p.Status,
	}
}

func craftingAdvanceResponse(p *campaignCraftingProject) map[string]any {
	return map[string]any{
		"id":             p.ID,
		"days_completed": p.DaysCompleted,
		"status":         p.Status,
	}
}

type createCraftingProjectRequest struct {
	ID           string `json:"id"`
	CharacterID  string `json:"character_id"`
	ItemSlug     string `json:"item_slug"`
	DaysRequired *int   `json:"days_required"`
	CostGP       *int   `json:"cost_gp"`
}

func createCraftingProjectHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createCraftingProjectRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.CharacterID == "" {
		writeError(w, http.StatusBadRequest, "character_id is required")
		return
	}
	if req.ItemSlug == "" {
		writeError(w, http.StatusBadRequest, "item_slug is required")
		return
	}
	if req.DaysRequired == nil || *req.DaysRequired <= 0 {
		writeError(w, http.StatusBadRequest, "days_required must be a positive integer")
		return
	}
	if req.CostGP == nil || *req.CostGP < 0 {
		writeError(w, http.StatusBadRequest, "cost_gp must be a non-negative integer")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	charExists := false
	for _, ch := range c.Characters {
		if ch.ID == req.CharacterID {
			charExists = true
			break
		}
	}
	if !charExists {
		writeError(w, http.StatusNotFound, "unknown character id")
		return
	}

	for _, p := range c.CraftingProjects {
		if p.ID == req.ID {
			writeError(w, http.StatusConflict, "crafting project id already exists")
			return
		}
	}

	p := &campaignCraftingProject{
		ID:            req.ID,
		CharacterID:   req.CharacterID,
		ItemSlug:      req.ItemSlug,
		DaysRequired:  *req.DaysRequired,
		DaysCompleted: 0,
		CostGP:        *req.CostGP,
		Status:        "active",
	}
	if err := saveCampaignCraftingProjectToDB(c.ID, p); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save crafting project")
		return
	}
	c.CraftingProjects = append(c.CraftingProjects, p)

	writeJSON(w, http.StatusCreated, craftingCreateResponse(p))
}

type advanceCraftingRequest struct {
	Days *int `json:"days"`
}

func advanceCraftingHandler(w http.ResponseWriter, r *http.Request, campaignID, projectID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req advanceCraftingRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Days == nil || *req.Days <= 0 {
		writeError(w, http.StatusBadRequest, "days must be a positive integer")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	var p *campaignCraftingProject
	for _, existing := range c.CraftingProjects {
		if existing.ID == projectID {
			p = existing
			break
		}
	}
	if p == nil {
		writeError(w, http.StatusNotFound, "unknown crafting project id")
		return
	}
	if p.Status == "complete" {
		writeError(w, http.StatusBadRequest, "crafting project is already complete")
		return
	}

	wasComplete := false
	p.DaysCompleted += *req.Days
	if p.DaysCompleted >= p.DaysRequired {
		p.DaysCompleted = p.DaysRequired
		p.Status = "complete"
		wasComplete = true
	}

	if err := saveCampaignCraftingProjectToDB(c.ID, p); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save crafting project")
		return
	}

	if wasComplete {
		var row *campaignInventoryItem
		for _, inv := range c.Inventory {
			if inv.ItemSlug == p.ItemSlug && inv.Owner == "party" {
				row = inv
				break
			}
		}
		if row == nil {
			row = &campaignInventoryItem{ItemSlug: p.ItemSlug, Owner: "party", Quantity: 0}
			c.Inventory = append(c.Inventory, row)
		}
		row.Quantity++
		if err := saveCampaignInventoryToDB(c.ID, row); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save inventory item")
			return
		}
	}

	writeJSON(w, http.StatusOK, craftingAdvanceResponse(p))
}

// campaignCraftingRouter dispatches /v1/campaigns/{id}/downtime/crafting...
// routes. rest is the path segment after "/v1/campaigns/{id}/". Returns true
// if it handled the request.
func campaignCraftingRouter(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "downtime/crafting" {
		createCraftingProjectHandler(w, r, campaignID)
		return true
	}
	if strings.HasPrefix(rest, "downtime/crafting/") && strings.HasSuffix(rest, "/advance") {
		projectID := strings.TrimSuffix(strings.TrimPrefix(rest, "downtime/crafting/"), "/advance")
		if projectID == "" {
			return false
		}
		advanceCraftingHandler(w, r, campaignID, projectID)
		return true
	}
	return false
}

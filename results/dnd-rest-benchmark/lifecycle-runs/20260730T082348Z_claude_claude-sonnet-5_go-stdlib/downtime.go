package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

type craftingProject struct {
	ID            string `json:"id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	CostGP        int    `json:"cost_gp"`
	Status        string `json:"status"`
}

func craftingProjectResponse(p *craftingProject) map[string]interface{} {
	return map[string]interface{}{
		"id":             p.ID,
		"character_id":   p.CharacterID,
		"item_slug":      p.ItemSlug,
		"days_required":  p.DaysRequired,
		"days_completed": p.DaysCompleted,
		"status":         p.Status,
	}
}

func craftingAdvanceResponse(p *craftingProject) map[string]interface{} {
	return map[string]interface{}{
		"id":             p.ID,
		"days_completed": p.DaysCompleted,
		"status":         p.Status,
	}
}

func handleCreateCraftingProject(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ID           string `json:"id"`
		CharacterID  string `json:"character_id"`
		ItemSlug     string `json:"item_slug"`
		DaysRequired *int   `json:"days_required"`
		CostGP       *int   `json:"cost_gp"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.CharacterID == "" || req.ItemSlug == "" || req.DaysRequired == nil || *req.DaysRequired <= 0 || req.CostGP == nil || *req.CostGP < 0 {
		writeError(w, http.StatusBadRequest, "id, character_id, item_slug, days_required, and cost_gp are required")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	characterExists := false
	for _, ch := range c.Characters {
		if ch.ID == req.CharacterID {
			characterExists = true
			break
		}
	}
	if !characterExists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	for _, p := range c.Crafting {
		if p.ID == req.ID {
			campaignMu.Unlock()
			writeError(w, http.StatusConflict, "crafting project id already exists")
			return
		}
	}
	p := &craftingProject{
		ID:           req.ID,
		CharacterID:  req.CharacterID,
		ItemSlug:     req.ItemSlug,
		DaysRequired: *req.DaysRequired,
		CostGP:       *req.CostGP,
		Status:       "active",
	}
	c.Crafting = append(c.Crafting, p)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, craftingProjectResponse(p))
}

func handleAdvanceCraftingProject(w http.ResponseWriter, r *http.Request, campaignID, projectID string) {
	var req struct {
		Days *int `json:"days"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Days == nil || *req.Days <= 0 {
		writeError(w, http.StatusBadRequest, "days is required")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	var p *craftingProject
	for _, proj := range c.Crafting {
		if proj.ID == projectID {
			p = proj
			break
		}
	}
	if p == nil {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "crafting project not found")
		return
	}
	if p.Status == "complete" {
		campaignMu.Unlock()
		writeError(w, http.StatusBadRequest, "crafting project already complete")
		return
	}

	p.DaysCompleted += *req.Days
	if p.DaysCompleted >= p.DaysRequired {
		p.DaysCompleted = p.DaysRequired
		p.Status = "complete"
	}
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, craftingAdvanceResponse(p))
}

func handleCampaignCraftingSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "downtime/crafting" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreateCraftingProject(w, r, campaignID)
		return true
	}
	if strings.HasPrefix(rest, "downtime/crafting/") && strings.HasSuffix(rest, "/advance") {
		projectID := strings.TrimSuffix(strings.TrimPrefix(rest, "downtime/crafting/"), "/advance")
		if projectID == "" {
			return false
		}
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAdvanceCraftingProject(w, r, campaignID, projectID)
		return true
	}
	return false
}

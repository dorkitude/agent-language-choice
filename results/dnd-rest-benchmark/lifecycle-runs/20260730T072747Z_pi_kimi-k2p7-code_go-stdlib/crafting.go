package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// craftingProjectCreateRequest is the payload for starting a crafting project.
type craftingProjectCreateRequest struct {
	ID           string `json:"id"`
	CharacterID  string `json:"character_id"`
	ItemSlug     string `json:"item_slug"`
	DaysRequired int    `json:"days_required"`
	CostGP       int    `json:"cost_gp"`
}

// craftingProjectCreateResponse mirrors the request plus progress tracking.
type craftingProjectCreateResponse struct {
	ID            string `json:"id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	Status        string `json:"status"`
}

// craftingProjectAdvanceRequest advances a project by a number of days.
type craftingProjectAdvanceRequest struct {
	Days int `json:"days"`
}

// craftingProjectAdvanceResponse reports the project's progress after advancing.
type craftingProjectAdvanceResponse struct {
	ID            string `json:"id"`
	DaysCompleted int    `json:"days_completed"`
	Status        string `json:"status"`
}

// craftingProjectRow is the raw database representation of a crafting project.
type craftingProjectRow struct {
	ID            string `json:"id"`
	CampaignID    string `json:"campaign_id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	CostGP        int    `json:"cost_gp"`
	Status        string `json:"status"`
}

// queryCraftingProjectExists returns true when a project with the given ID exists.
func queryCraftingProjectExists(id string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM crafting_projects WHERE id=%s LIMIT 1;", sq(id)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// queryCharacterInCampaign returns true when the character belongs to the campaign.
func queryCharacterInCampaign(characterID, campaignID string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT 1 FROM campaign_characters WHERE id=%s AND campaign_id=%s LIMIT 1;",
		sq(characterID), sq(campaignID)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// createCraftingProjectHandler starts a new downtime crafting project.
func createCraftingProjectHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req craftingProjectCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.CharacterID == "" || req.ItemSlug == "" || req.DaysRequired <= 0 || req.CostGP < 0 {
		writeError(w, http.StatusBadRequest, "invalid crafting project")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("create crafting project campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	charExists, err := queryCharacterInCampaign(req.CharacterID, campaignID)
	if err != nil {
		log.Printf("create crafting project character query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !charExists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	projectExists, err := queryCraftingProjectExists(req.ID)
	if err != nil {
		log.Printf("create crafting project duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if projectExists {
		writeError(w, http.StatusConflict, "crafting project already exists")
		return
	}

	insertSQL := fmt.Sprintf(
		"INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (%s, %s, %s, %s, %d, 0, %d, 'active');",
		sq(req.ID), sq(campaignID), sq(req.CharacterID), sq(req.ItemSlug), req.DaysRequired, req.CostGP)
	if err := dbExec(insertSQL); err != nil {
		log.Printf("create crafting project insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, craftingProjectCreateResponse{
		ID:            req.ID,
		CharacterID:   req.CharacterID,
		ItemSlug:      req.ItemSlug,
		DaysRequired:  req.DaysRequired,
		DaysCompleted: 0,
		Status:        "active",
	})
}

// advanceCraftingProjectHandler advances a crafting project and adds the item
// to the campaign inventory when it completes.
func advanceCraftingProjectHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	projectID := r.PathValue("project_id")

	var req craftingProjectAdvanceRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Days <= 0 {
		writeError(w, http.StatusBadRequest, "invalid days")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("advance crafting project campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf(
		"SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id=%s AND campaign_id=%s LIMIT 1;",
		sq(projectID), sq(campaignID)))
	if err != nil {
		log.Printf("advance crafting project query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []craftingProjectRow
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("advance crafting project unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(rows) == 0 {
		writeError(w, http.StatusNotFound, "crafting project not found")
		return
	}
	project := rows[0]

	if project.Status == "complete" {
		writeError(w, http.StatusBadRequest, "project already complete")
		return
	}

	newDaysCompleted := project.DaysCompleted + req.Days
	if newDaysCompleted > project.DaysRequired {
		newDaysCompleted = project.DaysRequired
	}
	newStatus := "active"
	if newDaysCompleted >= project.DaysRequired {
		newStatus = "complete"
	}

	updateSQL := fmt.Sprintf(
		"UPDATE crafting_projects SET days_completed=%d, status=%s WHERE id=%s AND campaign_id=%s;",
		newDaysCompleted, sq(newStatus), sq(projectID), sq(campaignID))
	if err := dbExec(updateSQL); err != nil {
		log.Printf("advance crafting project update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if newStatus == "complete" {
		addItemSQL := fmt.Sprintf(
			"INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (%s, %s, 1, 'party') ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;",
			sq(campaignID), sq(project.ItemSlug))
		if err := dbExec(addItemSQL); err != nil {
			log.Printf("advance crafting project inventory insert error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	writeJSON(w, http.StatusOK, craftingProjectAdvanceResponse{
		ID:            projectID,
		DaysCompleted: newDaysCompleted,
		Status:        newStatus,
	})
}

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

type createEncounterRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

// createEncounterResponse is the shape returned after a successful encounter
// creation. Combatants are always empty at creation time.
type createEncounterResponse struct {
	ID         string `json:"id"`
	Name       string `json:"name"`
	Status     string `json:"status"`
	Combatants []any  `json:"combatants"`
}

// createEncounterHandler lets the campaign owner start a campaign-bound
// encounter. Only the owner may call it. Duplicate encounter IDs within the
// campaign, or a campaign that already has an active encounter, return 409.
// The new encounter is independent from the exploration turn queue.
func createEncounterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	owner, ok := requireCampaignOwner(w, r, campaignID)
	if !ok {
		return
	}

	var req createEncounterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "invalid encounter")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("encounter campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_encounters WHERE id=%s AND campaign_id=%s LIMIT 1;", sq(req.ID), sq(campaignID)))
	if err != nil {
		log.Printf("encounter exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "encounter already exists")
		return
	}

	active, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_encounters WHERE campaign_id=%s AND status='active' LIMIT 1;", sq(campaignID)))
	if err != nil {
		log.Printf("encounter active query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if active {
		writeError(w, http.StatusConflict, "campaign already in combat")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_encounters (id, campaign_id, name, status, combatants, round, turn_index) VALUES (%s, %s, %s, 'active', '[]', 1, 0);",
		sq(req.ID), sq(campaignID), sq(req.Name))); err != nil {
		log.Printf("encounter insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE play_campaigns SET phase='combat', pre_combat_actor=%s WHERE id=%s;",
		sq(campaign.TurnActor), sq(campaignID))); err != nil {
		log.Printf("encounter phase update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, createEncounterResponse{
		ID:         req.ID,
		Name:       req.Name,
		Status:     "active",
		Combatants: []any{},
	})
}

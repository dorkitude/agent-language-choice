package main

import (
	"database/sql"
	"errors"
	"log"
	"net/http"
)

// Downtime crafting is another ordered child of a campaign, like quests and
// inventory. A project accumulates days_completed until it reaches
// days_required, at which point it reports status "complete".
//
// A finished project does not write to the campaign inventory ledger: the two
// are separate records, and the inventory ledger holds only what was added
// through the inventory endpoint. Keeping crafting side-effect free is what
// makes the audit and export rollups a function of what a client explicitly
// recorded.
//
// Advancing is additive and clamped: days_completed never exceeds
// days_required, and a project that is already complete absorbs further
// advances without changing state.

// Crafting project status values. A project starts active and ends complete;
// there is no cancelled state in the spec, so none is invented here.
const (
	craftingActive   = "active"
	craftingComplete = "complete"
)

// ---------- POST /v1/campaigns/{id}/downtime/crafting ----------

type craftingRequest struct {
	ID           *string  `json:"id"`
	CharacterID  *string  `json:"character_id"`
	ItemSlug     *string  `json:"item_slug"`
	DaysRequired *int     `json:"days_required"`
	CostGP       *float64 `json:"cost_gp"`
}

type craftingResponse struct {
	ID            string `json:"id"`
	CharacterID   string `json:"character_id"`
	ItemSlug      string `json:"item_slug"`
	DaysRequired  int    `json:"days_required"`
	DaysCompleted int    `json:"days_completed"`
	Status        string `json:"status"`
}

func handleCampaignCrafting(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req craftingRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	characterID, ok := requireField(w, req.CharacterID, "character_id")
	if !ok {
		return
	}
	itemSlug, ok := requireField(w, req.ItemSlug, "item_slug")
	if !ok {
		return
	}
	if req.DaysRequired == nil {
		writeError(w, http.StatusBadRequest, "days_required is required")
		return
	}
	daysRequired := *req.DaysRequired
	if daysRequired <= 0 {
		writeError(w, http.StatusBadRequest, "days_required must be positive")
		return
	}
	// cost_gp is bookkeeping only: no purse is debited, but a negative price is
	// still a malformed request rather than a refund.
	costGP := 0.0
	if req.CostGP != nil {
		costGP = *req.CostGP
		if costGP < 0 {
			writeError(w, http.StatusBadRequest, "cost_gp must not be negative")
			return
		}
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_crafting WHERE campaign_id = ? AND id = ?`, campaignID, id,
	); err != nil {
		writeStorageFailure(w, "crafting lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "crafting project id already exists")
		return
	}

	position, err := nextPosition(`campaign_crafting`, campaignID)
	if err != nil {
		writeStorageFailure(w, "crafting position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_crafting
		   (campaign_id, id, position, character_id, item_slug, days_required, days_completed, cost_gp, status)
		 VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)`,
		campaignID, id, position, characterID, itemSlug, daysRequired, costGP, craftingActive,
	); err != nil {
		log.Printf("crafting insert failed: %v", err)
		writeError(w, http.StatusConflict, "crafting project id already exists")
		return
	}

	writeJSON(w, http.StatusCreated, craftingResponse{
		ID:            id,
		CharacterID:   characterID,
		ItemSlug:      itemSlug,
		DaysRequired:  daysRequired,
		DaysCompleted: 0,
		Status:        craftingActive,
	})
}

// ---------- POST /v1/campaigns/{id}/downtime/crafting/{project_id}/advance ----------

type craftingAdvanceRequest struct {
	Days *int `json:"days"`
}

// craftingAdvanceResponse reports only what an advance can change, matching the
// shape the spec shows for this endpoint.
type craftingAdvanceResponse struct {
	ID            string `json:"id"`
	DaysCompleted int    `json:"days_completed"`
	Status        string `json:"status"`
}

func handleCampaignCraftingAdvance(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	projectID, ok := requirePathValue(w, r, "project_id", "project id")
	if !ok {
		return
	}
	var req craftingAdvanceRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.Days == nil {
		writeError(w, http.StatusBadRequest, "days is required")
		return
	}
	days := *req.Days
	if days <= 0 {
		writeError(w, http.StatusBadRequest, "days must be positive")
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	var (
		daysRequired int
		completed    int
		status       string
	)
	err := db.QueryRow(
		`SELECT days_required, days_completed, status
		   FROM campaign_crafting WHERE campaign_id = ? AND id = ?`,
		campaignID, projectID,
	).Scan(&daysRequired, &completed, &status)
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "crafting project not found")
		return
	}
	if err != nil {
		writeStorageFailure(w, "crafting read failed", err)
		return
	}

	completed += days
	if completed > daysRequired {
		completed = daysRequired
	}
	if status == craftingActive && completed >= daysRequired {
		status = craftingComplete
	}
	if _, err := db.Exec(
		`UPDATE campaign_crafting SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?`,
		completed, status, campaignID, projectID,
	); err != nil {
		writeStorageFailure(w, "crafting update failed", err)
		return
	}
	writeJSON(w, http.StatusOK, craftingAdvanceResponse{
		ID:            projectID,
		DaysCompleted: completed,
		Status:        status,
	})
}


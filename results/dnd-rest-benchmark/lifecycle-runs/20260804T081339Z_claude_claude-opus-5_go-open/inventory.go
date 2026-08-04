package main

import (
	"net/http"
	"strings"
)

// Campaign inventory has two ledgers that never merge. campaign_inventory holds
// what the campaign has acquired ("party items"), and campaign_equipment holds
// what has been handed to a named character ("assigned items"). An assignment
// does not delete the party row, so the summary reports both counts as row
// counts of their own table and derives availability by subtraction.
//
// Both tables are ordered children of a campaign, so they take positions from
// nextPosition like the roster, the event log, quests, factions and NPCs. Rows
// are appendable rather than keyed by slug: adding the same item twice records
// two stacks, which keeps party_items a simple count of what was logged.

// defaultInventoryOwner applies when an item is added without an owner. Owner is
// free text otherwise; the spec names "party" but fixes no closed set.
const defaultInventoryOwner = "party"

// healingPotionSlug is the one item the summary tracks by name, matching the
// "healing_potions_available" field the spec asks for.
const healingPotionSlug = "healing-potion"

// ---------- POST /v1/campaigns/{id}/inventory ----------

type inventoryRequest struct {
	ItemSlug *string `json:"item_slug"`
	Quantity *int    `json:"quantity"`
	Owner    *string `json:"owner"`
}

type inventoryResponse struct {
	ItemSlug string `json:"item_slug"`
	Quantity int    `json:"quantity"`
	Owner    string `json:"owner"`
}

func handleCampaignInventory(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req inventoryRequest
	if !decodeBody(w, r, &req) {
		return
	}
	itemSlug, ok := requireField(w, req.ItemSlug, "item_slug")
	if !ok {
		return
	}
	quantity, ok := requireQuantity(w, req.Quantity)
	if !ok {
		return
	}
	owner := defaultInventoryOwner
	if req.Owner != nil {
		if trimmed := strings.TrimSpace(*req.Owner); trimmed != "" {
			owner = trimmed
		}
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	position, err := nextPosition(`campaign_inventory`, campaignID)
	if err != nil {
		writeStorageFailure(w, "inventory position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_inventory (campaign_id, position, item_slug, quantity, owner)
		 VALUES (?, ?, ?, ?, ?)`,
		campaignID, position, itemSlug, quantity, owner,
	); err != nil {
		writeStorageFailure(w, "inventory insert failed", err)
		return
	}
	writeJSON(w, http.StatusCreated, inventoryResponse{ItemSlug: itemSlug, Quantity: quantity, Owner: owner})
}

// ---------- POST /v1/campaigns/{id}/characters/{character_id}/equipment ----------

type equipmentRequest struct {
	ItemSlug *string `json:"item_slug"`
	Quantity *int    `json:"quantity"`
}

type equipmentResponse struct {
	CharacterID string `json:"character_id"`
	ItemSlug    string `json:"item_slug"`
	Quantity    int    `json:"quantity"`
}

// handleCharacterEquipment answers 200 rather than 201: an assignment reads as
// an update to who holds an item, not the creation of a new addressable record.
func handleCharacterEquipment(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	characterID, ok := requirePathValue(w, r, "character_id", "character id")
	if !ok {
		return
	}
	var req equipmentRequest
	if !decodeBody(w, r, &req) {
		return
	}
	itemSlug, ok := requireField(w, req.ItemSlug, "item_slug")
	if !ok {
		return
	}
	quantity, ok := requireQuantity(w, req.Quantity)
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	// Equipment goes to a member of this campaign's roster; an unknown character
	// is a mistake rather than a new one to create implicitly.
	exists, err := rowExists(
		`SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?`, campaignID, characterID,
	)
	if err != nil {
		writeStorageFailure(w, "character lookup failed", err)
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	position, err := nextPosition(`campaign_equipment`, campaignID)
	if err != nil {
		writeStorageFailure(w, "equipment position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_equipment (campaign_id, position, character_id, item_slug, quantity)
		 VALUES (?, ?, ?, ?, ?)`,
		campaignID, position, characterID, itemSlug, quantity,
	); err != nil {
		writeStorageFailure(w, "equipment insert failed", err)
		return
	}
	writeJSON(w, http.StatusOK, equipmentResponse{
		CharacterID: characterID, ItemSlug: itemSlug, Quantity: quantity,
	})
}

// ---------- GET /v1/campaigns/{id}/inventory/summary ----------

type inventorySummaryResponse struct {
	CampaignID              string `json:"campaign_id"`
	PartyItems              int    `json:"party_items"`
	AssignedItems           int    `json:"assigned_items"`
	HealingPotionsAvailable int    `json:"healing_potions_available"`
}

func handleCampaignInventorySummary(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	out := inventorySummaryResponse{CampaignID: campaignID}
	// party_items and assigned_items count stacks, not units: three potions in
	// one row are one party item.
	var stocked, assigned int
	if err := db.QueryRow(
		`SELECT COUNT(*), COALESCE(SUM(CASE WHEN item_slug = ? THEN quantity END), 0)
		 FROM campaign_inventory WHERE campaign_id = ?`,
		healingPotionSlug, campaignID,
	).Scan(&out.PartyItems, &stocked); err != nil {
		writeStorageFailure(w, "inventory summary failed", err)
		return
	}
	if err := db.QueryRow(
		`SELECT COUNT(*), COALESCE(SUM(CASE WHEN item_slug = ? THEN quantity END), 0)
		 FROM campaign_equipment WHERE campaign_id = ?`,
		healingPotionSlug, campaignID,
	).Scan(&out.AssignedItems, &assigned); err != nil {
		writeStorageFailure(w, "equipment summary failed", err)
		return
	}
	out.HealingPotionsAvailable = stocked - assigned
	writeJSON(w, http.StatusOK, out)
}

// requireQuantity validates a required positive integer quantity. A missing,
// zero or negative count is a bad request rather than a silently defaulted one.
func requireQuantity(w http.ResponseWriter, value *int) (int, bool) {
	if value == nil {
		writeError(w, http.StatusBadRequest, "quantity is required")
		return 0, false
	}
	if *value <= 0 {
		writeError(w, http.StatusBadRequest, "quantity must be positive")
		return 0, false
	}
	return *value, true
}

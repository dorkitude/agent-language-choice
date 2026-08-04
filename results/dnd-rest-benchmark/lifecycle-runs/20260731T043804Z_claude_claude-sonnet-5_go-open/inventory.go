package main

import (
	"net/http"
)

type campaignInventoryItem struct {
	ItemSlug string `json:"item_slug"`
	Owner    string `json:"owner"`
	Quantity int    `json:"quantity"`
}

type campaignEquipmentItem struct {
	CharacterID string `json:"character_id"`
	ItemSlug    string `json:"item_slug"`
	Quantity    int    `json:"quantity"`
}

type addInventoryRequest struct {
	ItemSlug string `json:"item_slug"`
	Quantity *int   `json:"quantity"`
	Owner    string `json:"owner"`
}

func addInventoryHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req addInventoryRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ItemSlug == "" {
		writeError(w, http.StatusBadRequest, "item_slug is required")
		return
	}
	if req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "quantity must be a positive integer")
		return
	}
	if req.Owner == "" {
		writeError(w, http.StatusBadRequest, "owner is required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	var row *campaignInventoryItem
	for _, inv := range c.Inventory {
		if inv.ItemSlug == req.ItemSlug && inv.Owner == req.Owner {
			row = inv
			break
		}
	}
	if row == nil {
		row = &campaignInventoryItem{ItemSlug: req.ItemSlug, Owner: req.Owner, Quantity: 0}
		c.Inventory = append(c.Inventory, row)
	}
	row.Quantity += *req.Quantity

	if err := saveCampaignInventoryToDB(c.ID, row); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save inventory item")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"item_slug": req.ItemSlug,
		"quantity":  *req.Quantity,
		"owner":     req.Owner,
	})
}

type assignEquipmentRequest struct {
	ItemSlug string `json:"item_slug"`
	Quantity *int   `json:"quantity"`
}

func assignEquipmentHandler(w http.ResponseWriter, r *http.Request, campaignID, characterID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req assignEquipmentRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ItemSlug == "" {
		writeError(w, http.StatusBadRequest, "item_slug is required")
		return
	}
	if req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "quantity must be a positive integer")
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
		if ch.ID == characterID {
			charExists = true
			break
		}
	}
	if !charExists {
		writeError(w, http.StatusNotFound, "unknown character id")
		return
	}

	var partyRow *campaignInventoryItem
	for _, inv := range c.Inventory {
		if inv.ItemSlug == req.ItemSlug && inv.Owner == "party" {
			partyRow = inv
			break
		}
	}
	if partyRow == nil || partyRow.Quantity < *req.Quantity {
		writeError(w, http.StatusBadRequest, "insufficient party inventory for item")
		return
	}

	partyRow.Quantity -= *req.Quantity
	if err := saveCampaignInventoryToDB(c.ID, partyRow); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save inventory item")
		return
	}

	var equipRow *campaignEquipmentItem
	for _, eq := range c.Equipment {
		if eq.CharacterID == characterID && eq.ItemSlug == req.ItemSlug {
			equipRow = eq
			break
		}
	}
	if equipRow == nil {
		equipRow = &campaignEquipmentItem{CharacterID: characterID, ItemSlug: req.ItemSlug, Quantity: 0}
		c.Equipment = append(c.Equipment, equipRow)
	}
	equipRow.Quantity += *req.Quantity

	if err := saveCampaignEquipmentToDB(c.ID, equipRow); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save equipment")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": characterID,
		"item_slug":    req.ItemSlug,
		"quantity":     *req.Quantity,
	})
}

func inventorySummaryHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	partyItems := 0
	healingPotionsAvailable := 0
	for _, inv := range c.Inventory {
		if inv.Owner != "party" || inv.Quantity <= 0 {
			continue
		}
		partyItems++
		if inv.ItemSlug == "healing-potion" {
			healingPotionsAvailable += inv.Quantity
		}
	}

	assignedItems := 0
	for _, eq := range c.Equipment {
		if eq.Quantity > 0 {
			assignedItems++
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":               c.ID,
		"party_items":               partyItems,
		"assigned_items":            assignedItems,
		"healing_potions_available": healingPotionsAvailable,
	})
}

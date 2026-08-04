package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

type inventoryEntry struct {
	ItemSlug string `json:"item_slug"`
	Quantity int    `json:"quantity"`
	Owner    string `json:"owner"`
}

type equipmentEntry struct {
	CharacterID string `json:"character_id"`
	ItemSlug    string `json:"item_slug"`
	Quantity    int    `json:"quantity"`
}

func inventoryEntryResponse(e inventoryEntry) map[string]interface{} {
	return map[string]interface{}{
		"item_slug": e.ItemSlug,
		"quantity":  e.Quantity,
		"owner":     e.Owner,
	}
}

func equipmentEntryResponse(e equipmentEntry) map[string]interface{} {
	return map[string]interface{}{
		"character_id": e.CharacterID,
		"item_slug":    e.ItemSlug,
		"quantity":     e.Quantity,
	}
}

func handleAddInventoryItem(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ItemSlug string `json:"item_slug"`
		Quantity *int   `json:"quantity"`
		Owner    string `json:"owner"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ItemSlug == "" || req.Owner == "" || req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "item_slug, quantity, and owner are required")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	entry := inventoryEntry{ItemSlug: req.ItemSlug, Quantity: *req.Quantity, Owner: req.Owner}
	c.Inventory = append(c.Inventory, entry)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, inventoryEntryResponse(entry))
}

func handleAssignEquipment(w http.ResponseWriter, r *http.Request, campaignID, characterID string) {
	var req struct {
		ItemSlug string `json:"item_slug"`
		Quantity *int   `json:"quantity"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ItemSlug == "" || req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "item_slug and quantity are required")
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
		if ch.ID == characterID {
			characterExists = true
			break
		}
	}
	if !characterExists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	partyTotal := 0
	for _, e := range c.Inventory {
		if e.Owner == "party" && e.ItemSlug == req.ItemSlug {
			partyTotal += e.Quantity
		}
	}
	assignedTotal := 0
	for _, e := range c.Equipment {
		if e.ItemSlug == req.ItemSlug {
			assignedTotal += e.Quantity
		}
	}
	if partyTotal-assignedTotal < *req.Quantity {
		campaignMu.Unlock()
		writeError(w, http.StatusBadRequest, "insufficient party inventory for item")
		return
	}

	entry := equipmentEntry{CharacterID: characterID, ItemSlug: req.ItemSlug, Quantity: *req.Quantity}
	c.Equipment = append(c.Equipment, entry)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, equipmentEntryResponse(entry))
}

func handleInventorySummary(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	partyItems := 0
	healingPotionsTotal := 0
	for _, e := range c.Inventory {
		if e.Owner == "party" {
			partyItems++
			if e.ItemSlug == "healing-potion" {
				healingPotionsTotal += e.Quantity
			}
		}
	}
	assignedItems := len(c.Equipment)
	healingPotionsAssigned := 0
	for _, e := range c.Equipment {
		if e.ItemSlug == "healing-potion" {
			healingPotionsAssigned += e.Quantity
		}
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id":               campaignID,
		"party_items":               partyItems,
		"assigned_items":            assignedItems,
		"healing_potions_available": healingPotionsTotal - healingPotionsAssigned,
	})
}

func handleCampaignInventorySub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "inventory" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAddInventoryItem(w, r, campaignID)
		return true
	}
	if rest == "inventory/summary" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleInventorySummary(w, r, campaignID)
		return true
	}
	if strings.HasPrefix(rest, "characters/") && strings.HasSuffix(rest, "/equipment") {
		characterID := strings.TrimSuffix(strings.TrimPrefix(rest, "characters/"), "/equipment")
		if characterID == "" {
			return false
		}
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAssignEquipment(w, r, campaignID, characterID)
		return true
	}
	return false
}

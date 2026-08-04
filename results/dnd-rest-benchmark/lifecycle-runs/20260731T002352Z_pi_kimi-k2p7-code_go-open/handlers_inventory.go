package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func addInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req inventoryItem
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ItemSlug) == "" {
		badRequest(w, "item_slug is required")
		return
	}
	if req.Quantity <= 0 {
		badRequest(w, "quantity must be a positive integer")
		return
	}
	if strings.TrimSpace(req.Owner) == "" {
		badRequest(w, "owner is required")
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

	if err := dbAddInventoryItem(campaignID, req.ItemSlug, req.Quantity, req.Owner); err != nil {
		if isForeignKeyViolation(err) {
			notFound(w, "item not found")
			return
		}
		log.Printf("add inventory item: %v", err)
		badRequest(w, "failed to add inventory item")
		return
	}

	writeJSON(w, http.StatusCreated, &req)
}

func assignEquipmentHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	if campaignID == "" || characterID == "" {
		notFound(w, "campaign or character not found")
		return
	}
	if requireCampaign(w, campaignID) == nil {
		return
	}

	char, err := dbGetCharacter(characterID, campaignID)
	if err != nil {
		log.Printf("get character: %v", err)
		notFound(w, "character not found")
		return
	}
	if char == nil {
		notFound(w, "character not found")
		return
	}

	var req struct {
		ItemSlug string `json:"item_slug"`
		Quantity int    `json:"quantity"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ItemSlug) == "" {
		badRequest(w, "item_slug is required")
		return
	}
	if req.Quantity <= 0 {
		badRequest(w, "quantity must be a positive integer")
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

	if err := dbAssignEquipment(campaignID, characterID, req.ItemSlug, req.Quantity); err != nil {
		if strings.Contains(err.Error(), "insufficient quantity") {
			badRequest(w, err.Error())
			return
		}
		if isForeignKeyViolation(err) {
			notFound(w, "item not found")
			return
		}
		log.Printf("assign equipment: %v", err)
		badRequest(w, "failed to assign equipment")
		return
	}

	writeJSON(w, http.StatusOK, equipmentAssignment{
		CharacterID: characterID,
		ItemSlug:    req.ItemSlug,
		Quantity:    req.Quantity,
	})
}

func getInventorySummaryHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	summary, err := dbGetInventorySummary(campaignID)
	if err != nil {
		log.Printf("inventory summary: %v", err)
		badRequest(w, "failed to read inventory summary")
		return
	}

	writeJSON(w, http.StatusOK, summary)
}

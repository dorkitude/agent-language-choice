package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// inventoryItem is the request/response shape for party inventory.
type inventoryItem struct {
	ItemSlug string `json:"item_slug"`
	Quantity int    `json:"quantity"`
	Owner    string `json:"owner"`
}

// assignEquipmentRequest is the payload for assigning an item to a character.
type assignEquipmentRequest struct {
	ItemSlug string `json:"item_slug"`
	Quantity int    `json:"quantity"`
}

// assignEquipmentResponse is returned after assigning equipment.
type assignEquipmentResponse struct {
	CharacterID string `json:"character_id"`
	ItemSlug    string `json:"item_slug"`
	Quantity    int    `json:"quantity"`
}

// addInventoryItemHandler adds an item to a campaign inventory.
func addInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req inventoryItem
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ItemSlug == "" || req.Owner == "" || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "invalid inventory item")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("add inventory campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	insertSQL := fmt.Sprintf(
		"INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (%s, %s, %d, %s) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity;",
		sq(campaignID), sq(req.ItemSlug), req.Quantity, sq(req.Owner))
	if err := dbExec(insertSQL); err != nil {
		log.Printf("add inventory insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	out, err := dbQuery(fmt.Sprintf(
		"SELECT quantity FROM campaign_inventory WHERE campaign_id=%s AND item_slug=%s AND owner=%s LIMIT 1;",
		sq(campaignID), sq(req.ItemSlug), sq(req.Owner)))
	if err != nil {
		log.Printf("add inventory quantity query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		Quantity int `json:"quantity"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("add inventory quantity unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	qty := req.Quantity
	if len(rows) > 0 {
		qty = rows[0].Quantity
	}

	writeJSON(w, http.StatusCreated, inventoryItem{
		ItemSlug: req.ItemSlug,
		Quantity: qty,
		Owner:    req.Owner,
	})
}

// assignEquipmentHandler assigns an item from party inventory to a character.
func assignEquipmentHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	var req assignEquipmentRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ItemSlug == "" || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "invalid equipment assignment")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("assign equipment campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	charOut, err := dbQuery(fmt.Sprintf(
		"SELECT 1 FROM campaign_characters WHERE id=%s AND campaign_id=%s LIMIT 1;",
		sq(characterID), sq(campaignID)))
	if err != nil {
		log.Printf("assign equipment character query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var charRows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(charOut, &charRows); err != nil {
		log.Printf("assign equipment character unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(charRows) == 0 {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	availOut, err := dbQuery(fmt.Sprintf(
		"SELECT COALESCE(SUM(quantity), 0) AS qty FROM campaign_inventory WHERE campaign_id=%s AND item_slug=%s AND owner='party';",
		sq(campaignID), sq(req.ItemSlug)))
	if err != nil {
		log.Printf("assign equipment available query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var availRows []struct {
		Qty int `json:"qty"`
	}
	if err := json.Unmarshal(availOut, &availRows); err != nil {
		log.Printf("assign equipment available unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	available := 0
	if len(availRows) > 0 {
		available = availRows[0].Qty
	}

	assignedOut, err := dbQuery(fmt.Sprintf(
		"SELECT COALESCE(SUM(quantity), 0) AS qty FROM character_equipment WHERE campaign_id=%s AND item_slug=%s;",
		sq(campaignID), sq(req.ItemSlug)))
	if err != nil {
		log.Printf("assign equipment assigned query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var assignedRows []struct {
		Qty int `json:"qty"`
	}
	if err := json.Unmarshal(assignedOut, &assignedRows); err != nil {
		log.Printf("assign equipment assigned unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	assigned := 0
	if len(assignedRows) > 0 {
		assigned = assignedRows[0].Qty
	}

	if available-assigned < req.Quantity {
		writeError(w, http.StatusBadRequest, "insufficient inventory")
		return
	}

	upsertSQL := fmt.Sprintf(
		"INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity) VALUES (%s, %s, %s, %d) ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity;",
		sq(campaignID), sq(characterID), sq(req.ItemSlug), req.Quantity)
	if err := dbExec(upsertSQL); err != nil {
		log.Printf("assign equipment insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	out, err := dbQuery(fmt.Sprintf(
		"SELECT quantity FROM character_equipment WHERE campaign_id=%s AND character_id=%s AND item_slug=%s LIMIT 1;",
		sq(campaignID), sq(characterID), sq(req.ItemSlug)))
	if err != nil {
		log.Printf("assign equipment quantity query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		Quantity int `json:"quantity"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("assign equipment quantity unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	qty := req.Quantity
	if len(rows) > 0 {
		qty = rows[0].Quantity
	}

	writeJSON(w, http.StatusOK, assignEquipmentResponse{
		CharacterID: characterID,
		ItemSlug:    req.ItemSlug,
		Quantity:    qty,
	})
}

// itemAvailableFieldName converts an item slug into the summary availability key.
func itemAvailableFieldName(slug string) string {
	base := strings.ReplaceAll(slug, "-", "_")
	if !strings.HasSuffix(base, "s") {
		base += "s"
	}
	return base + "_available"
}

// getInventorySummaryHandler returns the campaign inventory overview.
func getInventorySummaryHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("inventory summary campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	partyOut, err := dbQuery(fmt.Sprintf(
		"SELECT COUNT(*) AS cnt FROM campaign_inventory WHERE campaign_id=%s AND owner='party';",
		sq(campaignID)))
	if err != nil {
		log.Printf("inventory summary party count query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var partyCounts []struct {
		Cnt int `json:"cnt"`
	}
	if err := json.Unmarshal(partyOut, &partyCounts); err != nil {
		log.Printf("inventory summary party count unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	partyItems := 0
	if len(partyCounts) > 0 {
		partyItems = partyCounts[0].Cnt
	}

	assignedOut, err := dbQuery(fmt.Sprintf(
		"SELECT COUNT(*) AS cnt FROM character_equipment WHERE campaign_id=%s;",
		sq(campaignID)))
	if err != nil {
		log.Printf("inventory summary assigned count query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var assignedCounts []struct {
		Cnt int `json:"cnt"`
	}
	if err := json.Unmarshal(assignedOut, &assignedCounts); err != nil {
		log.Printf("inventory summary assigned count unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	assignedItems := 0
	if len(assignedCounts) > 0 {
		assignedItems = assignedCounts[0].Cnt
	}

	availItems := map[string]int{}

	partyItemsOut, err := dbQuery(fmt.Sprintf(
		"SELECT item_slug, quantity FROM campaign_inventory WHERE campaign_id=%s AND owner='party';",
		sq(campaignID)))
	if err != nil {
		log.Printf("inventory summary party items query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var partyItemRows []struct {
		ItemSlug string `json:"item_slug"`
		Quantity int    `json:"quantity"`
	}
	if err := json.Unmarshal(partyItemsOut, &partyItemRows); err != nil {
		log.Printf("inventory summary party items unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for _, row := range partyItemRows {
		availItems[row.ItemSlug] = row.Quantity
	}

	assignedItemOut, err := dbQuery(fmt.Sprintf(
		"SELECT item_slug, COALESCE(SUM(quantity), 0) AS qty FROM character_equipment WHERE campaign_id=%s GROUP BY item_slug;",
		sq(campaignID)))
	if err != nil {
		log.Printf("inventory summary assigned items query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var assignedItemRows []struct {
		ItemSlug string `json:"item_slug"`
		Qty      int    `json:"qty"`
	}
	if err := json.Unmarshal(assignedItemOut, &assignedItemRows); err != nil {
		log.Printf("inventory summary assigned items unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for _, row := range assignedItemRows {
		availItems[row.ItemSlug] -= row.Qty
	}

	summary := map[string]any{
		"campaign_id":    campaignID,
		"party_items":    partyItems,
		"assigned_items": assignedItems,
	}
	for slug, available := range availItems {
		summary[itemAvailableFieldName(slug)] = available
	}

	writeJSON(w, http.StatusOK, summary)
}

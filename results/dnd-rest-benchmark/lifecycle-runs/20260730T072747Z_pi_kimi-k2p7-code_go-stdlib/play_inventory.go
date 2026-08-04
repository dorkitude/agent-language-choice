package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sort"
)

// validInventoryItemIDs is the catalog of items that can be held in a
// character's personal inventory stack.
var validInventoryItemIDs = map[string]bool{
	"healing-potion":     true,
	"torch":              true,
	"leather-armor":      true,
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

// inventoryItemRequest binds the payload for adding or removing a stackable
// inventory item. The item_id is omitted for removal because it comes from the
// URL path.
type inventoryItemRequest struct {
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

// inventoryItemResponse is the shape returned after adding or removing a stack
// from a character's inventory. Quantity reports the amount that was changed
// in the request; total_quantity reports the stack size after the change.
type inventoryItemResponse struct {
	CharacterID   string `json:"character_id"`
	ItemID        string `json:"item_id"`
	Quantity      int    `json:"quantity"`
	TotalQuantity int    `json:"total_quantity"`
}

// itemStack is a single held item in a character's inventory.
type itemStack struct {
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

// inventoryItemsResponse is the shape returned when listing a character's held
// items. Items are returned in lexicographic item_id order.
type inventoryItemsResponse struct {
	CharacterID string      `json:"character_id"`
	Items       []itemStack `json:"items"`
}

// consumableEffect is the embedded effect description in a consume response.
type consumableEffect struct {
	Type       string `json:"type"`
	HPRestored int    `json:"hp_restored"`
}

// consumeItemResponse is the shape returned after consuming a held consumable.
type consumeItemResponse struct {
	CharacterID      string           `json:"character_id"`
	ItemID           string           `json:"item_id"`
	QuantityConsumed int              `json:"quantity_consumed"`
	TotalQuantity    int              `json:"total_quantity"`
	Effect           consumableEffect `json:"effect"`
}

// consumableItems is the set of inventory items that may be consumed.
var consumableItems = map[string]bool{
	"healing-potion": true,
}

// addCharacterInventoryItemHandler lets the owner of a campaign character add
// stackable items to their personal inventory. Only healing-potion and torch
// are valid item IDs, and quantity must be positive.
func addCharacterInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("add inventory item member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req inventoryItemRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if !validInventoryItemIDs[req.ItemID] || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "invalid item or quantity")
		return
	}

	upsertSQL := fmt.Sprintf(
		"INSERT INTO character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (%s, %s, %s, %d) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity;",
		sq(campaignID), sq(characterID), sq(req.ItemID), req.Quantity)
	if err := dbExec(upsertSQL); err != nil {
		log.Printf("add inventory item upsert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	total, err := queryCharacterInventoryItemQuantity(campaignID, characterID, req.ItemID)
	if err != nil {
		log.Printf("add inventory item total query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, inventoryItemResponse{
		CharacterID:   characterID,
		ItemID:        req.ItemID,
		Quantity:      req.Quantity,
		TotalQuantity: total,
	})
}

// getCharacterInventoryItemsHandler returns the held items for a campaign
// character. Any campaign member may read the inventory; items are returned in
// lexicographic item_id order.
func getCharacterInventoryItemsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("get inventory items member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	items, err := queryCharacterInventoryItems(campaignID, characterID)
	if err != nil {
		log.Printf("get inventory items query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	sort.Slice(items, func(i, j int) bool {
		return items[i].ItemID < items[j].ItemID
	})

	writeJSON(w, http.StatusOK, inventoryItemsResponse{
		CharacterID: characterID,
		Items:       items,
	})
}

// removeCharacterInventoryItemHandler lets the owner of a campaign character
// remove a positive quantity from a held item stack. The item ID is taken from
// the path and must be a known catalog item; quantity must be positive and
// may not exceed the held stack.
func removeCharacterInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	itemID := r.PathValue("item_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("remove inventory item member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	if !validInventoryItemIDs[itemID] {
		writeError(w, http.StatusBadRequest, "invalid item")
		return
	}

	var req inventoryItemRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "invalid quantity")
		return
	}

	held, err := queryCharacterInventoryItemQuantity(campaignID, characterID, itemID)
	if err != nil {
		log.Printf("remove inventory item held query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if held == 0 || req.Quantity > held {
		writeError(w, http.StatusConflict, "insufficient quantity")
		return
	}

	remaining := held - req.Quantity
	if remaining == 0 {
		deleteSQL := fmt.Sprintf(
			"DELETE FROM character_inventory_items WHERE campaign_id=%s AND character_id=%s AND item_id=%s;",
			sq(campaignID), sq(characterID), sq(itemID))
		if err := dbExec(deleteSQL); err != nil {
			log.Printf("remove inventory item delete error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	} else {
		updateSQL := fmt.Sprintf(
			"UPDATE character_inventory_items SET quantity=%d WHERE campaign_id=%s AND character_id=%s AND item_id=%s;",
			remaining, sq(campaignID), sq(characterID), sq(itemID))
		if err := dbExec(updateSQL); err != nil {
			log.Printf("remove inventory item update error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	writeJSON(w, http.StatusOK, inventoryItemResponse{
		CharacterID:   characterID,
		ItemID:        itemID,
		Quantity:      req.Quantity,
		TotalQuantity: remaining,
	})
}

// consumeCharacterInventoryItemHandler lets the owner of a campaign character
// consume one unit of a held consumable item. Only healing-potion is
// consumable; other known or unknown item IDs return 400. Missing or empty
// stacks return 409. The stack is decremented by one and removed when empty.
func consumeCharacterInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	itemID := r.PathValue("item_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("consume item member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if member.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	if !validInventoryItemIDs[itemID] || !consumableItems[itemID] {
		writeError(w, http.StatusBadRequest, "item is not consumable")
		return
	}

	held, err := queryCharacterInventoryItemQuantity(campaignID, characterID, itemID)
	if err != nil {
		log.Printf("consume item held query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if held <= 0 {
		writeError(w, http.StatusConflict, "no quantity to consume")
		return
	}

	remaining := held - 1
	if remaining == 0 {
		deleteSQL := fmt.Sprintf(
			"DELETE FROM character_inventory_items WHERE campaign_id=%s AND character_id=%s AND item_id=%s;",
			sq(campaignID), sq(characterID), sq(itemID))
		if err := dbExec(deleteSQL); err != nil {
			log.Printf("consume item delete error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	} else {
		updateSQL := fmt.Sprintf(
			"UPDATE character_inventory_items SET quantity=%d WHERE campaign_id=%s AND character_id=%s AND item_id=%s;",
			remaining, sq(campaignID), sq(characterID), sq(itemID))
		if err := dbExec(updateSQL); err != nil {
			log.Printf("consume item update error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	writeJSON(w, http.StatusOK, consumeItemResponse{
		CharacterID:      characterID,
		ItemID:           itemID,
		QuantityConsumed: 1,
		TotalQuantity:    remaining,
		Effect: consumableEffect{
			Type:       "healing",
			HPRestored: 5,
		},
	})
}

// queryCharacterInventoryItemQuantity returns the held quantity for a single
// item stack. The caller must hold dbMu.
func queryCharacterInventoryItemQuantity(campaignID, characterID, itemID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT quantity FROM character_inventory_items WHERE campaign_id=%s AND character_id=%s AND item_id=%s LIMIT 1;",
		sq(campaignID), sq(characterID), sq(itemID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		Quantity int `json:"quantity"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 0, nil
	}
	return rows[0].Quantity, nil
}

// queryCharacterInventoryItems returns all held item stacks for a character.
// The caller must hold dbMu.
func queryCharacterInventoryItems(campaignID, characterID string) ([]itemStack, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT item_id, quantity FROM character_inventory_items WHERE campaign_id=%s AND character_id=%s;",
		sq(campaignID), sq(characterID)))
	if err != nil {
		return nil, err
	}
	var rows []itemStack
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	if rows == nil {
		return []itemStack{}, nil
	}
	return rows, nil
}

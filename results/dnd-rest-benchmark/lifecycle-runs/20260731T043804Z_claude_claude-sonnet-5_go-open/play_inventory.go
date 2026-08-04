package main

import (
	"net/http"
	"sort"
	"sync"
)

// playInventoryItem tracks how many of a single catalog item a character
// currently holds.
type playInventoryItem struct {
	CampaignID  string `json:"-"`
	CharacterID string `json:"-"`
	ItemID      string `json:"item_id"`
	Quantity    int    `json:"quantity"`
}

// inventoryItemsMu guards inventoryItems, the in-memory index mirroring the
// play_inventory_items table. Keyed by campaign id, then character id, then
// item id.
var (
	inventoryItemsMu sync.Mutex
	inventoryItems   = map[string]map[string]map[string]*playInventoryItem{}
)

// inventoryCatalog is the set of item ids that can be added to a character's
// inventory stack.
var inventoryCatalog = map[string]bool{
	"healing-potion":     true,
	"torch":              true,
	"leather-armor":      true,
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

// consumableEffects maps consumable catalog item ids to the effect applied
// when a held stack unit is consumed.
var consumableEffects = map[string]map[string]any{
	"healing-potion": {"type": "healing", "hp_restored": 5},
}

type addInventoryItemRequest struct {
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

type removeInventoryItemRequest struct {
	Quantity int `json:"quantity"`
}

// addInventoryItemHandler lets a character's owner add a positive quantity
// of a valid catalog item to that character's inventory stack.
func addInventoryItemHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req addInventoryItemRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !inventoryCatalog[req.ItemID] {
		writeError(w, http.StatusBadRequest, "unknown item_id")
		return
	}
	if req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "quantity must be positive")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may add inventory items")
		return
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	if inventoryItems[campaignID] == nil {
		inventoryItems[campaignID] = map[string]map[string]*playInventoryItem{}
	}
	if inventoryItems[campaignID][charID] == nil {
		inventoryItems[campaignID][charID] = map[string]*playInventoryItem{}
	}
	item, exists := inventoryItems[campaignID][charID][req.ItemID]
	if !exists {
		item = &playInventoryItem{CampaignID: campaignID, CharacterID: charID, ItemID: req.ItemID, Quantity: 0}
		inventoryItems[campaignID][charID][req.ItemID] = item
	}
	item.Quantity += req.Quantity

	if err := saveInventoryItemToDB(item); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save inventory item")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"character_id":   charID,
		"item_id":        req.ItemID,
		"quantity":       req.Quantity,
		"total_quantity": item.Quantity,
	})
}

// listInventoryItemsHandler returns a character's held item stacks in
// lexicographic item_id order. Any campaign member may call this.
func listInventoryItemsHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the owner or a member of this campaign")
		return
	}

	playMembersMu.Lock()
	if _, exists := findMemberByCharacterID(campaignID, charID); !exists {
		playMembersMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	playMembersMu.Unlock()

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	items := []map[string]any{}
	for itemID, item := range inventoryItems[campaignID][charID] {
		if item.Quantity <= 0 {
			continue
		}
		items = append(items, map[string]any{"item_id": itemID, "quantity": item.Quantity})
	}
	sort.Slice(items, func(i, j int) bool {
		return items[i]["item_id"].(string) < items[j]["item_id"].(string)
	})

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": charID,
		"items":        items,
	})
}

// removeInventoryItemHandler lets a character's owner remove a positive
// quantity, up to the held stack, of a valid catalog item.
func removeInventoryItemHandler(w http.ResponseWriter, r *http.Request, campaignID, charID, itemID string) {
	if !requireMethod(w, r, http.MethodDelete) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req removeInventoryItemRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if !inventoryCatalog[itemID] {
		writeError(w, http.StatusBadRequest, "unknown item_id")
		return
	}
	if req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "quantity must be positive")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may remove inventory items")
		return
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	var item *playInventoryItem
	if inventoryItems[campaignID] != nil {
		item = inventoryItems[campaignID][charID][itemID]
	}
	held := 0
	if item != nil {
		held = item.Quantity
	}
	if req.Quantity > held {
		writeError(w, http.StatusConflict, "cannot remove more than the held quantity")
		return
	}

	item.Quantity -= req.Quantity
	if item.Quantity <= 0 {
		if err := deleteInventoryItemFromDB(campaignID, charID, itemID); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to remove inventory item")
			return
		}
		delete(inventoryItems[campaignID][charID], itemID)
	} else {
		if err := saveInventoryItemToDB(item); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save inventory item")
			return
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id":   charID,
		"item_id":        itemID,
		"quantity":       req.Quantity,
		"total_quantity": held - req.Quantity,
	})
}

// consumeInventoryItemHandler lets a character's owner consume one unit of a
// held consumable item stack.
func consumeInventoryItemHandler(w http.ResponseWriter, r *http.Request, campaignID, charID, itemID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	effect, isConsumable := consumableEffects[itemID]
	if !inventoryCatalog[itemID] || !isConsumable {
		writeError(w, http.StatusBadRequest, "item is not consumable")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	member, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(member) {
		writeError(w, http.StatusForbidden, "only the character's owner may consume inventory items")
		return
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	var item *playInventoryItem
	if inventoryItems[campaignID] != nil {
		item = inventoryItems[campaignID][charID][itemID]
	}
	if item == nil || item.Quantity <= 0 {
		writeError(w, http.StatusConflict, "no held stack of this item")
		return
	}

	item.Quantity--
	if item.Quantity <= 0 {
		if err := deleteInventoryItemFromDB(campaignID, charID, itemID); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to remove inventory item")
			return
		}
		delete(inventoryItems[campaignID][charID], itemID)
	} else {
		if err := saveInventoryItemToDB(item); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save inventory item")
			return
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id":      charID,
		"item_id":           itemID,
		"quantity_consumed": 1,
		"total_quantity":    item.Quantity,
		"effect":            effect,
	})
}

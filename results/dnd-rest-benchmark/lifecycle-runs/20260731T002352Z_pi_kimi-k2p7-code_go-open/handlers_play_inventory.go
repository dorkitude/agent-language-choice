package main

import (
	"encoding/json"
	"log"
	"net/http"
)

// validInventoryItemIDs lists the catalog item IDs accepted for per-character
// inventory stacks.
var validInventoryItemIDs = map[string]bool{
	"healing-potion":     true,
	"torch":              true,
	"leather-armor":      true,
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

// itemEquipmentSlots maps each equippable item to its legal equipment slot.
var itemEquipmentSlots = map[string]string{
	"leather-armor":      "armor",
	"ring-of-protection": "accessory",
	"amulet-of-health":   "accessory",
}

// attunableItemIDs lists the accessories that can be attuned.
var attunableItemIDs = map[string]bool{
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

// consumableItemIDs lists the inventory items that may be consumed.
var consumableItemIDs = map[string]bool{
	"healing-potion": true,
}

const maxAttunements = 1

func addCharacterInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("add character inventory: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may add items")
		return
	}

	var req characterInventoryStackRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if !validInventoryItemIDs[req.ItemID] {
		badRequest(w, "invalid item_id")
		return
	}
	if req.Quantity <= 0 {
		badRequest(w, "quantity must be positive")
		return
	}

	total, err := dbAddCharacterInventoryStack(id, charID, req.ItemID, req.Quantity)
	if err != nil {
		log.Printf("add character inventory stack: %v", err)
		badRequest(w, "failed to add inventory item")
		return
	}

	writeJSON(w, http.StatusCreated, characterInventoryStackResponse{
		CharacterID:   charID,
		ItemID:        req.ItemID,
		Quantity:      req.Quantity,
		TotalQuantity: total,
	})
}

func getCharacterInventoryItemsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get character inventory: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	items, err := dbGetCharacterInventoryStacks(id, charID)
	if err != nil {
		log.Printf("get character inventory stacks: %v", err)
		badRequest(w, "failed to read inventory")
		return
	}

	writeJSON(w, http.StatusOK, characterInventoryResponse{
		CharacterID: charID,
		Items:       items,
	})
}

func removeCharacterInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")
	itemID := r.PathValue("item_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("remove character inventory: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may remove items")
		return
	}

	if !validInventoryItemIDs[itemID] {
		badRequest(w, "invalid item_id")
		return
	}

	var req characterInventoryStackRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Quantity <= 0 {
		badRequest(w, "quantity must be positive")
		return
	}

	total, err := dbRemoveCharacterInventoryStack(id, charID, itemID, req.Quantity)
	if err != nil {
		if err == errInsufficientInventory {
			conflict(w, "insufficient quantity")
			return
		}
		log.Printf("remove character inventory stack: %v", err)
		badRequest(w, "failed to remove inventory item")
		return
	}

	writeJSON(w, http.StatusOK, characterInventoryStackResponse{
		CharacterID:   charID,
		ItemID:        itemID,
		Quantity:      req.Quantity,
		TotalQuantity: total,
	})
}

func equipCharacterItemHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")
	slot := r.PathValue("slot")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("equip character: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may equip items")
		return
	}

	if slot != "armor" && slot != "accessory" {
		badRequest(w, "invalid slot")
		return
	}

	var req struct {
		ItemID string `json:"item_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	if !validInventoryItemIDs[req.ItemID] {
		badRequest(w, "unknown item_id")
		return
	}
	if expected, ok := itemEquipmentSlots[req.ItemID]; !ok || expected != slot {
		badRequest(w, "item does not match slot")
		return
	}

	held, err := dbHasCharacterInventoryItem(id, charID, req.ItemID)
	if err != nil {
		log.Printf("equip check inventory: %v", err)
		badRequest(w, "failed to read inventory")
		return
	}
	if !held {
		badRequest(w, "item not held in character inventory")
		return
	}

	if err := dbEquipCharacterItem(id, charID, slot, req.ItemID); err != nil {
		log.Printf("equip item: %v", err)
		badRequest(w, "failed to equip item")
		return
	}

	writeJSON(w, http.StatusOK, characterEquipmentSlot{
		CharacterID: charID,
		Slot:        slot,
		ItemID:      req.ItemID,
		Attuned:     false,
	})
}

func getCharacterEquipmentSlotHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")
	slot := r.PathValue("slot")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("get equipment slot: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}

	if slot != "armor" && slot != "accessory" {
		badRequest(w, "invalid slot")
		return
	}

	itemID, attuned, err := dbGetCharacterEquipmentSlot(id, charID, slot)
	if err != nil {
		log.Printf("get equipment slot: %v", err)
		badRequest(w, "failed to read equipment")
		return
	}

	writeJSON(w, http.StatusOK, characterEquipmentSlot{
		CharacterID: charID,
		Slot:        slot,
		ItemID:      itemID,
		Attuned:     attuned,
	})
}

func consumeCharacterInventoryItemHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")
	itemID := r.PathValue("item_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("consume character inventory: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may consume items")
		return
	}

	if !validInventoryItemIDs[itemID] {
		badRequest(w, "invalid item_id")
		return
	}
	if !consumableItemIDs[itemID] {
		badRequest(w, "item is not consumable")
		return
	}

	total, err := dbRemoveCharacterInventoryStack(id, charID, itemID, 1)
	if err != nil {
		if err == errInsufficientInventory {
			conflict(w, "no held stack to consume")
			return
		}
		log.Printf("consume character inventory stack: %v", err)
		badRequest(w, "failed to consume item")
		return
	}

	writeJSON(w, http.StatusOK, consumeItemResponse{
		CharacterID:      charID,
		ItemID:           itemID,
		QuantityConsumed: 1,
		TotalQuantity:    total,
		Effect: consumableEffect{
			Type:       "healing",
			HPRestored: 5,
		},
	})
}

func attuneCharacterItemHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")
	slot := r.PathValue("slot")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("attune character: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the character owner may attune items")
		return
	}

	if slot != "armor" && slot != "accessory" {
		badRequest(w, "invalid slot")
		return
	}

	itemID, attuned, err := dbGetCharacterEquipmentSlot(id, charID, slot)
	if err != nil {
		log.Printf("attune get slot: %v", err)
		badRequest(w, "failed to read equipment")
		return
	}
	if itemID == "" {
		badRequest(w, "slot is empty")
		return
	}
	if !attunableItemIDs[itemID] {
		badRequest(w, "item is not attunable")
		return
	}

	attunedCount, err := dbGetCharacterAttunedCount(id, charID)
	if err != nil {
		log.Printf("attune count: %v", err)
		badRequest(w, "failed to read attunement")
		return
	}
	if attuned || attunedCount >= maxAttunements {
		conflict(w, "already attuned to maximum")
		return
	}

	if err := dbAttuneCharacterSlot(id, charID, slot); err != nil {
		log.Printf("attune slot: %v", err)
		badRequest(w, "failed to attune item")
		return
	}

	writeJSON(w, http.StatusOK, characterAttunementResponse{
		CharacterID:     charID,
		Slot:            slot,
		ItemID:          itemID,
		Attuned:         true,
		AttunementCount: attunedCount + 1,
		MaxAttunements:  maxAttunements,
	})
}

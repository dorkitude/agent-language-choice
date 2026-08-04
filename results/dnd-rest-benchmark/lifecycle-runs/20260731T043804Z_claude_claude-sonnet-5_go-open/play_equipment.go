package main

import (
	"net/http"
	"sync"
)

// playEquipment tracks the item, if any, a character has equipped in a
// given slot.
type playEquipment struct {
	CampaignID  string `json:"-"`
	CharacterID string `json:"-"`
	Slot        string `json:"-"`
	ItemID      string `json:"item_id"`
	Attuned     bool   `json:"attuned"`
}

// equipmentMu guards equipment, the in-memory index mirroring the
// play_equipment table. Keyed by campaign id, then character id, then slot.
var (
	equipmentMu sync.Mutex
	equipment   = map[string]map[string]map[string]*playEquipment{}
)

// equipmentSlots maps every equippable item id to the single slot it may
// occupy.
var equipmentSlots = map[string]string{
	"leather-armor":      "armor",
	"ring-of-protection": "accessory",
	"amulet-of-health":   "accessory",
}

// attunableEquipment is the set of item ids that can be attuned once
// equipped.
var attunableEquipment = map[string]bool{
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

const maxAttunements = 1

func equipmentResponse(charID, slot string, e *playEquipment) map[string]any {
	if e == nil {
		return map[string]any{
			"character_id": charID,
			"slot":         slot,
			"item_id":      "",
			"attuned":      false,
		}
	}
	return map[string]any{
		"character_id": charID,
		"slot":         slot,
		"item_id":      e.ItemID,
		"attuned":      e.Attuned,
	}
}

// equipItemHandler lets a character's owner equip an inventory item into a
// valid slot, provided the item is held and matches the slot.
func equipItemHandler(w http.ResponseWriter, r *http.Request, campaignID, charID, slot string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req struct {
		ItemID string `json:"item_id"`
	}
	if !decodeJSONBody(w, r, &req) {
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
		writeError(w, http.StatusForbidden, "only the character's owner may equip items")
		return
	}

	if slot != "armor" && slot != "accessory" {
		writeError(w, http.StatusBadRequest, "invalid slot")
		return
	}
	legalSlot, known := equipmentSlots[req.ItemID]
	if !known {
		writeError(w, http.StatusBadRequest, "unknown item_id")
		return
	}
	if legalSlot != slot {
		writeError(w, http.StatusBadRequest, "item does not fit that slot")
		return
	}

	inventoryItemsMu.Lock()
	held := inventoryItems[campaignID][charID][req.ItemID]
	inventoryItemsMu.Unlock()
	if held == nil || held.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "item is not held in inventory")
		return
	}

	equipmentMu.Lock()
	defer equipmentMu.Unlock()

	e := &playEquipment{
		CampaignID:  campaignID,
		CharacterID: charID,
		Slot:        slot,
		ItemID:      req.ItemID,
		Attuned:     false,
	}
	if err := saveEquipmentToDB(e); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save equipment")
		return
	}
	if equipment[campaignID] == nil {
		equipment[campaignID] = map[string]map[string]*playEquipment{}
	}
	if equipment[campaignID][charID] == nil {
		equipment[campaignID][charID] = map[string]*playEquipment{}
	}
	equipment[campaignID][charID][slot] = e

	writeJSON(w, http.StatusOK, equipmentResponse(charID, slot, e))
}

// getEquipmentHandler returns the item equipped in a slot. Any campaign
// member may call this.
func getEquipmentHandler(w http.ResponseWriter, r *http.Request, campaignID, charID, slot string) {
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

	if slot != "armor" && slot != "accessory" {
		writeError(w, http.StatusBadRequest, "invalid slot")
		return
	}

	equipmentMu.Lock()
	defer equipmentMu.Unlock()

	writeJSON(w, http.StatusOK, equipmentResponse(charID, slot, equipment[campaignID][charID][slot]))
}

// attuneEquipmentHandler lets a character's owner attune to an equipped
// attunable accessory, subject to the character's single-attunement cap.
func attuneEquipmentHandler(w http.ResponseWriter, r *http.Request, campaignID, charID, slot string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
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
		writeError(w, http.StatusForbidden, "only the character's owner may attune")
		return
	}

	if slot != "armor" && slot != "accessory" {
		writeError(w, http.StatusBadRequest, "invalid slot")
		return
	}

	equipmentMu.Lock()
	defer equipmentMu.Unlock()

	e := equipment[campaignID][charID][slot]
	if e == nil || e.ItemID == "" {
		writeError(w, http.StatusBadRequest, "slot is empty")
		return
	}
	if !attunableEquipment[e.ItemID] {
		writeError(w, http.StatusBadRequest, "item is not attunable")
		return
	}

	attunedCount := 0
	for _, other := range equipment[campaignID][charID] {
		if other.Attuned {
			attunedCount++
		}
	}
	if attunedCount >= maxAttunements {
		writeError(w, http.StatusConflict, "attunement limit reached")
		return
	}

	e.Attuned = true
	if err := saveEquipmentToDB(e); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save attunement")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id":     charID,
		"slot":             slot,
		"item_id":          e.ItemID,
		"attuned":          e.Attuned,
		"attunement_count": attunedCount + 1,
		"max_attunements":  maxAttunements,
	})
}

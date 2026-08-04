package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

const (
	maxAttunements = 1
)

// equipmentItemSlots maps each equippable item to its legal slot.
var equipmentItemSlots = map[string]string{
	"leather-armor":      "armor",
	"ring-of-protection": "accessory",
	"amulet-of-health":   "accessory",
}

// attunableItems is the set of items that can be attuned. Both are accessories.
var attunableItems = map[string]bool{
	"ring-of-protection": true,
	"amulet-of-health":   true,
}

var validEquipmentSlots = map[string]bool{
	"armor":     true,
	"accessory": true,
}

// equipRequest binds the payload for a PUT equipment request.
type equipRequest struct {
	ItemID string `json:"item_id"`
}

// equipResponse is the shape returned for a slot read or equipment PUT.
type equipResponse struct {
	CharacterID string `json:"character_id"`
	Slot        string `json:"slot"`
	ItemID      string `json:"item_id"`
	Attuned     bool   `json:"attuned"`
}

// attuneResponse is the shape returned after a successful attunement.
type attuneResponse struct {
	CharacterID     string `json:"character_id"`
	Slot            string `json:"slot"`
	ItemID          string `json:"item_id"`
	Attuned         bool   `json:"attuned"`
	AttunementCount int    `json:"attunement_count"`
	MaxAttunements  int    `json:"max_attunements"`
}

// equipCharacterHandler equips an item from a character's personal inventory
// into one of their equipment slots. Only the character owner may equip items.
// Invalid slots, unknown item IDs, unheld items, or slot mismatches return 400.
func equipCharacterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	slot := r.PathValue("slot")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("equip member query error: %v", err)
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

	if !validEquipmentSlots[slot] {
		writeError(w, http.StatusBadRequest, "invalid slot")
		return
	}

	var req equipRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ItemID == "" {
		writeError(w, http.StatusBadRequest, "invalid item")
		return
	}

	expectedSlot, known := equipmentItemSlots[req.ItemID]
	if !known {
		writeError(w, http.StatusBadRequest, "invalid item")
		return
	}
	if expectedSlot != slot {
		writeError(w, http.StatusBadRequest, "slot mismatch")
		return
	}

	held, err := queryCharacterInventoryItemQuantity(campaignID, characterID, req.ItemID)
	if err != nil {
		log.Printf("equip held query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if held <= 0 {
		writeError(w, http.StatusBadRequest, "item not held")
		return
	}

	if err := upsertCharacterEquipmentSlot(campaignID, characterID, slot, req.ItemID, false); err != nil {
		log.Printf("equip upsert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, equipResponse{
		CharacterID: characterID,
		Slot:        slot,
		ItemID:      req.ItemID,
		Attuned:     false,
	})
}

// getCharacterEquipmentHandler returns the item currently equipped in a slot.
// Any campaign member may read the slot. Reading an empty but valid slot
// returns an empty item_id.
func getCharacterEquipmentHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	slot := r.PathValue("slot")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	_, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("get equipment member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	if !validEquipmentSlots[slot] {
		writeError(w, http.StatusBadRequest, "invalid slot")
		return
	}

	itemID, attuned, _, err := queryCharacterEquipmentSlot(campaignID, characterID, slot)
	if err != nil {
		log.Printf("get equipment slot query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, equipResponse{
		CharacterID: characterID,
		Slot:        slot,
		ItemID:      itemID,
		Attuned:     attuned,
	})
}

// attuneCharacterHandler attunes an equipped accessory. Only the character
// owner may attune. The slot must hold an attunable item, and the character may
// only have one attuned item at a time.
func attuneCharacterHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")
	slot := r.PathValue("slot")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("attune member query error: %v", err)
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

	if !validEquipmentSlots[slot] {
		writeError(w, http.StatusBadRequest, "invalid slot")
		return
	}

	itemID, attuned, _, err := queryCharacterEquipmentSlot(campaignID, characterID, slot)
	if err != nil {
		log.Printf("attune slot query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if itemID == "" {
		writeError(w, http.StatusBadRequest, "no item equipped")
		return
	}
	if !attunableItems[itemID] {
		writeError(w, http.StatusBadRequest, "item is not attunable")
		return
	}
	if attuned {
		writeError(w, http.StatusConflict, "already attuned")
		return
	}

	count, err := queryCharacterAttunementCount(campaignID, characterID)
	if err != nil {
		log.Printf("attune count query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if count >= maxAttunements {
		writeError(w, http.StatusConflict, "max attunements reached")
		return
	}

	if err := upsertCharacterEquipmentSlot(campaignID, characterID, slot, itemID, true); err != nil {
		log.Printf("attune upsert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, attuneResponse{
		CharacterID:     characterID,
		Slot:            slot,
		ItemID:          itemID,
		Attuned:         true,
		AttunementCount: 1,
		MaxAttunements:  maxAttunements,
	})
}

// upsertCharacterEquipmentSlot inserts or replaces the equipped item in a
// slot. The caller must hold dbMu.
func upsertCharacterEquipmentSlot(campaignID, characterID, slot, itemID string, attuned bool) error {
	att := 0
	if attuned {
		att = 1
	}
	sql := fmt.Sprintf(
		"INSERT INTO character_equipment_slots (campaign_id, character_id, slot, item_id, attuned) VALUES (%s, %s, %s, %s, %d) ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id=excluded.item_id, attuned=excluded.attuned;",
		sq(campaignID), sq(characterID), sq(slot), sq(itemID), att)
	return dbExec(sql)
}

// queryCharacterEquipmentSlot returns the equipped item and attunement state for
// a single slot. The bool result indicates whether a row exists.
func queryCharacterEquipmentSlot(campaignID, characterID, slot string) (string, bool, bool, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT item_id, attuned FROM character_equipment_slots WHERE campaign_id=%s AND character_id=%s AND slot=%s LIMIT 1;",
		sq(campaignID), sq(characterID), sq(slot)))
	if err != nil {
		return "", false, false, err
	}
	var rows []struct {
		ItemID  string `json:"item_id"`
		Attuned int    `json:"attuned"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return "", false, false, err
	}
	if len(rows) == 0 {
		return "", false, false, nil
	}
	return rows[0].ItemID, rows[0].Attuned != 0, true, nil
}

// queryCharacterAttunementCount returns the number of attuned items a character
// currently has across all slots.
func queryCharacterAttunementCount(campaignID, characterID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf(
		"SELECT COALESCE(SUM(attuned), 0) AS cnt FROM character_equipment_slots WHERE campaign_id=%s AND character_id=%s;",
		sq(campaignID), sq(characterID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		Cnt int `json:"cnt"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 0, nil
	}
	return rows[0].Cnt, nil
}

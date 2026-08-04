package main

import (
	"encoding/json"
	"net/http"
)

// Campaign inventory and per-character equipment assignment.
//
// A campaign owns an append-only list of inventory stacks (item slug, quantity,
// owner) and an append-only list of equipment assignments (character, item
// slug, quantity). Nothing is ever removed, matching the rest of the campaign
// model, so the summary is a pure function of the two lists:
//
//	party_items    = number of inventory entries
//	assigned_items = number of equipment assignments
//	available(slug) = added quantity - assigned quantity
//
// Availability is derived rather than stored so a reload from SQLite can never
// disagree with the lists it was computed from.
//
// Both lists live under campaigns.mu and are mirrored by flush(), like rosters,
// events, quests, factions, and NPCs.

// healingPotionSlug is the item the summary reports availability for.
const healingPotionSlug = "healing-potion"

// defaultInventoryOwner is used when a stack does not name an owner.
const defaultInventoryOwner = "party"

type inventoryItem struct {
	ItemSlug string `json:"item_slug"`
	Quantity int    `json:"quantity"`
	Owner    string `json:"owner"`
}

type equipmentAssignment struct {
	CharacterID string `json:"character_id"`
	ItemSlug    string `json:"item_slug"`
	Quantity    int    `json:"quantity"`
}

// available reports how many of slug remain unassigned. Callers must hold
// campaigns.mu.
func available(c *campaign, slug string) int {
	total := 0
	for _, it := range c.Inventory {
		if it.ItemSlug == slug {
			total += it.Quantity
		}
	}
	for _, e := range c.Equipment {
		if e.ItemSlug == slug {
			total -= e.Quantity
		}
	}
	return total
}

// ---------- request / response payloads ----------

type inventoryRequest struct {
	ItemSlug *string          `json:"item_slug"`
	Quantity *json.RawMessage `json:"quantity"`
	Owner    *string          `json:"owner"`
}

type equipmentRequest struct {
	ItemSlug *string          `json:"item_slug"`
	Quantity *json.RawMessage `json:"quantity"`
}

type inventorySummaryResponse struct {
	CampaignID              string `json:"campaign_id"`
	PartyItems              int    `json:"party_items"`
	AssignedItems           int    `json:"assigned_items"`
	HealingPotionsAvailable int    `json:"healing_potions_available"`
}

// quantityField reads an optional positive-integer quantity, defaulting to 1
// when the field is absent. A present value must be a real integer of at least
// one, so `null`, "3", and 0 are all rejected.
func quantityField(raw *json.RawMessage) (int, bool) {
	if raw == nil {
		return 1, true
	}
	n, ok := asInt(raw)
	if !ok || n < 1 {
		return 0, false
	}
	return n, true
}

// ---------- POST /v1/campaigns/{id}/inventory ----------

func handleAddInventoryItem(w http.ResponseWriter, r *http.Request) {
	var req inventoryRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	slug, ok := requiredString(req.ItemSlug)
	if !ok {
		writeError(w, http.StatusBadRequest, "item_slug is required")
		return
	}
	quantity, ok := quantityField(req.Quantity)
	if !ok {
		writeError(w, http.StatusBadRequest, "quantity must be a positive integer")
		return
	}
	owner := defaultInventoryOwner
	if req.Owner != nil {
		s, ok := requiredString(req.Owner)
		if !ok {
			writeError(w, http.StatusBadRequest, "owner must not be blank")
			return
		}
		owner = s
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	entry := &inventoryItem{ItemSlug: slug, Quantity: quantity, Owner: owner}
	c.Inventory = append(c.Inventory, entry)
	resp := *entry
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, resp)
}

// ---------- POST /v1/campaigns/{id}/characters/{character_id}/equipment ----------

// handleAssignEquipment records an assignment of campaign stock to a character.
// Assignments are a ledger, not a reservation: the stock is not required to
// cover the request, so availability may go negative and later stock additions
// bring it back up.
func handleAssignEquipment(w http.ResponseWriter, r *http.Request) {
	var req equipmentRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	slug, ok := requiredString(req.ItemSlug)
	if !ok {
		writeError(w, http.StatusBadRequest, "item_slug is required")
		return
	}
	quantity, ok := quantityField(req.Quantity)
	if !ok {
		writeError(w, http.StatusBadRequest, "quantity must be a positive integer")
		return
	}
	characterID := r.PathValue("character_id")
	if characterID == "" {
		writeError(w, http.StatusBadRequest, "character_id is required")
		return
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	entry := &equipmentAssignment{CharacterID: characterID, ItemSlug: slug, Quantity: quantity}
	c.Equipment = append(c.Equipment, entry)
	resp := *entry
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusOK, resp)
}

// ---------- GET /v1/campaigns/{id}/inventory/summary ----------

func handleInventorySummary(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	writeJSON(w, http.StatusOK, inventorySummaryResponse{
		CampaignID:              c.ID,
		PartyItems:              len(c.Inventory),
		AssignedItems:           len(c.Equipment),
		HealingPotionsAvailable: available(c, healingPotionSlug),
	})
}

// ---------- persistence helpers ----------

// inventoryFromRow / equipmentFromRow rebuild a list member from a storage row,
// returning the owning campaign id. Rows missing their identifying columns are
// rejected so a corrupt file cannot introduce anonymous stock.

func inventoryFromRow(row []any) (campaignID string, it *inventoryItem, ok bool) {
	if len(row) < 5 {
		return "", nil, false
	}
	campaignID, _ = row[0].(string)
	slug, _ := row[1].(string)
	quantity, _ := row[2].(int64)
	owner, _ := row[3].(string)
	if campaignID == "" || slug == "" {
		return "", nil, false
	}
	if owner == "" {
		owner = defaultInventoryOwner
	}
	return campaignID, &inventoryItem{ItemSlug: slug, Quantity: int(quantity), Owner: owner}, true
}

func equipmentFromRow(row []any) (campaignID string, e *equipmentAssignment, ok bool) {
	if len(row) < 5 {
		return "", nil, false
	}
	campaignID, _ = row[0].(string)
	characterID, _ := row[1].(string)
	slug, _ := row[2].(string)
	quantity, _ := row[3].(int64)
	if campaignID == "" || characterID == "" || slug == "" {
		return "", nil, false
	}
	return campaignID, &equipmentAssignment{
		CharacterID: characterID,
		ItemSlug:    slug,
		Quantity:    int(quantity),
	}, true
}

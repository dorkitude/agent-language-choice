package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createLootHandler creates a campaign-scoped open loot record. Only the
// campaign DM may create loot, and the item_id must be a known catalog item
// with a positive quantity.
func createLootHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create loot")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create loot")
		return
	}

	var req lootCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.LootID) == "" {
		badRequest(w, "loot_id is required")
		return
	}
	if strings.TrimSpace(req.ItemID) == "" {
		badRequest(w, "item_id is required")
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

	if err := dbCreatePlayLoot(id, req.LootID, req.ItemID, req.Quantity); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "loot_id already exists")
			return
		}
		log.Printf("create play loot: %v", err)
		badRequest(w, "failed to create loot")
		return
	}

	writeJSON(w, http.StatusCreated, lootCreateResponse{
		LootID:   req.LootID,
		ItemID:   req.ItemID,
		Quantity: req.Quantity,
		Status:   lootStatusOpen,
	})
}

// voteLootHandler records a player's immutable vote for a loot recipient. Only
// authenticated campaign players may vote, and the recipient must be a character
// in the same campaign.
func voteLootHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != rolePlayer {
		forbidden(w, "only players may vote")
		return
	}

	id := r.PathValue("id")
	lootID := r.PathValue("loot_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	var req lootVoteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.RecipientCharacterID) == "" {
		badRequest(w, "recipient_character_id is required")
		return
	}

	recipient, err := dbGetPlayMembershipByCharacterID(id, req.RecipientCharacterID)
	if err != nil {
		log.Printf("vote loot recipient: %v", err)
		badRequest(w, "failed to read recipient character")
		return
	}
	if recipient == nil {
		badRequest(w, "recipient character not found")
		return
	}

	votes, err := dbCreatePlayLootVote(id, lootID, u.Username, req.RecipientCharacterID)
	if err != nil {
		if err.Error() == "loot not found" {
			notFound(w, "loot not found")
			return
		}
		if err.Error() == "loot is not open" || err.Error() == "already voted" {
			conflict(w, err.Error())
			return
		}
		log.Printf("create play loot vote: %v", err)
		badRequest(w, "failed to record vote")
		return
	}

	writeJSON(w, http.StatusCreated, lootVoteResponse{
		LootID:               lootID,
		Voter:                u.Username,
		RecipientCharacterID: req.RecipientCharacterID,
		VotesForRecipient:    votes,
	})
}

// assignLootHandler assigns an open loot record to its unambiguous highest-vote
// recipient. Only the campaign DM may assign, and tied or voteless loot is
// rejected without changing the record.
func assignLootHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can assign loot")
		return
	}

	id := r.PathValue("id")
	lootID := r.PathValue("loot_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can assign loot")
		return
	}

	resp, err := dbAssignPlayLoot(id, lootID)
	if err != nil {
		if err.Error() == "tied or no votes" || err.Error() == "already assigned" {
			conflict(w, err.Error())
			return
		}
		log.Printf("assign play loot: %v", err)
		badRequest(w, "failed to assign loot")
		return
	}
	if resp == nil {
		notFound(w, "loot not found")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

// getLootHandler reads a single campaign loot record. It is available to any
// authenticated campaign member.
func getLootHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	lootID := r.PathValue("loot_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	loot, err := dbGetPlayLoot(id, lootID)
	if err != nil {
		log.Printf("get play loot: %v", err)
		badRequest(w, "failed to read loot")
		return
	}
	if loot == nil {
		notFound(w, "loot not found")
		return
	}

	writeJSON(w, http.StatusOK, loot)
}

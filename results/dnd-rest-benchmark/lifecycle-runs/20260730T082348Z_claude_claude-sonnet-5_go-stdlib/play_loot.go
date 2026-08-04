package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playLoot is an immutable campaign-scoped loot record: the dm opens it,
// players vote on a recipient character, and the dm assigns it exactly once.
type playLoot struct {
	LootID   string
	ItemID   string
	Quantity int
	Status   string // "open" or "assigned"

	// Votes maps each voter's username to the recipient character id they
	// voted for. A vote is immutable once cast.
	Votes map[string]string

	// RecipientCharacterID names the character loot was assigned to, once
	// assigned.
	RecipientCharacterID string

	// AssignedVotes records the winning recipient's vote count as of the
	// moment of assignment.
	AssignedVotes int
}

func playLootCreateResponse(l *playLoot) map[string]interface{} {
	return map[string]interface{}{
		"loot_id":  l.LootID,
		"item_id":  l.ItemID,
		"quantity": l.Quantity,
		"status":   l.Status,
	}
}

func playLootFullResponse(l *playLoot) map[string]interface{} {
	votes := playLootVoteCounts(l)
	return map[string]interface{}{
		"loot_id":                l.LootID,
		"item_id":                l.ItemID,
		"quantity":               l.Quantity,
		"status":                 l.Status,
		"recipient_character_id": l.RecipientCharacterID,
		"votes":                  votes,
	}
}

// playLootVoteCounts tallies l's votes by recipient character id.
func playLootVoteCounts(l *playLoot) map[string]int {
	counts := make(map[string]int)
	for _, recipient := range l.Votes {
		counts[recipient]++
	}
	return counts
}

// handlePlayCampaignLootSub routes the "loot" and "loot/..." sub-paths of a
// play campaign. It returns false if rest does not name a loot path, so the
// caller can fall through to its own routing.
func handlePlayCampaignLootSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "loot" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreatePlayLoot(w, r, campaignID)
		return true
	}
	if !strings.HasPrefix(rest, "loot/") {
		return false
	}
	lootRest := strings.TrimPrefix(rest, "loot/")

	if lootID, ok := strings.CutSuffix(lootRest, "/votes"); ok && lootID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreatePlayLootVote(w, r, campaignID, lootID)
		return true
	}
	if lootID, ok := strings.CutSuffix(lootRest, "/assign"); ok && lootID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleAssignPlayLoot(w, r, campaignID, lootID)
		return true
	}
	if lootRest == "" || strings.Contains(lootRest, "/") {
		return false
	}
	if r.Method != http.MethodGet {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return true
	}
	handleGetPlayLoot(w, r, campaignID, lootRest)
	return true
}

// handleCreatePlayLoot lets the campaign dm open a new loot record. Only the
// dm may call this; the item must be a known inventory catalog item and
// quantity must be positive. Duplicate loot ids return 409.
func handleCreatePlayLoot(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		LootID   string `json:"loot_id"`
		ItemID   string `json:"item_id"`
		Quantity *int   `json:"quantity"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.LootID == "" || !validInventoryItems[req.ItemID] || req.Quantity == nil || *req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "loot_id and a valid item_id are required, and quantity must be positive")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create loot")
		return
	}
	if c.Loot == nil {
		c.Loot = make(map[string]*playLoot)
	}
	if _, exists := c.Loot[req.LootID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "loot id already exists")
		return
	}

	l := &playLoot{
		LootID:   req.LootID,
		ItemID:   req.ItemID,
		Quantity: *req.Quantity,
		Status:   "open",
	}
	c.Loot[req.LootID] = l
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playLootCreateResponse(l))
}

// handleGetPlayLoot returns a loot record's immutable state. Any
// authenticated campaign member (owner or player) may call this.
func handleGetPlayLoot(w http.ResponseWriter, r *http.Request, campaignID, lootID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view loot")
		return
	}
	l := c.Loot[lootID]
	if l == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}
	resp := playLootFullResponse(l)
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

// handleCreatePlayLootVote lets a campaign player cast a single, immutable
// vote for who should receive a loot record. The dm may not vote. A duplicate
// or changed vote from the same player returns 409.
func handleCreatePlayLootVote(w http.ResponseWriter, r *http.Request, campaignID, lootID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		RecipientCharacterID string `json:"recipient_character_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.RecipientCharacterID == "" {
		writeError(w, http.StatusBadRequest, "recipient_character_id is required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner == username || !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only a campaign player may vote on loot")
		return
	}
	l := c.Loot[lootID]
	if l == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}
	if findPlayMemberByCharacterID(c, req.RecipientCharacterID) == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "recipient_character_id must name a character in this campaign")
		return
	}
	if l.Votes == nil {
		l.Votes = make(map[string]string)
	}
	if _, voted := l.Votes[username]; voted {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "player has already voted on this loot")
		return
	}

	l.Votes[username] = req.RecipientCharacterID
	votesForRecipient := playLootVoteCounts(l)[req.RecipientCharacterID]
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"loot_id":                l.LootID,
		"voter":                  username,
		"recipient_character_id": req.RecipientCharacterID,
		"votes_for_recipient":    votesForRecipient,
	})
}

// handleAssignPlayLoot lets the campaign dm assign an open loot record to its
// unambiguous highest-vote recipient exactly once. Tied or voteless loot
// returns 409, as does a duplicate assignment attempt.
func handleAssignPlayLoot(w http.ResponseWriter, r *http.Request, campaignID, lootID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may assign loot")
		return
	}
	l := c.Loot[lootID]
	if l == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}
	if l.Status != "open" {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "loot is not open")
		return
	}

	counts := playLootVoteCounts(l)
	if len(counts) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "loot has no votes")
		return
	}
	var winner string
	best := 0
	tied := false
	for recipient, n := range counts {
		switch {
		case n > best:
			best = n
			winner = recipient
			tied = false
		case n == best:
			tied = true
		}
	}
	if tied {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "loot vote is tied")
		return
	}

	recipient := findPlayMemberByCharacterID(c, winner)
	if recipient == nil {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "loot recipient is no longer a campaign character")
		return
	}
	if recipient.Items == nil {
		recipient.Items = make(map[string]int)
	}
	recipient.Items[l.ItemID] += l.Quantity

	l.Status = "assigned"
	l.RecipientCharacterID = winner
	l.AssignedVotes = best
	resp := map[string]interface{}{
		"loot_id":                l.LootID,
		"recipient_character_id": l.RecipientCharacterID,
		"item_id":                l.ItemID,
		"quantity":               l.Quantity,
		"votes":                  l.AssignedVotes,
		"status":                 l.Status,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

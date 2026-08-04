package main

import (
	"net/http"
	"sync"
)

// playLoot is an immutable-once-created campaign loot record. Its Status
// starts "open" and transitions exactly once to "assigned".
type playLoot struct {
	CampaignID           string `json:"-"`
	LootID               string `json:"loot_id"`
	ItemID               string `json:"item_id"`
	Quantity             int    `json:"quantity"`
	Status               string `json:"status"`
	RecipientCharacterID string `json:"recipient_character_id"`
	Votes                int    `json:"votes"`
}

// campaignLootMu guards campaignLoot, the in-memory index mirroring the
// play_loot table. Keyed by campaign id, then loot id.
var (
	campaignLootMu sync.Mutex
	campaignLoot   = map[string]map[string]*playLoot{}
)

// playLootVote is a single player's immutable vote for who should receive a
// loot record.
type playLootVote struct {
	CampaignID           string `json:"-"`
	LootID               string `json:"-"`
	Voter                string `json:"-"`
	RecipientCharacterID string `json:"-"`
}

// lootVotesMu guards lootVotes, the in-memory index mirroring the
// play_loot_votes table. Keyed by campaign id, then loot id, then voter
// username.
var (
	lootVotesMu sync.Mutex
	lootVotes   = map[string]map[string]map[string]*playLootVote{}
)

type createLootRequest struct {
	LootID   string `json:"loot_id"`
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

// createLootHandler lets the campaign's owning dm open a new loot record for
// a known inventory catalog item.
func createLootHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createLootRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.LootID == "" {
		writeError(w, http.StatusBadRequest, "loot_id is required")
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

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may create loot")
		return
	}

	campaignLootMu.Lock()
	defer campaignLootMu.Unlock()

	if campaignLoot[campaignID] != nil {
		if _, exists := campaignLoot[campaignID][req.LootID]; exists {
			writeError(w, http.StatusConflict, "loot_id already exists")
			return
		}
	}

	rec := &playLoot{
		CampaignID: campaignID,
		LootID:     req.LootID,
		ItemID:     req.ItemID,
		Quantity:   req.Quantity,
		Status:     "open",
	}
	if err := saveLootToDB(rec); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save loot")
		return
	}
	if campaignLoot[campaignID] == nil {
		campaignLoot[campaignID] = map[string]*playLoot{}
	}
	campaignLoot[campaignID][req.LootID] = rec

	writeJSON(w, http.StatusCreated, map[string]any{
		"loot_id":  rec.LootID,
		"item_id":  rec.ItemID,
		"quantity": rec.Quantity,
		"status":   rec.Status,
	})
}

type createLootVoteRequest struct {
	RecipientCharacterID string `json:"recipient_character_id"`
}

// voteLootHandler lets an authenticated campaign player cast a single
// immutable vote for who should receive an open loot record.
func voteLootHandler(w http.ResponseWriter, r *http.Request, campaignID, lootID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createLootVoteRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}
	if !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "only campaign players may vote on loot")
		return
	}

	playMembersMu.Lock()
	_, recipientExists := findMemberByCharacterID(campaignID, req.RecipientCharacterID)
	playMembersMu.Unlock()
	if !recipientExists {
		writeError(w, http.StatusBadRequest, "unknown recipient character")
		return
	}

	campaignLootMu.Lock()
	defer campaignLootMu.Unlock()

	rec, exists := campaignLoot[campaignID][lootID]
	if !exists {
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}
	if rec.Status != "open" {
		writeError(w, http.StatusConflict, "loot is not open")
		return
	}

	lootVotesMu.Lock()
	defer lootVotesMu.Unlock()

	if lootVotes[campaignID] == nil {
		lootVotes[campaignID] = map[string]map[string]*playLootVote{}
	}
	if lootVotes[campaignID][lootID] == nil {
		lootVotes[campaignID][lootID] = map[string]*playLootVote{}
	}
	if _, voted := lootVotes[campaignID][lootID][actor.Username]; voted {
		writeError(w, http.StatusConflict, "you have already voted on this loot")
		return
	}

	v := &playLootVote{
		CampaignID:           campaignID,
		LootID:               lootID,
		Voter:                actor.Username,
		RecipientCharacterID: req.RecipientCharacterID,
	}
	if err := saveLootVoteToDB(v); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save vote")
		return
	}
	lootVotes[campaignID][lootID][actor.Username] = v

	votesForRecipient := 0
	for _, ov := range lootVotes[campaignID][lootID] {
		if ov.RecipientCharacterID == req.RecipientCharacterID {
			votesForRecipient++
		}
	}

	writeJSON(w, http.StatusCreated, map[string]any{
		"loot_id":                lootID,
		"voter":                  actor.Username,
		"recipient_character_id": req.RecipientCharacterID,
		"votes_for_recipient":    votesForRecipient,
	})
}

// assignLootHandler lets the campaign's owning dm assign an open loot record
// to its single unambiguous highest-vote recipient, atomically crediting
// that character's inventory and closing the record.
func assignLootHandler(w http.ResponseWriter, r *http.Request, campaignID, lootID string) {
	if !requireMethod(w, r, http.MethodPost) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the owning dm may assign loot")
		return
	}

	campaignLootMu.Lock()
	defer campaignLootMu.Unlock()

	rec, exists := campaignLoot[campaignID][lootID]
	if !exists {
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}
	if rec.Status != "open" {
		writeError(w, http.StatusConflict, "loot is not open")
		return
	}

	lootVotesMu.Lock()
	tally := map[string]int{}
	for _, v := range lootVotes[campaignID][lootID] {
		tally[v.RecipientCharacterID]++
	}
	lootVotesMu.Unlock()

	if len(tally) == 0 {
		writeError(w, http.StatusConflict, "loot has no votes")
		return
	}

	winner := ""
	winnerCount := 0
	tied := false
	for charID, count := range tally {
		switch {
		case count > winnerCount:
			winner = charID
			winnerCount = count
			tied = false
		case count == winnerCount:
			tied = true
		}
	}
	if tied {
		writeError(w, http.StatusConflict, "loot has a tied vote and no unambiguous recipient")
		return
	}

	inventoryItemsMu.Lock()
	defer inventoryItemsMu.Unlock()

	if inventoryItems[campaignID] == nil {
		inventoryItems[campaignID] = map[string]map[string]*playInventoryItem{}
	}
	if inventoryItems[campaignID][winner] == nil {
		inventoryItems[campaignID][winner] = map[string]*playInventoryItem{}
	}
	item, exists := inventoryItems[campaignID][winner][rec.ItemID]
	if !exists {
		item = &playInventoryItem{CampaignID: campaignID, CharacterID: winner, ItemID: rec.ItemID, Quantity: 0}
		inventoryItems[campaignID][winner][rec.ItemID] = item
	}
	item.Quantity += rec.Quantity
	if err := saveInventoryItemToDB(item); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save inventory item")
		return
	}

	rec.Status = "assigned"
	rec.RecipientCharacterID = winner
	rec.Votes = winnerCount
	if err := saveLootToDB(rec); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save loot")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"loot_id":                rec.LootID,
		"recipient_character_id": rec.RecipientCharacterID,
		"item_id":                rec.ItemID,
		"quantity":               rec.Quantity,
		"votes":                  rec.Votes,
		"status":                 rec.Status,
	})
}

// getLootHandler returns an immutable loot record's current state. Any
// authenticated campaign member (owner or player) may call this.
func getLootHandler(w http.ResponseWriter, r *http.Request, campaignID, lootID string) {
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

	campaignLootMu.Lock()
	defer campaignLootMu.Unlock()

	rec, exists := campaignLoot[campaignID][lootID]
	if !exists {
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}

	lootVotesMu.Lock()
	votes := map[string]int{}
	for _, v := range lootVotes[campaignID][lootID] {
		votes[v.RecipientCharacterID]++
	}
	lootVotesMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]any{
		"loot_id":                rec.LootID,
		"item_id":                rec.ItemID,
		"quantity":               rec.Quantity,
		"status":                 rec.Status,
		"recipient_character_id": rec.RecipientCharacterID,
		"votes":                  votes,
	})
}

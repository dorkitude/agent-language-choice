package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// lootRecord is the durable campaign-scoped loot record.
type lootRecord struct {
	LootID               string `json:"loot_id"`
	ItemID               string `json:"item_id"`
	Quantity             int    `json:"quantity"`
	Status               string `json:"status"`
	RecipientCharacterID string `json:"recipient_character_id,omitempty"`
}

// createLootRequest binds the payload for creating a new loot record.
type createLootRequest struct {
	LootID   string `json:"loot_id"`
	ItemID   string `json:"item_id"`
	Quantity int    `json:"quantity"`
}

// voteRequest binds the payload for casting a loot vote.
type voteRequest struct {
	RecipientCharacterID string `json:"recipient_character_id"`
}

// voteResponse is the shape returned after a successful loot vote.
type voteResponse struct {
	LootID               string `json:"loot_id"`
	Voter                string `json:"voter"`
	RecipientCharacterID string `json:"recipient_character_id"`
	VotesForRecipient    int    `json:"votes_for_recipient"`
}

// assignResponse is the shape returned after successfully assigning loot.
type assignResponse struct {
	LootID               string `json:"loot_id"`
	RecipientCharacterID string `json:"recipient_character_id"`
	ItemID               string `json:"item_id"`
	Quantity             int    `json:"quantity"`
	Votes                int    `json:"votes"`
	Status               string `json:"status"`
}

// lootGetResponse is the shape returned when reading a loot record.
type lootGetResponse struct {
	LootID               string         `json:"loot_id"`
	ItemID               string         `json:"item_id"`
	Quantity             int            `json:"quantity"`
	Status               string         `json:"status"`
	RecipientCharacterID string         `json:"recipient_character_id,omitempty"`
	Votes                map[string]int `json:"votes"`
}

// queryLoot loads a single loot record by campaign and loot id. The caller
// must hold dbMu.
func queryLoot(campaignID, lootID string) (*lootRecord, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT campaign_id, loot_id, item_id, quantity, status, recipient_character_id FROM campaign_loot WHERE campaign_id=%s AND loot_id=%s LIMIT 1;", sq(campaignID), sq(lootID)))
	if err != nil {
		return nil, false, err
	}
	var rows []lootRecord
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// queryLootVoteCounts returns a map from recipient character id to the number
// of votes cast for that recipient on the given loot record. The caller must
// hold dbMu.
func queryLootVoteCounts(campaignID, lootID string) (map[string]int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT recipient_character_id, COUNT(*) AS votes FROM campaign_loot_votes WHERE campaign_id=%s AND loot_id=%s GROUP BY recipient_character_id;", sq(campaignID), sq(lootID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		RecipientCharacterID string `json:"recipient_character_id"`
		Votes                int    `json:"votes"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	counts := make(map[string]int)
	for _, row := range rows {
		counts[row.RecipientCharacterID] = row.Votes
	}
	return counts, nil
}

// playerHasVotedForLoot reports whether the given player has already cast a
// vote on the given loot record. The caller must hold dbMu.
func playerHasVotedForLoot(campaignID, lootID, voter string) (bool, error) {
	return queryExists(fmt.Sprintf("SELECT 1 FROM campaign_loot_votes WHERE campaign_id=%s AND loot_id=%s AND voter=%s LIMIT 1;", sq(campaignID), sq(lootID), sq(voter)))
}

// requireCampaignPlayer authenticates a player and ensures they are a member
// of the given campaign. On failure it writes a response and returns false.
func requireCampaignPlayer(w http.ResponseWriter, r *http.Request, campaignID string) (string, bool) {
	username, ok := requirePlayer(w, r)
	if !ok {
		return "", false
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("campaign player query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return "", false
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("campaign player members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return "", false
	}
	for _, m := range members {
		if m.Username == username {
			return username, true
		}
	}

	// If the player is also the campaign owner (DM), they are not a player
	// member for loot-voting purposes.
	if campaign.Owner == username {
		writeError(w, http.StatusForbidden, "forbidden")
		return "", false
	}
	writeError(w, http.StatusForbidden, "forbidden")
	return "", false
}

// createLootHandler lets the campaign DM create an open loot record. Only the
// campaign owner may call it, and the item must be a known inventory catalog
// item with a positive quantity. Duplicate loot ids within the campaign are
// rejected with 409.
func createLootHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createLootRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.LootID == "" || req.ItemID == "" || req.Quantity <= 0 {
		writeError(w, http.StatusBadRequest, "invalid loot")
		return
	}
	if !validInventoryItemIDs[req.ItemID] {
		writeError(w, http.StatusBadRequest, "invalid item")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_loot WHERE campaign_id=%s AND loot_id=%s LIMIT 1;", sq(campaignID), sq(req.LootID)))
	if err != nil {
		log.Printf("loot exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "loot already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (%s, %s, %s, %d, 'open');",
		sq(campaignID), sq(req.LootID), sq(req.ItemID), req.Quantity)); err != nil {
		log.Printf("loot insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, lootRecord{
		LootID:   req.LootID,
		ItemID:   req.ItemID,
		Quantity: req.Quantity,
		Status:   "open",
	})
}

// voteLootHandler lets an authenticated campaign player cast a single
// immutable vote for a recipient character on an open loot record. Unknown
// recipients return 400; duplicate or changed votes return 409.
func voteLootHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	lootID := r.PathValue("loot_id")

	username, ok := requireCampaignPlayer(w, r, campaignID)
	if !ok {
		return
	}

	loot, ok, err := queryLoot(campaignID, lootID)
	if err != nil {
		log.Printf("vote loot query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}
	if loot.Status != "open" {
		writeError(w, http.StatusConflict, "loot is not open")
		return
	}

	var req voteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.RecipientCharacterID == "" {
		writeError(w, http.StatusBadRequest, "invalid recipient")
		return
	}

	if _, ok, err := queryPlayCampaignMember(campaignID, req.RecipientCharacterID); err != nil {
		log.Printf("vote recipient query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusBadRequest, "character not found")
		return
	}

	alreadyVoted, err := playerHasVotedForLoot(campaignID, lootID, username)
	if err != nil {
		log.Printf("vote check query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if alreadyVoted {
		writeError(w, http.StatusConflict, "vote already cast")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (%s, %s, %s, %s);",
		sq(campaignID), sq(lootID), sq(username), sq(req.RecipientCharacterID))); err != nil {
		log.Printf("vote insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	votesForRecipient, err := queryLootVotesForRecipient(campaignID, lootID, req.RecipientCharacterID)
	if err != nil {
		log.Printf("vote count query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, voteResponse{
		LootID:               lootID,
		Voter:                username,
		RecipientCharacterID: req.RecipientCharacterID,
		VotesForRecipient:    votesForRecipient,
	})
}

// queryLootVotesForRecipient returns the number of votes for a specific
// recipient on a loot record. The caller must hold dbMu.
func queryLootVotesForRecipient(campaignID, lootID, recipient string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COUNT(*) AS votes FROM campaign_loot_votes WHERE campaign_id=%s AND loot_id=%s AND recipient_character_id=%s;", sq(campaignID), sq(lootID), sq(recipient)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		Votes int `json:"votes"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 0, nil
	}
	return rows[0].Votes, nil
}

// assignLootHandler lets the campaign DM assign an open loot record to the
// single unambiguous highest vote recipient. Tied or voteless loot returns 409.
// A valid assignment atomically adds the loot quantity to the recipient's
// personal inventory and closes the loot.
func assignLootHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	lootID := r.PathValue("loot_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	loot, ok, err := queryLoot(campaignID, lootID)
	if err != nil {
		log.Printf("assign loot query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}
	if loot.Status != "open" {
		writeError(w, http.StatusConflict, "loot already assigned")
		return
	}

	counts, err := queryLootVoteCounts(campaignID, lootID)
	if err != nil {
		log.Printf("assign vote counts query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	winner := ""
	winnerVotes := 0
	tied := false
	for recipient, votes := range counts {
		if votes > winnerVotes {
			winner = recipient
			winnerVotes = votes
			tied = false
		} else if votes == winnerVotes && votes > 0 {
			tied = true
		}
	}

	if winnerVotes == 0 || tied {
		writeError(w, http.StatusConflict, "loot votes are tied or missing")
		return
	}

	if _, ok, err := queryPlayCampaignMember(campaignID, winner); err != nil {
		log.Printf("assign winner query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	} else if !ok {
		writeError(w, http.StatusNotFound, "recipient not found")
		return
	}

	txSQL := fmt.Sprintf("BEGIN; INSERT INTO character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (%s, %s, %s, %d) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity; UPDATE campaign_loot SET status='assigned', recipient_character_id=%s WHERE campaign_id=%s AND loot_id=%s; COMMIT;",
		sq(campaignID), sq(winner), sq(loot.ItemID), loot.Quantity, sq(winner), sq(campaignID), sq(lootID))
	if err := dbExec(txSQL); err != nil {
		log.Printf("assign transaction error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, assignResponse{
		LootID:               lootID,
		RecipientCharacterID: winner,
		ItemID:               loot.ItemID,
		Quantity:             loot.Quantity,
		Votes:                winnerVotes,
		Status:               "assigned",
	})
}

// getLootHandler returns a loot record, including its current vote tally, to
// any authenticated campaign member.
func getLootHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	lootID := r.PathValue("loot_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	loot, ok, err := queryLoot(campaignID, lootID)
	if err != nil {
		log.Printf("get loot query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "loot not found")
		return
	}

	counts, err := queryLootVoteCounts(campaignID, lootID)
	if err != nil {
		log.Printf("get loot vote counts query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if counts == nil {
		counts = map[string]int{}
	}

	writeJSON(w, http.StatusOK, lootGetResponse{
		LootID:               loot.LootID,
		ItemID:               loot.ItemID,
		Quantity:             loot.Quantity,
		Status:               loot.Status,
		RecipientCharacterID: loot.RecipientCharacterID,
		Votes:                counts,
	})
}

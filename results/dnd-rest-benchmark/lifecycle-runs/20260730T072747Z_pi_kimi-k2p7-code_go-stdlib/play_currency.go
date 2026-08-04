package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// currencyResponse is the shape returned by the per-character currency query.
type currencyResponse struct {
	CharacterID string `json:"character_id"`
	Gold        int    `json:"gold"`
}

// transferRequest binds the payload for a character-to-character gold transfer.
type transferRequest struct {
	ToCharacterID string `json:"to_character_id"`
	Gold          int    `json:"gold"`
}

// transferResponse is the shape returned after a successful gold transfer.
type transferResponse struct {
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Gold            int    `json:"gold"`
	FromGold        int    `json:"from_gold"`
	ToGold          int    `json:"to_gold"`
	TransferID      int    `json:"transfer_id"`
}

// getCurrencyHandler returns the deterministic gold balance for a campaign
// character. Any campaign owner or member may read it; unknown characters
// return 404.
func getCurrencyHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	if _, ok := requireCampaignOwnerOrMember(w, r, campaignID); !ok {
		return
	}

	member, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("currency query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}

	writeJSON(w, http.StatusOK, currencyResponse{
		CharacterID: characterID,
		Gold:        member.Gold,
	})
}

// transferCurrencyHandler performs an atomic character-to-character gold
// transfer within a campaign. Only the source character's owner may initiate
// a transfer. Unknown or identical destinations and non-positive amounts return
// 400. Insufficient source gold returns 409 without changing either balance.
func transferCurrencyHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	characterID := r.PathValue("character_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	source, ok, err := queryPlayCampaignMember(campaignID, characterID)
	if err != nil {
		log.Printf("transfer source query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if source.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req transferRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Gold <= 0 {
		writeError(w, http.StatusBadRequest, "invalid gold amount")
		return
	}
	if req.ToCharacterID == "" || req.ToCharacterID == characterID {
		writeError(w, http.StatusBadRequest, "invalid destination")
		return
	}

	dest, ok, err := queryPlayCampaignMember(campaignID, req.ToCharacterID)
	if err != nil {
		log.Printf("transfer destination query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusBadRequest, "character not found")
		return
	}
	if dest.CharacterID == characterID {
		writeError(w, http.StatusBadRequest, "invalid destination")
		return
	}

	if source.Gold < req.Gold {
		writeError(w, http.StatusConflict, "insufficient gold")
		return
	}

	fromGold := source.Gold - req.Gold
	toGold := dest.Gold + req.Gold
	transferID, err := nextCurrencyTransferID(campaignID)
	if err != nil {
		log.Printf("transfer next id error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	txSQL := fmt.Sprintf("BEGIN; UPDATE play_campaign_members SET gold=%d WHERE campaign_id=%s AND character_id=%s; UPDATE play_campaign_members SET gold=%d WHERE campaign_id=%s AND character_id=%s; INSERT INTO campaign_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (%s, %d, %s, %s, %d); COMMIT;",
		fromGold, sq(campaignID), sq(characterID),
		toGold, sq(campaignID), sq(req.ToCharacterID),
		sq(campaignID), transferID, sq(characterID), sq(req.ToCharacterID), req.Gold)
	if err := dbExec(txSQL); err != nil {
		log.Printf("transfer update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, transferResponse{
		FromCharacterID: characterID,
		ToCharacterID:   req.ToCharacterID,
		Gold:            req.Gold,
		FromGold:        fromGold,
		ToGold:          toGold,
		TransferID:      transferID,
	})
}

// nextCurrencyTransferID returns the next campaign-local transfer id,
// starting at 1 for each campaign.
func nextCurrencyTransferID(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(transfer_id), 0) + 1 AS next_id FROM campaign_currency_transfers WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextID int `json:"next_id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextID, nil
}

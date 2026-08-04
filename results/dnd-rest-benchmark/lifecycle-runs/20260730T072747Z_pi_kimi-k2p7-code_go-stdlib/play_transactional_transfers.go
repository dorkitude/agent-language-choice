package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// transactionalTransferRequest binds the payload for a campaign-scoped
// transactional currency transfer.
type transactionalTransferRequest struct {
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Amount          int    `json:"amount"`
	SimulateFailure bool   `json:"simulate_failure"`
}

// transactionalTransferResponse is the shape returned after a successful
// transactional transfer. It echoes the source and destination, the amount,
// the resulting balances, and the campaign-local sequence number.
type transactionalTransferResponse struct {
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Amount          int    `json:"amount"`
	FromGold        int    `json:"from_gold"`
	ToGold          int    `json:"to_gold"`
	Sequence        int    `json:"sequence"`
}

// transactionalTransfersListResponse is the shape returned by the read
// endpoint. Transfers are ordered by sequence.
type transactionalTransfersListResponse struct {
	Transfers []transactionalTransferResponse `json:"transfers"`
}

// createTransactionalTransferHandler performs a campaign-scoped atomic gold
// transfer between two party characters. Only the owner of the source character
// may initiate the transfer. Validation failures return 400, insufficient
// balance returns 409, and simulate_failure returns 500 without persisting
// any partial state.
func createTransactionalTransferHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("transactional transfer user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("transactional transfer campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isMember := campaign.Owner == username
	if !isMember {
		out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
		if err != nil {
			log.Printf("transactional transfer member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		var memberRows []struct {
			One int `json:"1"`
		}
		if err := json.Unmarshal(out, &memberRows); err != nil {
			log.Printf("transactional transfer member unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		isMember = len(memberRows) > 0
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req transactionalTransferRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Amount <= 0 {
		writeError(w, http.StatusBadRequest, "invalid amount")
		return
	}
	if req.FromCharacterID == "" {
		writeError(w, http.StatusBadRequest, "character not found")
		return
	}
	if req.ToCharacterID == "" || req.ToCharacterID == req.FromCharacterID {
		writeError(w, http.StatusBadRequest, "invalid destination")
		return
	}

	source, ok, err := queryPlayCampaignMember(campaignID, req.FromCharacterID)
	if err != nil {
		log.Printf("transactional transfer source query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusBadRequest, "character not found")
		return
	}
	if source.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	dest, ok, err := queryPlayCampaignMember(campaignID, req.ToCharacterID)
	if err != nil {
		log.Printf("transactional transfer destination query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusBadRequest, "character not found")
		return
	}
	if dest.CharacterID == req.FromCharacterID {
		writeError(w, http.StatusBadRequest, "invalid destination")
		return
	}

	if source.Gold < req.Amount {
		writeError(w, http.StatusConflict, "insufficient gold")
		return
	}

	if req.SimulateFailure {
		writeError(w, http.StatusInternalServerError, "simulated failure")
		return
	}

	fromGold := source.Gold - req.Amount
	toGold := dest.Gold + req.Amount
	sequence, err := nextTransactionalTransferSequence(campaignID)
	if err != nil {
		log.Printf("transactional transfer next sequence error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	txSQL := fmt.Sprintf("BEGIN; UPDATE play_campaign_members SET gold=%d WHERE campaign_id=%s AND character_id=%s; UPDATE play_campaign_members SET gold=%d WHERE campaign_id=%s AND character_id=%s; INSERT INTO campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (%s, %d, %s, %s, %d, %d, %d); COMMIT;",
		fromGold, sq(campaignID), sq(req.FromCharacterID),
		toGold, sq(campaignID), sq(req.ToCharacterID),
		sq(campaignID), sequence, sq(req.FromCharacterID), sq(req.ToCharacterID), req.Amount, fromGold, toGold)
	if err := dbExec(txSQL); err != nil {
		log.Printf("transactional transfer exec error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, transactionalTransferResponse{
		FromCharacterID: req.FromCharacterID,
		ToCharacterID:   req.ToCharacterID,
		Amount:          req.Amount,
		FromGold:        fromGold,
		ToGold:          toGold,
		Sequence:        sequence,
	})
}

// listTransactionalTransfersHandler returns all successful transactional
// transfers for a campaign. The campaign owner and members may read it;
// failed simulated operations never appear.
func listTransactionalTransfersHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("transactional transfers list user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("transactional transfers list campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isMember := campaign.Owner == username
	if !isMember {
		out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
		if err != nil {
			log.Printf("transactional transfers list member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		var memberRows []struct {
			One int `json:"1"`
		}
		if err := json.Unmarshal(out, &memberRows); err != nil {
			log.Printf("transactional transfers list member unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		isMember = len(memberRows) > 0
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var transfers []transactionalTransferResponse
	if err := queryRows(fmt.Sprintf("SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence FROM campaign_transactional_transfers WHERE campaign_id=%s ORDER BY sequence;", sq(campaignID)), &transfers); err != nil {
		log.Printf("transactional transfers list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if transfers == nil {
		transfers = []transactionalTransferResponse{}
	}

	writeJSON(w, http.StatusOK, transactionalTransfersListResponse{Transfers: transfers})
}

// nextTransactionalTransferSequence returns the next campaign-local transfer
// sequence number, starting at 1 for each campaign.
func nextTransactionalTransferSequence(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM campaign_transactional_transfers WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		NextSeq int `json:"next_seq"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) == 0 {
		return 1, nil
	}
	return rows[0].NextSeq, nil
}

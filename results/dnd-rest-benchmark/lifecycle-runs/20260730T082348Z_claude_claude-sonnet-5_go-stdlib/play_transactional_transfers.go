package main

import (
	"encoding/json"
	"net/http"
)

// playTransactionalTransfer is a successfully committed transactional
// currency transfer record.
type playTransactionalTransfer struct {
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Amount          int    `json:"amount"`
	FromGold        int    `json:"from_gold"`
	ToGold          int    `json:"to_gold"`
	Sequence        int    `json:"sequence"`
}

// handlePlayCampaignTransactionalTransfersSub routes the
// "transactional-transfers" sub-path of a play campaign.
func handlePlayCampaignTransactionalTransfersSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest != "transactional-transfers" {
		return false
	}
	switch r.Method {
	case http.MethodPost:
		handleCreatePlayTransactionalTransfer(w, r, id)
	case http.MethodGet:
		handleListPlayTransactionalTransfers(w, r, id)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
	return true
}

func handleCreatePlayTransactionalTransfer(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		FromCharacterID string `json:"from_character_id"`
		ToCharacterID   string `json:"to_character_id"`
		Amount          *int   `json:"amount"`
		SimulateFailure bool   `json:"simulate_failure"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign member")
		return
	}

	if req.FromCharacterID == "" || req.ToCharacterID == "" || req.FromCharacterID == req.ToCharacterID || req.Amount == nil || *req.Amount <= 0 {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "from_character_id and to_character_id must name different campaign characters and amount must be positive")
		return
	}

	source := findPlayMemberByCharacterID(c, req.FromCharacterID)
	if source == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "from_character_id must name a campaign character")
		return
	}
	dest := findPlayMemberByCharacterID(c, req.ToCharacterID)
	if dest == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "to_character_id must name a campaign character")
		return
	}
	if playMemberOwner(source) != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the source character's owner may transfer gold")
		return
	}
	if source.Gold < *req.Amount {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "insufficient gold for transfer")
		return
	}

	if req.SimulateFailure {
		playMu.Unlock()
		writeJSON(w, http.StatusInternalServerError, map[string]interface{}{"error": "simulated failure"})
		return
	}

	source.Gold -= *req.Amount
	dest.Gold += *req.Amount
	c.TransactionalTransferSeq++
	entry := &playTransactionalTransfer{
		FromCharacterID: req.FromCharacterID,
		ToCharacterID:   req.ToCharacterID,
		Amount:          *req.Amount,
		FromGold:        source.Gold,
		ToGold:          dest.Gold,
		Sequence:        c.TransactionalTransferSeq,
	}
	c.TransactionalTransfers = append(c.TransactionalTransfers, entry)
	resp := map[string]interface{}{
		"from_character_id": entry.FromCharacterID,
		"to_character_id":   entry.ToCharacterID,
		"amount":            entry.Amount,
		"from_gold":         entry.FromGold,
		"to_gold":           entry.ToGold,
		"sequence":          entry.Sequence,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleListPlayTransactionalTransfers(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "must be a campaign dm or member")
		return
	}

	transfers := make([]map[string]interface{}, 0, len(c.TransactionalTransfers))
	for _, t := range c.TransactionalTransfers {
		transfers = append(transfers, map[string]interface{}{
			"from_character_id": t.FromCharacterID,
			"to_character_id":   t.ToCharacterID,
			"amount":            t.Amount,
			"from_gold":         t.FromGold,
			"to_gold":           t.ToGold,
			"sequence":          t.Sequence,
		})
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"transfers": transfers})
}

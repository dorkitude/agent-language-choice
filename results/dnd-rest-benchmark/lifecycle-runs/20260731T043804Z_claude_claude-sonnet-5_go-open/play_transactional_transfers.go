package main

import (
	"net/http"
	"sync"
)

// transactionalTransfer records one completed transactional gold transfer
// between two characters in the same campaign.
type transactionalTransfer struct {
	CampaignID      string `json:"-"`
	Sequence        int    `json:"-"`
	FromCharacterID string `json:"-"`
	ToCharacterID   string `json:"-"`
	Amount          int    `json:"-"`
	FromGold        int    `json:"-"`
	ToGold          int    `json:"-"`
}

// transactionalTransfersMu guards transactionalTransfers, the in-memory index
// mirroring the play_transactional_transfers table. Keyed by campaign id,
// ordered by sequence.
var (
	transactionalTransfersMu sync.Mutex
	transactionalTransfers   = map[string][]*transactionalTransfer{}
)

func transactionalTransferJSON(t *transactionalTransfer) map[string]any {
	return map[string]any{
		"from_character_id": t.FromCharacterID,
		"to_character_id":   t.ToCharacterID,
		"amount":            t.Amount,
		"from_gold":         t.FromGold,
		"to_gold":           t.ToGold,
		"sequence":          t.Sequence,
	}
}

type createTransactionalTransferRequest struct {
	FromCharacterID string `json:"from_character_id"`
	ToCharacterID   string `json:"to_character_id"`
	Amount          int    `json:"amount"`
	SimulateFailure bool   `json:"simulate_failure"`
}

// createTransactionalTransferHandler lets a character's owner move gold to a
// different character in the same campaign. The debit, credit, and success
// record are applied together; when simulate_failure is set the request is
// fully validated and prepared but the response is a 500 with no mutation.
func createTransactionalTransferHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createTransactionalTransferRequest
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

	fromMember, exists := findMemberByCharacterID(campaignID, req.FromCharacterID)
	if !exists {
		writeError(w, http.StatusBadRequest, "unknown source character")
		return
	}
	if actor.Username != playMemberOwner(fromMember) {
		writeError(w, http.StatusForbidden, "only the source character's owner may create this transfer")
		return
	}
	if req.ToCharacterID == req.FromCharacterID {
		writeError(w, http.StatusBadRequest, "cannot transfer gold to the same character")
		return
	}
	if _, exists := findMemberByCharacterID(campaignID, req.ToCharacterID); !exists {
		writeError(w, http.StatusBadRequest, "unknown destination character")
		return
	}
	if req.Amount <= 0 {
		writeError(w, http.StatusBadRequest, "amount must be a positive integer")
		return
	}

	currencyMu.Lock()
	defer currencyMu.Unlock()

	fromCur, err := getOrInitCurrency(campaignID, req.FromCharacterID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load currency")
		return
	}
	toCur, err := getOrInitCurrency(campaignID, req.ToCharacterID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load currency")
		return
	}

	if fromCur.Gold < req.Amount {
		writeError(w, http.StatusConflict, "insufficient gold")
		return
	}

	if req.SimulateFailure {
		writeError(w, http.StatusInternalServerError, "simulated failure")
		return
	}

	transactionalTransfersMu.Lock()
	defer transactionalTransfersMu.Unlock()

	newFromGold := fromCur.Gold - req.Amount
	newToGold := toCur.Gold + req.Amount
	sequence := len(transactionalTransfers[campaignID]) + 1

	t := &transactionalTransfer{
		CampaignID:      campaignID,
		Sequence:        sequence,
		FromCharacterID: req.FromCharacterID,
		ToCharacterID:   req.ToCharacterID,
		Amount:          req.Amount,
		FromGold:        newFromGold,
		ToGold:          newToGold,
	}

	if err := saveTransactionalTransferToDB(t); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save transfer")
		return
	}

	fromCur.Gold = newFromGold
	toCur.Gold = newToGold
	if err := saveCurrencyToDB(fromCur); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save currency")
		return
	}
	if err := saveCurrencyToDB(toCur); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save currency")
		return
	}

	transactionalTransfers[campaignID] = append(transactionalTransfers[campaignID], t)

	writeJSON(w, http.StatusCreated, transactionalTransferJSON(t))
}

// listTransactionalTransfersHandler lets the campaign DM and members read
// the campaign's successful transactional transfers in sequence order.
// Simulated failures never appear.
func listTransactionalTransfersHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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

	transactionalTransfersMu.Lock()
	defer transactionalTransfersMu.Unlock()

	list := transactionalTransfers[campaignID]
	transfersOut := make([]map[string]any, 0, len(list))
	for _, t := range list {
		transfersOut = append(transfersOut, transactionalTransferJSON(t))
	}

	writeJSON(w, http.StatusOK, map[string]any{"transfers": transfersOut})
}

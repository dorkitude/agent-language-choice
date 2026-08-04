package main

import (
	"net/http"
	"sync"
)

// startingGold is the gold balance assigned to a character the moment it
// joins a play campaign.
const startingGold = 10

// playCurrency tracks a single character's gold balance within a campaign.
type playCurrency struct {
	CampaignID  string `json:"-"`
	CharacterID string `json:"-"`
	Gold        int    `json:"-"`
}

// currencyMu guards currency, the in-memory index mirroring the
// play_currency table. Keyed by campaign id, then character id.
var (
	currencyMu sync.Mutex
	currency   = map[string]map[string]*playCurrency{}
)

// playTransfer records one completed gold transfer between two characters
// in the same campaign.
type playTransfer struct {
	CampaignID      string `json:"-"`
	TransferID      int    `json:"-"`
	FromCharacterID string `json:"-"`
	ToCharacterID   string `json:"-"`
	Gold            int    `json:"-"`
}

// transfersMu guards transfers, the in-memory index mirroring the
// play_transfers table. Keyed by campaign id, ordered by transfer id.
var (
	transfersMu sync.Mutex
	transfers   = map[string][]*playTransfer{}
)

// initCurrencyForMember gives a newly joined character its starting gold
// balance. Callers must hold currencyMu and have already persisted the
// member itself.
func initCurrencyForMember(campaignID, charID string) error {
	c := &playCurrency{CampaignID: campaignID, CharacterID: charID, Gold: startingGold}
	if currency[campaignID] == nil {
		currency[campaignID] = map[string]*playCurrency{}
	}
	currency[campaignID][charID] = c
	return saveCurrencyToDB(c)
}

// getOrInitCurrency returns charID's currency record within campaignID,
// lazily creating one with the starting balance if it's missing. Callers
// must hold currencyMu.
func getOrInitCurrency(campaignID, charID string) (*playCurrency, error) {
	if currency[campaignID] != nil {
		if c, exists := currency[campaignID][charID]; exists {
			return c, nil
		}
	}
	c := &playCurrency{CampaignID: campaignID, CharacterID: charID, Gold: startingGold}
	if currency[campaignID] == nil {
		currency[campaignID] = map[string]*playCurrency{}
	}
	currency[campaignID][charID] = c
	if err := saveCurrencyToDB(c); err != nil {
		return nil, err
	}
	return c, nil
}

// getCurrencyHandler returns a character's gold balance. Any authenticated
// campaign member (owner or player) may call this.
func getCurrencyHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
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

	playMembersMu.Lock()
	if _, exists := findMemberByCharacterID(campaignID, charID); !exists {
		playMembersMu.Unlock()
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	playMembersMu.Unlock()

	currencyMu.Lock()
	defer currencyMu.Unlock()

	cur, err := getOrInitCurrency(campaignID, charID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load currency")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"character_id": charID,
		"gold":         cur.Gold,
	})
}

type createTransferRequest struct {
	ToCharacterID string `json:"to_character_id"`
	Gold          int    `json:"gold"`
}

// createTransferHandler lets a character's owner move gold to a different
// character in the same campaign, atomically debiting the source and
// crediting the destination.
func createTransferHandler(w http.ResponseWriter, r *http.Request, campaignID, charID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createTransferRequest
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

	fromMember, exists := findMemberByCharacterID(campaignID, charID)
	if !exists {
		writeError(w, http.StatusNotFound, "character not found")
		return
	}
	if actor.Username != playMemberOwner(fromMember) {
		writeError(w, http.StatusForbidden, "only the source character's owner may transfer gold")
		return
	}
	if req.ToCharacterID == charID {
		writeError(w, http.StatusBadRequest, "cannot transfer gold to the same character")
		return
	}
	if _, exists := findMemberByCharacterID(campaignID, req.ToCharacterID); !exists {
		writeError(w, http.StatusBadRequest, "unknown destination character")
		return
	}
	if req.Gold <= 0 {
		writeError(w, http.StatusBadRequest, "gold must be positive")
		return
	}

	currencyMu.Lock()
	defer currencyMu.Unlock()

	fromCur, err := getOrInitCurrency(campaignID, charID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load currency")
		return
	}
	toCur, err := getOrInitCurrency(campaignID, req.ToCharacterID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to load currency")
		return
	}

	if fromCur.Gold < req.Gold {
		writeError(w, http.StatusConflict, "insufficient gold")
		return
	}

	fromCur.Gold -= req.Gold
	toCur.Gold += req.Gold
	if err := saveCurrencyToDB(fromCur); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save currency")
		return
	}
	if err := saveCurrencyToDB(toCur); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save currency")
		return
	}

	transfersMu.Lock()
	defer transfersMu.Unlock()

	transferID := len(transfers[campaignID]) + 1
	t := &playTransfer{
		CampaignID:      campaignID,
		TransferID:      transferID,
		FromCharacterID: charID,
		ToCharacterID:   req.ToCharacterID,
		Gold:            req.Gold,
	}
	if err := saveTransferToDB(t); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save transfer")
		return
	}
	transfers[campaignID] = append(transfers[campaignID], t)

	writeJSON(w, http.StatusCreated, map[string]any{
		"from_character_id": charID,
		"to_character_id":   req.ToCharacterID,
		"gold":              req.Gold,
		"from_gold":         fromCur.Gold,
		"to_gold":           toCur.Gold,
		"transfer_id":       transferID,
	})
}

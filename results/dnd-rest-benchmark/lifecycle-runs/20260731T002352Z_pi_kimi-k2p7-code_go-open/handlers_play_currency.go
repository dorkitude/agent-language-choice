package main

import (
	"database/sql"
	"encoding/json"
	"log"
	"net/http"
)

// getCharacterCurrencyHandler returns the current gold balance for a campaign
// character. It is available to any authenticated member of the campaign and
// returns 404 for unknown characters.
func getCharacterCurrencyHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	gold, err := dbGetCharacterGold(id, charID)
	if err != nil {
		if err == sql.ErrNoRows {
			notFound(w, "character not found")
			return
		}
		log.Printf("get character gold: %v", err)
		badRequest(w, "failed to read character currency")
		return
	}

	writeJSON(w, http.StatusOK, currencyResponse{
		CharacterID: charID,
		Gold:        gold,
	})
}

// transferCharacterGoldHandler moves gold from the source character to another
// character in the same campaign. Only the source character's owner may call
// this endpoint. Unknown destinations, self-transfers, and non-positive
// amounts return 400; insufficient gold returns 409 without changing balances.
func transferCharacterGoldHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	charID := r.PathValue("char_id")

	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	m, err := dbGetPlayMembershipByCharacterID(id, charID)
	if err != nil {
		log.Printf("transfer gold: %v", err)
		badRequest(w, "failed to read character")
		return
	}
	if m == nil {
		notFound(w, "character not found")
		return
	}
	if m.Username != u.Username {
		forbidden(w, "only the source character owner may transfer gold")
		return
	}

	var req goldTransferRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if req.Gold <= 0 {
		badRequest(w, "gold must be positive")
		return
	}
	if req.ToCharacterID == "" {
		badRequest(w, "to_character_id is required")
		return
	}
	if req.ToCharacterID == charID {
		badRequest(w, "cannot transfer gold to the same character")
		return
	}

	dest, err := dbGetPlayMembershipByCharacterID(id, req.ToCharacterID)
	if err != nil {
		log.Printf("transfer gold destination: %v", err)
		badRequest(w, "failed to read destination character")
		return
	}
	if dest == nil {
		badRequest(w, "destination character not found")
		return
	}

	resp, err := dbTransferCharacterGold(id, charID, req.ToCharacterID, req.Gold)
	if err != nil {
		if err == errInsufficientGold {
			conflict(w, "insufficient gold")
			return
		}
		log.Printf("transfer gold: %v", err)
		badRequest(w, "failed to transfer gold")
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

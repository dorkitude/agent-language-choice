package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayClueHandler creates a campaign clue. Only the campaign owner (DM)
// may create clues. Players receive 403. clue_id and text are required nonempty
// strings. audience must be character, party, or hidden. Character clues must
// target an existing campaign member; party and hidden clues must omit
// character_id. Duplicate clue ids within a campaign return 409.
func createPlayClueHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create clues")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create clues")
		return
	}

	var req clueCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ClueID) == "" {
		badRequest(w, "clue_id is required")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		badRequest(w, "text is required")
		return
	}

	switch req.Audience {
	case clueAudienceCharacter:
		if req.CharacterID == nil || strings.TrimSpace(*req.CharacterID) == "" {
			badRequest(w, "character_id is required for character audience")
			return
		}
		m, err := dbGetPlayMembershipByCharacterID(id, *req.CharacterID)
		if err != nil {
			log.Printf("check clue character: %v", err)
			badRequest(w, "failed to validate character")
			return
		}
		if m == nil {
			badRequest(w, "character not found")
			return
		}
	case clueAudienceParty, clueAudienceHidden:
		if req.CharacterID != nil {
			badRequest(w, "character_id must be omitted for party or hidden audience")
			return
		}
	default:
		badRequest(w, "audience must be character, party, or hidden")
		return
	}

	if err := dbCreatePlayClue(id, req.ClueID, req.Text, req.Audience, req.CharacterID); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "clue already exists")
			return
		}
		log.Printf("create play clue: %v", err)
		badRequest(w, "failed to create clue")
		return
	}

	resp := clueResponse{
		ClueID:   req.ClueID,
		Text:     req.Text,
		Audience: req.Audience,
	}
	if req.Audience == clueAudienceCharacter && req.CharacterID != nil {
		resp.CharacterID = *req.CharacterID
	}
	writeJSON(w, http.StatusCreated, resp)
}

// getPlayCluesHandler lists campaign clues available to the caller. The DM
// receives all clues in insertion order. A player receives party clues and
// character clues targeted to their own character only.
func getPlayCluesHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	var clues []clueResponse
	var err error
	if p.Owner == u.Username {
		clues, err = dbGetPlayClues(id)
	} else {
		m, err2 := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
		if err2 != nil {
			log.Printf("get membership for clues: %v", err2)
			badRequest(w, "failed to read membership")
			return
		}
		ownCharID := ""
		if m != nil {
			ownCharID = m.CharacterID
		}
		clues, err = dbGetPlayCluesForPlayer(id, ownCharID)
	}
	if err != nil {
		log.Printf("get play clues: %v", err)
		badRequest(w, "failed to read clues")
		return
	}

	writeJSON(w, http.StatusOK, cluesResponse{Clues: clues})
}

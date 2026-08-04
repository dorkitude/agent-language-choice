package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// createClueRequest binds the payload for a new campaign clue.
type createClueRequest struct {
	ClueID      string `json:"clue_id"`
	Text        string `json:"text"`
	Audience    string `json:"audience"`
	CharacterID string `json:"character_id"`
}

// clueResponse is the shape returned when a clue is created or listed.
// Character clues include character_id; party and hidden clues omit it.
type clueResponse struct {
	ClueID      string `json:"clue_id"`
	Text        string `json:"text"`
	Audience    string `json:"audience"`
	CharacterID string `json:"character_id,omitempty"`
}

// clueListResponse is the shape returned by the clue listing endpoint.
type clueListResponse struct {
	Clues []clueResponse `json:"clues"`
}

// createClueHandler lets the campaign DM create a clue. Players receive 403.
// clue_id and text are required nonempty strings, audience must be exactly
// character, party, or hidden, and character clues must target a known
// campaign member character.
func createClueHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createClueRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ClueID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "invalid clue")
		return
	}
	if req.Audience != "character" && req.Audience != "party" && req.Audience != "hidden" {
		writeError(w, http.StatusBadRequest, "invalid audience")
		return
	}

	if req.Audience == "character" {
		if req.CharacterID == "" {
			writeError(w, http.StatusBadRequest, "invalid character_id")
			return
		}
		_, ok, err := queryPlayCampaignMember(campaignID, req.CharacterID)
		if err != nil {
			log.Printf("clue character query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !ok {
			writeError(w, http.StatusBadRequest, "character not found")
			return
		}
	} else {
		if req.CharacterID != "" {
			writeError(w, http.StatusBadRequest, "invalid character_id")
			return
		}
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_clues WHERE campaign_id=%s AND clue_id=%s LIMIT 1;", sq(campaignID), sq(req.ClueID)))
	if err != nil {
		log.Printf("clue duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "clue already exists")
		return
	}

	charID := "NULL"
	if req.CharacterID != "" {
		charID = sq(req.CharacterID)
	}
	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_clues (campaign_id, clue_id, text, audience, character_id) VALUES (%s, %s, %s, %s, %s);",
		sq(campaignID), sq(req.ClueID), sq(req.Text), sq(req.Audience), charID)); err != nil {
		log.Printf("clue insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, clueResponse{
		ClueID:      req.ClueID,
		Text:        req.Text,
		Audience:    req.Audience,
		CharacterID: req.CharacterID,
	})
}

// listCluesHandler returns campaign clues visible to the caller. The DM sees
// all clues in insertion order. A player sees party clues and character clues
// targeted to their own character; hidden clues and clues for other
// characters are omitted.
func listCluesHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("list clues campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	var sql string
	if campaign.Owner == username {
		sql = fmt.Sprintf("SELECT clue_id, text, audience, character_id FROM campaign_clues WHERE campaign_id=%s ORDER BY id;", sq(campaignID))
	} else {
		member, ok, err := queryPlayCampaignMemberByUsername(campaignID, username)
		if err != nil {
			log.Printf("list clues member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !ok {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		sql = fmt.Sprintf("SELECT clue_id, text, audience, character_id FROM campaign_clues WHERE campaign_id=%s AND (audience='party' OR (audience='character' AND character_id=%s)) ORDER BY id;",
			sq(campaignID), sq(member.CharacterID))
	}

	out, err := dbQuery(sql)
	if err != nil {
		log.Printf("list clues query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		ClueID      string  `json:"clue_id"`
		Text        string  `json:"text"`
		Audience    string  `json:"audience"`
		CharacterID *string `json:"character_id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("list clues unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	clues := make([]clueResponse, 0, len(rows))
	for _, row := range rows {
		charID := ""
		if row.CharacterID != nil {
			charID = *row.CharacterID
		}
		clues = append(clues, clueResponse{
			ClueID:      row.ClueID,
			Text:        row.Text,
			Audience:    row.Audience,
			CharacterID: charID,
		})
	}
	if clues == nil {
		clues = []clueResponse{}
	}

	writeJSON(w, http.StatusOK, clueListResponse{Clues: clues})
}

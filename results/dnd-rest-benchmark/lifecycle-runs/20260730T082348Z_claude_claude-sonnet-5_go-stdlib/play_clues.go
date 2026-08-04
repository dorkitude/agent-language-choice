package main

import (
	"encoding/json"
	"net/http"
)

// playClue is a piece of campaign lore the DM may reveal to one character,
// the whole party, or nobody (hidden, for DM record-keeping only).
type playClue struct {
	ClueID      string
	Text        string
	Audience    string
	CharacterID string
}

func playClueResponse(clue *playClue) map[string]interface{} {
	resp := map[string]interface{}{
		"clue_id":  clue.ClueID,
		"text":     clue.Text,
		"audience": clue.Audience,
	}
	if clue.Audience == "character" {
		resp["character_id"] = clue.CharacterID
	}
	return resp
}

// handlePlayCampaignCluesSub routes the "clues" sub-path of a play campaign.
// It returns false if rest does not name the clues path, so the caller can
// fall through to its own routing.
func handlePlayCampaignCluesSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest != "clues" {
		return false
	}
	switch r.Method {
	case http.MethodPost:
		handleCreatePlayClue(w, r, campaignID)
	case http.MethodGet:
		handleListPlayClues(w, r, campaignID)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
	return true
}

// handleCreatePlayClue lets the campaign dm create a new clue targeted to a
// character, the party, or hidden.
func handleCreatePlayClue(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		ClueID      string `json:"clue_id"`
		Text        string `json:"text"`
		Audience    string `json:"audience"`
		CharacterID string `json:"character_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ClueID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "clue_id and text are required")
		return
	}
	switch req.Audience {
	case "character":
		if req.CharacterID == "" {
			writeError(w, http.StatusBadRequest, "character_id is required for character audience")
			return
		}
	case "party", "hidden":
		if req.CharacterID != "" {
			writeError(w, http.StatusBadRequest, "character_id must be omitted for this audience")
			return
		}
	default:
		writeError(w, http.StatusBadRequest, "audience must be character, party, or hidden")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create clues")
		return
	}
	if req.Audience == "character" && findPlayMemberByCharacterID(c, req.CharacterID) == nil {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "unknown character")
		return
	}
	for _, clue := range c.Clues {
		if clue.ClueID == req.ClueID {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "clue_id already exists")
			return
		}
	}

	clue := &playClue{
		ClueID:      req.ClueID,
		Text:        req.Text,
		Audience:    req.Audience,
		CharacterID: req.CharacterID,
	}
	c.Clues = append(c.Clues, clue)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playClueResponse(clue))
}

// handleListPlayClues returns clues visible to the requesting campaign
// member: the dm sees all clues in insertion order, a player sees party
// clues and clues targeted to their own character.
func handleListPlayClues(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "only the owner or a member may view clues")
		return
	}

	isDM := c.Owner == username
	var ownCharacterID string
	if !isDM {
		for _, m := range c.Members {
			if m.Username == username {
				ownCharacterID = m.CharacterID
				break
			}
		}
	}

	clues := make([]map[string]interface{}, 0, len(c.Clues))
	for _, clue := range c.Clues {
		if isDM {
			clues = append(clues, playClueResponse(clue))
			continue
		}
		switch clue.Audience {
		case "party":
			clues = append(clues, playClueResponse(clue))
		case "character":
			if clue.CharacterID == ownCharacterID {
				clues = append(clues, playClueResponse(clue))
			}
		}
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"clues": clues,
	})
}

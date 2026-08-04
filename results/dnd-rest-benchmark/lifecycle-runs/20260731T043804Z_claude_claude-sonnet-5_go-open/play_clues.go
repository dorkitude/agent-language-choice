package main

import (
	"net/http"
	"sync"
)

// playClue is a campaign clue the DM may reveal to a single character, the
// whole party, or nobody (hidden).
type playClue struct {
	CampaignID  string `json:"-"`
	ClueID      string `json:"clue_id"`
	Text        string `json:"text"`
	Audience    string `json:"audience"`
	CharacterID string `json:"character_id,omitempty"`
}

// campaignCluesMu guards campaignClues, the in-memory index mirroring the
// play_clues table. Keyed by campaign id, holding clues in insertion order.
var (
	campaignCluesMu sync.Mutex
	campaignClues   = map[string][]*playClue{}
)

func clueJSON(clue *playClue) map[string]any {
	out := map[string]any{
		"clue_id":  clue.ClueID,
		"text":     clue.Text,
		"audience": clue.Audience,
	}
	if clue.Audience == "character" {
		out["character_id"] = clue.CharacterID
	}
	return out
}

type createClueRequest struct {
	ClueID      string `json:"clue_id"`
	Text        string `json:"text"`
	Audience    string `json:"audience"`
	CharacterID string `json:"character_id"`
}

// createClueHandler lets the campaign's owning dm create a clue targeted at
// a single character, the whole party, or hidden from everyone.
func createClueHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createClueRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may create clues")
		return
	}

	if req.ClueID == "" || req.Text == "" {
		writeError(w, http.StatusBadRequest, "clue_id and text are required nonempty strings")
		return
	}

	switch req.Audience {
	case "character":
		if req.CharacterID == "" {
			writeError(w, http.StatusBadRequest, "character_id is required for character audience")
			return
		}
		playMembersMu.Lock()
		_, exists := findMemberByCharacterID(campaignID, req.CharacterID)
		playMembersMu.Unlock()
		if !exists {
			writeError(w, http.StatusBadRequest, "character_id must name a campaign member character")
			return
		}
	case "party", "hidden":
		if req.CharacterID != "" {
			writeError(w, http.StatusBadRequest, "character_id must be omitted for party and hidden audience")
			return
		}
	default:
		writeError(w, http.StatusBadRequest, "audience must be exactly character, party, or hidden")
		return
	}

	campaignCluesMu.Lock()
	defer campaignCluesMu.Unlock()

	for _, existing := range campaignClues[campaignID] {
		if existing.ClueID == req.ClueID {
			writeError(w, http.StatusConflict, "clue_id already exists in this campaign")
			return
		}
	}

	clue := &playClue{
		CampaignID:  campaignID,
		ClueID:      req.ClueID,
		Text:        req.Text,
		Audience:    req.Audience,
		CharacterID: req.CharacterID,
	}
	if err := saveClueToDB(clue); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save clue")
		return
	}
	campaignClues[campaignID] = append(campaignClues[campaignID], clue)

	writeJSON(w, http.StatusCreated, clueJSON(clue))
}

// listCluesHandler returns clues visible to the requesting actor. The dm
// receives all clues in insertion order. A player receives party clues and
// character clues targeted to their own character only.
func listCluesHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	var ownCharacterID string
	if !isDM {
		playMembersMu.Lock()
		if m, exists := playMembers[campaignID][actor.Username]; exists {
			ownCharacterID = m.CharacterID
		}
		playMembersMu.Unlock()
	}

	campaignCluesMu.Lock()
	defer campaignCluesMu.Unlock()

	clues := make([]map[string]any, 0, len(campaignClues[campaignID]))
	for _, clue := range campaignClues[campaignID] {
		if isDM {
			clues = append(clues, clueJSON(clue))
			continue
		}
		switch clue.Audience {
		case "party":
			clues = append(clues, clueJSON(clue))
		case "character":
			if clue.CharacterID == ownCharacterID {
				clues = append(clues, clueJSON(clue))
			}
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{"clues": clues})
}

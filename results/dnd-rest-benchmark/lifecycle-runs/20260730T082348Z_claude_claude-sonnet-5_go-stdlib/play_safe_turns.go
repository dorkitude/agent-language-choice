package main

import (
	"encoding/json"
	"net/http"
)

// playSafeTurn is an accepted campaign-scoped safe turn submission.
type playSafeTurn struct {
	SubmissionID string `json:"submission_id"`
	Action       string `json:"action"`
	AcceptedTurn int    `json:"accepted_turn"`
	NextTurn     int    `json:"next_turn"`
}

// handlePlayCampaignSafeTurnsSub routes the "safe-turns" sub-path of a play
// campaign.
func handlePlayCampaignSafeTurnsSub(w http.ResponseWriter, r *http.Request, id, rest string) bool {
	if rest != "safe-turns" {
		return false
	}
	switch r.Method {
	case http.MethodPost:
		handleSubmitPlaySafeTurn(w, r, id)
	case http.MethodGet:
		handleListPlaySafeTurns(w, r, id)
	default:
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
	}
	return true
}

func handleSubmitPlaySafeTurn(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		SubmissionID string `json:"submission_id"`
		ExpectedTurn int    `json:"expected_turn"`
		Action       string `json:"action"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SubmissionID == "" || req.Action == "" || req.ExpectedTurn <= 0 {
		writeError(w, http.StatusBadRequest, "submission_id, action, and a positive expected_turn are required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign member")
		return
	}

	if c.SafeTurnCurrent == 0 {
		c.SafeTurnCurrent = 1
	}

	if c.SafeTurnSubmissionIDs != nil && c.SafeTurnSubmissionIDs[req.SubmissionID] {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "submission_id already used in this campaign")
		return
	}

	if req.ExpectedTurn != c.SafeTurnCurrent {
		current := c.SafeTurnCurrent
		playMu.Unlock()
		writeJSON(w, http.StatusConflict, map[string]interface{}{"current_turn": current})
		return
	}

	acceptedTurn := c.SafeTurnCurrent
	c.SafeTurnCurrent++
	entry := &playSafeTurn{
		SubmissionID: req.SubmissionID,
		Action:       req.Action,
		AcceptedTurn: acceptedTurn,
		NextTurn:     c.SafeTurnCurrent,
	}
	c.SafeTurns = append(c.SafeTurns, entry)
	if c.SafeTurnSubmissionIDs == nil {
		c.SafeTurnSubmissionIDs = make(map[string]bool)
	}
	c.SafeTurnSubmissionIDs[req.SubmissionID] = true
	resp := map[string]interface{}{
		"submission_id": entry.SubmissionID,
		"action":        entry.Action,
		"accepted_turn": entry.AcceptedTurn,
		"next_turn":     entry.NextTurn,
	}
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

func handleListPlaySafeTurns(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if c.Owner != username && !playIsCampaignMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "must be a campaign dm or member")
		return
	}

	current := c.SafeTurnCurrent
	if current == 0 {
		current = 1
	}
	accepted := make([]map[string]interface{}, 0, len(c.SafeTurns))
	for _, t := range c.SafeTurns {
		accepted = append(accepted, map[string]interface{}{
			"submission_id": t.SubmissionID,
			"action":        t.Action,
			"accepted_turn": t.AcceptedTurn,
			"next_turn":     t.NextTurn,
		})
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"current_turn": current,
		"accepted":     accepted,
	})
}

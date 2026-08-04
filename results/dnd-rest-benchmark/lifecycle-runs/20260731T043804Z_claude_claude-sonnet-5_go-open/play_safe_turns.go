package main

import (
	"net/http"
	"sync"
)

// acceptedSafeTurn is one immutable accepted safe-turn submission record.
type acceptedSafeTurn struct {
	CampaignID   string
	SubmissionID string
	Action       string
	AcceptedTurn int
	NextTurn     int
}

func acceptedSafeTurnJSON(t *acceptedSafeTurn) map[string]any {
	return map[string]any{
		"submission_id": t.SubmissionID,
		"action":        t.Action,
		"accepted_turn": t.AcceptedTurn,
		"next_turn":     t.NextTurn,
	}
}

// campaignSafeTurnsMu guards campaignSafeTurnState and campaignSafeTurnHistory,
// the in-memory index mirroring the play_safe_turns table. Keyed by campaign id.
var (
	campaignSafeTurnsMu     sync.Mutex
	campaignSafeTurnState   = map[string]int{}
	campaignSafeTurnHistory = map[string][]*acceptedSafeTurn{}
	campaignSafeTurnSeen    = map[string]map[string]bool{}
)

type submitSafeTurnRequest struct {
	SubmissionID string `json:"submission_id"`
	ExpectedTurn int    `json:"expected_turn"`
	Action       string `json:"action"`
}

// submitSafeTurnHandler lets authenticated campaign members, including the
// owner, submit safe turn actions. Submissions whose expected_turn does not
// match the campaign's current safe-turn are rejected without changing state.
func submitSafeTurnHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req submitSafeTurnRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a campaign member to submit safe turns")
		return
	}

	if req.SubmissionID == "" || req.Action == "" || req.ExpectedTurn <= 0 {
		writeError(w, http.StatusBadRequest, "submission_id and action must be nonempty strings and expected_turn must be a positive integer")
		return
	}

	campaignSafeTurnsMu.Lock()
	defer campaignSafeTurnsMu.Unlock()

	current, ok := campaignSafeTurnState[campaignID]
	if !ok {
		current = 1
		campaignSafeTurnState[campaignID] = current
	}

	if campaignSafeTurnSeen[campaignID][req.SubmissionID] {
		writeError(w, http.StatusConflict, "submission_id already used")
		return
	}

	if req.ExpectedTurn != current {
		writeJSON(w, http.StatusConflict, map[string]any{"current_turn": current})
		return
	}

	entry := &acceptedSafeTurn{
		CampaignID:   campaignID,
		SubmissionID: req.SubmissionID,
		Action:       req.Action,
		AcceptedTurn: current,
		NextTurn:     current + 1,
	}
	if err := saveSafeTurnToDB(entry); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save safe turn submission")
		return
	}

	if campaignSafeTurnSeen[campaignID] == nil {
		campaignSafeTurnSeen[campaignID] = map[string]bool{}
	}
	campaignSafeTurnSeen[campaignID][req.SubmissionID] = true
	campaignSafeTurnHistory[campaignID] = append(campaignSafeTurnHistory[campaignID], entry)
	campaignSafeTurnState[campaignID] = entry.NextTurn

	writeJSON(w, http.StatusCreated, acceptedSafeTurnJSON(entry))
}

// listSafeTurnsHandler lets the campaign DM and members read the campaign's
// safe-turn state in acceptance order.
func listSafeTurnsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
		writeError(w, http.StatusForbidden, "must be a campaign member to read safe turns")
		return
	}

	campaignSafeTurnsMu.Lock()
	defer campaignSafeTurnsMu.Unlock()

	current, ok := campaignSafeTurnState[campaignID]
	if !ok {
		current = 1
	}

	accepted := make([]map[string]any, 0, len(campaignSafeTurnHistory[campaignID]))
	for _, t := range campaignSafeTurnHistory[campaignID] {
		accepted = append(accepted, acceptedSafeTurnJSON(t))
	}

	writeJSON(w, http.StatusOK, map[string]any{"current_turn": current, "accepted": accepted})
}

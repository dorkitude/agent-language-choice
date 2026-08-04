package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// submitSafeTurnHandler accepts a deterministic, campaign-scoped safe turn
// submission. Members (including the owner) may submit. If the expected turn
// matches the campaign's current turn, the submission is recorded and the
// turn advances exactly once. Stale or duplicate submissions are rejected
// without changing state.
func submitSafeTurnHandler(w http.ResponseWriter, r *http.Request) {
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

	var req safeTurnSubmitRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.SubmissionID) == "" {
		badRequest(w, "submission_id is required")
		return
	}
	if strings.TrimSpace(req.Action) == "" {
		badRequest(w, "action is required")
		return
	}
	if req.ExpectedTurn <= 0 {
		badRequest(w, "expected_turn must be a positive integer")
		return
	}

	resp, currentTurn, err := dbSubmitSafeTurn(id, &req)
	if err != nil {
		if err == errSafeTurnDuplicate {
			conflict(w, "duplicate submission_id")
			return
		}
		log.Printf("submit safe turn: %v", err)
		badRequest(w, "failed to submit safe turn")
		return
	}
	if resp == nil {
		writeJSON(w, http.StatusConflict, safeTurnStaleResponse{CurrentTurn: currentTurn})
		return
	}

	writeJSON(w, http.StatusCreated, resp)
}

// getSafeTurnsHandler reads the campaign-scoped safe turn state for the owner
// and any campaign member.
func getSafeTurnsHandler(w http.ResponseWriter, r *http.Request) {
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

	currentTurn, entries, err := dbGetSafeTurns(id)
	if err != nil {
		log.Printf("get safe turns: %v", err)
		badRequest(w, "failed to read safe turns")
		return
	}

	writeJSON(w, http.StatusOK, safeTurnsResponse{
		CurrentTurn: currentTurn,
		Accepted:    entries,
	})
}

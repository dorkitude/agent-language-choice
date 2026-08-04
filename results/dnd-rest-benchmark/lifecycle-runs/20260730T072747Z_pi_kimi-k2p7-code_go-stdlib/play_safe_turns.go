package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// safeTurnSubmissionRequest binds the payload for a safe turn submission.
type safeTurnSubmissionRequest struct {
	SubmissionID string `json:"submission_id"`
	ExpectedTurn int    `json:"expected_turn"`
	Action       string `json:"action"`
}

// safeTurnSubmissionResponse is the shape returned after a successful safe
// turn submission.
type safeTurnSubmissionResponse struct {
	SubmissionID string `json:"submission_id"`
	Action       string `json:"action"`
	AcceptedTurn int    `json:"accepted_turn"`
	NextTurn     int    `json:"next_turn"`
}

// safeTurnStaleResponse is the exact body returned when expected_turn does not
// match the campaign's current turn.
type safeTurnStaleResponse struct {
	CurrentTurn int `json:"current_turn"`
}

// safeTurnAcceptedRow is the durable shape for an accepted safe turn.
type safeTurnAcceptedRow struct {
	CampaignID   string `json:"campaign_id"`
	SubmissionID string `json:"submission_id"`
	Action       string `json:"action"`
	AcceptedTurn int    `json:"accepted_turn"`
	NextTurn     int    `json:"next_turn"`
}

// safeTurnsReadResponse is the shape returned by the read endpoint.
type safeTurnsReadResponse struct {
	CurrentTurn int                          `json:"current_turn"`
	Accepted    []safeTurnSubmissionResponse `json:"accepted"`
}

// querySafeTurnCurrent loads the campaign safe-turn current_turn value,
// initializing it lazily to 1 if no row exists. The caller must hold dbMu.
func querySafeTurnCurrent(campaignID string) (int, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT current_turn FROM campaign_safe_turns WHERE campaign_id=%s LIMIT 1;", sq(campaignID)))
	if err != nil {
		return 0, err
	}
	var rows []struct {
		CurrentTurn int `json:"current_turn"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return 0, err
	}
	if len(rows) > 0 {
		return rows[0].CurrentTurn, nil
	}
	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_safe_turns (campaign_id, current_turn) VALUES (%s, 1);", sq(campaignID))); err != nil {
		return 0, err
	}
	return 1, nil
}

// querySafeTurnAcceptedBySubmission loads a single accepted safe turn by its
// submission_id. The caller must hold dbMu.
func querySafeTurnAcceptedBySubmission(campaignID, submissionID string) (*safeTurnAcceptedRow, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT campaign_id, submission_id, action, accepted_turn, next_turn FROM campaign_safe_turn_accepted WHERE campaign_id=%s AND submission_id=%s LIMIT 1;", sq(campaignID), sq(submissionID)))
	if err != nil {
		return nil, false, err
	}
	var rows []safeTurnAcceptedRow
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// querySafeTurnAcceptedAll loads all accepted safe turns for a campaign ordered
// by accepted_turn. The caller must hold dbMu.
func querySafeTurnAcceptedAll(campaignID string) ([]safeTurnAcceptedRow, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT campaign_id, submission_id, action, accepted_turn, next_turn FROM campaign_safe_turn_accepted WHERE campaign_id=%s ORDER BY accepted_turn;", sq(campaignID)))
	if err != nil {
		return nil, err
	}
	var rows []safeTurnAcceptedRow
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	if rows == nil {
		return []safeTurnAcceptedRow{}, nil
	}
	return rows, nil
}

// createSafeTurnHandler accepts campaign-scoped safe turn submissions. The
// caller must be the campaign owner or a member. Valid submissions whose
// expected_turn matches the current turn advance the turn exactly once and are
// recorded in the accepted history. Duplicate submission_id values or stale
// expected_turn values are rejected with 409 and no state change.
func createSafeTurnHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("safe turn auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")
	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("safe turn campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isMember := campaign.Owner == username
	if !isMember {
		isMember, err = isPlayCampaignMember(campaignID, username)
		if err != nil {
			log.Printf("safe turn member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isMember {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req safeTurnSubmissionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SubmissionID == "" || req.Action == "" || req.ExpectedTurn < 1 {
		writeError(w, http.StatusBadRequest, "invalid safe turn submission")
		return
	}

	currentTurn, err := querySafeTurnCurrent(campaignID)
	if err != nil {
		log.Printf("safe turn current query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	_, exists, err := querySafeTurnAcceptedBySubmission(campaignID, req.SubmissionID)
	if err != nil {
		log.Printf("safe turn duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "duplicate submission_id")
		return
	}

	if req.ExpectedTurn != currentTurn {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusConflict)
		if err := json.NewEncoder(w).Encode(safeTurnStaleResponse{CurrentTurn: currentTurn}); err != nil {
			log.Printf("encode error: %v", err)
		}
		return
	}

	nextTurn := currentTurn + 1
	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_safe_turn_accepted (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (%s, %s, %s, %d, %d);",
		sq(campaignID), sq(req.SubmissionID), sq(req.Action), currentTurn, nextTurn)); err != nil {
		log.Printf("safe turn insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_safe_turns SET current_turn=%d WHERE campaign_id=%s;", nextTurn, sq(campaignID))); err != nil {
		log.Printf("safe turn advance error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, safeTurnSubmissionResponse{
		SubmissionID: req.SubmissionID,
		Action:       req.Action,
		AcceptedTurn: currentTurn,
		NextTurn:     nextTurn,
	})
}

// listSafeTurnsHandler returns the campaign safe-turn state and ordered accepted
// history. The campaign owner and members may read it.
func listSafeTurnsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("safe turns list auth query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")
	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("safe turns list campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isReader := campaign.Owner == username
	if !isReader {
		isReader, err = isPlayCampaignMember(campaignID, username)
		if err != nil {
			log.Printf("safe turns list member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}
	if !isReader {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	currentTurn, err := querySafeTurnCurrent(campaignID)
	if err != nil {
		log.Printf("safe turns list current query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	acceptedRows, err := querySafeTurnAcceptedAll(campaignID)
	if err != nil {
		log.Printf("safe turns list accepted query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	accepted := make([]safeTurnSubmissionResponse, 0, len(acceptedRows))
	for _, row := range acceptedRows {
		accepted = append(accepted, safeTurnSubmissionResponse{
			SubmissionID: row.SubmissionID,
			Action:       row.Action,
			AcceptedTurn: row.AcceptedTurn,
			NextTurn:     row.NextTurn,
		})
	}

	writeJSON(w, http.StatusOK, safeTurnsReadResponse{
		CurrentTurn: currentTurn,
		Accepted:    accepted,
	})
}

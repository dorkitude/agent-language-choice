package main

import (
	"database/sql"
	"errors"
	"sync"
)

var errSafeTurnDuplicate = errors.New("duplicate safe turn submission")

var safeTurnLocksMu sync.Mutex
var safeTurnLocks = make(map[string]*sync.Mutex)

// safeTurnLock returns a mutex dedicated to safe-turn operations for a single
// campaign. It is used to serialize concurrent turn submissions so that only
// one submission can observe and advance the current turn at a time.
func safeTurnLock(campaignID string) *sync.Mutex {
	safeTurnLocksMu.Lock()
	defer safeTurnLocksMu.Unlock()
	m, ok := safeTurnLocks[campaignID]
	if !ok {
		m = &sync.Mutex{}
		safeTurnLocks[campaignID] = m
	}
	return m
}

// dbSubmitSafeTurn attempts to accept a safe-turn submission for a campaign.
// It returns the accepted response with a nil currentTurn when the submission
// matches the current turn. If the expected turn is stale, it returns nil and
// the current turn the campaign is on. Duplicate submission_ids return
// errSafeTurnDuplicate.
func dbSubmitSafeTurn(campaignID string, req *safeTurnSubmitRequest) (*safeTurnSubmitResponse, int, error) {
	lock := safeTurnLock(campaignID)
	lock.Lock()
	defer lock.Unlock()

	tx, err := db.Begin()
	if err != nil {
		return nil, 0, err
	}
	defer tx.Rollback()

	var existing string
	err = tx.QueryRow(
		"SELECT action FROM play_safe_turns WHERE campaign_id = ? AND submission_id = ?",
		campaignID, req.SubmissionID,
	).Scan(&existing)
	if err != nil && err != sql.ErrNoRows {
		return nil, 0, err
	}
	if err == nil {
		return nil, 0, errSafeTurnDuplicate
	}

	var max sql.NullInt64
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(accepted_turn), 0) FROM play_safe_turns WHERE campaign_id = ?",
		campaignID,
	).Scan(&max)
	if err != nil {
		return nil, 0, err
	}
	currentTurn := 1
	if max.Valid {
		currentTurn = int(max.Int64) + 1
	}

	if req.ExpectedTurn != currentTurn {
		return nil, currentTurn, nil
	}

	acceptedTurn := currentTurn
	nextTurn := acceptedTurn + 1
	_, err = tx.Exec(
		"INSERT INTO play_safe_turns (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)",
		campaignID, req.SubmissionID, req.Action, acceptedTurn, nextTurn,
	)
	if err != nil {
		if isUniqueViolation(err) {
			return nil, 0, errSafeTurnDuplicate
		}
		return nil, 0, err
	}

	if err := tx.Commit(); err != nil {
		return nil, 0, err
	}

	return &safeTurnSubmitResponse{
		SubmissionID: req.SubmissionID,
		Action:       req.Action,
		AcceptedTurn: acceptedTurn,
		NextTurn:     nextTurn,
	}, 0, nil
}

// dbGetSafeTurns returns the current turn and the ordered accepted turn
// history for a campaign. The current turn is 1 when no submissions have
// been accepted.
func dbGetSafeTurns(campaignID string) (int, []safeTurnAcceptedEntry, error) {
	rows, err := db.Query(
		"SELECT submission_id, action, accepted_turn, next_turn FROM play_safe_turns WHERE campaign_id = ? ORDER BY accepted_turn ASC",
		campaignID,
	)
	if err != nil {
		return 0, nil, err
	}
	defer rows.Close()

	entries := make([]safeTurnAcceptedEntry, 0)
	maxAccepted := 0
	for rows.Next() {
		var e safeTurnAcceptedEntry
		if err := rows.Scan(&e.SubmissionID, &e.Action, &e.AcceptedTurn, &e.NextTurn); err != nil {
			return 0, nil, err
		}
		entries = append(entries, e)
		if e.AcceptedTurn > maxAccepted {
			maxAccepted = e.AcceptedTurn
		}
	}
	if err := rows.Err(); err != nil {
		return 0, nil, err
	}

	currentTurn := 1
	if len(entries) > 0 {
		currentTurn = maxAccepted + 1
	}
	return currentTurn, entries, nil
}

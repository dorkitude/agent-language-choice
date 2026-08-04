package main

import (
	"database/sql"
	"encoding/json"
)

// dbCreatePlayDelegation grants a co-GM delegation to an existing campaign
// member. It validates that the target is a member, rejects duplicate active
// delegations, records the active state, and appends a grant audit entry.
func dbCreatePlayDelegation(campaignID, username string, powers []string) (*delegation, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var memberExists int
	err = tx.QueryRow(
		"SELECT 1 FROM play_members WHERE campaign_id = ? AND username = ?",
		campaignID, username,
	).Scan(&memberExists)
	if err == sql.ErrNoRows {
		return nil, errDelegationMemberNotFound
	}
	if err != nil {
		return nil, err
	}

	var active int
	var storedPowers string
	var rowExists bool
	err = tx.QueryRow(
		"SELECT active, powers FROM play_delegations WHERE campaign_id = ? AND username = ?",
		campaignID, username,
	).Scan(&active, &storedPowers)
	if err == sql.ErrNoRows {
		err = nil
	} else if err != nil {
		return nil, err
	} else {
		rowExists = true
	}
	if rowExists && active == 1 {
		return nil, errDelegationActiveExists
	}

	powersJSON, err := json.Marshal(powers)
	if err != nil {
		return nil, err
	}

	if rowExists {
		_, err = tx.Exec(
			"UPDATE play_delegations SET active = 1, powers = ? WHERE campaign_id = ? AND username = ?",
			powersJSON, campaignID, username,
		)
	} else {
		_, err = tx.Exec(
			"INSERT INTO play_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, 1)",
			campaignID, username, powersJSON,
		)
	}
	if err != nil {
		return nil, err
	}

	_, err = tx.Exec(
		"INSERT INTO play_delegation_audit (campaign_id, username, action, powers) VALUES (?, ?, ?, ?)",
		campaignID, username, "granted", powersJSON,
	)
	if err != nil {
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &delegation{Username: username, Powers: powers, Active: true}, nil
}

// dbRevokePlayDelegation deactivates a delegation for a campaign member. If
// an active delegation existed, it appends a revoke audit entry. The caller
// receives the inactive delegation record.
func dbRevokePlayDelegation(campaignID, username string) (*delegation, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var active int
	var storedPowers string
	var rowExists bool
	err = tx.QueryRow(
		"SELECT active, powers FROM play_delegations WHERE campaign_id = ? AND username = ?",
		campaignID, username,
	).Scan(&active, &storedPowers)
	if err == sql.ErrNoRows {
		err = nil
	} else if err != nil {
		return nil, err
	} else {
		rowExists = true
	}

	powers := []string{"narrate"}
	if rowExists {
		if err := json.Unmarshal([]byte(storedPowers), &powers); err != nil {
			return nil, err
		}
	}

	powersJSON, err := json.Marshal(powers)
	if err != nil {
		return nil, err
	}

	if rowExists && active == 1 {
		_, err = tx.Exec(
			"UPDATE play_delegations SET active = 0 WHERE campaign_id = ? AND username = ?",
			campaignID, username,
		)
		if err != nil {
			return nil, err
		}
		_, err = tx.Exec(
			"INSERT INTO play_delegation_audit (campaign_id, username, action, powers) VALUES (?, ?, ?, ?)",
			campaignID, username, "revoked", powersJSON,
		)
		if err != nil {
			return nil, err
		}
	} else if !rowExists {
		_, err = tx.Exec(
			"INSERT INTO play_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, 0)",
			campaignID, username, powersJSON,
		)
		if err != nil {
			return nil, err
		}
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return &delegation{Username: username, Powers: powers, Active: false}, nil
}

// dbHasDelegationPower reports whether a user has an active delegation that
// includes the requested power in a campaign.
func dbHasDelegationPower(campaignID, username, power string) (bool, error) {
	var active int
	var powersJSON string
	err := db.QueryRow(
		"SELECT active, powers FROM play_delegations WHERE campaign_id = ? AND username = ?",
		campaignID, username,
	).Scan(&active, &powersJSON)
	if err == sql.ErrNoRows {
		return false, nil
	}
	if err != nil {
		return false, err
	}
	if active != 1 {
		return false, nil
	}

	var powers []string
	if err := json.Unmarshal([]byte(powersJSON), &powers); err != nil {
		return false, err
	}
	for _, p := range powers {
		if p == power {
			return true, nil
		}
	}
	return false, nil
}

// dbListPlayDelegationAudit returns immutable grant/revoke entries for a campaign
// in chronological order.
func dbListPlayDelegationAudit(campaignID string) ([]delegationAuditEntry, error) {
	rows, err := db.Query(
		"SELECT username, action, powers FROM play_delegation_audit WHERE campaign_id = ? ORDER BY id ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	entries := make([]delegationAuditEntry, 0)
	for rows.Next() {
		var e delegationAuditEntry
		var powersJSON string
		if err := rows.Scan(&e.Username, &e.Action, &powersJSON); err != nil {
			return nil, err
		}
		if err := json.Unmarshal([]byte(powersJSON), &e.Powers); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

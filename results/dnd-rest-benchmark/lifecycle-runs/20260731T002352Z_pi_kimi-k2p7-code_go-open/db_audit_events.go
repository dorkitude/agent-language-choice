package main

import (
	"database/sql"
	"errors"
)

var errAuditEventDuplicate = errors.New("duplicate correlation id")

// dbCreatePlayAuditEvent creates an immutable audit event for a campaign. The
// timestamp is a deterministic per-campaign sequence starting at 1. Duplicate
// correlation_ids within the same campaign are rejected.
func dbCreatePlayAuditEvent(campaignID string, e *auditEvent) (*auditEvent, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var existing int
	err = tx.QueryRow(
		"SELECT 1 FROM play_audit_events WHERE campaign_id = ? AND correlation_id = ?",
		campaignID, e.CorrelationID,
	).Scan(&existing)
	if err != sql.ErrNoRows {
		if err == nil {
			return nil, errAuditEventDuplicate
		}
		return nil, err
	}

	var nextTimestamp int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_audit_events WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextTimestamp)
	if err != nil {
		return nil, err
	}

	_, err = tx.Exec(
		"INSERT INTO play_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (?, ?, ?, ?, ?, ?)",
		campaignID, e.Kind, e.Actor, e.Role, nextTimestamp, e.CorrelationID,
	)
	if err != nil {
		if isUniqueViolation(err) {
			return nil, errAuditEventDuplicate
		}
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	e.Timestamp = nextTimestamp
	return e, nil
}

// dbListPlayAuditEvents returns all audit events for a campaign in timestamp
// order.
func dbListPlayAuditEvents(campaignID string) ([]auditEvent, error) {
	rows, err := db.Query(
		"SELECT kind, actor, role, timestamp, correlation_id FROM play_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	entries := make([]auditEvent, 0)
	for rows.Next() {
		var e auditEvent
		if err := rows.Scan(&e.Kind, &e.Actor, &e.Role, &e.Timestamp, &e.CorrelationID); err != nil {
			return nil, err
		}
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

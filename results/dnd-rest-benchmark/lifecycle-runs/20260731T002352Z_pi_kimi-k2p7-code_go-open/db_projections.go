package main

import (
	"database/sql"
	"errors"
)

var errProjectionEventDuplicate = errors.New("duplicate event id")

// dbCreateProjectionEvent creates an immutable projection event for a campaign.
// The sequence is a deterministic per-campaign integer starting at 1.
// Duplicate event_ids within the same campaign are rejected.
func dbCreateProjectionEvent(campaignID string, e *projectionEvent) (*projectionEvent, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, err
	}
	defer tx.Rollback()

	var existing int
	err = tx.QueryRow(
		"SELECT 1 FROM play_projection_events WHERE campaign_id = ? AND event_id = ?",
		campaignID, e.EventID,
	).Scan(&existing)
	if err != sql.ErrNoRows {
		if err == nil {
			return nil, errProjectionEventDuplicate
		}
		return nil, err
	}

	var nextSequence int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_projection_events WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSequence)
	if err != nil {
		return nil, err
	}

	var value any
	if e.Value != "" {
		value = e.Value
	}

	_, err = tx.Exec(
		"INSERT INTO play_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)",
		campaignID, nextSequence, e.EventID, e.Kind, value,
	)
	if err != nil {
		if isUniqueViolation(err) {
			return nil, errProjectionEventDuplicate
		}
		return nil, err
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	e.Sequence = nextSequence
	return e, nil
}

// dbListProjectionEvents returns all projection events for a campaign in
// sequence order.
func dbListProjectionEvents(campaignID string) ([]projectionEvent, error) {
	rows, err := db.Query(
		"SELECT sequence, event_id, kind, value FROM play_projection_events WHERE campaign_id = ? ORDER BY sequence ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := make([]projectionEvent, 0)
	for rows.Next() {
		var e projectionEvent
		var value sql.NullString
		if err := rows.Scan(&e.Sequence, &e.EventID, &e.Kind, &value); err != nil {
			return nil, err
		}
		if value.Valid {
			e.Value = value.String
		}
		events = append(events, e)
	}
	return events, rows.Err()
}

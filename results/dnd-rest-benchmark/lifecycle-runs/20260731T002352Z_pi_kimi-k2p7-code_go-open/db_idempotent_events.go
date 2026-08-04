package main

import (
	"database/sql"
	"errors"
)

var (
	errIdempotentKeyConflict    = errors.New("idempotency key conflict")
	errIdempotentEventDuplicate = errors.New("duplicate event id")
)

// dbCreateIdempotentEvent creates an immutable campaign-scoped idempotent event.
// The sequence is a deterministic per-campaign integer starting at 1.
//
// If the idempotency key already exists for the campaign, the stored event is
// returned when the event_id and value match; otherwise a conflict is
// reported. If the event_id already exists under a different idempotency key,
// a conflict is reported.
func dbCreateIdempotentEvent(campaignID string, e *idempotentEvent) (*idempotentEvent, bool, error) {
	tx, err := db.Begin()
	if err != nil {
		return nil, false, err
	}
	defer tx.Rollback()

	var existing idempotentEvent
	err = tx.QueryRow(
		"SELECT sequence, event_id, value FROM play_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?",
		campaignID, e.IdempotencyKey,
	).Scan(&existing.Sequence, &existing.EventID, &existing.Value)
	if err != nil && err != sql.ErrNoRows {
		return nil, false, err
	}
	if err == nil {
		if existing.EventID == e.EventID && existing.Value == e.Value {
			existing.IdempotencyKey = e.IdempotencyKey
			return &existing, false, nil
		}
		return nil, false, errIdempotentKeyConflict
	}

	var existingByEvent idempotentEvent
	err = tx.QueryRow(
		"SELECT sequence, event_id, value, idempotency_key FROM play_idempotent_events WHERE campaign_id = ? AND event_id = ?",
		campaignID, e.EventID,
	).Scan(&existingByEvent.Sequence, &existingByEvent.EventID, &existingByEvent.Value, &existingByEvent.IdempotencyKey)
	if err != nil && err != sql.ErrNoRows {
		return nil, false, err
	}
	if err == nil {
		return nil, false, errIdempotentEventDuplicate
	}

	var nextSequence int
	err = tx.QueryRow(
		"SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_idempotent_events WHERE campaign_id = ?",
		campaignID,
	).Scan(&nextSequence)
	if err != nil {
		return nil, false, err
	}

	_, err = tx.Exec(
		"INSERT INTO play_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)",
		campaignID, nextSequence, e.EventID, e.Value, e.IdempotencyKey,
	)
	if err != nil {
		if isUniqueViolation(err) {
			return nil, false, errIdempotentEventDuplicate
		}
		return nil, false, err
	}

	if err := tx.Commit(); err != nil {
		return nil, false, err
	}
	e.Sequence = nextSequence
	return e, true, nil
}

// dbListIdempotentEvents returns all idempotent events for a campaign in
// sequence order.
func dbListIdempotentEvents(campaignID string) ([]idempotentEvent, error) {
	rows, err := db.Query(
		"SELECT sequence, event_id, value, idempotency_key FROM play_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC",
		campaignID,
	)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	events := make([]idempotentEvent, 0)
	for rows.Next() {
		var e idempotentEvent
		if err := rows.Scan(&e.Sequence, &e.EventID, &e.Value, &e.IdempotencyKey); err != nil {
			return nil, err
		}
		events = append(events, e)
	}
	return events, rows.Err()
}

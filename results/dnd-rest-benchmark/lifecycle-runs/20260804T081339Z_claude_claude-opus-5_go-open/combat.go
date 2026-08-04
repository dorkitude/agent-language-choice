package main

import (
	"database/sql"
	"errors"
	"net/http"
)

// SQLite-backed combat trackers. A session is created once with a frozen
// initiative order (see initiative.go) and then mutated turn by turn. The
// combatant rows never change after creation; only the turn pointer and the
// condition table do.
//
// Every handler here holds storeMu for its whole load-mutate-save sequence, so
// a concurrent advance can never interleave with a condition write.

type condition struct {
	Condition string `json:"condition"`
	Remaining int    `json:"remaining_rounds"`
}

type combatSession struct {
	ID        string
	Order     []combatant
	Round     int
	TurnIndex int
	// Conditions is keyed by combatant name. A name is present once it has ever
	// been given a condition, so callers can read an empty list after expiry.
	Conditions map[string][]condition
}

// ---------- persistence ----------

// loadSession reads a full session (order plus conditions) from SQLite. It
// returns sql.ErrNoRows when the id is unknown; see writeSessionLoadError.
func loadSession(id string) (*combatSession, error) {
	sess := &combatSession{ID: id, Conditions: make(map[string][]condition)}
	err := db.QueryRow(`SELECT round, turn_index FROM combat_sessions WHERE id = ?`, id).
		Scan(&sess.Round, &sess.TurnIndex)
	if err != nil {
		return nil, err
	}
	if err := loadSessionOrder(sess); err != nil {
		return nil, err
	}
	if err := loadSessionConditions(sess); err != nil {
		return nil, err
	}
	return sess, nil
}

// loadSessionOrder replays the initiative order by stored position, which is
// the ranking computed at creation time.
func loadSessionOrder(sess *combatSession) error {
	rows, err := db.Query(
		`SELECT name, dex, score FROM combat_combatants WHERE session_id = ? ORDER BY position`, sess.ID)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var c combatant
		if err := rows.Scan(&c.Name, &c.Dex, &c.Score); err != nil {
			return err
		}
		sess.Order = append(sess.Order, c)
	}
	return rows.Err()
}

// loadSessionConditions rebuilds the per-target condition lists. A row whose
// condition is NULL is only a marker that the target has held a condition at
// some point, so the map keeps the key with an empty list.
func loadSessionConditions(sess *combatSession) error {
	rows, err := db.Query(
		`SELECT target, condition, remaining FROM combat_conditions WHERE session_id = ? ORDER BY target, position`,
		sess.ID)
	if err != nil {
		return err
	}
	defer rows.Close()
	for rows.Next() {
		var target string
		var name sql.NullString
		var remaining sql.NullInt64
		if err := rows.Scan(&target, &name, &remaining); err != nil {
			return err
		}
		list := sess.Conditions[target]
		if list == nil {
			list = []condition{}
		}
		if name.Valid {
			list = append(list, condition{Condition: name.String, Remaining: int(remaining.Int64)})
		}
		sess.Conditions[target] = list
	}
	return rows.Err()
}

// insertSession persists a freshly created session, reporting created=false if
// the id is already taken. INSERT OR IGNORE on the primary key makes the
// duplicate check atomic with the insert.
func insertSession(sess *combatSession) (created bool, err error) {
	tx, err := db.Begin()
	if err != nil {
		return false, err
	}
	defer tx.Rollback()

	res, err := tx.Exec(
		`INSERT OR IGNORE INTO combat_sessions (id, round, turn_index) VALUES (?, ?, ?)`,
		sess.ID, sess.Round, sess.TurnIndex)
	if err != nil {
		return false, err
	}
	n, err := res.RowsAffected()
	if err != nil {
		return false, err
	}
	if n == 0 {
		return false, nil
	}
	for i, c := range sess.Order {
		if _, err := tx.Exec(
			`INSERT INTO combat_combatants (session_id, position, name, dex, score) VALUES (?, ?, ?, ?, ?)`,
			sess.ID, i, c.Name, c.Dex, c.Score); err != nil {
			return false, err
		}
	}
	return true, tx.Commit()
}

// saveSessionState rewrites the mutable parts of a session: the turn pointer
// and the whole condition table. Rewriting rather than diffing keeps the stored
// row order aligned with the in-memory lists.
func saveSessionState(sess *combatSession) error {
	tx, err := db.Begin()
	if err != nil {
		return err
	}
	defer tx.Rollback()

	if _, err := tx.Exec(`UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?`,
		sess.Round, sess.TurnIndex, sess.ID); err != nil {
		return err
	}
	if _, err := tx.Exec(`DELETE FROM combat_conditions WHERE session_id = ?`, sess.ID); err != nil {
		return err
	}
	// Iterate the combatant order, not the map, so the stored rows stay
	// deterministic regardless of Go's map iteration order.
	for _, c := range sess.Order {
		list, ok := sess.Conditions[c.Name]
		if !ok {
			continue
		}
		if len(list) == 0 {
			// Preserve the "has been targeted" marker for an emptied list.
			if _, err := tx.Exec(
				`INSERT INTO combat_conditions (session_id, target, position, condition, remaining) VALUES (?, ?, 0, NULL, NULL)`,
				sess.ID, c.Name); err != nil {
				return err
			}
			continue
		}
		for i, cond := range list {
			if _, err := tx.Exec(
				`INSERT INTO combat_conditions (session_id, target, position, condition, remaining) VALUES (?, ?, ?, ?, ?)`,
				sess.ID, c.Name, i, cond.Condition, cond.Remaining); err != nil {
				return err
			}
		}
	}
	return tx.Commit()
}

// writeSessionLoadError maps a load failure onto a response: a missing row is
// an unknown session, anything else is a storage fault.
func writeSessionLoadError(w http.ResponseWriter, err error) {
	if errors.Is(err, sql.ErrNoRows) {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}
	writeStorageError(w, "load session failed", err)
}

// ---------- session projections ----------

func (s *combatSession) has(name string) bool {
	for _, c := range s.Order {
		if c.Name == name {
			return true
		}
	}
	return false
}

// active is the combatant whose turn it is. Session creation guarantees a
// non-empty order, so the index is always in range.
func (s *combatSession) active() combatant {
	return s.Order[s.TurnIndex]
}

func (s *combatSession) activeOut() combatantOut {
	active := s.active()
	return combatantOut{Name: active.Name, Score: active.Score}
}

func (s *combatSession) orderOut() []combatantOut {
	return combatantsOut(s.Order)
}

// conditionsOut renders the per-combatant condition map, always emitting a list
// (never null) for every name that has been targeted.
func (s *combatSession) conditionsOut() map[string][]condition {
	out := make(map[string][]condition, len(s.Conditions))
	for name, list := range s.Conditions {
		if list == nil {
			list = []condition{}
		}
		out[name] = list
	}
	return out
}

// ---------- POST /v1/combat/sessions ----------

type createSessionRequest struct {
	ID         *string       `json:"id"`
	Combatants []combatantIn `json:"combatants"`
}

type createSessionResponse struct {
	ID        string         `json:"id"`
	Round     int            `json:"round"`
	TurnIndex int            `json:"turn_index"`
	Active    combatantOut   `json:"active"`
	Order     []combatantOut `json:"order"`
}

func handleCreateSession(w http.ResponseWriter, r *http.Request) {
	var req createSessionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	if req.ID == nil || *req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "at least one combatant is required")
		return
	}

	// Names must be present and unique because they key the condition map.
	seen := make(map[string]bool, len(req.Combatants))
	entries := make([]combatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == nil || *c.Name == "" || c.Roll == nil {
			writeError(w, http.StatusBadRequest, "combatant name and roll are required")
			return
		}
		if seen[*c.Name] {
			writeError(w, http.StatusBadRequest, "combatant names must be unique")
			return
		}
		seen[*c.Name] = true
		dex := 0
		if c.Dex != nil {
			dex = *c.Dex
		}
		entries = append(entries, resolveCombatant(*c.Name, dex, *c.Roll))
	}
	sortInitiative(entries)

	sess := &combatSession{
		ID:         *req.ID,
		Order:      entries,
		Round:      1,
		TurnIndex:  0,
		Conditions: make(map[string][]condition),
	}

	storeMu.Lock()
	created, err := insertSession(sess)
	storeMu.Unlock()
	if err != nil {
		writeStorageError(w, "create session failed", err)
		return
	}
	if !created {
		writeError(w, http.StatusBadRequest, "session id already exists")
		return
	}

	writeJSON(w, http.StatusOK, createSessionResponse{
		ID:        sess.ID,
		Round:     sess.Round,
		TurnIndex: sess.TurnIndex,
		Active:    sess.activeOut(),
		Order:     sess.orderOut(),
	})
}

// ---------- POST /v1/combat/sessions/{id}/conditions ----------

type addConditionRequest struct {
	Target    *string `json:"target"`
	Condition *string `json:"condition"`
	Duration  *int    `json:"duration_rounds"`
}

type addConditionResponse struct {
	Target     string      `json:"target"`
	Conditions []condition `json:"conditions"`
}

func handleAddCondition(w http.ResponseWriter, r *http.Request) {
	var req addConditionRequest
	if !decodeBody(w, r, &req) {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	// The session must exist before the payload is judged: an unknown id is a
	// 404 even when the body is also invalid.
	sess, err := loadSession(r.PathValue("id"))
	if err != nil {
		writeSessionLoadError(w, err)
		return
	}
	if req.Target == nil || req.Condition == nil || *req.Condition == "" {
		writeError(w, http.StatusBadRequest, "target and condition are required")
		return
	}
	if !sess.has(*req.Target) {
		writeError(w, http.StatusBadRequest, "target is not a combatant in this session")
		return
	}
	if req.Duration == nil || *req.Duration <= 0 {
		writeError(w, http.StatusBadRequest, "duration_rounds must be a positive integer")
		return
	}

	list := sess.Conditions[*req.Target]
	if list == nil {
		list = []condition{}
	}
	list = append(list, condition{Condition: *req.Condition, Remaining: *req.Duration})
	sess.Conditions[*req.Target] = list
	if err := saveSessionState(sess); err != nil {
		writeStorageError(w, "save session failed", err)
		return
	}

	writeJSON(w, http.StatusOK, addConditionResponse{Target: *req.Target, Conditions: list})
}

// ---------- POST /v1/combat/sessions/{id}/advance ----------

type advanceResponse struct {
	ID         string                 `json:"id"`
	Round      int                    `json:"round"`
	TurnIndex  int                    `json:"turn_index"`
	Active     combatantOut           `json:"active"`
	Order      []combatantOut         `json:"order"`
	Conditions map[string][]condition `json:"conditions"`
}

// handleAdvance moves the turn pointer forward one step, wrapping to the top of
// the order and incrementing the round. It takes no body, so it guards its
// method directly instead of via decodeBody.
func handleAdvance(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	sess, err := loadSession(r.PathValue("id"))
	if err != nil {
		writeSessionLoadError(w, err)
		return
	}

	sess.TurnIndex++
	if sess.TurnIndex >= len(sess.Order) {
		sess.TurnIndex = 0
		sess.Round++
	}

	// The newly active combatant ticks down its own conditions at turn start.
	// Expired entries drop out but the key stays, so the response still shows
	// the target with an empty list.
	active := sess.active()
	if list, ok := sess.Conditions[active.Name]; ok {
		kept := make([]condition, 0, len(list))
		for _, c := range list {
			c.Remaining--
			if c.Remaining > 0 {
				kept = append(kept, c)
			}
		}
		sess.Conditions[active.Name] = kept
	}

	if err := saveSessionState(sess); err != nil {
		writeStorageError(w, "save session failed", err)
		return
	}

	writeJSON(w, http.StatusOK, advanceResponse{
		ID:         sess.ID,
		Round:      sess.Round,
		TurnIndex:  sess.TurnIndex,
		Active:     sess.activeOut(),
		Order:      sess.orderOut(),
		Conditions: sess.conditionsOut(),
	})
}

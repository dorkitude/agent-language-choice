package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
)

// Stateful combat tracker: an initiative order per session, a turn cursor, and
// per-combatant conditions that tick down. Sessions live in memory and are
// mirrored to SQLite after every mutation (see store.go).

type conditionState struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

// combatSession is one tracked fight. TurnIndex always points at a valid entry
// of Order, which is never empty — handlers rely on that to report the active
// combatant without a bounds check, and the loader drops any persisted row that
// would violate it.
type combatSession struct {
	ID         string
	Round      int
	TurnIndex  int
	Order      []initiativeEntry
	Conditions map[string][]conditionState
}

type combatStore struct {
	mu       sync.Mutex
	sessions map[string]*combatSession
}

var sessions = &combatStore{sessions: map[string]*combatSession{}}

// conditionsView deep-copies the condition lists so the response cannot alias
// session state once the lock is released. Combatants whose conditions have all
// expired keep an empty list, which is how callers tell "cleared" apart from
// "never present".
func (s *combatSession) conditionsView() map[string][]conditionState {
	view := make(map[string][]conditionState, len(s.Conditions))
	for name, list := range s.Conditions {
		view[name] = append(make([]conditionState, 0, len(list)), list...)
	}
	return view
}

// hasCombatant reports whether name appears in the initiative order.
func (s *combatSession) hasCombatant(name string) bool {
	for _, e := range s.Order {
		if e.Name == name {
			return true
		}
	}
	return false
}

// ---------- payloads ----------

type createSessionRequest struct {
	ID         *string     `json:"id"`
	Combatants []combatant `json:"combatants"`
}

// sessionResponse is the create reply: no conditions, since a new session has
// none.
type sessionResponse struct {
	ID        string            `json:"id"`
	Round     int               `json:"round"`
	TurnIndex int               `json:"turn_index"`
	Active    initiativeEntry   `json:"active"`
	Order     []initiativeEntry `json:"order"`
}

// sessionStateResponse is the full session view returned by reads and advances.
type sessionStateResponse struct {
	ID         string                      `json:"id"`
	Round      int                         `json:"round"`
	TurnIndex  int                         `json:"turn_index"`
	Active     initiativeEntry             `json:"active"`
	Order      []initiativeEntry           `json:"order"`
	Conditions map[string][]conditionState `json:"conditions"`
}

type addConditionRequest struct {
	Target         *string          `json:"target"`
	Condition      *string          `json:"condition"`
	DurationRounds *json.RawMessage `json:"duration_rounds"`
}

type addConditionResponse struct {
	Target     string           `json:"target"`
	Conditions []conditionState `json:"conditions"`
}

// stateOf renders the full session view. Callers must hold sessions.mu.
func (s *combatSession) stateOf() sessionStateResponse {
	return sessionStateResponse{
		ID:         s.ID,
		Round:      s.Round,
		TurnIndex:  s.TurnIndex,
		Active:     s.Order[s.TurnIndex],
		Order:      s.Order,
		Conditions: s.conditionsView(),
	}
}

// ---------- POST /v1/combat/sessions ----------

func handleCreateSession(w http.ResponseWriter, r *http.Request) {
	var req createSessionRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.ID == nil || strings.TrimSpace(*req.ID) == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "at least one combatant is required")
		return
	}
	order, msg := initiativeOrder(req.Combatants, true)
	if msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}

	// The stored id is the raw value, not the trimmed one used for the blank
	// check, so lookups keep matching what the client sent.
	id := *req.ID
	session := &combatSession{
		ID:         id,
		Round:      1,
		TurnIndex:  0,
		Order:      order,
		Conditions: map[string][]conditionState{},
	}

	// Creating a session is idempotent: re-posting an id rolls that encounter
	// back to round 1 with a fresh initiative order. Combat state is persisted,
	// so rejecting a repeat id would make a restarted server refuse to start the
	// same encounter again.
	sessions.mu.Lock()
	sessions.sessions[id] = session
	sessions.mu.Unlock()
	flush()

	writeJSON(w, http.StatusOK, sessionResponse{
		ID:        session.ID,
		Round:     session.Round,
		TurnIndex: session.TurnIndex,
		Active:    session.Order[session.TurnIndex],
		Order:     session.Order,
	})
}

// ---------- GET /v1/combat/sessions/{id} ----------

func handleGetSession(w http.ResponseWriter, r *http.Request) {
	sessions.mu.Lock()
	defer sessions.mu.Unlock()
	session, ok := sessions.sessions[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}
	writeJSON(w, http.StatusOK, session.stateOf())
}

// ---------- POST /v1/combat/sessions/{id}/conditions ----------

func handleAddCondition(w http.ResponseWriter, r *http.Request) {
	var req addConditionRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	if req.Target == nil || *req.Target == "" {
		writeError(w, http.StatusBadRequest, "target is required")
		return
	}
	if req.Condition == nil || *req.Condition == "" {
		writeError(w, http.StatusBadRequest, "condition is required")
		return
	}
	duration, ok := asInt(req.DurationRounds)
	if !ok {
		writeError(w, http.StatusBadRequest, "duration_rounds must be an integer")
		return
	}
	if duration < 1 {
		writeError(w, http.StatusBadRequest, "duration_rounds must be positive")
		return
	}

	sessions.mu.Lock()
	session, found := sessions.sessions[r.PathValue("id")]
	if !found {
		sessions.mu.Unlock()
		writeError(w, http.StatusNotFound, "session not found")
		return
	}
	if !session.hasCombatant(*req.Target) {
		sessions.mu.Unlock()
		writeError(w, http.StatusBadRequest, "target is not a combatant in this session")
		return
	}

	// Re-applying an existing condition refreshes its duration rather than
	// stacking a second copy.
	list := session.Conditions[*req.Target]
	refreshed := false
	for i := range list {
		if list[i].Condition == *req.Condition {
			list[i].RemainingRounds = duration
			refreshed = true
			break
		}
	}
	if !refreshed {
		list = append(list, conditionState{Condition: *req.Condition, RemainingRounds: duration})
	}
	session.Conditions[*req.Target] = list
	view := append([]conditionState(nil), list...)
	sessions.mu.Unlock()

	// flush takes every store's lock, so it must run unlocked.
	flush()

	writeJSON(w, http.StatusOK, addConditionResponse{Target: *req.Target, Conditions: view})
}

// ---------- POST /v1/combat/sessions/{id}/advance ----------

func handleAdvanceTurn(w http.ResponseWriter, r *http.Request) {
	sessions.mu.Lock()
	session, ok := sessions.sessions[r.PathValue("id")]
	if !ok {
		sessions.mu.Unlock()
		writeError(w, http.StatusNotFound, "session not found")
		return
	}

	session.TurnIndex++
	if session.TurnIndex >= len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}
	session.tickConditions(session.Order[session.TurnIndex].Name)

	resp := session.stateOf()
	sessions.mu.Unlock()
	flush()

	writeJSON(w, http.StatusOK, resp)
}

// tickConditions decrements the named combatant's conditions and drops the
// expired ones. Durations are consumed at the start of that combatant's own
// turn, so a 1-round condition applied on their turn survives until it comes
// around again. The (possibly empty) map entry is kept so callers can see that
// conditions were cleared rather than never present.
func (s *combatSession) tickConditions(name string) {
	list := s.Conditions[name]
	if len(list) == 0 {
		return
	}
	kept := list[:0]
	for _, c := range list {
		c.RemainingRounds--
		if c.RemainingRounds > 0 {
			kept = append(kept, c)
		}
	}
	s.Conditions[name] = kept
}

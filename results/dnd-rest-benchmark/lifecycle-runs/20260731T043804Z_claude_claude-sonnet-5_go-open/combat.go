package main

import (
	"net/http"
	"sort"
	"sync"
)

type condition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type combatSessionCombatant struct {
	Name       string      `json:"name"`
	Dex        int         `json:"dex"`
	Score      int         `json:"score"`
	Conditions []condition `json:"-"`
}

type combatSession struct {
	ID        string
	Order     []*combatSessionCombatant
	Round     int
	TurnIndex int
}

// combatSessionsMu guards combatSessions, the in-memory index that mirrors
// the combat_sessions table. All handlers must hold it while reading or
// mutating a session, including across its DB write, to keep the memory and
// SQLite copies consistent.
var (
	combatSessionsMu sync.Mutex
	combatSessions   = map[string]*combatSession{}
)

type activeCombatant struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
}

func (s *combatSession) activeCombatant() *combatSessionCombatant {
	return s.Order[s.TurnIndex]
}

func (s *combatSession) findCombatant(name string) *combatSessionCombatant {
	for _, c := range s.Order {
		if c.Name == name {
			return c
		}
	}
	return nil
}

type createCombatSessionRequest struct {
	ID         string      `json:"id"`
	Combatants []combatant `json:"combatants"`
}

func createCombatSessionHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createCombatSessionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "combatants is required")
		return
	}

	combatSessionsMu.Lock()
	defer combatSessionsMu.Unlock()

	if _, exists := combatSessions[req.ID]; exists {
		writeError(w, http.StatusBadRequest, "session id already exists")
		return
	}

	order := make([]*combatSessionCombatant, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		if c.Name == "" {
			writeError(w, http.StatusBadRequest, "combatant name is required")
			return
		}
		order = append(order, &combatSessionCombatant{
			Name:  c.Name,
			Dex:   c.Dex,
			Score: c.Roll + c.Dex,
		})
	}

	sort.Slice(order, func(i, j int) bool {
		if order[i].Score != order[j].Score {
			return order[i].Score > order[j].Score
		}
		if order[i].Dex != order[j].Dex {
			return order[i].Dex > order[j].Dex
		}
		return order[i].Name < order[j].Name
	})

	session := &combatSession{
		ID:        req.ID,
		Order:     order,
		Round:     1,
		TurnIndex: 0,
	}
	combatSessions[req.ID] = session
	if err := saveCombatSessionToDB(session); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to persist combat session")
		return
	}

	writeJSON(w, http.StatusOK, combatSessionResponse(session))
}

func combatSessionResponse(s *combatSession) map[string]any {
	orderOut := make([]activeCombatant, 0, len(s.Order))
	for _, c := range s.Order {
		orderOut = append(orderOut, activeCombatant{Name: c.Name, Score: c.Score})
	}
	active := s.activeCombatant()
	return map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     activeCombatant{Name: active.Name, Score: active.Score},
		"order":      orderOut,
	}
}

type addConditionRequest struct {
	Target         string `json:"target"`
	Condition      string `json:"condition"`
	DurationRounds *int   `json:"duration_rounds"`
}

func addConditionHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	id, ok := extractSessionID(r.URL.Path, "/v1/combat/sessions/", "/conditions")
	if !ok || id == "" {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}

	var req addConditionRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.Target == "" {
		writeError(w, http.StatusBadRequest, "target is required")
		return
	}
	if req.Condition == "" {
		writeError(w, http.StatusBadRequest, "condition is required")
		return
	}
	if req.DurationRounds == nil || *req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "duration_rounds must be a positive integer")
		return
	}

	combatSessionsMu.Lock()
	defer combatSessionsMu.Unlock()

	session, exists := combatSessions[id]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}

	target := session.findCombatant(req.Target)
	if target == nil {
		writeError(w, http.StatusBadRequest, "target must name a combatant in the session")
		return
	}

	target.Conditions = append(target.Conditions, condition{
		Condition:       req.Condition,
		RemainingRounds: *req.DurationRounds,
	})
	if err := saveCombatSessionToDB(session); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to persist combat session")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"target":     target.Name,
		"conditions": target.Conditions,
	})
}

func advanceTurnHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	id, ok := extractSessionID(r.URL.Path, "/v1/combat/sessions/", "/advance")
	if !ok || id == "" {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}

	combatSessionsMu.Lock()
	defer combatSessionsMu.Unlock()

	session, exists := combatSessions[id]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown session id")
		return
	}

	session.TurnIndex++
	if session.TurnIndex >= len(session.Order) {
		session.TurnIndex = 0
		session.Round++
	}

	// Conditions tick down on the combatant whose turn is starting, and
	// expire (are dropped) once their remaining-rounds count reaches zero.
	active := session.activeCombatant()
	remaining := active.Conditions[:0]
	for _, c := range active.Conditions {
		c.RemainingRounds--
		if c.RemainingRounds > 0 {
			remaining = append(remaining, c)
		}
	}
	active.Conditions = remaining

	if err := saveCombatSessionToDB(session); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to persist combat session")
		return
	}

	conditionsOut := map[string][]condition{}
	for _, c := range session.Order {
		if len(c.Conditions) > 0 {
			conditionsOut[c.Name] = c.Conditions
		}
	}
	if _, ok := conditionsOut[active.Name]; !ok {
		conditionsOut[active.Name] = []condition{}
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         session.ID,
		"round":      session.Round,
		"turn_index": session.TurnIndex,
		"active":     activeCombatant{Name: active.Name, Score: active.Score},
		"conditions": conditionsOut,
	})
}

// combatSessionsRouter dispatches requests under /v1/combat/sessions/{id}/...
// by matching the trailing path segment, since http.ServeMux only supports
// prefix matching on this pattern.
func combatSessionsRouter(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path
	switch {
	case len(path) >= len("/conditions") && path[len(path)-len("/conditions"):] == "/conditions":
		addConditionHandler(w, r)
	case len(path) >= len("/advance") && path[len(path)-len("/advance"):] == "/advance":
		advanceTurnHandler(w, r)
	default:
		writeError(w, http.StatusNotFound, "unknown route")
	}
}

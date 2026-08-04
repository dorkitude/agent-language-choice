package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"sort"
	"strings"
)

// CombatOrderEntry is the public representation of a combatant in the order.
type CombatOrderEntry struct {
	Name  string `json:"name"`
	Score int    `json:"score"`
	Dex   int    `json:"-"`
}

// Condition tracks a named condition and how many rounds it has remaining.
type Condition struct {
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

type createCombatSessionRequest struct {
	ID         string      `json:"id"`
	Combatants []combatant `json:"combatants"`
}

type sessionResponse struct {
	ID        string             `json:"id"`
	Round     int                `json:"round"`
	TurnIndex int                `json:"turn_index"`
	Active    CombatOrderEntry   `json:"active"`
	Order     []CombatOrderEntry `json:"order"`
}

type conditionRequest struct {
	Target         string `json:"target"`
	Condition      string `json:"condition"`
	DurationRounds int    `json:"duration_rounds"`
}

type conditionsResponse struct {
	Target     string      `json:"target"`
	Conditions []Condition `json:"conditions"`
}

type advanceTurnResponse struct {
	ID         string                 `json:"id"`
	Round      int                    `json:"round"`
	TurnIndex  int                    `json:"turn_index"`
	Active     CombatOrderEntry       `json:"active"`
	Conditions map[string][]Condition `json:"conditions"`
}

// dbSession is the raw row shape returned by sqlite3 for combat_sessions.
type dbSession struct {
	ID        string `json:"id"`
	Round     int    `json:"round"`
	TurnIndex int    `json:"turn_index"`
}

// dbOrderEntry is the raw row shape returned by sqlite3 for combat_order.
type dbOrderEntry struct {
	Idx   int    `json:"idx"`
	Name  string `json:"name"`
	Score int    `json:"score"`
	Dex   int    `json:"dex"`
}

// dbConditionRow is the raw row shape returned by sqlite3 for combat_conditions.
type dbConditionRow struct {
	Target          string `json:"target"`
	Condition       string `json:"condition"`
	RemainingRounds int    `json:"remaining_rounds"`
}

// querySessionExists returns true when a combat session row exists.
func querySessionExists(id string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT id FROM combat_sessions WHERE id=%s LIMIT 1;", sq(id)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		ID string `json:"id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// querySessionOrder returns the ordered list of combatants for a session.
func querySessionOrder(id string) ([]dbOrderEntry, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT idx, name, score, dex FROM combat_order WHERE session_id=%s ORDER BY idx;", sq(id)))
	if err != nil {
		return nil, err
	}
	var order []dbOrderEntry
	if err := json.Unmarshal(out, &order); err != nil {
		return nil, err
	}
	return order, nil
}

// querySession loads a session header, its order, and its conditions. It
// returns nil session when the session is not found.
func querySession(id string) (*dbSession, []dbOrderEntry, []dbConditionRow, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT id, round, turn_index FROM combat_sessions WHERE id=%s LIMIT 1;", sq(id)))
	if err != nil {
		return nil, nil, nil, err
	}
	var sessions []dbSession
	if err := json.Unmarshal(out, &sessions); err != nil {
		return nil, nil, nil, err
	}
	if len(sessions) == 0 {
		return nil, nil, nil, nil
	}
	order, err := querySessionOrder(id)
	if err != nil {
		return nil, nil, nil, err
	}
	out, err = dbQuery(fmt.Sprintf("SELECT target, \"condition\", remaining_rounds FROM combat_conditions WHERE session_id=%s ORDER BY id;", sq(id)))
	if err != nil {
		return nil, nil, nil, err
	}
	var conds []dbConditionRow
	if err := json.Unmarshal(out, &conds); err != nil {
		return nil, nil, nil, err
	}
	return &sessions[0], order, conds, nil
}

// createCombatSessionHandler creates a new combat session, sorts the submitted
// combatants using the initiative rules, and stores the order. The first
// combatant becomes the active turn.
func createCombatSessionHandler(w http.ResponseWriter, r *http.Request) {
	var req createCombatSessionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "missing id")
		return
	}
	if len(req.Combatants) == 0 {
		writeError(w, http.StatusBadRequest, "combatants required")
		return
	}

	order := make([]CombatOrderEntry, 0, len(req.Combatants))
	for _, c := range req.Combatants {
		order = append(order, CombatOrderEntry{Name: c.Name, Score: c.Roll + c.Dex, Dex: c.Dex})
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

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := querySessionExists(req.ID)
	if err != nil {
		log.Printf("create session query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusBadRequest, "session already exists")
		return
	}

	var b strings.Builder
	fmt.Fprintf(&b, "INSERT INTO combat_sessions (id, round, turn_index) VALUES (%s, 1, 0);", sq(req.ID))
	for i, c := range order {
		fmt.Fprintf(&b, "INSERT INTO combat_order (session_id, idx, name, score, dex) VALUES (%s, %d, %s, %d, %d);",
			sq(req.ID), i, sq(c.Name), c.Score, c.Dex)
	}
	if err := dbExec(b.String()); err != nil {
		log.Printf("create session insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, sessionResponse{
		ID:        req.ID,
		Round:     1,
		TurnIndex: 0,
		Active:    order[0],
		Order:     order,
	})
}

// addConditionHandler attaches a condition to a combatant for a given number of
// rounds. It returns the full list of conditions currently on that target.
func addConditionHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	var req conditionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Target == "" || req.Condition == "" || req.DurationRounds <= 0 {
		writeError(w, http.StatusBadRequest, "invalid condition")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM combat_order WHERE session_id=%s AND name=%s LIMIT 1;",
		sq(id), sq(req.Target)))
	if err != nil {
		log.Printf("add condition query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var found []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &found); err != nil {
		log.Printf("add condition unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(found) == 0 {
		// Check if session exists to return the correct error.
		exists, err := querySessionExists(id)
		if err != nil {
			log.Printf("add condition exists error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !exists {
			writeError(w, http.StatusNotFound, "session not found")
			return
		}
		writeError(w, http.StatusBadRequest, "target not found")
		return
	}

	insertSQL := fmt.Sprintf("INSERT INTO combat_conditions (session_id, target, \"condition\", remaining_rounds) VALUES (%s, %s, %s, %d);",
		sq(id), sq(req.Target), sq(req.Condition), req.DurationRounds)
	if err := dbExec(insertSQL); err != nil {
		log.Printf("add condition insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	out, err = dbQuery(fmt.Sprintf("SELECT \"condition\", remaining_rounds FROM combat_conditions WHERE session_id=%s AND target=%s ORDER BY id;",
		sq(id), sq(req.Target)))
	if err != nil {
		log.Printf("add condition list error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var conds []Condition
	if err := json.Unmarshal(out, &conds); err != nil {
		log.Printf("add condition unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, conditionsResponse{
		Target:     req.Target,
		Conditions: conds,
	})
}

// advanceTurnHandler moves the turn index forward, wraps to the next round,
// and decrements then removes conditions whose remaining rounds have expired
// on the newly active combatant's turn.
func advanceTurnHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	session, order, _, err := querySession(id)
	if err != nil {
		log.Printf("advance turn query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if session == nil {
		writeError(w, http.StatusNotFound, "session not found")
		return
	}
	if len(order) == 0 {
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	newRound := session.Round
	newTurn := session.TurnIndex
	if session.TurnIndex >= len(order)-1 {
		newTurn = 0
		newRound++
	} else {
		newTurn++
	}
	active := CombatOrderEntry{Name: order[newTurn].Name, Score: order[newTurn].Score, Dex: order[newTurn].Dex}

	updateSQL := fmt.Sprintf("UPDATE combat_sessions SET round=%d, turn_index=%d WHERE id=%s; UPDATE combat_conditions SET remaining_rounds = remaining_rounds - 1 WHERE session_id=%s AND target=%s; DELETE FROM combat_conditions WHERE session_id=%s AND target=%s AND remaining_rounds <= 0;",
		newRound, newTurn, sq(id), sq(id), sq(active.Name), sq(id), sq(active.Name))
	if err := dbExec(updateSQL); err != nil {
		log.Printf("advance turn update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT target, \"condition\", remaining_rounds FROM combat_conditions WHERE session_id=%s ORDER BY id;", sq(id)))
	if err != nil {
		log.Printf("advance turn conditions error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var condRows []dbConditionRow
	if err := json.Unmarshal(out, &condRows); err != nil {
		log.Printf("advance turn unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	condMap := make(map[string][]Condition)
	for _, row := range condRows {
		condMap[row.Target] = append(condMap[row.Target], Condition{
			Condition:       row.Condition,
			RemainingRounds: row.RemainingRounds,
		})
	}

	condsCopy := make(map[string][]Condition, len(order))
	for _, c := range order {
		if list, ok := condMap[c.Name]; ok {
			condsCopy[c.Name] = list
		} else {
			condsCopy[c.Name] = []Condition{}
		}
	}

	writeJSON(w, http.StatusOK, advanceTurnResponse{
		ID:         id,
		Round:      newRound,
		TurnIndex:  newTurn,
		Active:     active,
		Conditions: condsCopy,
	})
}

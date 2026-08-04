package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func createCombatSessionHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID         string           `json:"id"`
		Combatants []combatantInput `json:"combatants"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if len(req.Combatants) == 0 {
		badRequest(w, "combatants are required")
		return
	}
	for _, c := range req.Combatants {
		if strings.TrimSpace(c.Name) == "" {
			badRequest(w, "combatant name is required")
			return
		}
	}

	combat.mu.Lock()
	defer combat.mu.Unlock()

	if _, exists := combat.sessions[req.ID]; exists {
		badRequest(w, "session id already exists")
		return
	}

	order := computeInitiative(req.Combatants)

	s := &session{
		ID:         req.ID,
		Round:      1,
		TurnIndex:  0,
		Order:      order,
		Conditions: make(map[string][]condition),
	}

	if err := dbCreateSession(s); err != nil {
		log.Printf("create combat session: %v", err)
		badRequest(w, "failed to create session")
		return
	}

	combat.sessions[req.ID] = s

	active := activeEntry(s)
	writeJSON(w, http.StatusOK, map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     active,
		"order":      s.Order,
	})
}

func addConditionHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		notFound(w, "session not found")
		return
	}

	var req struct {
		Target    string `json:"target"`
		Condition string `json:"condition"`
		Duration  int    `json:"duration_rounds"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Target) == "" {
		badRequest(w, "target is required")
		return
	}
	if req.Duration <= 0 {
		badRequest(w, "duration_rounds must be a positive integer")
		return
	}

	combat.mu.Lock()
	defer combat.mu.Unlock()

	s, ok := combat.sessions[id]
	if !ok {
		notFound(w, "session not found")
		return
	}

	if !combatantExists(s, req.Target) {
		badRequest(w, "target not found in session")
		return
	}

	conds := s.Conditions[req.Target]
	conds = append(conds, condition{Condition: req.Condition, Remaining: req.Duration})
	s.Conditions[req.Target] = conds

	if err := dbSaveSession(s); err != nil {
		log.Printf("save combat session: %v", err)
		badRequest(w, "failed to add condition")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"target":     req.Target,
		"conditions": conds,
	})
}

func advanceTurnHandler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		notFound(w, "session not found")
		return
	}

	combat.mu.Lock()
	defer combat.mu.Unlock()

	s, ok := combat.sessions[id]
	if !ok {
		notFound(w, "session not found")
		return
	}

	if len(s.Order) > 0 {
		s.TurnIndex++
		if s.TurnIndex >= len(s.Order) {
			s.TurnIndex = 0
			s.Round++
		}
	}

	// Decrement conditions on the newly active combatant at the start of its turn.
	activeName := ""
	if active := activeEntry(s); active != nil {
		activeName = active.Name
		if conds, ok := s.Conditions[activeName]; ok {
			filtered := conds[:0]
			for _, c := range conds {
				c.Remaining--
				if c.Remaining > 0 {
					filtered = append(filtered, c)
				}
			}
			s.Conditions[activeName] = filtered
		}
	}

	if err := dbSaveSession(s); err != nil {
		log.Printf("save combat session: %v", err)
		badRequest(w, "failed to advance turn")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         s.ID,
		"round":      s.Round,
		"turn_index": s.TurnIndex,
		"active":     activeEntry(s),
		"conditions": s.Conditions,
	})
}

func activeEntry(s *session) *orderEntry {
	if len(s.Order) == 0 || s.TurnIndex < 0 || s.TurnIndex >= len(s.Order) {
		return nil
	}
	entry := s.Order[s.TurnIndex]
	return &entry
}

func combatantExists(s *session, name string) bool {
	for _, e := range s.Order {
		if e.Name == name {
			return true
		}
	}
	return false
}

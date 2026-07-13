package main

// Campaign state APIs (Maintenance Stage 6).
//
// Consistent with the durable-storage stage, the campaign schema is added to the
// on-disk SQLite file for durability, while the records themselves are served
// from in-memory structures (the standard library ships no query engine).

import (
	"encoding/json"
	"net/http"
	"sync"
)

type character struct {
	ID    string
	Name  string
	Level int
	Class string
}

type logEvent struct {
	ID      string
	Kind    string
	Summary string
}

type campaign struct {
	ID         string
	Name       string
	DM         string
	Characters []*character
	CharIndex  map[string]*character
	Events     []*logEvent
	EventIndex map[string]*logEvent
}

var (
	campaignMu sync.Mutex
	campaigns  = map[string]*campaign{}
)

func characterView(c *character) map[string]interface{} {
	return map[string]interface{}{
		"id":    c.ID,
		"name":  c.Name,
		"level": c.Level,
		"class": c.Class,
	}
}

func handleCreateCampaign(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.ID == "" || req.Name == "" || req.DM == "" {
		badRequest(w)
		return
	}
	campaignMu.Lock()
	defer campaignMu.Unlock()
	if _, exists := campaigns[req.ID]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "campaign already exists"})
		return
	}
	campaigns[req.ID] = &campaign{
		ID:         req.ID,
		Name:       req.Name,
		DM:         req.DM,
		Characters: []*character{},
		CharIndex:  map[string]*character{},
		Events:     []*logEvent{},
		EventIndex: map[string]*logEvent{},
	}
	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"id":   req.ID,
		"name": req.Name,
		"dm":   req.DM,
	})
}

func handleAddCharacter(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		ID    string `json:"id"`
		Name  string `json:"name"`
		Level *int   `json:"level"`
		Class string `json:"class"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	campaignMu.Lock()
	defer campaignMu.Unlock()
	c, ok := campaigns[id]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if req.ID == "" || req.Name == "" || req.Class == "" || req.Level == nil {
		badRequest(w)
		return
	}
	if _, exists := c.CharIndex[req.ID]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "character already exists"})
		return
	}
	ch := &character{
		ID:    req.ID,
		Name:  req.Name,
		Level: *req.Level,
		Class: req.Class,
	}
	c.Characters = append(c.Characters, ch)
	c.CharIndex[req.ID] = ch
	writeJSON(w, http.StatusCreated, characterView(ch))
}

func handleAddEvent(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	var req struct {
		ID      string `json:"id"`
		Kind    string `json:"kind"`
		Summary string `json:"summary"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	campaignMu.Lock()
	defer campaignMu.Unlock()
	c, ok := campaigns[id]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	if req.ID == "" || req.Kind == "" {
		badRequest(w)
		return
	}
	if _, exists := c.EventIndex[req.ID]; exists {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "event already exists"})
		return
	}
	ev := &logEvent{
		ID:      req.ID,
		Kind:    req.Kind,
		Summary: req.Summary,
	}
	c.Events = append(c.Events, ev)
	c.EventIndex[req.ID] = ev
	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"id":   ev.ID,
		"kind": ev.Kind,
	})
}

func handleReadCampaignState(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	campaignMu.Lock()
	defer campaignMu.Unlock()
	c, ok := campaigns[id]
	if !ok {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown campaign"})
		return
	}
	chars := make([]map[string]interface{}, 0, len(c.Characters))
	for _, ch := range c.Characters {
		chars = append(chars, characterView(ch))
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"id":         c.ID,
		"name":       c.Name,
		"dm":         c.DM,
		"characters": chars,
		"log_count":  len(c.Events),
	})
}

package main

import (
	"encoding/json"
	"net/http"
	"strings"
	"sync"
)

type campaignCharacter struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level int    `json:"level"`
	Class string `json:"class"`
}

type campaignEvent struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Summary string `json:"summary"`
}

type campaign struct {
	ID         string
	Name       string
	DM         string
	Characters []campaignCharacter
	Events     []campaignEvent
	Quests     []*quest
	Factions   []*faction
	NPCs       []*npc
	Inventory  []inventoryEntry
	Equipment  []equipmentEntry
	Crafting   []*craftingProject
	Sessions   []*campaignSession
}

var (
	campaignMu    sync.Mutex
	campaignStore = map[string]*campaign{}
)

func campaignResponse(c *campaign) map[string]interface{} {
	return map[string]interface{}{
		"id":   c.ID,
		"name": c.Name,
		"dm":   c.DM,
	}
}

func campaignCharacterResponse(ch campaignCharacter) map[string]interface{} {
	return map[string]interface{}{
		"id":    ch.ID,
		"name":  ch.Name,
		"level": ch.Level,
		"class": ch.Class,
	}
}

func campaignEventResponse(ev campaignEvent) map[string]interface{} {
	return map[string]interface{}{
		"id":   ev.ID,
		"kind": ev.Kind,
	}
}

func handleCreateCampaign(w http.ResponseWriter, r *http.Request) {
	var req struct {
		ID   string `json:"id"`
		Name string `json:"name"`
		DM   string `json:"dm"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.DM == "" {
		writeError(w, http.StatusBadRequest, "id, name, and dm are required")
		return
	}

	campaignMu.Lock()
	if _, exists := campaignStore[req.ID]; exists {
		campaignMu.Unlock()
		writeError(w, http.StatusConflict, "campaign id already exists")
		return
	}
	c := &campaign{
		ID:         req.ID,
		Name:       req.Name,
		DM:         req.DM,
		Characters: []campaignCharacter{},
		Events:     []campaignEvent{},
		Inventory:  []inventoryEntry{},
		Equipment:  []equipmentEntry{},
		Crafting:   []*craftingProject{},
		Sessions:   []*campaignSession{},
	}
	campaignStore[req.ID] = c
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, campaignResponse(c))
}

func handleCampaignsCollection(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return
	}
	handleCreateCampaign(w, r)
}

func campaignSubPath(path string) (id, rest string, ok bool) {
	const prefix = "/v1/campaigns/"
	if !strings.HasPrefix(path, prefix) {
		return "", "", false
	}
	trimmed := strings.TrimPrefix(path, prefix)
	parts := strings.SplitN(trimmed, "/", 2)
	if len(parts) == 0 || parts[0] == "" {
		return "", "", false
	}
	if len(parts) == 1 {
		return parts[0], "", true
	}
	return parts[0], parts[1], true
}

func handleAddCharacter(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ID    string `json:"id"`
		Name  string `json:"name"`
		Level *int   `json:"level"`
		Class string `json:"class"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.Class == "" || req.Level == nil {
		writeError(w, http.StatusBadRequest, "id, name, level, and class are required")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, ch := range c.Characters {
		if ch.ID == req.ID {
			campaignMu.Unlock()
			writeError(w, http.StatusConflict, "character id already exists")
			return
		}
	}
	ch := campaignCharacter{ID: req.ID, Name: req.Name, Level: *req.Level, Class: req.Class}
	c.Characters = append(c.Characters, ch)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, campaignCharacterResponse(ch))
}

func handleAddEvent(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		ID      string `json:"id"`
		Kind    string `json:"kind"`
		Summary string `json:"summary"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Kind == "" || req.Summary == "" {
		writeError(w, http.StatusBadRequest, "id, kind, and summary are required")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, ev := range c.Events {
		if ev.ID == req.ID {
			campaignMu.Unlock()
			writeError(w, http.StatusConflict, "event id already exists")
			return
		}
	}
	ev := campaignEvent{ID: req.ID, Kind: req.Kind, Summary: req.Summary}
	c.Events = append(c.Events, ev)
	campaignMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, campaignEventResponse(ev))
}

func handleCampaignState(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	characters := make([]map[string]interface{}, 0, len(c.Characters))
	for _, ch := range c.Characters {
		characters = append(characters, campaignCharacterResponse(ch))
	}
	logCount := len(c.Events)
	resp := map[string]interface{}{
		"id":         c.ID,
		"name":       c.Name,
		"dm":         c.DM,
		"characters": characters,
		"log_count":  logCount,
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handleCampaignsSub(w http.ResponseWriter, r *http.Request) {
	id, rest, ok := campaignSubPath(r.URL.Path)
	if !ok || id == "" || rest == "" {
		writeError(w, http.StatusNotFound, "not found")
		return
	}

	if handleCampaignQuestsSub(w, r, id, rest) {
		return
	}

	if handleCampaignNPCFactionSub(w, r, id, rest) {
		return
	}

	if handleCampaignInventorySub(w, r, id, rest) {
		return
	}

	if handleCampaignCraftingSub(w, r, id, rest) {
		return
	}

	if handleCampaignSessionsSub(w, r, id, rest) {
		return
	}

	if handleCampaignAuditExportSub(w, r, id, rest) {
		return
	}

	if handleCampaignAnalyticsSub(w, r, id, rest) {
		return
	}

	switch rest {
	case "characters":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		handleAddCharacter(w, r, id)
	case "events":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		handleAddEvent(w, r, id)
	case "state":
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return
		}
		handleCampaignState(w, r, id)
	default:
		writeError(w, http.StatusNotFound, "not found")
	}
}

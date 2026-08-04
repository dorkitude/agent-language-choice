package main

import (
	"encoding/json"
	"net/http"
	"sync"
)

// Campaign state: campaigns, their party rosters, and an append-only session
// log. Ids are unique per collection, roster and log order is insertion order,
// and nothing is ever removed.
//
// State lives in memory and is mirrored to SQLite after each write; the
// in-memory maps are authoritative for reads (see store.go).

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
	Characters []*campaignCharacter
	Events     []*campaignEvent
	Quests     []*quest
	Factions   []*faction
	NPCs       []*npc
	Inventory  []*inventoryItem
	Equipment  []*equipmentAssignment
	Crafting   []*craftingProject
	Sessions   []*campaignSession
}

// campaignStore holds campaigns by id plus the id list in creation order, since
// map iteration order would otherwise make snapshots non-deterministic.
type campaignStore struct {
	mu        sync.Mutex
	campaigns map[string]*campaign
	order     []string
}

var campaigns = &campaignStore{campaigns: map[string]*campaign{}}

// add registers a campaign, preserving creation order. Callers must hold s.mu
// and must have already rejected duplicate ids, or order would gain a second
// entry for the same campaign.
func (s *campaignStore) add(c *campaign) {
	s.campaigns[c.ID] = c
	s.order = append(s.order, c.ID)
}

// ---------- request payloads ----------

type campaignRequest struct {
	ID   *string `json:"id"`
	Name *string `json:"name"`
	DM   *string `json:"dm"`
}

type campaignResponse struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

type campaignCharacterRequest struct {
	ID    *string          `json:"id"`
	Name  *string          `json:"name"`
	Level *json.RawMessage `json:"level"`
	Class *string          `json:"class"`
}

type campaignEventRequest struct {
	ID      *string `json:"id"`
	Kind    *string `json:"kind"`
	Summary *string `json:"summary"`
}

type campaignEventResponse struct {
	ID   string `json:"id"`
	Kind string `json:"kind"`
}

type campaignStateResponse struct {
	ID         string               `json:"id"`
	Name       string               `json:"name"`
	DM         string               `json:"dm"`
	Characters []*campaignCharacter `json:"characters"`
	LogCount   int                  `json:"log_count"`
}

// ---------- POST /v1/campaigns ----------

func handleCreateCampaign(w http.ResponseWriter, r *http.Request) {
	var req campaignRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	dm, ok := requiredString(req.DM)
	if !ok {
		writeError(w, http.StatusBadRequest, "dm is required")
		return
	}

	campaigns.mu.Lock()
	if _, exists := campaigns.campaigns[id]; exists {
		campaigns.mu.Unlock()
		writeError(w, http.StatusConflict, "campaign id already exists")
		return
	}
	campaigns.add(&campaign{
		ID:         id,
		Name:       name,
		DM:         dm,
		Characters: []*campaignCharacter{},
		Events:     []*campaignEvent{},
		Quests:     []*quest{},
		Factions:   []*faction{},
		NPCs:       []*npc{},
		Inventory:  []*inventoryItem{},
		Equipment:  []*equipmentAssignment{},
		Crafting:   []*craftingProject{},
		Sessions:   []*campaignSession{},
	})
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, campaignResponse{ID: id, Name: name, DM: dm})
}

// ---------- POST /v1/campaigns/{id}/characters ----------

func handleAddCampaignCharacter(w http.ResponseWriter, r *http.Request) {
	var req campaignCharacterRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	name, ok := requiredString(req.Name)
	if !ok {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	level, ok := asInt(req.Level)
	if !ok {
		writeError(w, http.StatusBadRequest, "level must be an integer")
		return
	}
	if level < 1 || level > 20 {
		writeError(w, http.StatusBadRequest, "level must be between 1 and 20")
		return
	}
	class, ok := requiredString(req.Class)
	if !ok {
		writeError(w, http.StatusBadRequest, "class is required")
		return
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, existing := range c.Characters {
		if existing.ID == id {
			campaigns.mu.Unlock()
			writeError(w, http.StatusConflict, "character id already exists")
			return
		}
	}
	entry := &campaignCharacter{ID: id, Name: name, Level: level, Class: class}
	c.Characters = append(c.Characters, entry)
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, entry)
}

// ---------- POST /v1/campaigns/{id}/events ----------

func handleAddCampaignEvent(w http.ResponseWriter, r *http.Request) {
	var req campaignEventRequest
	if err := decodeBody(r, &req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	id, ok := requiredString(req.ID)
	if !ok {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	kind, ok := requiredString(req.Kind)
	if !ok {
		writeError(w, http.StatusBadRequest, "kind is required")
		return
	}
	summary := ""
	if req.Summary != nil {
		summary = *req.Summary
	}

	campaigns.mu.Lock()
	c, found := campaigns.campaigns[r.PathValue("id")]
	if !found {
		campaigns.mu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	for _, existing := range c.Events {
		if existing.ID == id {
			campaigns.mu.Unlock()
			writeError(w, http.StatusConflict, "event id already exists")
			return
		}
	}
	c.Events = append(c.Events, &campaignEvent{ID: id, Kind: kind, Summary: summary})
	campaigns.mu.Unlock()
	flush()

	writeJSON(w, http.StatusCreated, campaignEventResponse{ID: id, Kind: kind})
}

// ---------- GET /v1/campaigns/{id}/state ----------

func handleCampaignState(w http.ResponseWriter, r *http.Request) {
	campaigns.mu.Lock()
	defer campaigns.mu.Unlock()
	c, ok := campaigns.campaigns[r.PathValue("id")]
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	writeJSON(w, http.StatusOK, campaignStateResponse{
		ID:         c.ID,
		Name:       c.Name,
		DM:         c.DM,
		Characters: append([]*campaignCharacter{}, c.Characters...),
		LogCount:   len(c.Events),
	})
}

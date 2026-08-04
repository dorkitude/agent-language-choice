package main

import (
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
	ID               string `json:"id"`
	Name             string `json:"name"`
	DM               string `json:"dm"`
	Characters       []*campaignCharacter
	Events           []*campaignEvent
	Quests           []*campaignQuest
	Factions         []*campaignFaction
	NPCs             []*campaignNPC
	Inventory        []*campaignInventoryItem
	Equipment        []*campaignEquipmentItem
	CraftingProjects []*campaignCraftingProject
	Sessions         []*campaignSession
}

// campaignsMu guards campaigns, the in-memory index mirroring the campaigns,
// campaign_characters, and campaign_events tables.
var (
	campaignsMu sync.Mutex
	campaigns   = map[string]*campaign{}
)

type createCampaignRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
	DM   string `json:"dm"`
}

func createCampaignHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req createCampaignRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.DM == "" {
		writeError(w, http.StatusBadRequest, "dm is required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	if _, exists := campaigns[req.ID]; exists {
		writeError(w, http.StatusConflict, "campaign id already exists")
		return
	}

	c := &campaign{ID: req.ID, Name: req.Name, DM: req.DM}
	if err := saveCampaignToDB(c); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save campaign")
		return
	}
	campaigns[c.ID] = c

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":   c.ID,
		"name": c.Name,
		"dm":   c.DM,
	})
}

type addCampaignCharacterRequest struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Level *int   `json:"level"`
	Class string `json:"class"`
}

func addCampaignCharacterHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req addCampaignCharacterRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	if req.Level == nil {
		writeError(w, http.StatusBadRequest, "level is required")
		return
	}
	if req.Class == "" {
		writeError(w, http.StatusBadRequest, "class is required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	for _, ch := range c.Characters {
		if ch.ID == req.ID {
			writeError(w, http.StatusConflict, "character id already exists")
			return
		}
	}

	ch := &campaignCharacter{ID: req.ID, Name: req.Name, Level: *req.Level, Class: req.Class}
	if err := saveCampaignCharacterToDB(c.ID, ch); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save character")
		return
	}
	c.Characters = append(c.Characters, ch)

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":    ch.ID,
		"name":  ch.Name,
		"level": ch.Level,
		"class": ch.Class,
	})
}

type addCampaignEventRequest struct {
	ID      string `json:"id"`
	Kind    string `json:"kind"`
	Summary string `json:"summary"`
}

func addCampaignEventHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req addCampaignEventRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.ID == "" {
		writeError(w, http.StatusBadRequest, "id is required")
		return
	}
	if req.Kind == "" {
		writeError(w, http.StatusBadRequest, "kind is required")
		return
	}
	if req.Summary == "" {
		writeError(w, http.StatusBadRequest, "summary is required")
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	for _, ev := range c.Events {
		if ev.ID == req.ID {
			writeError(w, http.StatusConflict, "event id already exists")
			return
		}
	}

	ev := &campaignEvent{ID: req.ID, Kind: req.Kind, Summary: req.Summary}
	if err := saveCampaignEventToDB(c.ID, ev); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save event")
		return
	}
	c.Events = append(c.Events, ev)

	writeJSON(w, http.StatusCreated, map[string]any{
		"id":   ev.ID,
		"kind": ev.Kind,
	})
}

func campaignStateHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	characters := make([]map[string]any, 0, len(c.Characters))
	for _, ch := range c.Characters {
		characters = append(characters, map[string]any{
			"id":    ch.ID,
			"name":  ch.Name,
			"level": ch.Level,
			"class": ch.Class,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         c.ID,
		"name":       c.Name,
		"dm":         c.DM,
		"characters": characters,
		"log_count":  len(c.Events),
	})
}

// campaignsRouter dispatches /v1/campaigns and /v1/campaigns/{id}/... routes,
// matching the trailing path segment since http.ServeMux only supports
// prefix matching on the registered "/v1/campaigns/" pattern.
func campaignsRouter(w http.ResponseWriter, r *http.Request) {
	path := r.URL.Path
	if path == "/v1/campaigns" {
		createCampaignHandler(w, r)
		return
	}

	rest := path[len("/v1/campaigns/"):]
	if idx := strings.Index(rest, "/quests"); idx > 0 {
		campaignID := rest[:idx]
		questRest := rest[idx+1:]
		if campaignQuestsRouter(w, r, campaignID, questRest) {
			return
		}
	}
	if idx := strings.Index(rest, "/downtime"); idx > 0 {
		campaignID := rest[:idx]
		downtimeRest := rest[idx+1:]
		if campaignCraftingRouter(w, r, campaignID, downtimeRest) {
			return
		}
	}
	if idx := strings.Index(rest, "/sessions"); idx > 0 {
		campaignID := rest[:idx]
		sessionsRest := rest[idx+1:]
		if campaignSessionsRouter(w, r, campaignID, sessionsRest) {
			return
		}
	}
	if idx := strings.Index(rest, "/analytics"); idx > 0 {
		campaignID := rest[:idx]
		analyticsRest := rest[idx+1:]
		if campaignAnalyticsRouter(w, r, campaignID, analyticsRest) {
			return
		}
	}
	if id, ok := extractSessionID(rest, "", "/characters"); ok && id != "" {
		addCampaignCharacterHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/events"); ok && id != "" {
		addCampaignEventHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/state"); ok && id != "" {
		campaignStateHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/audit"); ok && id != "" {
		campaignAuditHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/export"); ok && id != "" {
		campaignExportHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/factions"); ok && id != "" {
		createFactionHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/npcs"); ok && id != "" {
		createNPCHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/relationships"); ok && id != "" {
		relationshipSummaryHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/inventory/summary"); ok && id != "" {
		inventorySummaryHandler(w, r, id)
		return
	}
	if id, ok := extractSessionID(rest, "", "/inventory"); ok && id != "" {
		addInventoryHandler(w, r, id)
		return
	}
	if idx := strings.Index(rest, "/characters/"); idx > 0 {
		campaignID := rest[:idx]
		charRest := rest[idx+len("/characters/"):]
		if charID, ok := extractSessionID(charRest, "", "/equipment"); ok && charID != "" {
			assignEquipmentHandler(w, r, campaignID, charID)
			return
		}
	}

	writeError(w, http.StatusNotFound, "unknown route")
}

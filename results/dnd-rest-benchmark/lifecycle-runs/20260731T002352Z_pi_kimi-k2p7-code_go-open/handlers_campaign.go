package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func createCampaignHandler(w http.ResponseWriter, r *http.Request) {
	var req campaign
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if strings.TrimSpace(req.DM) == "" {
		badRequest(w, "dm is required")
		return
	}

	if err := dbCreateCampaign(&req); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "campaign id already exists")
			return
		}
		log.Printf("create campaign: %v", err)
		badRequest(w, "failed to create campaign")
		return
	}

	writeJSON(w, http.StatusCreated, &req)
}

func addCharacterHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req character
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Name) == "" {
		badRequest(w, "name is required")
		return
	}
	if req.Level <= 0 {
		badRequest(w, "level must be a positive integer")
		return
	}
	if strings.TrimSpace(req.Class) == "" {
		badRequest(w, "class is required")
		return
	}

	if err := dbCreateCharacter(&req, campaignID); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "character id already exists")
			return
		}
		log.Printf("create character: %v", err)
		badRequest(w, "failed to create character")
		return
	}

	writeJSON(w, http.StatusCreated, &req)
}

func addEventHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req campaignEvent
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.ID) == "" {
		badRequest(w, "id is required")
		return
	}
	if strings.TrimSpace(req.Kind) == "" {
		badRequest(w, "kind is required")
		return
	}
	if strings.TrimSpace(req.Summary) == "" {
		badRequest(w, "summary is required")
		return
	}

	if err := dbCreateEvent(campaignID, &req); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "event id already exists")
			return
		}
		log.Printf("create event: %v", err)
		badRequest(w, "failed to create event")
		return
	}

	writeJSON(w, http.StatusCreated, map[string]string{
		"id":   req.ID,
		"kind": req.Kind,
	})
}

func getCampaignStateHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	c := requireCampaign(w, campaignID)
	if c == nil {
		return
	}

	characters, err := dbGetCharactersByCampaign(campaignID)
	if err != nil {
		log.Printf("get characters: %v", err)
		badRequest(w, "failed to read campaign state")
		return
	}
	if characters == nil {
		characters = []character{}
	}

	logCount, err := dbCountEventsByCampaign(campaignID)
	if err != nil {
		log.Printf("count events: %v", err)
		badRequest(w, "failed to read campaign state")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"id":         c.ID,
		"name":       c.Name,
		"dm":         c.DM,
		"characters": characters,
		"log_count":  logCount,
	})
}

func auditCampaignHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	c := requireCampaign(w, campaignID)
	if c == nil {
		return
	}

	events, err := dbCountEventsByCampaign(campaignID)
	if err != nil {
		log.Printf("count events: %v", err)
		badRequest(w, "failed to read campaign audit")
		return
	}
	quests, err := dbCountQuestsByCampaign(campaignID)
	if err != nil {
		log.Printf("count quests: %v", err)
		badRequest(w, "failed to read campaign audit")
		return
	}
	npcs, err := dbCountNPCsByCampaign(campaignID)
	if err != nil {
		log.Printf("count npcs: %v", err)
		badRequest(w, "failed to read campaign audit")
		return
	}
	sessions, err := dbCountSessionsByCampaign(campaignID)
	if err != nil {
		log.Printf("count sessions: %v", err)
		badRequest(w, "failed to read campaign audit")
		return
	}

	writeJSON(w, http.StatusOK, auditResponse{
		CampaignID: c.ID,
		Events:     events,
		Quests:     quests,
		NPCs:       npcs,
		Sessions:   sessions,
	})
}

func exportCampaignHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	c := requireCampaign(w, campaignID)
	if c == nil {
		return
	}

	characters, err := dbCountCharactersByCampaign(campaignID)
	if err != nil {
		log.Printf("count characters: %v", err)
		badRequest(w, "failed to export campaign")
		return
	}
	quests, err := dbCountQuestsByCampaign(campaignID)
	if err != nil {
		log.Printf("count quests: %v", err)
		badRequest(w, "failed to export campaign")
		return
	}
	npcs, err := dbCountNPCsByCampaign(campaignID)
	if err != nil {
		log.Printf("count npcs: %v", err)
		badRequest(w, "failed to export campaign")
		return
	}
	inventory, err := dbCountInventoryItemsByCampaign(campaignID)
	if err != nil {
		log.Printf("count inventory: %v", err)
		badRequest(w, "failed to export campaign")
		return
	}
	sessions, err := dbCountSessionsByCampaign(campaignID)
	if err != nil {
		log.Printf("count sessions: %v", err)
		badRequest(w, "failed to export campaign")
		return
	}

	writeJSON(w, http.StatusOK, exportResponse{
		CampaignID:     c.ID,
		Name:           c.Name,
		Characters:     characters,
		Quests:         quests,
		NPCs:           npcs,
		InventoryItems: inventory,
		Sessions:       sessions,
		SchemaVersion:  schemaVersion,
	})
}

package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func createFactionHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req faction
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
	if strings.TrimSpace(req.Stance) == "" {
		badRequest(w, "stance is required")
		return
	}

	if err := dbCreateFaction(campaignID, &req); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "faction id already exists")
			return
		}
		log.Printf("create faction: %v", err)
		badRequest(w, "failed to create faction")
		return
	}

	writeJSON(w, http.StatusCreated, &req)
}

func createNPCHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	var req npc
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
	if strings.TrimSpace(req.FactionID) == "" {
		badRequest(w, "faction_id is required")
		return
	}
	f, err := dbGetFaction(req.FactionID)
	if err != nil {
		log.Printf("get faction: %v", err)
		badRequest(w, "failed to create npc")
		return
	}
	if f == nil || f.CampaignID != campaignID {
		badRequest(w, "faction not found")
		return
	}

	if err := dbCreateNPC(campaignID, &req); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "npc id already exists")
			return
		}
		if isForeignKeyViolation(err) {
			badRequest(w, "faction not found")
			return
		}
		log.Printf("create npc: %v", err)
		badRequest(w, "failed to create npc")
		return
	}

	writeJSON(w, http.StatusCreated, &req)
}

func getRelationshipsHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	if requireCampaign(w, campaignID) == nil {
		return
	}

	factionCount, err := dbCountFactionsByCampaign(campaignID)
	if err != nil {
		log.Printf("count factions: %v", err)
		badRequest(w, "failed to read relationships")
		return
	}

	npcCount, err := dbCountNPCsByCampaign(campaignID)
	if err != nil {
		log.Printf("count npcs: %v", err)
		badRequest(w, "failed to read relationships")
		return
	}

	friendlyCount, err := dbCountFriendlyNPCsByCampaign(campaignID)
	if err != nil {
		log.Printf("count friendly npcs: %v", err)
		badRequest(w, "failed to read relationships")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":   campaignID,
		"factions":      factionCount,
		"npcs":          npcCount,
		"friendly_npcs": friendlyCount,
	})
}

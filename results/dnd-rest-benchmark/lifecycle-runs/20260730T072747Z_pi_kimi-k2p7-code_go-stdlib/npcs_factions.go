package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// faction is a campaign organization or group with a stance toward the party.
type faction struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Stance string `json:"stance"`
}

// npc is a non-player character tied to a campaign and optionally a faction.
type npc struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition int    `json:"disposition"`
}

// relationshipSummary aggregates factions and NPCs for a campaign.
type relationshipSummary struct {
	CampaignID   string `json:"campaign_id"`
	Factions     int    `json:"factions"`
	NPCs         int    `json:"npcs"`
	FriendlyNPCs int    `json:"friendly_npcs"`
}

// queryFactionExists returns true when a faction with the given ID exists.
func queryFactionExists(id string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM factions WHERE id=%s LIMIT 1;", sq(id)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// queryFactionExistsInCampaign returns true when a faction belongs to the given campaign.
func queryFactionExistsInCampaign(id, campaignID string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM factions WHERE id=%s AND campaign_id=%s LIMIT 1;", sq(id), sq(campaignID)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// queryNPCExists returns true when an NPC with the given ID exists.
func queryNPCExists(id string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT 1 FROM npcs WHERE id=%s LIMIT 1;", sq(id)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		One int `json:"1"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	return len(rows) > 0, nil
}

// createFactionHandler creates a new faction under a campaign.
func createFactionHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req faction
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.Stance == "" {
		writeError(w, http.StatusBadRequest, "invalid faction")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("create faction campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	dup, err := queryFactionExists(req.ID)
	if err != nil {
		log.Printf("create faction duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "faction already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO factions (id, campaign_id, name, stance) VALUES (%s, %s, %s, %s);",
		sq(req.ID), sq(campaignID), sq(req.Name), sq(req.Stance))); err != nil {
		log.Printf("create faction insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

// createNPCHandler creates a new NPC under a campaign, optionally tied to a faction.
func createNPCHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	var req npc
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.ID == "" || req.Name == "" || req.FactionID == "" {
		writeError(w, http.StatusBadRequest, "invalid npc")
		return
	}

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("create npc campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	factionExists, err := queryFactionExistsInCampaign(req.FactionID, campaignID)
	if err != nil {
		log.Printf("create npc faction exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !factionExists {
		writeError(w, http.StatusBadRequest, "invalid faction")
		return
	}

	dup, err := queryNPCExists(req.ID)
	if err != nil {
		log.Printf("create npc duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "npc already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (%s, %s, %s, %s, %d);",
		sq(req.ID), sq(campaignID), sq(req.Name), sq(req.FactionID), req.Disposition)); err != nil {
		log.Printf("create npc insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, req)
}

// getRelationshipSummaryHandler returns the number of factions, NPCs, and friendly NPCs for a campaign.
func getRelationshipSummaryHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")

	dbMu.Lock()
	defer dbMu.Unlock()

	exists, err := queryCampaignExists(campaignID)
	if err != nil {
		log.Printf("relationship summary campaign exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT COUNT(*) AS count FROM factions WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		log.Printf("relationship summary factions query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var factionCounts []struct {
		Count int `json:"count"`
	}
	if err := json.Unmarshal(out, &factionCounts); err != nil {
		log.Printf("relationship summary factions unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	factionCount := 0
	if len(factionCounts) > 0 {
		factionCount = factionCounts[0].Count
	}

	out, err = dbQuery(fmt.Sprintf("SELECT COUNT(*) AS count FROM npcs WHERE campaign_id=%s;", sq(campaignID)))
	if err != nil {
		log.Printf("relationship summary npcs query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var npcCounts []struct {
		Count int `json:"count"`
	}
	if err := json.Unmarshal(out, &npcCounts); err != nil {
		log.Printf("relationship summary npcs unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	npcCount := 0
	if len(npcCounts) > 0 {
		npcCount = npcCounts[0].Count
	}

	out, err = dbQuery(fmt.Sprintf("SELECT COUNT(*) AS count FROM npcs WHERE campaign_id=%s AND disposition > 0;", sq(campaignID)))
	if err != nil {
		log.Printf("relationship summary friendly npcs query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var friendlyCounts []struct {
		Count int `json:"count"`
	}
	if err := json.Unmarshal(out, &friendlyCounts); err != nil {
		log.Printf("relationship summary friendly npcs unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	friendlyCount := 0
	if len(friendlyCounts) > 0 {
		friendlyCount = friendlyCounts[0].Count
	}

	writeJSON(w, http.StatusOK, relationshipSummary{
		CampaignID:   campaignID,
		Factions:     factionCount,
		NPCs:         npcCount,
		FriendlyNPCs: friendlyCount,
	})
}

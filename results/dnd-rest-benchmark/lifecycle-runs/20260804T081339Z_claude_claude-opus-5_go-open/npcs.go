package main

import (
	"log"
	"net/http"
	"strings"
)

// Factions and NPCs are the campaign's social layer: a faction is a standalone
// record with a stance toward the party, and an NPC optionally belongs to one.
// Both are ordered children of a campaign like the roster, the event log and
// the quest list, so they follow the same insert-position convention.
//
// The relationship summary derives every number from these two tables; nothing
// is cached. An NPC counts as friendly when its disposition is positive, which
// keeps "friendly" a property of the individual rather than of their faction.

// defaultStance applies when a faction is created without one. Stance is free
// text otherwise: the spec names "friendly" but fixes no closed set, so an
// unrecognized value is stored rather than rejected.
const defaultStance = "neutral"

// ---------- POST /v1/campaigns/{id}/factions ----------

type factionRequest struct {
	ID     *string `json:"id"`
	Name   *string `json:"name"`
	Stance *string `json:"stance"`
}

type factionResponse struct {
	ID     string `json:"id"`
	Name   string `json:"name"`
	Stance string `json:"stance"`
}

func handleCampaignFactions(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req factionRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	name, ok := requireField(w, req.Name, "name")
	if !ok {
		return
	}
	stance := defaultStance
	if req.Stance != nil {
		if trimmed := strings.TrimSpace(*req.Stance); trimmed != "" {
			stance = trimmed
		}
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?`, campaignID, id,
	); err != nil {
		writeStorageFailure(w, "faction lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "faction id already exists")
		return
	}

	position, err := nextPosition(`campaign_factions`, campaignID)
	if err != nil {
		writeStorageFailure(w, "faction position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_factions (campaign_id, id, position, name, stance) VALUES (?, ?, ?, ?, ?)`,
		campaignID, id, position, name, stance,
	); err != nil {
		log.Printf("faction insert failed: %v", err)
		writeError(w, http.StatusConflict, "faction id already exists")
		return
	}
	writeJSON(w, http.StatusCreated, factionResponse{ID: id, Name: name, Stance: stance})
}

// ---------- POST /v1/campaigns/{id}/npcs ----------

type npcRequest struct {
	ID          *string `json:"id"`
	Name        *string `json:"name"`
	FactionID   *string `json:"faction_id"`
	Disposition *int    `json:"disposition"`
}

// FactionID stays a plain string rather than a pointer so an unaffiliated NPC
// renders as "" instead of null, matching how the campaign roster reports
// optional fields.
type npcResponse struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	FactionID   string `json:"faction_id"`
	Disposition int    `json:"disposition"`
}

func handleCampaignNPCs(w http.ResponseWriter, r *http.Request) {
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}
	var req npcRequest
	if !decodeBody(w, r, &req) {
		return
	}
	id, ok := requireField(w, req.ID, "id")
	if !ok {
		return
	}
	name, ok := requireField(w, req.Name, "name")
	if !ok {
		return
	}
	out := npcResponse{ID: id, Name: name}
	if req.FactionID != nil {
		out.FactionID = strings.TrimSpace(*req.FactionID)
	}
	if req.Disposition != nil {
		out.Disposition = *req.Disposition
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	// Membership is optional, but naming a faction that this campaign does not
	// have is a mistake rather than an unaffiliated NPC.
	if out.FactionID != "" {
		exists, err := rowExists(
			`SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?`, campaignID, out.FactionID,
		)
		if err != nil {
			writeStorageFailure(w, "faction lookup failed", err)
			return
		}
		if !exists {
			writeError(w, http.StatusNotFound, "faction not found")
			return
		}
	}
	if exists, err := rowExists(
		`SELECT 1 FROM campaign_npcs WHERE campaign_id = ? AND id = ?`, campaignID, id,
	); err != nil {
		writeStorageFailure(w, "npc lookup failed", err)
		return
	} else if exists {
		writeError(w, http.StatusConflict, "npc id already exists")
		return
	}

	position, err := nextPosition(`campaign_npcs`, campaignID)
	if err != nil {
		writeStorageFailure(w, "npc position lookup failed", err)
		return
	}
	if _, err := db.Exec(
		`INSERT INTO campaign_npcs (campaign_id, id, position, name, faction_id, disposition)
		 VALUES (?, ?, ?, ?, ?, ?)`,
		campaignID, out.ID, position, out.Name, out.FactionID, out.Disposition,
	); err != nil {
		log.Printf("npc insert failed: %v", err)
		writeError(w, http.StatusConflict, "npc id already exists")
		return
	}
	writeJSON(w, http.StatusCreated, out)
}

// ---------- GET /v1/campaigns/{id}/relationships ----------

type relationshipSummaryResponse struct {
	CampaignID   string `json:"campaign_id"`
	Factions     int    `json:"factions"`
	NPCs         int    `json:"npcs"`
	FriendlyNPCs int    `json:"friendly_npcs"`
}

func handleCampaignRelationships(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}
	campaignID, ok := requirePathValue(w, r, "id", "campaign id")
	if !ok {
		return
	}

	storeMu.Lock()
	defer storeMu.Unlock()

	if !requireCampaign(w, campaignID) {
		return
	}
	out := relationshipSummaryResponse{CampaignID: campaignID}
	if err := db.QueryRow(
		`SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?`, campaignID,
	).Scan(&out.Factions); err != nil {
		writeStorageFailure(w, "faction count failed", err)
		return
	}
	if err := db.QueryRow(
		`SELECT COUNT(*), COALESCE(SUM(disposition > 0), 0) FROM campaign_npcs WHERE campaign_id = ?`,
		campaignID,
	).Scan(&out.NPCs, &out.FriendlyNPCs); err != nil {
		writeStorageFailure(w, "npc count failed", err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

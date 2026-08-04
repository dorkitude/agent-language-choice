package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// campaignNPC is the durable campaign-scoped NPC record with a private DM
// agenda and a player-visible public status.
type campaignNPC struct {
	CampaignID   string `json:"campaign_id"`
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// createNPCRequest binds the payload for creating a new campaign NPC.
type createNPCRequest struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// npcDMResponse is the full NPC shape exposed to the campaign DM.
type npcDMResponse struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// npcPlayerResponse is the reduced NPC shape exposed to player members. It
// deliberately omits the private agenda field.
type npcPlayerResponse struct {
	NPCID        string `json:"npc_id"`
	Name         string `json:"name"`
	PublicStatus string `json:"public_status"`
}

// updateNPCAgendaRequest binds the payload for updating an NPC agenda and
// public status.
type updateNPCAgendaRequest struct {
	Agenda       string `json:"agenda"`
	PublicStatus string `json:"public_status"`
}

// queryCampaignNPC loads a single campaign NPC by campaign and npc id. The
// caller must hold dbMu.
func queryCampaignNPC(campaignID, npcID string) (*campaignNPC, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT campaign_id, npc_id, name, agenda, public_status FROM campaign_npcs WHERE campaign_id=%s AND npc_id=%s LIMIT 1;", sq(campaignID), sq(npcID)))
	if err != nil {
		return nil, false, err
	}
	var rows []campaignNPC
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// createPlayNPCHandler lets the campaign DM create a new NPC for a play
// campaign. Only the campaign owner may call it. Duplicate npc_id values
// within the same campaign are rejected with 409.
func createPlayNPCHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createNPCRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.NPCID == "" || req.Name == "" || req.Agenda == "" || req.PublicStatus == "" {
		writeError(w, http.StatusBadRequest, "invalid npc")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_npcs WHERE campaign_id=%s AND npc_id=%s LIMIT 1;", sq(campaignID), sq(req.NPCID)))
	if err != nil {
		log.Printf("npc exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "npc already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (%s, %s, %s, %s, %s);",
		sq(campaignID), sq(req.NPCID), sq(req.Name), sq(req.Agenda), sq(req.PublicStatus))); err != nil {
		log.Printf("npc insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, npcDMResponse{
		NPCID:        req.NPCID,
		Name:         req.Name,
		Agenda:       req.Agenda,
		PublicStatus: req.PublicStatus,
	})
}

// updatePlayNPCAgendaHandler lets the campaign DM update an NPC's agenda and
// public status. Only the campaign owner may call it. Unknown NPCs return 404.
func updatePlayNPCAgendaHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	npc, ok, err := queryCampaignNPC(campaignID, npcID)
	if err != nil {
		log.Printf("npc update query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	var req updateNPCAgendaRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Agenda == "" || req.PublicStatus == "" {
		writeError(w, http.StatusBadRequest, "invalid npc")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_npcs SET agenda=%s, public_status=%s WHERE campaign_id=%s AND npc_id=%s;",
		sq(req.Agenda), sq(req.PublicStatus), sq(campaignID), sq(npcID))); err != nil {
		log.Printf("npc update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, npcDMResponse{
		NPCID:        npc.NPCID,
		Name:         npc.Name,
		Agenda:       req.Agenda,
		PublicStatus: req.PublicStatus,
	})
}

// getPlayNPCHandler returns a campaign NPC to an authenticated campaign member.
// The DM receives the full shape including agenda; players receive only the
// public fields.
func getPlayNPCHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	npcID := r.PathValue("npc_id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("npc get campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	npc, ok, err := queryCampaignNPC(campaignID, npcID)
	if err != nil {
		log.Printf("npc get query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "npc not found")
		return
	}

	if campaign.Owner == username {
		writeJSON(w, http.StatusOK, npcDMResponse{
			NPCID:        npc.NPCID,
			Name:         npc.Name,
			Agenda:       npc.Agenda,
			PublicStatus: npc.PublicStatus,
		})
		return
	}

	writeJSON(w, http.StatusOK, npcPlayerResponse{
		NPCID:        npc.NPCID,
		Name:         npc.Name,
		PublicStatus: npc.PublicStatus,
	})
}

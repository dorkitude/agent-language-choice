package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// createSpectatorRequest binds the payload for a new spectator ticket.
type createSpectatorRequest struct {
	SpectatorID string `json:"spectator_id"`
}

// createSpectatorResponse is the exact shape returned after creating a
// spectator ticket.
type createSpectatorResponse struct {
	SpectatorID string `json:"spectator_id"`
	Token       string `json:"token"`
}

// spectatorViewResponse is the public read-only campaign summary exposed to
// spectators. It deliberately omits member names, character IDs, private notes,
// chat, tokens, ownership, and internal IDs.
type spectatorViewResponse struct {
	CampaignID string `json:"campaign_id"`
	Name       string `json:"name"`
	Status     string `json:"status"`
	PartySize  int    `json:"party_size"`
	Story      string `json:"story"`
}

// bearerSpectatorID extracts the spectator ID from an Authorization header of
// the form "Bearer spectator-<id>". It returns false for any other bearer
// scheme so that callers can distinguish spectator tokens from session tokens.
func bearerSpectatorID(r *http.Request) (string, bool) {
	auth := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if auth == "" || !strings.HasPrefix(auth, prefix) {
		return "", false
	}
	token := strings.TrimPrefix(auth, prefix)
	if !strings.HasPrefix(token, "spectator-") {
		return "", false
	}
	return strings.TrimPrefix(token, "spectator-"), true
}

// querySpectatorTicket loads a spectator ticket by spectator ID. The caller
// must hold dbMu. The bool result indicates whether the ticket exists.
func querySpectatorTicket(spectatorID string) (campaignID string, ok bool, err error) {
	out, err := dbQuery(fmt.Sprintf("SELECT campaign_id FROM campaign_spectators WHERE spectator_id=%s LIMIT 1;", sq(spectatorID)))
	if err != nil {
		return "", false, err
	}
	var rows []struct {
		CampaignID string `json:"campaign_id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return "", false, err
	}
	if len(rows) == 0 {
		return "", false, nil
	}
	return rows[0].CampaignID, true, nil
}

// createSpectatorHandler lets a campaign owner issue a read-only spectator
// ticket for a campaign. The spectator ID must be a nonempty string and
// globally unique across all spectator tickets.
func createSpectatorHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")
	if _, ok := requireCampaignOwner(w, r, campaignID); !ok {
		return
	}

	var req createSpectatorRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SpectatorID == "" {
		writeError(w, http.StatusBadRequest, "invalid spectator_id")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_spectators WHERE spectator_id=%s LIMIT 1;", sq(req.SpectatorID)))
	if err != nil {
		log.Printf("create spectator duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "spectator_id already exists")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_spectators (campaign_id, spectator_id) VALUES (%s, %s);",
		sq(campaignID), sq(req.SpectatorID))); err != nil {
		log.Printf("create spectator insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, createSpectatorResponse{
		SpectatorID: req.SpectatorID,
		Token:       "spectator-" + req.SpectatorID,
	})
}

// getSpectatorViewHandler returns the public read-only view of a campaign
// for an authenticated spectator. It accepts only "Bearer spectator-<id>"
// tokens; session tokens receive 403, and missing or invalid tokens receive
// 401. A valid spectator ticket for a different campaign returns 403, and an
// unknown campaign with a valid-shaped spectator ticket returns 404.
func getSpectatorViewHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	auth := r.Header.Get("Authorization")
	const prefix = "Bearer "
	if auth == "" || !strings.HasPrefix(auth, prefix) {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	token := strings.TrimPrefix(auth, prefix)
	if strings.HasPrefix(token, "session-") {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	spectatorID, ok := bearerSpectatorID(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}

	ticketCampaignID, exists, err := querySpectatorTicket(spectatorID)
	if err != nil {
		log.Printf("spectator view ticket query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}

	campaign, exists, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("spectator view campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	if ticketCampaignID != campaignID {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("spectator view members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	proj, err := rebuildProjection(campaignID)
	if err != nil {
		log.Printf("spectator view projection rebuild error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, spectatorViewResponse{
		CampaignID: campaign.ID,
		Name:       campaign.Name,
		Status:     campaign.Status,
		PartySize:  len(members),
		Story:      proj.Story,
	})
}

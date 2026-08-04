package main

import (
	"net/http"
	"strings"
	"sync"
)

// playSpectator is a read-only ticket letting its bearer view a campaign's
// public spectator projection. SpectatorID is globally unique across all
// campaigns because the bearer token ("spectator-<id>") encodes only the
// spectator id, with no campaign id alongside it.
type playSpectator struct {
	SpectatorID string
	CampaignID  string
}

// playSpectatorsMu guards playSpectators, the in-memory index mirroring the
// play_spectators table. It is keyed by spectator id.
var (
	playSpectatorsMu sync.Mutex
	playSpectators   = map[string]*playSpectator{}
)

type createSpectatorRequest struct {
	SpectatorID string `json:"spectator_id"`
}

// createSpectatorHandler lets only the campaign dm mint a spectator ticket.
func createSpectatorHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createSpectatorRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign dm may issue spectator tokens")
		return
	}

	if req.SpectatorID == "" {
		writeError(w, http.StatusBadRequest, "spectator_id is required")
		return
	}

	playSpectatorsMu.Lock()
	defer playSpectatorsMu.Unlock()

	if _, exists := playSpectators[req.SpectatorID]; exists {
		writeError(w, http.StatusConflict, "spectator_id already exists")
		return
	}

	s := &playSpectator{SpectatorID: req.SpectatorID, CampaignID: campaignID}
	if err := saveSpectatorToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save spectator ticket")
		return
	}
	playSpectators[s.SpectatorID] = s

	writeJSON(w, http.StatusCreated, map[string]any{
		"spectator_id": s.SpectatorID,
		"token":        "spectator-" + s.SpectatorID,
	})
}

// spectatorViewHandler returns a read-only, mutation-free projection of a
// campaign for a spectator ticket bearer. It is authenticated exclusively by
// "Authorization: Bearer spectator-<id>" and never accepts normal dm/player
// session tokens.
func spectatorViewHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	authHeader := r.Header.Get("Authorization")
	const spectatorPrefix = "Bearer spectator-"
	const sessionPrefix = "Bearer session-"

	if strings.HasPrefix(authHeader, sessionPrefix) {
		writeError(w, http.StatusForbidden, "session tokens may not access the spectator view")
		return
	}

	spectatorID := strings.TrimPrefix(authHeader, spectatorPrefix)
	if !strings.HasPrefix(authHeader, spectatorPrefix) || spectatorID == "" {
		writeError(w, http.StatusUnauthorized, "missing or invalid spectator token")
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	playSpectatorsMu.Lock()
	ticket, exists := playSpectators[spectatorID]
	playSpectatorsMu.Unlock()
	if !exists {
		writeError(w, http.StatusUnauthorized, "missing or invalid spectator token")
		return
	}
	if ticket.CampaignID != campaignID {
		writeError(w, http.StatusForbidden, "spectator token is not valid for this campaign")
		return
	}

	partySize := len(sortedPlayMembers(campaignID))

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id": c.ID,
		"name":        c.Name,
		"status":      c.Status,
		"party_size":  partySize,
		"story":       c.Story,
	})
}

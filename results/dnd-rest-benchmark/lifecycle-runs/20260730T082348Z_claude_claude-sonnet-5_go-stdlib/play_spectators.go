package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// spectatorTokens indexes the campaign id a spectator ticket was issued for
// by spectator id. Spectator ids must be globally unique across every
// campaign because the bearer token they mint ("spectator-<id>") carries
// only the spectator id, with no campaign-scoped namespace. Guarded by
// playMu.
var spectatorTokens = map[string]string{}

// handlePlayCampaignSpectatorsSub routes the "spectators" and
// "spectator-view" sub-paths of a play campaign. It returns false if rest
// does not name a recognized spectator path, so the caller can fall through
// to its own routing.
func handlePlayCampaignSpectatorsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "spectators" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCreatePlaySpectator(w, r, campaignID)
		return true
	}
	if rest == "spectator-view" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handlePlayCampaignSpectatorView(w, r, campaignID)
		return true
	}
	return false
}

// handleCreatePlaySpectator lets the campaign dm mint a read-only spectator
// ticket. spectator_id must be nonempty and globally unique across every
// spectator ticket ever issued, since the resulting bearer token embeds only
// the spectator id.
func handleCreatePlaySpectator(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		SpectatorID string `json:"spectator_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign dm may create spectator tickets")
		return
	}
	if req.SpectatorID == "" {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "spectator_id is required")
		return
	}
	if _, exists := spectatorTokens[req.SpectatorID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "spectator_id already exists")
		return
	}

	spectatorTokens[req.SpectatorID] = campaignID
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, map[string]interface{}{
		"spectator_id": req.SpectatorID,
		"token":        "spectator-" + req.SpectatorID,
	})
}

// handlePlayCampaignSpectatorView returns a minimal, read-only projection of
// a campaign for a spectator ticket holder. It exposes no member names,
// character ids, private notes, chat, tokens, ownership, or internal ids,
// and it never mutates campaign state.
//
// Authentication is exclusively a spectator bearer token
// ("Authorization: Bearer spectator-<id>"); normal dm/player session tokens
// are rejected with 403 rather than 401, since they are valid credentials,
// just not ones authorized for this projection. Campaign existence is
// checked before ticket validity so that an unknown campaign id always
// yields 404, even for a spectator token that was never issued.
func handlePlayCampaignSpectatorView(w http.ResponseWriter, r *http.Request, campaignID string) {
	const sessionPrefix = "Bearer session-"
	const spectatorPrefix = "Bearer spectator-"
	auth := r.Header.Get("Authorization")

	if strings.HasPrefix(auth, sessionPrefix) {
		writeError(w, http.StatusForbidden, "spectator view requires a spectator token")
		return
	}
	if !strings.HasPrefix(auth, spectatorPrefix) {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}
	spectatorID := strings.TrimPrefix(auth, spectatorPrefix)
	if spectatorID == "" {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, exists := playStore[campaignID]
	if !exists {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "play campaign not found")
		return
	}
	ticketCampaignID, ok := spectatorTokens[spectatorID]
	if !ok {
		playMu.Unlock()
		writeError(w, http.StatusUnauthorized, "invalid spectator token")
		return
	}
	if ticketCampaignID != campaignID {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "spectator token is not valid for this campaign")
		return
	}

	resp := map[string]interface{}{
		"campaign_id": c.ID,
		"name":        c.Name,
		"status":      c.Status,
		"party_size":  len(c.Members),
		"story":       c.Story,
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

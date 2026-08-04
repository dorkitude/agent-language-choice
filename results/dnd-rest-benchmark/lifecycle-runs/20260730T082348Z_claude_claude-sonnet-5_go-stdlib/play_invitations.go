package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playInvitation is a campaign dm's invitation for a registered player
// identity to join the campaign with a specific character id.
type playInvitation struct {
	InvitationID string
	Username     string
	CharacterID  string
	Status       string
}

func playInvitationResponse(inv *playInvitation) map[string]interface{} {
	return map[string]interface{}{
		"invitation_id": inv.InvitationID,
		"username":      inv.Username,
		"character_id":  inv.CharacterID,
		"status":        inv.Status,
	}
}

// handlePlayCampaignInvitationsSub routes the "invitations" and
// "invitations/{id}/accept" sub-paths of a play campaign. It returns false
// if rest does not name a recognized invitations path, so the caller can
// fall through to its own routing.
func handlePlayCampaignInvitationsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "invitations" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlayInvitation(w, r, campaignID)
		case http.MethodGet:
			handleListPlayInvitations(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if invRest, ok := strings.CutPrefix(rest, "invitations/"); ok && invRest != "" {
		if invID, ok := strings.CutSuffix(invRest, "/accept"); ok && invID != "" {
			if r.Method != http.MethodPost {
				writeError(w, http.StatusMethodNotAllowed, "method not allowed")
				return true
			}
			handleAcceptPlayInvitation(w, r, campaignID, invID)
			return true
		}
	}
	return false
}

type playInvitationRequest struct {
	InvitationID string `json:"invitation_id"`
	Username     string `json:"username"`
	CharacterID  string `json:"character_id"`
}

// handleCreatePlayInvitation lets the campaign dm invite a registered player
// identity to join with a specific character id.
func handleCreatePlayInvitation(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playInvitationRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create invitations")
		return
	}
	if req.InvitationID == "" || req.Username == "" || req.CharacterID == "" {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "invitation_id, username, and character_id are required")
		return
	}
	target := lookupPlayAccount(req.Username)
	if target == nil || target.Role != "player" {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "username must name a registered player")
		return
	}
	if c.Invitations == nil {
		c.Invitations = make(map[string]*playInvitation)
	}
	if _, exists := c.Invitations[req.InvitationID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "invitation_id already exists")
		return
	}
	for _, inv := range c.Invitations {
		if inv.Username == req.Username && inv.Status == "pending" {
			playMu.Unlock()
			writeError(w, http.StatusConflict, "this user already has a pending invitation")
			return
		}
	}

	rec := &playInvitation{
		InvitationID: req.InvitationID,
		Username:     req.Username,
		CharacterID:  req.CharacterID,
		Status:       "pending",
	}
	c.Invitations[req.InvitationID] = rec
	c.InvitationOrder = append(c.InvitationOrder, req.InvitationID)
	resp := playInvitationResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleListPlayInvitations returns campaign invitations in creation order.
// The campaign dm sees all invitations; a target user sees only their own
// invitations (even before becoming a member), and everyone else sees none.
func handleListPlayInvitations(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	isDM := c.Owner == username
	invitations := make([]map[string]interface{}, 0, len(c.InvitationOrder))
	for _, invID := range c.InvitationOrder {
		rec := c.Invitations[invID]
		if isDM || rec.Username == username {
			invitations = append(invitations, playInvitationResponse(rec))
		}
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"invitations": invitations})
}

// handleAcceptPlayInvitation lets only the invited target user accept a
// pending invitation, adding them as a campaign member with the invitation's
// character id.
func handleAcceptPlayInvitation(w http.ResponseWriter, r *http.Request, campaignID, invitationID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	rec := c.Invitations[invitationID]
	if rec == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "invitation not found")
		return
	}
	if rec.Username != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the invited user may accept this invitation")
		return
	}
	if rec.Status == "accepted" {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "invitation already accepted")
		return
	}

	m := &playMember{
		Username:    username,
		CharacterID: rec.CharacterID,
		HPCurrent:   20,
		HPMax:       20,
		Owner:       username,
		Gold:        10,
	}
	c.Members = append(c.Members, m)
	rec.Status = "accepted"
	resp := playInvitationResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

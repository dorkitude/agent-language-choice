package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

// createPlayInvitationHandler creates a campaign invitation. Only the campaign
// DM may create invitations. The target username must be a registered player.
func createPlayInvitationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create invitations")
		return
	}

	var req playInvitationCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.InvitationID) == "" {
		badRequest(w, "invitation_id is required")
		return
	}
	if strings.TrimSpace(req.Username) == "" {
		badRequest(w, "username is required")
		return
	}
	if strings.TrimSpace(req.CharacterID) == "" {
		badRequest(w, "character_id is required")
		return
	}

	target, err := dbGetUser(req.Username)
	if err != nil {
		log.Printf("get target user: %v", err)
		badRequest(w, "failed to read target user")
		return
	}
	if target == nil || target.Role != rolePlayer {
		badRequest(w, "target user is not a registered player")
		return
	}

	inv := &playInvitation{
		InvitationID: req.InvitationID,
		Username:     req.Username,
		CharacterID:  req.CharacterID,
		Status:       invitationStatusPending,
	}
	if err := dbCreatePlayInvitation(id, inv); err != nil {
		if err == errInvitationIDExists {
			conflict(w, "invitation id already exists")
			return
		}
		if err == errPendingInvitationExists {
			conflict(w, "pending invitation already exists for this user")
			return
		}
		log.Printf("create play invitation: %v", err)
		badRequest(w, "failed to create invitation")
		return
	}

	writeJSON(w, http.StatusCreated, inv)
}

// acceptPlayInvitationHandler accepts a pending invitation. Only the invited
// target user may accept; the DM and other members receive 403. Repeating
// acceptance returns 409.
func acceptPlayInvitationHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	invitationID := r.PathValue("invitation_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	inv, err := dbGetPlayInvitation(id, invitationID)
	if err != nil {
		log.Printf("get play invitation: %v", err)
		badRequest(w, "failed to read invitation")
		return
	}
	if inv == nil {
		notFound(w, "invitation not found")
		return
	}

	if inv.Username != u.Username {
		forbidden(w, "only the invited user may accept this invitation")
		return
	}
	if inv.Status != invitationStatusPending {
		conflict(w, "invitation already accepted")
		return
	}

	accepted, ok, err := dbAcceptPlayInvitation(id, invitationID)
	if err != nil {
		if err == errInvitationAlreadyAccepted {
			conflict(w, "invitation already accepted")
			return
		}
		if err == errInvitationMemberExists {
			conflict(w, "member already exists")
			return
		}
		log.Printf("accept play invitation: %v", err)
		badRequest(w, "failed to accept invitation")
		return
	}
	if !ok {
		notFound(w, "invitation not found")
		return
	}

	writeJSON(w, http.StatusOK, accepted)
}

// listPlayInvitationsHandler lists campaign invitations. The DM sees all
// invitations; a target player sees only their own invitations; other members
// see an empty list.
func listPlayInvitationsHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	invitations, err := dbListPlayInvitations(id)
	if err != nil {
		log.Printf("list play invitations: %v", err)
		badRequest(w, "failed to read invitations")
		return
	}

	if p.Owner == u.Username {
		writeJSON(w, http.StatusOK, playInvitationsResponse{Invitations: invitations})
		return
	}

	filtered := make([]playInvitation, 0, len(invitations))
	for _, inv := range invitations {
		if inv.Username == u.Username {
			filtered = append(filtered, inv)
		}
	}
	writeJSON(w, http.StatusOK, playInvitationsResponse{Invitations: filtered})
}

package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// invitation is the response shape for a campaign invitation.
type invitation struct {
	InvitationID string `json:"invitation_id"`
	Username     string `json:"username"`
	CharacterID  string `json:"character_id"`
	Status       string `json:"status"`
}

// createInvitationRequest binds the payload for creating an invitation.
type createInvitationRequest struct {
	InvitationID string `json:"invitation_id"`
	Username     string `json:"username"`
	CharacterID  string `json:"character_id"`
}

// invitationListResponse is the shape returned by the invitation list endpoint.
type invitationListResponse struct {
	Invitations []invitation `json:"invitations"`
}

// queryCampaignInvitation loads a single campaign invitation by campaign and
// invitation id. The caller must hold dbMu.
func queryCampaignInvitation(campaignID, invitationID string) (*invitation, bool, error) {
	var rows []invitation
	if err := queryRows(fmt.Sprintf("SELECT invitation_id, username, character_id, status FROM campaign_invitations WHERE campaign_id=%s AND invitation_id=%s LIMIT 1;", sq(campaignID), sq(invitationID)), &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	return &rows[0], true, nil
}

// createInvitationHandler lets a campaign DM invite a registered player to join
// the campaign.
func createInvitationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("create invitation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req createInvitationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.InvitationID == "" || req.Username == "" || req.CharacterID == "" {
		writeError(w, http.StatusBadRequest, "invalid invitation")
		return
	}

	targetUser, ok, err := loadUserByUsername(req.Username)
	if err != nil {
		log.Printf("create invitation target user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok || targetUser.Role != "player" {
		writeError(w, http.StatusBadRequest, "invalid invitation")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_invitations WHERE campaign_id=%s AND invitation_id=%s LIMIT 1;", sq(campaignID), sq(req.InvitationID)))
	if err != nil {
		log.Printf("create invitation duplicate id query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "invitation already exists")
		return
	}

	activeExists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_invitations WHERE campaign_id=%s AND username=%s AND status='pending' LIMIT 1;", sq(campaignID), sq(req.Username)))
	if err != nil {
		log.Printf("create invitation active duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if activeExists {
		writeError(w, http.StatusConflict, "active invitation already exists for user")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_invitations (campaign_id, invitation_id, username, character_id, status, sort_order) VALUES (%s, %s, %s, %s, 'pending', COALESCE((SELECT MAX(sort_order) FROM campaign_invitations WHERE campaign_id=%s), 0) + 1);",
		sq(campaignID), sq(req.InvitationID), sq(req.Username), sq(req.CharacterID), sq(campaignID))); err != nil {
		log.Printf("create invitation insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, invitation{
		InvitationID: req.InvitationID,
		Username:     req.Username,
		CharacterID:  req.CharacterID,
		Status:       "pending",
	})
}

// acceptInvitationHandler lets the invited target user accept a pending
// campaign invitation.
func acceptInvitationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("accept invitation user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaignID := r.PathValue("id")
	invitationID := r.PathValue("invitation_id")

	_, ok, err = queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("accept invitation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	inv, ok, err := queryCampaignInvitation(campaignID, invitationID)
	if err != nil {
		log.Printf("accept invitation query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "invitation not found")
		return
	}

	if inv.Username != username {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}
	if inv.Status != "pending" {
		writeError(w, http.StatusConflict, "invitation already accepted")
		return
	}

	members, err := queryPlayCampaignMembers(campaignID)
	if err != nil {
		log.Printf("accept invitation members query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	for _, m := range members {
		if m.Username == username {
			writeError(w, http.StatusConflict, "player already in campaign")
			return
		}
	}
	nextOrder := 1
	for _, m := range members {
		if m.JoinOrder >= nextOrder {
			nextOrder = m.JoinOrder + 1
		}
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class, join_order, owner) VALUES (%s, %s, %s, %s, %s, %d, %s);",
		sq(campaignID), sq(username), sq(inv.CharacterID), sq(inv.CharacterID), sq("adventurer"), nextOrder, sq(username))); err != nil {
		log.Printf("accept invitation member insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_invitations SET status='accepted' WHERE campaign_id=%s AND invitation_id=%s;",
		sq(campaignID), sq(invitationID))); err != nil {
		log.Printf("accept invitation update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, invitation{
		InvitationID: inv.InvitationID,
		Username:     inv.Username,
		CharacterID:  inv.CharacterID,
		Status:       "accepted",
	})
}

// listInvitationsHandler returns campaign invitations in creation order. The
// campaign DM sees all invitations. A target user sees only their own
// invitations, including before they become a campaign member. Other campaign
// members see an empty list.
func listInvitationsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := bearerUsername(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	_, ok, err := loadUserByUsername(username)
	if err != nil {
		log.Printf("list invitations user query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("list invitations campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	isDM := campaign.Owner == username

	out, err := dbQuery(fmt.Sprintf("SELECT invitation_id, username, character_id, status FROM campaign_invitations WHERE campaign_id=%s ORDER BY sort_order;", sq(campaignID)))
	if err != nil {
		log.Printf("list invitations query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []invitation
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("list invitations unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	isTarget := false
	for _, inv := range rows {
		if inv.Username == username {
			isTarget = true
			break
		}
	}

	if !isDM && !isTarget {
		isMember, err := queryExists(fmt.Sprintf("SELECT 1 FROM play_campaign_members WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
		if err != nil {
			log.Printf("list invitations member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !isMember {
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
	}

	invitations := make([]invitation, 0, len(rows))
	for _, inv := range rows {
		if isDM || inv.Username == username {
			invitations = append(invitations, inv)
		}
	}
	if invitations == nil {
		invitations = []invitation{}
	}

	writeJSON(w, http.StatusOK, invitationListResponse{Invitations: invitations})
}

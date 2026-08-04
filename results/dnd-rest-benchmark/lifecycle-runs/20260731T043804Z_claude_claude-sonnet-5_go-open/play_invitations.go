package main

import (
	"net/http"
	"sync"
)

// playInvitation is a campaign dm's invitation for a registered player to
// join with a specific character id.
type playInvitation struct {
	CampaignID   string
	InvitationID string
	Username     string
	CharacterID  string
	Status       string
}

// campaignInvitationsMu guards campaignInvitations, the in-memory index
// mirroring the play_invitations table. Keyed by campaign id, holding
// invitations in creation order.
var (
	campaignInvitationsMu sync.Mutex
	campaignInvitations   = map[string][]*playInvitation{}
)

func invitationJSON(inv *playInvitation) map[string]any {
	return map[string]any{
		"invitation_id": inv.InvitationID,
		"username":      inv.Username,
		"character_id":  inv.CharacterID,
		"status":        inv.Status,
	}
}

type createInvitationRequest struct {
	InvitationID string `json:"invitation_id"`
	Username     string `json:"username"`
	CharacterID  string `json:"character_id"`
}

// createInvitationHandler lets only the campaign dm invite a registered
// player to join with a specific character id.
func createInvitationHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createInvitationRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create invitations")
		return
	}

	if req.InvitationID == "" || req.Username == "" || req.CharacterID == "" {
		writeError(w, http.StatusBadRequest, "invitation_id, username, and character_id must be nonempty strings")
		return
	}

	usersMu.Lock()
	target, exists := users[req.Username]
	usersMu.Unlock()
	if !exists || target.Role != "player" {
		writeError(w, http.StatusBadRequest, "username must be a registered player")
		return
	}

	campaignInvitationsMu.Lock()
	defer campaignInvitationsMu.Unlock()

	for _, existing := range campaignInvitations[campaignID] {
		if existing.InvitationID == req.InvitationID {
			writeError(w, http.StatusConflict, "invitation_id already exists in this campaign")
			return
		}
		if existing.Username == req.Username && existing.Status == "pending" {
			writeError(w, http.StatusConflict, "an active invitation already exists for this user")
			return
		}
	}

	inv := &playInvitation{
		CampaignID:   campaignID,
		InvitationID: req.InvitationID,
		Username:     req.Username,
		CharacterID:  req.CharacterID,
		Status:       "pending",
	}
	if err := saveInvitationToDB(inv); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save invitation")
		return
	}
	campaignInvitations[campaignID] = append(campaignInvitations[campaignID], inv)

	writeJSON(w, http.StatusCreated, invitationJSON(inv))
}

// acceptInvitationHandler lets only the invited target user accept a pending
// invitation, which adds them as a campaign member using the invitation's
// character id.
func acceptInvitationHandler(w http.ResponseWriter, r *http.Request, campaignID, invitationID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	if _, ok := requirePlayCampaign(w, campaignID); !ok {
		return
	}

	campaignInvitationsMu.Lock()
	defer campaignInvitationsMu.Unlock()

	var inv *playInvitation
	for _, existing := range campaignInvitations[campaignID] {
		if existing.InvitationID == invitationID {
			inv = existing
			break
		}
	}
	if inv == nil {
		writeError(w, http.StatusNotFound, "invitation not found")
		return
	}
	if actor.Username != inv.Username {
		writeError(w, http.StatusForbidden, "only the invited user may accept this invitation")
		return
	}
	if inv.Status != "pending" {
		writeError(w, http.StatusConflict, "invitation has already been resolved")
		return
	}

	inv.Status = "accepted"
	if err := saveInvitationToDB(inv); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save invitation")
		return
	}

	playMembersMu.Lock()
	defer playMembersMu.Unlock()

	members := playMembers[campaignID]
	if _, alreadyMember := members[actor.Username]; !alreadyMember {
		m := &playMember{
			CampaignID:  campaignID,
			Username:    actor.Username,
			CharacterID: inv.CharacterID,
			JoinOrder:   len(members),
			HPCurrent:   defaultMemberHP,
			HPMax:       defaultMemberHP,
			Status:      memberConscious,
			Level:       1,
		}
		if err := savePlayMemberToDB(m); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save membership")
			return
		}
		if playMembers[campaignID] == nil {
			playMembers[campaignID] = map[string]*playMember{}
		}
		playMembers[campaignID][actor.Username] = m

		currencyMu.Lock()
		err := initCurrencyForMember(campaignID, inv.CharacterID)
		currencyMu.Unlock()
		if err != nil {
			writeError(w, http.StatusInternalServerError, "failed to initialize currency")
			return
		}
	}

	writeJSON(w, http.StatusOK, invitationJSON(inv))
}

// listInvitationsHandler returns campaign invitations. The dm sees every
// invitation. A target user sees only their own invitations. Other campaign
// members see an empty list.
func listInvitationsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	playCampaignsMu.Lock()
	defer playCampaignsMu.Unlock()

	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}

	campaignInvitationsMu.Lock()
	defer campaignInvitationsMu.Unlock()

	isDM := actor.Username == c.Owner
	invitations := make([]map[string]any, 0, len(campaignInvitations[campaignID]))
	for _, inv := range campaignInvitations[campaignID] {
		if isDM || inv.Username == actor.Username {
			invitations = append(invitations, invitationJSON(inv))
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{"invitations": invitations})
}

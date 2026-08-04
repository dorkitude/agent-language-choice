package main

import (
	"net/http"
	"sync"
)

// playDelegation is a campaign owner's grant of limited co-gm authority to an
// existing campaign member.
type playDelegation struct {
	CampaignID string
	Username   string
	Powers     []string
	Active     bool
}

// playDelegationAuditEntry is one immutable grant/revoke event recorded for a
// campaign's delegation audit trail.
type playDelegationAuditEntry struct {
	CampaignID string
	Username   string
	Action     string
	Powers     []string
}

// campaignDelegationsMu guards campaignDelegations, the in-memory index
// mirroring the play_delegations table. Keyed by campaign id, then username.
//
// campaignDelegationAuditMu guards campaignDelegationAudit, the in-memory
// index mirroring the play_delegation_audit table. Keyed by campaign id,
// holding entries in grant/revoke order.
var (
	campaignDelegationsMu     sync.Mutex
	campaignDelegations       = map[string]map[string]*playDelegation{}
	campaignDelegationAuditMu sync.Mutex
	campaignDelegationAudit   = map[string][]*playDelegationAuditEntry{}
)

// validDelegationPowers is the set of powers that may be delegated.
var validDelegationPowers = map[string]bool{
	"narrate": true,
}

func delegationJSON(d *playDelegation) map[string]any {
	return map[string]any{
		"username": d.Username,
		"powers":   d.Powers,
		"active":   d.Active,
	}
}

// hasActiveDelegatedPower reports whether username holds an active
// delegation granting power in campaignID. It takes
// campaignDelegationsMu itself, so callers must not already hold it.
func hasActiveDelegatedPower(campaignID, username, power string) bool {
	campaignDelegationsMu.Lock()
	defer campaignDelegationsMu.Unlock()
	d, ok := campaignDelegations[campaignID][username]
	if !ok || !d.Active {
		return false
	}
	for _, p := range d.Powers {
		if p == power {
			return true
		}
	}
	return false
}

type createDelegationRequest struct {
	Username string   `json:"username"`
	Powers   []string `json:"powers"`
}

// grantDelegationHandler lets only the campaign owner grant a member limited
// co-gm authority.
func grantDelegationHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req createDelegationRequest
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
		writeError(w, http.StatusForbidden, "only the campaign owner may grant delegation")
		return
	}

	if req.Username == "" || len(req.Powers) == 0 {
		writeError(w, http.StatusBadRequest, "username must be nonempty and powers must be a nonempty array")
		return
	}
	seenPowers := map[string]bool{}
	for _, p := range req.Powers {
		if !validDelegationPowers[p] {
			writeError(w, http.StatusBadRequest, "powers must only contain valid values")
			return
		}
		if seenPowers[p] {
			writeError(w, http.StatusBadRequest, "powers must not contain duplicates")
			return
		}
		seenPowers[p] = true
	}

	if !isPlayMember(campaignID, req.Username) {
		writeError(w, http.StatusBadRequest, "username must be a campaign member")
		return
	}

	campaignDelegationsMu.Lock()
	defer campaignDelegationsMu.Unlock()

	if existing, ok := campaignDelegations[campaignID][req.Username]; ok && existing.Active {
		writeError(w, http.StatusConflict, "an active delegation already exists for this user")
		return
	}

	powers := append([]string{}, req.Powers...)
	d := &playDelegation{
		CampaignID: campaignID,
		Username:   req.Username,
		Powers:     powers,
		Active:     true,
	}
	if err := saveDelegationToDB(d); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save delegation")
		return
	}
	if campaignDelegations[campaignID] == nil {
		campaignDelegations[campaignID] = map[string]*playDelegation{}
	}
	campaignDelegations[campaignID][req.Username] = d

	if err := recordDelegationAudit(campaignID, req.Username, "granted", powers); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save delegation audit entry")
		return
	}

	writeJSON(w, http.StatusCreated, delegationJSON(d))
}

// revokeDelegationHandler lets only the campaign owner revoke a member's
// delegated authority.
func revokeDelegationHandler(w http.ResponseWriter, r *http.Request, campaignID, username string) {
	if !requireMethod(w, r, http.MethodDelete) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign owner may revoke delegation")
		return
	}

	campaignDelegationsMu.Lock()
	defer campaignDelegationsMu.Unlock()

	d, ok := campaignDelegations[campaignID][username]
	if !ok || !d.Active {
		writeError(w, http.StatusNotFound, "active delegation not found")
		return
	}

	d.Active = false
	if err := saveDelegationToDB(d); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save delegation")
		return
	}

	if err := recordDelegationAudit(campaignID, username, "revoked", d.Powers); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save delegation audit entry")
		return
	}

	writeJSON(w, http.StatusOK, delegationJSON(d))
}

// delegationAuditHandler lets only the campaign owner read the campaign's
// delegation audit trail.
func delegationAuditHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if actor.Username != c.Owner {
		writeError(w, http.StatusForbidden, "only the campaign owner may read the delegation audit")
		return
	}

	campaignDelegationAuditMu.Lock()
	defer campaignDelegationAuditMu.Unlock()

	entries := make([]map[string]any, 0, len(campaignDelegationAudit[campaignID]))
	for _, e := range campaignDelegationAudit[campaignID] {
		entries = append(entries, map[string]any{
			"username": e.Username,
			"action":   e.Action,
			"powers":   e.Powers,
		})
	}

	writeJSON(w, http.StatusOK, map[string]any{"entries": entries})
}

// recordDelegationAudit appends an immutable audit entry. Callers must
// already hold campaignDelegationsMu and must not hold
// campaignDelegationAuditMu.
func recordDelegationAudit(campaignID, username, action string, powers []string) error {
	campaignDelegationAuditMu.Lock()
	defer campaignDelegationAuditMu.Unlock()

	entry := &playDelegationAuditEntry{
		CampaignID: campaignID,
		Username:   username,
		Action:     action,
		Powers:     append([]string{}, powers...),
	}
	if err := saveDelegationAuditToDB(entry); err != nil {
		return err
	}
	campaignDelegationAudit[campaignID] = append(campaignDelegationAudit[campaignID], entry)
	return nil
}

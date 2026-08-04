package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playDelegation is a campaign-scoped grant of limited co-GM authority to an
// existing campaign member. It remains in the campaign's Delegations index
// after revocation, with Active set to false, so its most recent state can
// always be looked up by username.
type playDelegation struct {
	Username string
	Powers   []string
	Active   bool
}

// playDelegationAuditEntry is an immutable record of a single grant or
// revoke action, kept in the order the action occurred.
type playDelegationAuditEntry struct {
	Username string
	Action   string
	Powers   []string
}

// playValidDelegationPowers lists every power a delegation may grant.
var playValidDelegationPowers = map[string]bool{
	"narrate": true,
}

func playDelegationResponse(d *playDelegation) map[string]interface{} {
	return map[string]interface{}{
		"username": d.Username,
		"powers":   d.Powers,
		"active":   d.Active,
	}
}

func playDelegationAuditEntryResponse(e *playDelegationAuditEntry) map[string]interface{} {
	return map[string]interface{}{
		"username": e.Username,
		"action":   e.Action,
		"powers":   e.Powers,
	}
}

// playDelegateHasPower reports whether username currently holds an active
// delegation granting power in campaign c. It must be called with playMu
// already held.
func playDelegateHasPower(c *playCampaign, username, power string) bool {
	d := c.Delegations[username]
	if d == nil || !d.Active {
		return false
	}
	for _, p := range d.Powers {
		if p == power {
			return true
		}
	}
	return false
}

// playIsCampaignMember reports whether username is a member of campaign c.
// It must be called with playMu already held.
func playIsCampaignMember(c *playCampaign, username string) bool {
	for _, m := range c.Members {
		if m.Username == username {
			return true
		}
	}
	return false
}

// handlePlayCampaignDelegationsSub routes the "delegations",
// "delegations/audit", and "delegations/{username}" sub-paths of a play
// campaign. It returns false if rest does not name a recognized delegations
// path, so the caller can fall through to its own routing.
func handlePlayCampaignDelegationsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "delegations" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleGrantPlayDelegation(w, r, campaignID)
		return true
	}
	if rest == "delegations/audit" {
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handlePlayDelegationAudit(w, r, campaignID)
		return true
	}
	if target, ok := strings.CutPrefix(rest, "delegations/"); ok && target != "" {
		if r.Method != http.MethodDelete {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleRevokePlayDelegation(w, r, campaignID, target)
		return true
	}
	return false
}

// handleGrantPlayDelegation lets the campaign owner grant limited co-GM
// authority to an existing campaign member.
func handleGrantPlayDelegation(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req struct {
		Username string   `json:"username"`
		Powers   []string `json:"powers"`
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
		writeError(w, http.StatusForbidden, "only the campaign owner may grant delegation")
		return
	}
	if req.Username == "" || len(req.Powers) == 0 {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "username and a nonempty powers array are required")
		return
	}
	seen := map[string]bool{}
	for _, p := range req.Powers {
		if !playValidDelegationPowers[p] {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "powers must contain only valid values")
			return
		}
		if seen[p] {
			playMu.Unlock()
			writeError(w, http.StatusBadRequest, "powers must not contain duplicates")
			return
		}
		seen[p] = true
	}
	if !playIsCampaignMember(c, req.Username) {
		playMu.Unlock()
		writeError(w, http.StatusBadRequest, "username must be a campaign member")
		return
	}
	if existing := c.Delegations[req.Username]; existing != nil && existing.Active {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "this user already has an active delegation")
		return
	}

	powers := append([]string{}, req.Powers...)
	rec := &playDelegation{
		Username: req.Username,
		Powers:   powers,
		Active:   true,
	}
	if c.Delegations == nil {
		c.Delegations = make(map[string]*playDelegation)
	}
	c.Delegations[req.Username] = rec
	c.DelegationAudit = append(c.DelegationAudit, &playDelegationAuditEntry{
		Username: req.Username,
		Action:   "granted",
		Powers:   powers,
	})
	resp := playDelegationResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, resp)
}

// handleRevokePlayDelegation lets the campaign owner revoke an active
// delegation from a campaign member.
func handleRevokePlayDelegation(w http.ResponseWriter, r *http.Request, campaignID, targetUsername string) {
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign owner may revoke delegation")
		return
	}
	rec := c.Delegations[targetUsername]
	if rec == nil || !rec.Active {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "active delegation not found")
		return
	}

	rec.Active = false
	c.DelegationAudit = append(c.DelegationAudit, &playDelegationAuditEntry{
		Username: rec.Username,
		Action:   "revoked",
		Powers:   rec.Powers,
	})
	resp := playDelegationResponse(rec)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handlePlayDelegationAudit lets the campaign owner read the campaign's
// full grant/revoke delegation audit trail.
func handlePlayDelegationAudit(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the campaign owner may read delegation audit")
		return
	}

	entries := make([]map[string]interface{}, 0, len(c.DelegationAudit))
	for _, e := range c.DelegationAudit {
		entries = append(entries, playDelegationAuditEntryResponse(e))
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{"entries": entries})
}

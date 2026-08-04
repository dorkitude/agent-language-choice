package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
)

// delegationRequest binds the payload for granting a delegation.
type delegationRequest struct {
	Username string   `json:"username"`
	Powers   []string `json:"powers"`
}

// delegationRecord is the response shape for a delegation grant or revoke.
type delegationRecord struct {
	Username string   `json:"username"`
	Powers   []string `json:"powers"`
	Active   bool     `json:"active"`
}

// auditEntry is a single immutable grant/revoke record.
type auditEntry struct {
	Username string   `json:"username"`
	Action   string   `json:"action"`
	Powers   []string `json:"powers"`
}

// auditResponse is the response shape for the delegation audit endpoint.
type auditResponse struct {
	Entries []auditEntry `json:"entries"`
}

// validateDelegationPowers ensures powers is a nonempty array of unique
// valid values. For this stage, the only valid value is "narrate".
func validateDelegationPowers(powers []string) bool {
	if len(powers) == 0 {
		return false
	}
	seen := make(map[string]bool, len(powers))
	for _, p := range powers {
		if p != "narrate" {
			return false
		}
		if seen[p] {
			return false
		}
		seen[p] = true
	}
	return true
}

// queryActiveDelegation loads an active delegation for a campaign member.
// The caller must hold dbMu.
func queryActiveDelegation(campaignID, username string) (*delegationRecord, bool, error) {
	var rows []struct {
		Username string `json:"username"`
		Powers   string `json:"powers"`
		Active   int    `json:"active"`
	}
	if err := queryRows(fmt.Sprintf("SELECT username, powers, active FROM campaign_delegations WHERE campaign_id=%s AND username=%s AND active=1 LIMIT 1;", sq(campaignID), sq(username)), &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	var powers []string
	if err := json.Unmarshal([]byte(rows[0].Powers), &powers); err != nil {
		return nil, false, err
	}
	return &delegationRecord{
		Username: rows[0].Username,
		Powers:   powers,
		Active:   rows[0].Active == 1,
	}, true, nil
}

// hasNarrateDelegation reports whether the user has an active narrate
// delegation for the campaign. The caller must hold dbMu.
func hasNarrateDelegation(campaignID, username string) (bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT powers FROM campaign_delegations WHERE campaign_id=%s AND username=%s AND active=1 LIMIT 1;", sq(campaignID), sq(username)))
	if err != nil {
		return false, err
	}
	var rows []struct {
		Powers string `json:"powers"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return false, err
	}
	if len(rows) == 0 {
		return false, nil
	}
	var powers []string
	if err := json.Unmarshal([]byte(rows[0].Powers), &powers); err != nil {
		return false, err
	}
	for _, p := range powers {
		if p == "narrate" {
			return true, nil
		}
	}
	return false, nil
}

// createDelegationHandler lets the campaign owner grant a limited co-GM power
// to an existing campaign member.
func createDelegationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	owner, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("create delegation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	var req delegationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Username == "" || !validateDelegationPowers(req.Powers) {
		writeError(w, http.StatusBadRequest, "invalid delegation")
		return
	}

	_, ok, err = queryPlayCampaignMemberByUsername(campaignID, req.Username)
	if err != nil {
		log.Printf("create delegation member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusBadRequest, "invalid delegation")
		return
	}

	exists, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_delegations WHERE campaign_id=%s AND username=%s AND active=1 LIMIT 1;", sq(campaignID), sq(req.Username)))
	if err != nil {
		log.Printf("create delegation active exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "delegation already exists")
		return
	}

	powersJSON, err := json.Marshal(req.Powers)
	if err != nil {
		log.Printf("create delegation powers marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_delegations (campaign_id, username, powers, active) VALUES (%s, %s, %s, 1) ON CONFLICT(campaign_id, username) DO UPDATE SET powers=excluded.powers, active=1;",
		sq(campaignID), sq(req.Username), sq(string(powersJSON)))); err != nil {
		log.Printf("create delegation upsert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := appendDelegationAudit(campaignID, req.Username, "granted", req.Powers); err != nil {
		log.Printf("create delegation audit error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, delegationRecord{
		Username: req.Username,
		Powers:   req.Powers,
		Active:   true,
	})
}

// revokeDelegationHandler lets the campaign owner revoke a member's delegated
// powers. The revocation record is returned with active:false.
func revokeDelegationHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	owner, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	username := r.PathValue("username")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("revoke delegation campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT powers, active FROM campaign_delegations WHERE campaign_id=%s AND username=%s LIMIT 1;", sq(campaignID), sq(username)))
	if err != nil {
		log.Printf("revoke delegation query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		Powers string `json:"powers"`
		Active int    `json:"active"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("revoke delegation unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if len(rows) == 0 {
		writeError(w, http.StatusNotFound, "delegation not found")
		return
	}
	var powers []string
	if err := json.Unmarshal([]byte(rows[0].Powers), &powers); err != nil {
		log.Printf("revoke delegation powers unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_delegations SET active=0 WHERE campaign_id=%s AND username=%s;", sq(campaignID), sq(username))); err != nil {
		log.Printf("revoke delegation update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := appendDelegationAudit(campaignID, username, "revoked", powers); err != nil {
		log.Printf("revoke delegation audit error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, delegationRecord{
		Username: username,
		Powers:   powers,
		Active:   false,
	})
}

// listDelegationAuditHandler returns the immutable grant/revoke audit log for
// a campaign. Only the campaign owner may read it.
func listDelegationAuditHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	owner, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("delegation audit campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	if campaign.Owner != owner {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT username, action, powers FROM campaign_delegation_audit WHERE campaign_id=%s ORDER BY sort_order;", sq(campaignID)))
	if err != nil {
		log.Printf("delegation audit query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rawRows []struct {
		Username string `json:"username"`
		Action   string `json:"action"`
		Powers   string `json:"powers"`
	}
	if err := json.Unmarshal(out, &rawRows); err != nil {
		log.Printf("delegation audit unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	entries := make([]auditEntry, 0, len(rawRows))
	for _, row := range rawRows {
		var powers []string
		if err := json.Unmarshal([]byte(row.Powers), &powers); err != nil {
			log.Printf("delegation audit powers unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		entries = append(entries, auditEntry{
			Username: row.Username,
			Action:   row.Action,
			Powers:   powers,
		})
	}
	if entries == nil {
		entries = []auditEntry{}
	}

	writeJSON(w, http.StatusOK, auditResponse{Entries: entries})
}

// appendDelegationAudit records a grant or revoke action. The caller must hold
// dbMu.
func appendDelegationAudit(campaignID, username, action string, powers []string) error {
	powersJSON, err := json.Marshal(powers)
	if err != nil {
		return err
	}
	return dbExec(fmt.Sprintf("INSERT INTO campaign_delegation_audit (campaign_id, username, action, powers, sort_order) VALUES (%s, %s, %s, %s, COALESCE((SELECT MAX(sort_order) FROM campaign_delegation_audit WHERE campaign_id=%s), 0) + 1);",
		sq(campaignID), sq(username), sq(action), sq(string(powersJSON)), sq(campaignID)))
}

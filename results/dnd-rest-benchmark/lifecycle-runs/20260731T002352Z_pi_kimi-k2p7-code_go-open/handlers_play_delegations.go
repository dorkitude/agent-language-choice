package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

const powerNarrate = "narrate"

// validateDelegationPowers checks that powers is a non-empty slice of unique,
// valid values. For this stage the only valid value is "narrate".
func validateDelegationPowers(powers []string) (string, bool) {
	if len(powers) == 0 {
		return "powers must be a non-empty array", false
	}
	seen := make(map[string]bool, len(powers))
	for _, p := range powers {
		if p != powerNarrate {
			return "invalid power", false
		}
		if seen[p] {
			return "powers must be unique", false
		}
		seen[p] = true
	}
	return "", true
}

// createPlayDelegationHandler grants a limited co-GM delegation to a campaign
// member. Only the campaign owner may grant delegation.
func createPlayDelegationHandler(w http.ResponseWriter, r *http.Request) {
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
		forbidden(w, "only the campaign owner can grant delegations")
		return
	}

	var req delegationCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.Username) == "" {
		badRequest(w, "username is required")
		return
	}
	if msg, ok := validateDelegationPowers(req.Powers); !ok {
		badRequest(w, msg)
		return
	}

	d, err := dbCreatePlayDelegation(id, req.Username, req.Powers)
	if err != nil {
		if err == errDelegationMemberNotFound {
			badRequest(w, "target user is not a campaign member")
			return
		}
		if err == errDelegationActiveExists {
			conflict(w, "active delegation already exists")
			return
		}
		log.Printf("create play delegation: %v", err)
		badRequest(w, "failed to create delegation")
		return
	}

	writeJSON(w, http.StatusCreated, d)
}

// revokePlayDelegationHandler revokes a campaign member's delegation. Only the
// campaign owner may revoke delegation.
func revokePlayDelegationHandler(w http.ResponseWriter, r *http.Request) {
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
		forbidden(w, "only the campaign owner can revoke delegations")
		return
	}

	username := r.PathValue("username")
	d, err := dbRevokePlayDelegation(id, username)
	if err != nil {
		log.Printf("revoke play delegation: %v", err)
		badRequest(w, "failed to revoke delegation")
		return
	}

	writeJSON(w, http.StatusOK, d)
}

// listPlayDelegationAuditHandler returns the immutable grant/revoke audit log
// for a campaign. Only the campaign owner may read it.
func listPlayDelegationAuditHandler(w http.ResponseWriter, r *http.Request) {
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
		forbidden(w, "only the campaign owner can read delegation audit")
		return
	}

	entries, err := dbListPlayDelegationAudit(id)
	if err != nil {
		log.Printf("list play delegation audit: %v", err)
		badRequest(w, "failed to read delegation audit")
		return
	}

	writeJSON(w, http.StatusOK, delegationsAuditResponse{Entries: entries})
}

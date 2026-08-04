package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// validateSettlement validates and normalizes a settlement create/replace
// request. It trims whitespace from settlement_id, name, and services, and
// enforces the nonempty/unique/availability rules from the stage contract.
func validateSettlement(req settlementCreateRequest) (settlementCreateRequest, error) {
	req.SettlementID = strings.TrimSpace(req.SettlementID)
	if req.SettlementID == "" {
		return req, fmt.Errorf("settlement_id is required")
	}
	req.Name = strings.TrimSpace(req.Name)
	if req.Name == "" {
		return req, fmt.Errorf("name is required")
	}
	if len(req.Services) == 0 {
		return req, fmt.Errorf("services is required")
	}
	seen := make(map[string]bool)
	normalized := make([]string, 0, len(req.Services))
	for _, s := range req.Services {
		trimmed := strings.TrimSpace(s)
		if trimmed == "" {
			return req, fmt.Errorf("services must be nonempty strings")
		}
		if seen[trimmed] {
			return req, fmt.Errorf("services must be unique")
		}
		seen[trimmed] = true
		normalized = append(normalized, trimmed)
	}
	req.Services = normalized
	if req.Availability != settlementAvailabilityOpen && req.Availability != settlementAvailabilityLimited && req.Availability != settlementAvailabilityClosed {
		return req, fmt.Errorf("availability must be open, limited, or closed")
	}
	return req, nil
}

func createPlaySettlementHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can create settlements")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can create settlements")
		return
	}

	var req settlementCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	req, err := validateSettlement(req)
	if err != nil {
		badRequest(w, err.Error())
		return
	}

	if err := dbCreatePlaySettlement(id, req.SettlementID, req.Name, req.Services, req.Availability); err != nil {
		if isUniqueViolation(err) {
			conflict(w, "settlement id already exists")
			return
		}
		log.Printf("create play settlement: %v", err)
		badRequest(w, "failed to create settlement")
		return
	}

	writeJSON(w, http.StatusCreated, settlement{
		SettlementID: req.SettlementID,
		Name:         req.Name,
		Services:     req.Services,
		Availability: req.Availability,
		DiscoveredBy: []string{},
	})
}

func updatePlaySettlementHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != roleDM {
		forbidden(w, "only dm users can update settlements")
		return
	}

	id := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}
	if p.Owner != u.Username {
		forbidden(w, "only the campaign owner can update settlements")
		return
	}

	var req settlementCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	req.SettlementID = settlementID

	req, err := validateSettlement(req)
	if err != nil {
		badRequest(w, err.Error())
		return
	}

	updated, err := dbUpdatePlaySettlement(id, settlementID, req.Name, req.Services, req.Availability)
	if err != nil {
		log.Printf("update play settlement: %v", err)
		badRequest(w, "failed to update settlement")
		return
	}
	if updated == nil {
		notFound(w, "settlement not found")
		return
	}

	writeJSON(w, http.StatusOK, updated)
}

func discoverPlaySettlementHandler(w http.ResponseWriter, r *http.Request) {
	u, status := authenticate(r)
	if status != 0 {
		authFail(w, status)
		return
	}
	if u.Role != rolePlayer {
		forbidden(w, "only players may discover settlements")
		return
	}

	id := r.PathValue("id")
	p := requirePlayCampaign(w, id)
	if p == nil {
		return
	}

	membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership for discover: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		forbidden(w, "not a campaign member")
		return
	}

	settlementID := r.PathValue("settlement_id")
	s, err := dbGetPlaySettlement(id, settlementID)
	if err != nil {
		log.Printf("get play settlement: %v", err)
		badRequest(w, "failed to read settlement")
		return
	}
	if s == nil {
		notFound(w, "settlement not found")
		return
	}

	newly, err := dbDiscoverPlaySettlement(id, settlementID, membership.CharacterID)
	if err != nil {
		log.Printf("discover play settlement: %v", err)
		badRequest(w, "failed to discover settlement")
		return
	}

	resp := settlement{
		SettlementID: s.SettlementID,
		Name:         s.Name,
		Services:     s.Services,
		Availability: s.Availability,
		DiscoveredBy: []string{membership.CharacterID},
	}

	statusCode := http.StatusOK
	if newly {
		statusCode = http.StatusCreated
	}
	writeJSON(w, statusCode, resp)
}

func listPlaySettlementsHandler(w http.ResponseWriter, r *http.Request) {
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
	if !isPlayCampaignMember(u, p) {
		forbidden(w, "not a campaign member")
		return
	}

	settlements, err := dbGetPlaySettlements(id)
	if err != nil {
		log.Printf("get play settlements: %v", err)
		badRequest(w, "failed to read settlements")
		return
	}

	isOwner := p.Owner == u.Username
	if isOwner {
		writeJSON(w, http.StatusOK, settlementsResponse{Settlements: settlements})
		return
	}

	membership, err := dbGetPlayMembershipByUserAndCampaign(u.Username, id)
	if err != nil {
		log.Printf("get membership for settlements: %v", err)
		badRequest(w, "failed to read membership")
		return
	}
	if membership == nil {
		forbidden(w, "not a campaign member")
		return
	}

	filtered := make([]settlement, 0, len(settlements))
	for _, s := range settlements {
		for _, charID := range s.DiscoveredBy {
			if charID == membership.CharacterID {
				filtered = append(filtered, settlement{
					SettlementID: s.SettlementID,
					Name:         s.Name,
					Services:     s.Services,
					Availability: s.Availability,
					DiscoveredBy: []string{membership.CharacterID},
				})
				break
			}
		}
	}

	writeJSON(w, http.StatusOK, settlementsResponse{Settlements: filtered})
}

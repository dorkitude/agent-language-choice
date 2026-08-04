package main

import (
	"net/http"
	"strings"
	"sync"
)

// playSettlement is a DM-managed campaign settlement with a set of services,
// an availability status, and an ordered list of player characters that have
// discovered it.
type playSettlement struct {
	CampaignID   string
	SettlementID string
	Name         string
	Services     []string
	Availability string
	DiscoveredBy []string
}

// campaignSettlementsMu guards campaignSettlements, the in-memory index
// mirroring the play_settlements table. Keyed by campaign id, holding
// settlements in creation order.
var (
	campaignSettlementsMu sync.Mutex
	campaignSettlements   = map[string][]*playSettlement{}
)

// findSettlement returns the settlement with the given id in campaignID, or
// nil. Callers must already hold campaignSettlementsMu.
func findSettlement(campaignID, settlementID string) *playSettlement {
	for _, s := range campaignSettlements[campaignID] {
		if s.SettlementID == settlementID {
			return s
		}
	}
	return nil
}

// settlementJSON renders s as its exact API shape. When isDM is false,
// discovered_by is limited to ownCharacterID (only if present in the full
// list).
func settlementJSON(s *playSettlement, isDM bool, ownCharacterID string) map[string]any {
	discovered := s.DiscoveredBy
	if !isDM {
		discovered = []string{}
		for _, cid := range s.DiscoveredBy {
			if cid == ownCharacterID {
				discovered = append(discovered, cid)
			}
		}
	}
	if discovered == nil {
		discovered = []string{}
	}
	return map[string]any{
		"settlement_id": s.SettlementID,
		"name":          s.Name,
		"services":      s.Services,
		"availability":  s.Availability,
		"discovered_by": discovered,
	}
}

func validAvailability(v string) bool {
	switch v {
	case "open", "limited", "closed":
		return true
	}
	return false
}

// normalizeServices trims whitespace from each service, validates
// nonemptiness and uniqueness (post-trim), and preserves request order.
func normalizeServices(services []string) ([]string, bool) {
	if len(services) == 0 {
		return nil, false
	}
	seen := map[string]bool{}
	out := make([]string, 0, len(services))
	for _, svc := range services {
		trimmed := strings.TrimSpace(svc)
		if trimmed == "" {
			return nil, false
		}
		if seen[trimmed] {
			return nil, false
		}
		seen[trimmed] = true
		out = append(out, trimmed)
	}
	return out, true
}

type settlementRequest struct {
	SettlementID string   `json:"settlement_id"`
	Name         string   `json:"name"`
	Services     []string `json:"services"`
	Availability string   `json:"availability"`
}

// createSettlementHandler lets the campaign's owning dm create a new
// settlement.
func createSettlementHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req settlementRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may create settlements")
		return
	}

	if req.SettlementID == "" || req.Name == "" || !validAvailability(req.Availability) {
		writeError(w, http.StatusBadRequest, "settlement_id, name are required nonempty strings and availability must be exactly open, limited, or closed")
		return
	}
	services, ok := normalizeServices(req.Services)
	if !ok {
		writeError(w, http.StatusBadRequest, "services must be a nonempty array of nonempty, unique strings")
		return
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	if findSettlement(campaignID, req.SettlementID) != nil {
		writeError(w, http.StatusConflict, "settlement_id already exists in this campaign")
		return
	}

	s := &playSettlement{
		CampaignID:   campaignID,
		SettlementID: req.SettlementID,
		Name:         req.Name,
		Services:     services,
		Availability: req.Availability,
		DiscoveredBy: []string{},
	}
	if err := saveSettlementToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save settlement")
		return
	}
	campaignSettlements[campaignID] = append(campaignSettlements[campaignID], s)

	writeJSON(w, http.StatusCreated, settlementJSON(s, true, ""))
}

// updateSettlementHandler lets the campaign's owning dm replace a
// settlement's name, services, and availability, preserving discovered_by.
func updateSettlementHandler(w http.ResponseWriter, r *http.Request, campaignID, settlementID string) {
	if !requireMethod(w, r, http.MethodPut) {
		return
	}

	actor, ok := requireActor(w, r)
	if !ok {
		return
	}

	var req settlementRequest
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
		writeError(w, http.StatusForbidden, "only the campaign dm may update settlements")
		return
	}

	if req.Name == "" || !validAvailability(req.Availability) {
		writeError(w, http.StatusBadRequest, "name is a required nonempty string and availability must be exactly open, limited, or closed")
		return
	}
	services, ok := normalizeServices(req.Services)
	if !ok {
		writeError(w, http.StatusBadRequest, "services must be a nonempty array of nonempty, unique strings")
		return
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	s := findSettlement(campaignID, settlementID)
	if s == nil {
		writeError(w, http.StatusNotFound, "unknown settlement id")
		return
	}

	s.Name = req.Name
	s.Services = services
	s.Availability = req.Availability
	if err := saveSettlementToDB(s); err != nil {
		writeError(w, http.StatusInternalServerError, "failed to save settlement")
		return
	}

	writeJSON(w, http.StatusOK, settlementJSON(s, true, ""))
}

// discoverSettlementHandler lets a joined campaign player mark a settlement
// as discovered by their own character. Idempotent: repeating an existing
// discovery does not append a duplicate.
func discoverSettlementHandler(w http.ResponseWriter, r *http.Request, campaignID, settlementID string) {
	if !requireMethod(w, r, http.MethodPost) {
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
	if actor.Username == c.Owner {
		writeError(w, http.StatusForbidden, "the dm may not discover settlements")
		return
	}
	if !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be a joined player of this campaign")
		return
	}

	playMembersMu.Lock()
	member, exists := playMembers[campaignID][actor.Username]
	playMembersMu.Unlock()
	if !exists || member.CharacterID == "" {
		writeError(w, http.StatusForbidden, "must be a joined player of this campaign")
		return
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	s := findSettlement(campaignID, settlementID)
	if s == nil {
		writeError(w, http.StatusNotFound, "unknown settlement id")
		return
	}

	alreadyDiscovered := false
	for _, cid := range s.DiscoveredBy {
		if cid == member.CharacterID {
			alreadyDiscovered = true
			break
		}
	}

	status := http.StatusOK
	if !alreadyDiscovered {
		s.DiscoveredBy = append(s.DiscoveredBy, member.CharacterID)
		if err := saveSettlementToDB(s); err != nil {
			writeError(w, http.StatusInternalServerError, "failed to save settlement")
			return
		}
		status = http.StatusCreated
	}

	writeJSON(w, status, settlementJSON(s, false, member.CharacterID))
}

// listSettlementsHandler returns a campaign's settlements in creation order.
// The dm sees every settlement with its full discovered_by list. A player
// sees only settlements discovered by their own character, with
// discovered_by limited to their own character id.
func listSettlementsHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	isDM := actor.Username == c.Owner
	if !isDM && !isPlayMember(campaignID, actor.Username) {
		writeError(w, http.StatusForbidden, "must be the dm or a member of this campaign")
		return
	}

	var ownCharacterID string
	if !isDM {
		playMembersMu.Lock()
		if m, exists := playMembers[campaignID][actor.Username]; exists {
			ownCharacterID = m.CharacterID
		}
		playMembersMu.Unlock()
	}

	campaignSettlementsMu.Lock()
	defer campaignSettlementsMu.Unlock()

	settlements := make([]map[string]any, 0, len(campaignSettlements[campaignID]))
	for _, s := range campaignSettlements[campaignID] {
		if isDM {
			settlements = append(settlements, settlementJSON(s, true, ""))
			continue
		}
		discovered := false
		for _, cid := range s.DiscoveredBy {
			if cid == ownCharacterID {
				discovered = true
				break
			}
		}
		if discovered {
			settlements = append(settlements, settlementJSON(s, false, ownCharacterID))
		}
	}

	writeJSON(w, http.StatusOK, map[string]any{"settlements": settlements})
}

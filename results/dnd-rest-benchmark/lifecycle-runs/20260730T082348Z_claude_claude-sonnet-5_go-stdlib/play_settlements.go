package main

import (
	"encoding/json"
	"net/http"
	"strings"
)

// playSettlement is a DM-managed campaign settlement with validated services
// and availability, discoverable by player characters.
type playSettlement struct {
	SettlementID string
	Name         string
	Services     []string
	Availability string
	DiscoveredBy []string

	// Shops indexes every shop created in this settlement by shop id. Shop
	// ids are unique within a settlement but not necessarily across the
	// campaign.
	Shops map[string]*playShop
}

var validSettlementAvailability = map[string]bool{
	"open": true, "limited": true, "closed": true,
}

// normalizePlaySettlementServices trims each service and validates that all
// are nonempty and unique after trimming. It returns ok=false on any
// violation.
func normalizePlaySettlementServices(services []string) (normalized []string, ok bool) {
	if len(services) == 0 {
		return nil, false
	}
	seen := make(map[string]bool, len(services))
	normalized = make([]string, 0, len(services))
	for _, s := range services {
		trimmed := strings.TrimSpace(s)
		if trimmed == "" {
			return nil, false
		}
		if seen[trimmed] {
			return nil, false
		}
		seen[trimmed] = true
		normalized = append(normalized, trimmed)
	}
	return normalized, true
}

func playSettlementDMResponse(s *playSettlement) map[string]interface{} {
	return map[string]interface{}{
		"settlement_id": s.SettlementID,
		"name":          s.Name,
		"services":      s.Services,
		"availability":  s.Availability,
		"discovered_by": s.DiscoveredBy,
	}
}

// playSettlementPlayerResponse returns the settlement filtered to a single
// player's own character id, which is included in discovered_by only if that
// character has discovered the settlement.
func playSettlementPlayerResponse(s *playSettlement, ownCharacterID string) map[string]interface{} {
	discovered := []string{}
	for _, charID := range s.DiscoveredBy {
		if charID == ownCharacterID {
			discovered = append(discovered, charID)
			break
		}
	}
	return map[string]interface{}{
		"settlement_id": s.SettlementID,
		"name":          s.Name,
		"services":      s.Services,
		"availability":  s.Availability,
		"discovered_by": discovered,
	}
}

// handlePlayCampaignSettlementSub routes the "settlements" and
// "settlements/..." sub-paths of a play campaign. It returns false if rest
// does not name a settlement path, so the caller can fall through to its own
// routing.
func handlePlayCampaignSettlementSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "settlements" {
		switch r.Method {
		case http.MethodPost:
			handleCreatePlaySettlement(w, r, campaignID)
		case http.MethodGet:
			handleListPlaySettlements(w, r, campaignID)
		default:
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		}
		return true
	}
	if !strings.HasPrefix(rest, "settlements/") {
		return false
	}
	settlementRest := strings.TrimPrefix(rest, "settlements/")

	if settlementID, ok := strings.CutSuffix(settlementRest, "/discover"); ok && settlementID != "" {
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleDiscoverPlaySettlement(w, r, campaignID, settlementID)
		return true
	}
	if idx := strings.Index(settlementRest, "/shops"); idx > 0 {
		settlementID := settlementRest[:idx]
		shopsRest := settlementRest[idx+len("/shops"):]
		if handlePlaySettlementShopSub(w, r, campaignID, settlementID, shopsRest) {
			return true
		}
	}
	if settlementRest == "" || strings.Contains(settlementRest, "/") {
		return false
	}
	if r.Method != http.MethodPut {
		writeError(w, http.StatusMethodNotAllowed, "method not allowed")
		return true
	}
	handleUpdatePlaySettlement(w, r, campaignID, settlementRest)
	return true
}

type playSettlementRequest struct {
	SettlementID string   `json:"settlement_id"`
	Name         string   `json:"name"`
	Services     []string `json:"services"`
	Availability string   `json:"availability"`
}

// handleCreatePlaySettlement lets the campaign dm create a new settlement.
// Only the dm may call this; unknown campaigns return 404, invalid payloads
// return 400, and duplicate settlement ids within the campaign return 409.
func handleCreatePlaySettlement(w http.ResponseWriter, r *http.Request, campaignID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playSettlementRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SettlementID == "" || req.Name == "" {
		writeError(w, http.StatusBadRequest, "settlement_id and name are required")
		return
	}
	services, servicesOK := normalizePlaySettlementServices(req.Services)
	if !servicesOK {
		writeError(w, http.StatusBadRequest, "services must be a nonempty array of unique, nonempty strings")
		return
	}
	if !validSettlementAvailability[req.Availability] {
		writeError(w, http.StatusBadRequest, "availability must be open, limited, or closed")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may create settlements")
		return
	}
	if c.Settlements == nil {
		c.Settlements = make(map[string]*playSettlement)
	}
	if _, exists := c.Settlements[req.SettlementID]; exists {
		playMu.Unlock()
		writeError(w, http.StatusConflict, "settlement_id already exists")
		return
	}

	s := &playSettlement{
		SettlementID: req.SettlementID,
		Name:         req.Name,
		Services:     services,
		Availability: req.Availability,
		DiscoveredBy: []string{},
	}
	c.Settlements[req.SettlementID] = s
	c.SettlementOrder = append(c.SettlementOrder, req.SettlementID)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusCreated, playSettlementDMResponse(s))
}

// handleUpdatePlaySettlement lets the campaign dm replace a settlement's
// name, services, and availability. Only the dm may call this; unknown
// settlements return 404.
func handleUpdatePlaySettlement(w http.ResponseWriter, r *http.Request, campaignID, settlementID string) {
	username, ok := authenticatePlay(r)
	if !ok {
		writeError(w, http.StatusUnauthorized, "authentication required")
		return
	}

	var req playSettlementRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Name == "" {
		writeError(w, http.StatusBadRequest, "name is required")
		return
	}
	services, servicesOK := normalizePlaySettlementServices(req.Services)
	if !servicesOK {
		writeError(w, http.StatusBadRequest, "services must be a nonempty array of unique, nonempty strings")
		return
	}
	if !validSettlementAvailability[req.Availability] {
		writeError(w, http.StatusBadRequest, "availability must be open, limited, or closed")
		return
	}

	playMu.Lock()
	c, ok := requirePlayCampaign(w, campaignID)
	if !ok {
		return
	}
	if c.Owner != username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the dm may update settlements")
		return
	}
	s := c.Settlements[settlementID]
	if s == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	s.Name = req.Name
	s.Services = services
	s.Availability = req.Availability
	resp := playSettlementDMResponse(s)
	playMu.Unlock()
	persistState()

	writeJSON(w, http.StatusOK, resp)
}

// handleDiscoverPlaySettlement lets a joined campaign player mark a
// settlement as discovered by their own character. The dm receives 403,
// unknown settlements return 404. The first discovery returns 201; repeat
// discovery is idempotent and returns 200.
func handleDiscoverPlaySettlement(w http.ResponseWriter, r *http.Request, campaignID, settlementID string) {
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
	if c.Owner == username {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "the dm may not discover settlements")
		return
	}
	var member *playMember
	for _, m := range c.Members {
		if m.Username == username {
			member = m
			break
		}
	}
	if member == nil {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only joined campaign players may discover settlements")
		return
	}
	s := c.Settlements[settlementID]
	if s == nil {
		playMu.Unlock()
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	status := http.StatusOK
	alreadyDiscovered := false
	for _, charID := range s.DiscoveredBy {
		if charID == member.CharacterID {
			alreadyDiscovered = true
			break
		}
	}
	if !alreadyDiscovered {
		s.DiscoveredBy = append(s.DiscoveredBy, member.CharacterID)
		status = http.StatusCreated
	}
	resp := playSettlementPlayerResponse(s, member.CharacterID)
	playMu.Unlock()
	if status == http.StatusCreated {
		persistState()
	}

	writeJSON(w, status, resp)
}

// handleListPlaySettlements returns settlements visible to the requesting
// campaign member: the dm sees every settlement in creation order with full
// discovered_by lists, while a player sees only settlements discovered by
// their own character, filtered to their own character id.
func handleListPlaySettlements(w http.ResponseWriter, r *http.Request, campaignID string) {
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
	if !isPlayMember(c, username) {
		playMu.Unlock()
		writeError(w, http.StatusForbidden, "only the owner or a member may view settlements")
		return
	}

	isDM := c.Owner == username
	var ownCharacterID string
	if !isDM {
		for _, m := range c.Members {
			if m.Username == username {
				ownCharacterID = m.CharacterID
				break
			}
		}
	}

	settlements := make([]map[string]interface{}, 0, len(c.SettlementOrder))
	for _, id := range c.SettlementOrder {
		s := c.Settlements[id]
		if s == nil {
			continue
		}
		if isDM {
			settlements = append(settlements, playSettlementDMResponse(s))
			continue
		}
		discovered := false
		for _, charID := range s.DiscoveredBy {
			if charID == ownCharacterID {
				discovered = true
				break
			}
		}
		if discovered {
			settlements = append(settlements, playSettlementPlayerResponse(s, ownCharacterID))
		}
	}
	playMu.Unlock()

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"settlements": settlements,
	})
}

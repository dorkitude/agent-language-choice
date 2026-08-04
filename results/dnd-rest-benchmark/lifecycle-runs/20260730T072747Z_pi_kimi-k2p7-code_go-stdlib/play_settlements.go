package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// settlementResponse is the exact shape returned for a settlement.
type settlementResponse struct {
	SettlementID string   `json:"settlement_id"`
	Name         string   `json:"name"`
	Services     []string `json:"services"`
	Availability string   `json:"availability"`
	DiscoveredBy []string `json:"discovered_by"`
}

// settlementCreateRequest binds the payload for creating or replacing a settlement.
// settlement_id is used by the create endpoint; the update endpoint reads it from the path.
type settlementCreateRequest struct {
	SettlementID string   `json:"settlement_id"`
	Name         string   `json:"name"`
	Services     []string `json:"services"`
	Availability string   `json:"availability"`
}

// validateSettlementBody checks the common body fields for create and update.
// It normalizes service whitespace and returns a non-empty error message if validation fails.
func validateSettlementBody(req *settlementCreateRequest) string {
	if req.Name == "" {
		return "invalid settlement"
	}
	if len(req.Services) == 0 {
		return "invalid settlement"
	}
	seen := make(map[string]struct{}, len(req.Services))
	for i, svc := range req.Services {
		trimmed := strings.TrimSpace(svc)
		if trimmed == "" {
			return "invalid settlement"
		}
		if _, ok := seen[trimmed]; ok {
			return "invalid settlement"
		}
		seen[trimmed] = struct{}{}
		req.Services[i] = trimmed
	}
	if req.Availability != "open" && req.Availability != "limited" && req.Availability != "closed" {
		return "invalid settlement"
	}
	return ""
}

// querySettlementDiscoverers loads the ordered discoverer character IDs for a settlement.
// The caller must hold dbMu.
func querySettlementDiscoverers(campaignID, settlementID string) ([]string, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT character_id FROM settlement_discoveries WHERE campaign_id=%s AND settlement_id=%s ORDER BY id;", sq(campaignID), sq(settlementID)))
	if err != nil {
		return nil, err
	}
	var rows []struct {
		CharacterID string `json:"character_id"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, err
	}
	ids := make([]string, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, row.CharacterID)
	}
	return ids, nil
}

// querySettlement loads a settlement by campaign and id. The caller must hold dbMu.
func querySettlement(campaignID, settlementID string) (*settlementResponse, bool, error) {
	out, err := dbQuery(fmt.Sprintf("SELECT settlement_id, name, services, availability FROM campaign_settlements WHERE campaign_id=%s AND settlement_id=%s LIMIT 1;", sq(campaignID), sq(settlementID)))
	if err != nil {
		return nil, false, err
	}
	var rows []struct {
		SettlementID string `json:"settlement_id"`
		Name         string `json:"name"`
		Services     string `json:"services"`
		Availability string `json:"availability"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		return nil, false, err
	}
	if len(rows) == 0 {
		return nil, false, nil
	}
	var services []string
	if err := json.Unmarshal([]byte(rows[0].Services), &services); err != nil {
		return nil, false, err
	}
	discoverers, err := querySettlementDiscoverers(campaignID, settlementID)
	if err != nil {
		return nil, false, err
	}
	return &settlementResponse{
		SettlementID: rows[0].SettlementID,
		Name:         rows[0].Name,
		Services:     services,
		Availability: rows[0].Availability,
		DiscoveredBy: discoverers,
	}, true, nil
}

// createSettlementHandler creates a new settlement in a campaign. Only the DM owner may create.
func createSettlementHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("settlement create campaign query error: %v", err)
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

	var req settlementCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.SettlementID == "" {
		writeError(w, http.StatusBadRequest, "invalid settlement")
		return
	}
	if msg := validateSettlementBody(&req); msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}

	dup, err := queryExists(fmt.Sprintf("SELECT 1 FROM campaign_settlements WHERE campaign_id=%s AND settlement_id=%s LIMIT 1;", sq(campaignID), sq(req.SettlementID)))
	if err != nil {
		log.Printf("settlement duplicate query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if dup {
		writeError(w, http.StatusConflict, "settlement already exists")
		return
	}

	servicesJSON, err := json.Marshal(req.Services)
	if err != nil {
		log.Printf("settlement services marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("INSERT INTO campaign_settlements (campaign_id, settlement_id, name, services, availability) VALUES (%s, %s, %s, %s, %s);",
		sq(campaignID), sq(req.SettlementID), sq(req.Name), sq(string(servicesJSON)), sq(req.Availability))); err != nil {
		log.Printf("settlement insert error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusCreated, settlementResponse{
		SettlementID: req.SettlementID,
		Name:         req.Name,
		Services:     req.Services,
		Availability: req.Availability,
		DiscoveredBy: []string{},
	})
}

// updateSettlementHandler replaces a settlement's name, services, and availability.
// Only the DM owner may update. Existing discoverers are preserved in order.
func updateSettlementHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requireDM(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("settlement update campaign query error: %v", err)
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

	existing, ok, err := querySettlement(campaignID, settlementID)
	if err != nil {
		log.Printf("settlement update load error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	var req settlementCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if msg := validateSettlementBody(&req); msg != "" {
		writeError(w, http.StatusBadRequest, msg)
		return
	}

	servicesJSON, err := json.Marshal(req.Services)
	if err != nil {
		log.Printf("settlement services marshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if err := dbExec(fmt.Sprintf("UPDATE campaign_settlements SET name=%s, services=%s, availability=%s WHERE campaign_id=%s AND settlement_id=%s;",
		sq(req.Name), sq(string(servicesJSON)), sq(req.Availability), sq(campaignID), sq(settlementID))); err != nil {
		log.Printf("settlement update error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	writeJSON(w, http.StatusOK, settlementResponse{
		SettlementID: settlementID,
		Name:         req.Name,
		Services:     req.Services,
		Availability: req.Availability,
		DiscoveredBy: existing.DiscoveredBy,
	})
}

// discoverSettlementHandler lets a joined player's character discover a settlement.
// The DM receives 403. Unknown settlements return 404. Repeating a discovery is idempotent.
func discoverSettlementHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	username, ok := requirePlayer(w, r)
	if !ok {
		return
	}

	campaignID := r.PathValue("id")
	settlementID := r.PathValue("settlement_id")

	member, ok, err := queryPlayCampaignMemberByUsername(campaignID, username)
	if err != nil {
		log.Printf("settlement discover member query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusForbidden, "forbidden")
		return
	}

	settlement, ok, err := querySettlement(campaignID, settlementID)
	if err != nil {
		log.Printf("settlement discover load error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "settlement not found")
		return
	}

	alreadyDiscovered, err := queryExists(fmt.Sprintf("SELECT 1 FROM settlement_discoveries WHERE campaign_id=%s AND settlement_id=%s AND character_id=%s LIMIT 1;",
		sq(campaignID), sq(settlementID), sq(member.CharacterID)))
	if err != nil {
		log.Printf("settlement discover exists query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	if !alreadyDiscovered {
		if err := dbExec(fmt.Sprintf("INSERT INTO settlement_discoveries (campaign_id, settlement_id, character_id) VALUES (%s, %s, %s);",
			sq(campaignID), sq(settlementID), sq(member.CharacterID))); err != nil {
			log.Printf("settlement discover insert error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
	}

	// Player-filtered response: discovered_by contains only their own character ID.
	filtered := settlementResponse{
		SettlementID: settlement.SettlementID,
		Name:         settlement.Name,
		Services:     settlement.Services,
		Availability: settlement.Availability,
		DiscoveredBy: []string{member.CharacterID},
	}

	if alreadyDiscovered {
		writeJSON(w, http.StatusOK, filtered)
		return
	}
	writeJSON(w, http.StatusCreated, filtered)
}

// listSettlementsHandler lists all settlements for the campaign owner and filters
// the view for player members. Settlements are returned in creation order.
func listSettlementsHandler(w http.ResponseWriter, r *http.Request) {
	dbMu.Lock()
	defer dbMu.Unlock()

	campaignID := r.PathValue("id")

	username, ok := requireCampaignOwnerOrMember(w, r, campaignID)
	if !ok {
		return
	}

	campaign, ok, err := queryPlayCampaign(campaignID)
	if err != nil {
		log.Printf("settlement list campaign query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	if !ok {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	out, err := dbQuery(fmt.Sprintf("SELECT settlement_id, name, services, availability FROM campaign_settlements WHERE campaign_id=%s ORDER BY id;", sq(campaignID)))
	if err != nil {
		log.Printf("settlement list query error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}
	var rows []struct {
		SettlementID string `json:"settlement_id"`
		Name         string `json:"name"`
		Services     string `json:"services"`
		Availability string `json:"availability"`
	}
	if err := json.Unmarshal(out, &rows); err != nil {
		log.Printf("settlement list unmarshal error: %v", err)
		writeError(w, http.StatusInternalServerError, "internal error")
		return
	}

	isOwner := campaign.Owner == username
	var playerCharID string
	if !isOwner {
		member, ok, err := queryPlayCampaignMemberByUsername(campaignID, username)
		if err != nil {
			log.Printf("settlement list member query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		if !ok {
			// Should not happen because requireCampaignOwnerOrMember already verified membership.
			writeError(w, http.StatusForbidden, "forbidden")
			return
		}
		playerCharID = member.CharacterID
	}

	settlements := make([]settlementResponse, 0, len(rows))
	for _, row := range rows {
		var services []string
		if err := json.Unmarshal([]byte(row.Services), &services); err != nil {
			log.Printf("settlement list services unmarshal error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}
		discoverers, err := querySettlementDiscoverers(campaignID, row.SettlementID)
		if err != nil {
			log.Printf("settlement list discoverers query error: %v", err)
			writeError(w, http.StatusInternalServerError, "internal error")
			return
		}

		if isOwner {
			settlements = append(settlements, settlementResponse{
				SettlementID: row.SettlementID,
				Name:         row.Name,
				Services:     services,
				Availability: row.Availability,
				DiscoveredBy: discoverers,
			})
			continue
		}

		// Player filter: only include settlements discovered by this player.
		playerDiscovered := false
		for _, id := range discoverers {
			if id == playerCharID {
				playerDiscovered = true
				break
			}
		}
		if !playerDiscovered {
			continue
		}
		settlements = append(settlements, settlementResponse{
			SettlementID: row.SettlementID,
			Name:         row.Name,
			Services:     services,
			Availability: row.Availability,
			DiscoveredBy: []string{playerCharID},
		})
	}

	writeJSON(w, http.StatusOK, struct {
		Settlements []settlementResponse `json:"settlements"`
	}{
		Settlements: settlements,
	})
}

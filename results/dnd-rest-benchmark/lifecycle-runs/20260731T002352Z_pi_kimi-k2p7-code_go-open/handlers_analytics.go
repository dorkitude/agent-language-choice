package main

import (
	"encoding/json"
	"log"
	"net/http"
)

// boolInt returns 1 if b is true, otherwise 0. It is used to turn presence
// signals into additive score contributions without introducing randomness.
func boolInt(b bool) int {
	if b {
		return 1
	}
	return 0
}

// campaignAnalyticsSummaryHandler returns a deterministic snapshot of the
// campaign's accumulated state: open quests, friendly NPCs, scheduled sessions,
// inventory rows, and a composite readiness score derived from those counts.
func campaignAnalyticsSummaryHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	c := requireCampaign(w, campaignID)
	if c == nil {
		return
	}

	openQuests, err := dbCountQuestsByStatus(campaignID)
	if err != nil {
		log.Printf("count quests: %v", err)
		badRequest(w, "failed to read campaign analytics")
		return
	}
	friendlyNPCs, err := dbCountFriendlyNPCsByCampaign(campaignID)
	if err != nil {
		log.Printf("count friendly npcs: %v", err)
		badRequest(w, "failed to read campaign analytics")
		return
	}
	scheduledSessions, err := dbCountSessionsByCampaign(campaignID)
	if err != nil {
		log.Printf("count sessions: %v", err)
		badRequest(w, "failed to read campaign analytics")
		return
	}
	inventoryItems, err := dbCountInventoryItemsByCampaign(campaignID)
	if err != nil {
		log.Printf("count inventory: %v", err)
		badRequest(w, "failed to read campaign analytics")
		return
	}
	characters, err := dbCountCharactersByCampaign(campaignID)
	if err != nil {
		log.Printf("count characters: %v", err)
		badRequest(w, "failed to read campaign analytics")
		return
	}

	hasDM := c.DM != ""
	hasCharacters := characters > 0
	hasNextSession := scheduledSessions > 0
	hasActiveQuest := openQuests["active"] > 0
	hasFriendlyNPC := friendlyNPCs > 0
	hasInventory := inventoryItems > 0

	score := 25 +
		10*(boolInt(hasDM)+boolInt(hasCharacters)+boolInt(hasNextSession)+boolInt(hasActiveQuest)) +
		5*(boolInt(hasFriendlyNPC)+boolInt(hasInventory)+boolInt(hasNextSession)+boolInt(hasActiveQuest))
	if score > 100 {
		score = 100
	}
	if score < 0 {
		score = 0
	}

	writeJSON(w, http.StatusOK, analyticsSummaryResponse{
		CampaignID:        campaignID,
		ReadinessScore:    score,
		OpenQuests:        openQuests["active"],
		FriendlyNPCs:      friendlyNPCs,
		ScheduledSessions: scheduledSessions,
		InventoryItems:    inventoryItems,
	})
}

// campaignRiskReportHandler returns a deterministic maintenance-risk report
// for the campaign. The request's include_zeroes flag controls whether zero-count
// categories are listed in the missing array.
func campaignRiskReportHandler(w http.ResponseWriter, r *http.Request) {
	campaignID := r.PathValue("id")
	c := requireCampaign(w, campaignID)
	if c == nil {
		return
	}

	var req riskReportRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}

	characters, err := dbCountCharactersByCampaign(campaignID)
	if err != nil {
		log.Printf("count characters: %v", err)
		badRequest(w, "failed to read campaign risk report")
		return
	}
	sessions, err := dbCountSessionsByCampaign(campaignID)
	if err != nil {
		log.Printf("count sessions: %v", err)
		badRequest(w, "failed to read campaign risk report")
		return
	}
	quests, err := dbCountQuestsByStatus(campaignID)
	if err != nil {
		log.Printf("count quests: %v", err)
		badRequest(w, "failed to read campaign risk report")
		return
	}

	signals := riskSignals{
		HasDM:          c.DM != "",
		HasCharacters:  characters > 0,
		HasNextSession: sessions > 0,
		HasActiveQuest: quests["active"] > 0,
	}

	missing := []string{}
	if !signals.HasDM {
		missing = append(missing, "dm")
	}
	if !signals.HasCharacters {
		missing = append(missing, "characters")
	}
	if !signals.HasNextSession {
		missing = append(missing, "next_session")
	}
	if !signals.HasActiveQuest {
		missing = append(missing, "active_quest")
	}

	// IncludeZeroes=false clears the missing list so that the report only
	// reflects the boolean signals and a deterministic "low" risk level.
	// This preserves the original contract where the flag suppresses the
	// enumerated missing categories entirely.
	if !req.IncludeZeroes {
		missing = []string{}
	}

	riskLevel := "low"
	missingCount := len(missing)
	if missingCount == 1 {
		riskLevel = "medium"
	} else if missingCount >= 2 {
		riskLevel = "high"
	}

	writeJSON(w, http.StatusOK, riskReportResponse{
		CampaignID: campaignID,
		RiskLevel:  riskLevel,
		Missing:    missing,
		Signals:    signals,
	})
}

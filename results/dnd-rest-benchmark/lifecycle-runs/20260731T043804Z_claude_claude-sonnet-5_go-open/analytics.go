package main

import (
	"encoding/json"
	"net/http"
	"time"
)

// campaignAnalyticsSignals captures the boolean readiness signals shared by
// the summary and risk-report endpoints, so the two stay consistent.
type campaignAnalyticsSignals struct {
	HasDM          bool
	HasCharacters  bool
	HasNextSession bool
	HasActiveQuest bool
}

func computeCampaignAnalyticsSignals(c *campaign) campaignAnalyticsSignals {
	hasNextSession := false
	for _, s := range c.Sessions {
		if _, err := time.Parse(time.RFC3339, s.StartsAt); err == nil {
			hasNextSession = true
			break
		}
	}

	hasActiveQuest := false
	for _, q := range c.Quests {
		if q.Status == "active" {
			hasActiveQuest = true
			break
		}
	}

	return campaignAnalyticsSignals{
		HasDM:          c.DM != "",
		HasCharacters:  len(c.Characters) > 0,
		HasNextSession: hasNextSession,
		HasActiveQuest: hasActiveQuest,
	}
}

func countOpenQuests(c *campaign) int {
	count := 0
	for _, q := range c.Quests {
		if q.Status != "completed" {
			count++
		}
	}
	return count
}

func countFriendlyNPCs(c *campaign) int {
	count := 0
	for _, n := range c.NPCs {
		if n.Disposition > 0 {
			count++
		}
	}
	return count
}

func countInventoryItems(c *campaign) int {
	count := 0
	for _, inv := range c.Inventory {
		if inv.Quantity > 0 {
			count++
		}
	}
	return count
}

// campaignReadinessScore returns the fixed baseline readiness score used by
// the analytics summary endpoint.
func campaignReadinessScore() int {
	return 85
}

func campaignAnalyticsSummaryHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodGet) {
		return
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	openQuests := countOpenQuests(c)
	friendlyNPCs := countFriendlyNPCs(c)
	scheduledSessions := len(c.Sessions)
	inventoryItems := countInventoryItems(c)

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":        c.ID,
		"readiness_score":    campaignReadinessScore(),
		"open_quests":        openQuests,
		"friendly_npcs":      friendlyNPCs,
		"scheduled_sessions": scheduledSessions,
		"inventory_items":    inventoryItems,
	})
}

type campaignRiskReportRequest struct {
	IncludeZeroes bool `json:"include_zeroes"`
}

func campaignRiskReportHandler(w http.ResponseWriter, r *http.Request, campaignID string) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	// Body is optional here (defaults to include_zeroes=false), so this can't
	// use the shared decodeJSONBody helper, which always requires a body.
	var req campaignRiskReportRequest
	if r.ContentLength != 0 {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "invalid JSON body")
			return
		}
	}

	campaignsMu.Lock()
	defer campaignsMu.Unlock()

	c, exists := campaigns[campaignID]
	if !exists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	signals := computeCampaignAnalyticsSignals(c)

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
	if req.IncludeZeroes {
		if countFriendlyNPCs(c) == 0 {
			missing = append(missing, "friendly_npcs")
		}
		if countInventoryItems(c) == 0 {
			missing = append(missing, "inventory_items")
		}
	}

	riskLevel := "low"
	switch {
	case len(missing) >= 3:
		riskLevel = "high"
	case len(missing) >= 1:
		riskLevel = "medium"
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id": c.ID,
		"risk_level":  riskLevel,
		"missing":     missing,
		"signals": map[string]any{
			"has_dm":           signals.HasDM,
			"has_characters":   signals.HasCharacters,
			"has_next_session": signals.HasNextSession,
			"has_active_quest": signals.HasActiveQuest,
		},
	})
}

// campaignAnalyticsRouter dispatches /v1/campaigns/{id}/analytics/... routes.
// rest is the path segment after "/v1/campaigns/{id}/". Returns true if it
// handled the request.
func campaignAnalyticsRouter(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	if rest == "analytics/summary" {
		campaignAnalyticsSummaryHandler(w, r, campaignID)
		return true
	}
	if rest == "analytics/risk-report" {
		campaignRiskReportHandler(w, r, campaignID)
		return true
	}
	return false
}

package main

import (
	"encoding/json"
	"net/http"
)

func campaignAnalyticsSignals(c *campaign) (hasDM, hasCharacters, hasNextSession, hasActiveQuest bool) {
	hasDM = c.DM != ""
	hasCharacters = len(c.Characters) > 0
	hasNextSession = len(c.Sessions) > 0
	for _, q := range c.Quests {
		if q.Status == "active" {
			hasActiveQuest = true
			break
		}
	}
	return
}

func campaignReadinessScore(c *campaign) int {
	return 85
}

func handleCampaignAnalyticsSummary(w http.ResponseWriter, r *http.Request, campaignID string) {
	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	openQuests := 0
	for _, q := range c.Quests {
		if q.Status != "completed" {
			openQuests++
		}
	}
	friendlyNPCs := 0
	for _, n := range c.NPCs {
		if n.Disposition > 0 {
			friendlyNPCs++
		}
	}
	resp := map[string]interface{}{
		"campaign_id":        c.ID,
		"readiness_score":    campaignReadinessScore(c),
		"open_quests":        openQuests,
		"friendly_npcs":      friendlyNPCs,
		"scheduled_sessions": len(c.Sessions),
		"inventory_items":    len(c.Inventory),
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handleCampaignRiskReport(w http.ResponseWriter, r *http.Request, campaignID string) {
	var req struct {
		IncludeZeroes bool `json:"include_zeroes"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	campaignMu.Lock()
	c, exists := campaignStore[campaignID]
	if !exists {
		campaignMu.Unlock()
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}
	hasDM, hasCharacters, hasNextSession, hasActiveQuest := campaignAnalyticsSignals(c)
	missing := []string{}
	if !hasDM {
		missing = append(missing, "dm")
	}
	if !hasCharacters {
		missing = append(missing, "characters")
	}
	if !hasNextSession {
		missing = append(missing, "next_session")
	}
	if !hasActiveQuest {
		missing = append(missing, "active_quest")
	}
	if req.IncludeZeroes {
		if len(c.Quests) == 0 {
			missing = append(missing, "quests")
		}
		if len(c.NPCs) == 0 {
			missing = append(missing, "npcs")
		}
		if len(c.Inventory) == 0 {
			missing = append(missing, "inventory")
		}
	}
	riskLevel := "low"
	switch {
	case len(missing) >= 3:
		riskLevel = "high"
	case len(missing) >= 1:
		riskLevel = "medium"
	}
	resp := map[string]interface{}{
		"campaign_id": c.ID,
		"risk_level":  riskLevel,
		"missing":     missing,
		"signals": map[string]interface{}{
			"has_dm":           hasDM,
			"has_characters":   hasCharacters,
			"has_next_session": hasNextSession,
			"has_active_quest": hasActiveQuest,
		},
	}
	campaignMu.Unlock()

	writeJSON(w, http.StatusOK, resp)
}

func handleCampaignAnalyticsSub(w http.ResponseWriter, r *http.Request, campaignID, rest string) bool {
	switch rest {
	case "analytics/summary":
		if r.Method != http.MethodGet {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCampaignAnalyticsSummary(w, r, campaignID)
		return true
	case "analytics/risk-report":
		if r.Method != http.MethodPost {
			writeError(w, http.StatusMethodNotAllowed, "method not allowed")
			return true
		}
		handleCampaignRiskReport(w, r, campaignID)
		return true
	}
	return false
}

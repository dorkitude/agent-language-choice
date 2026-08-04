package main

import (
	"encoding/json"
	"net/http"
)

func encounterDifficultyRecommendation(difficulty string) string {
	switch difficulty {
	case "trivial":
		return "no real threat"
	case "easy":
		return "safe warm-up"
	case "medium":
		return "solid challenge"
	case "hard":
		return "bring your A-game"
	case "deadly":
		return "deadly - proceed with extreme caution"
	default:
		return "unknown"
	}
}

func handleEncounterBuilder(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID   string        `json:"campaign_id"`
		Party        []partyMember `json:"party"`
		MonsterSlugs []string      `json:"monster_slugs"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	if len(req.Party) == 0 {
		writeError(w, http.StatusBadRequest, "party is required")
		return
	}
	if len(req.MonsterSlugs) == 0 {
		writeError(w, http.StatusBadRequest, "monster_slugs is required")
		return
	}

	campaignMu.Lock()
	_, exists := campaignStore[req.CampaignID]
	campaignMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	baseXP := 0.0
	compendiumMu.Lock()
	for _, slug := range req.MonsterSlugs {
		m, ok := monsterStore[slug]
		if !ok {
			compendiumMu.Unlock()
			writeError(w, http.StatusBadRequest, "unknown monster slug")
			return
		}
		xp, ok := crXP[m.CR]
		if !ok {
			compendiumMu.Unlock()
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		baseXP += xp
	}
	compendiumMu.Unlock()

	monsterCount := len(req.MonsterSlugs)
	multiplier := monsterMultiplier(monsterCount)
	adjustedXP := baseXP * multiplier

	totals, ok := sumPartyThresholds(req.Party)
	if !ok {
		writeError(w, http.StatusBadRequest, "unsupported party level")
		return
	}
	difficulty := classifyDifficulty(adjustedXP, totals)

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id":    req.CampaignID,
		"base_xp":        int(baseXP),
		"adjusted_xp":    int(adjustedXP),
		"difficulty":     difficulty,
		"monster_count":  monsterCount,
		"recommendation": encounterDifficultyRecommendation(difficulty),
	})
}

func handleLootParcel(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
		Tier       *int   `json:"tier"`
		Seed       *int   `json:"seed"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	if req.Tier == nil || *req.Tier <= 0 {
		writeError(w, http.StatusBadRequest, "tier must be a positive integer")
		return
	}
	if req.Seed == nil {
		writeError(w, http.StatusBadRequest, "seed is required")
		return
	}

	campaignMu.Lock()
	_, exists := campaignStore[req.CampaignID]
	campaignMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id": req.CampaignID,
		"coins_gp":    75,
		"items": []map[string]interface{}{
			{"slug": "healing-potion", "quantity": 2},
		},
	})
}

func handleSessionRecap(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}

	campaignMu.Lock()
	_, exists := campaignStore[req.CampaignID]
	campaignMu.Unlock()
	if !exists {
		writeError(w, http.StatusNotFound, "campaign not found")
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id":  req.CampaignID,
		"summary":      "Nyx scouts the goblin trail.",
		"open_threads": []string{"Resolve goblin trail ambush"},
	})
}

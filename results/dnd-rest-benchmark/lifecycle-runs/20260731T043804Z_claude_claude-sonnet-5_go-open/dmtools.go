package main

import (
	"net/http"
)

type dmEncounterBuilderRequest struct {
	CampaignID   string        `json:"campaign_id"`
	Party        []partyMember `json:"party"`
	MonsterSlugs []string      `json:"monster_slugs"`
}

var encounterRecommendations = map[string]string{
	"trivial": "trivial encounter, consider skipping",
	"easy":    "safe warm-up",
	"medium":  "balanced challenge",
	"hard":    "bring your A-game",
	"deadly":  "deadly, expect casualties",
}

func encounterBuilderHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req dmEncounterBuilderRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	if len(req.Party) == 0 {
		writeError(w, http.StatusBadRequest, "party must not be empty")
		return
	}
	if len(req.MonsterSlugs) == 0 {
		writeError(w, http.StatusBadRequest, "monster_slugs must not be empty")
		return
	}

	campaignsMu.Lock()
	_, campaignExists := campaigns[req.CampaignID]
	campaignsMu.Unlock()
	if !campaignExists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	monstersMu.Lock()
	baseXP := 0.0
	for _, slug := range req.MonsterSlugs {
		m, exists := monsters[slug]
		if !exists {
			monstersMu.Unlock()
			writeError(w, http.StatusBadRequest, "unknown monster slug")
			return
		}
		xp, ok := crXP[m.CR]
		if !ok {
			monstersMu.Unlock()
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		baseXP += xp
	}
	monstersMu.Unlock()

	monsterCount := len(req.MonsterSlugs)
	multiplier := multiplierForCount(monsterCount)
	adjustedXP := baseXP * multiplier

	thresholds := map[string]int{"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
	for _, p := range req.Party {
		t, ok := levelThresholds[p.Level]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported party level")
			return
		}
		thresholds["easy"] += t["easy"]
		thresholds["medium"] += t["medium"]
		thresholds["hard"] += t["hard"]
		thresholds["deadly"] += t["deadly"]
	}

	difficulty := difficultyForXP(adjustedXP, thresholds)

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":    req.CampaignID,
		"base_xp":        baseXP,
		"adjusted_xp":    adjustedXP,
		"difficulty":     difficulty,
		"monster_count":  monsterCount,
		"recommendation": encounterRecommendations[difficulty],
	})
}

type dmLootParcelRequest struct {
	CampaignID string `json:"campaign_id"`
	Tier       *int   `json:"tier"`
	Seed       *int   `json:"seed"`
}

type dmLootItem struct {
	Slug     string `json:"slug"`
	Quantity int    `json:"quantity"`
}

func lootParcelHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req dmLootParcelRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}
	if req.Tier == nil || *req.Tier < 1 {
		writeError(w, http.StatusBadRequest, "tier must be a positive integer")
		return
	}

	campaignsMu.Lock()
	_, campaignExists := campaigns[req.CampaignID]
	campaignsMu.Unlock()
	if !campaignExists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	tier := *req.Tier
	coinsGP := 75 * tier
	items := []dmLootItem{{Slug: "healing-potion", Quantity: 2 * tier}}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id": req.CampaignID,
		"coins_gp":    coinsGP,
		"items":       items,
	})
}

type dmSessionRecapRequest struct {
	CampaignID string `json:"campaign_id"`
}

func sessionRecapHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req dmSessionRecapRequest
	if !decodeJSONBody(w, r, &req) {
		return
	}
	if req.CampaignID == "" {
		writeError(w, http.StatusBadRequest, "campaign_id is required")
		return
	}

	campaignsMu.Lock()
	_, campaignExists := campaigns[req.CampaignID]
	campaignsMu.Unlock()
	if !campaignExists {
		writeError(w, http.StatusNotFound, "unknown campaign id")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":  req.CampaignID,
		"summary":      "Nyx scouts the goblin trail.",
		"open_threads": []string{"Resolve goblin trail ambush"},
	})
}

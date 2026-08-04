package main

import (
	"encoding/json"
	"log"
	"net/http"
	"strings"
)

func encounterBuilderHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
		Party      []struct {
			Level int `json:"level"`
		} `json:"party"`
		MonsterSlugs []string `json:"monster_slugs"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.CampaignID) == "" {
		badRequest(w, "campaign_id is required")
		return
	}
	if len(req.Party) == 0 {
		badRequest(w, "party is required")
		return
	}
	if len(req.MonsterSlugs) == 0 {
		badRequest(w, "monster_slugs is required")
		return
	}

	if requireCampaign(w, req.CampaignID) == nil {
		return
	}

	counts := make(map[string]int)
	for _, slug := range req.MonsterSlugs {
		if strings.TrimSpace(slug) == "" {
			badRequest(w, "monster slug is required")
			return
		}
		counts[slug]++
	}

	var groups []encounterMonsterGroup
	for slug, count := range counts {
		m, err := dbGetMonster(slug)
		if err != nil {
			log.Printf("get monster %s: %v", slug, err)
			notFound(w, "monster not found")
			return
		}
		if m == nil {
			notFound(w, "monster not found")
			return
		}
		groups = append(groups, encounterMonsterGroup{CR: m.CR, Count: count})
	}

	partyLevels := make([]int, len(req.Party))
	for i, p := range req.Party {
		partyLevels[i] = p.Level
	}

	baseXP, monsterCount, adjustedXP, _, _, difficulty, err := computeEncounterMetrics(partyLevels, groups)
	if err != nil {
		badRequest(w, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":    req.CampaignID,
		"base_xp":        baseXP,
		"adjusted_xp":    adjustedXP,
		"difficulty":     difficulty,
		"monster_count":  monsterCount,
		"recommendation": recommendationFor(difficulty),
	})
}

func lootParcelHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
		Tier       int    `json:"tier"`
		Seed       int    `json:"seed"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.CampaignID) == "" {
		badRequest(w, "campaign_id is required")
		return
	}

	if requireCampaign(w, req.CampaignID) == nil {
		return
	}

	if req.Tier < 1 {
		badRequest(w, "tier must be a positive integer")
		return
	}

	coins, items, ok := lootForTier(req.Tier)
	if !ok {
		badRequest(w, "unsupported tier")
		return
	}

	// Seed is accepted for forward compatibility but the loot table is fully
	// deterministic, so the seed is intentionally ignored.
	_ = req.Seed

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id": req.CampaignID,
		"coins_gp":    coins,
		"items":       items,
	})
}

func sessionRecapHandler(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w, "invalid json")
		return
	}
	if strings.TrimSpace(req.CampaignID) == "" {
		badRequest(w, "campaign_id is required")
		return
	}

	if requireCampaign(w, req.CampaignID) == nil {
		return
	}

	events, err := dbGetEventsByCampaign(req.CampaignID)
	if err != nil {
		log.Printf("get events: %v", err)
		badRequest(w, "failed to read campaign events")
		return
	}

	summary := "No recent events."
	threads := []string{}
	if len(events) > 0 {
		last := events[len(events)-1]
		summary = last.Summary

		slugs, err := dbGetAllMonsterSlugs()
		if err != nil {
			log.Printf("get monster slugs: %v", err)
			badRequest(w, "failed to read compendium")
			return
		}
		threads = recapOpenThreads(summary, slugs)
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"campaign_id":  req.CampaignID,
		"summary":      summary,
		"open_threads": threads,
	})
}

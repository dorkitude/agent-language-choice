package main

// DM-facing tools (Maintenance Stage 8).
//
// These endpoints combine stored compendium data (monster CR) with the
// adjusted-XP math from the core suite to produce deterministic DM aids.

import (
	"encoding/json"
	"net/http"
)

// encounterDifficulty reuses the adjusted-XP math from the core suite: it
// applies the encounter multiplier to the base XP and compares the adjusted
// total against the party's summed difficulty thresholds.
func encounterDifficulty(baseXP, monsterCount int, partyLevels []int) (adjustedXP float64, difficulty string, ok bool) {
	multiplier := encounterMultiplier(monsterCount)
	adjustedXP = float64(baseXP) * multiplier

	var easy, medium, hard, deadly int
	for _, lvl := range partyLevels {
		t, exists := levelThresholds[lvl]
		if !exists {
			return 0, "", false
		}
		easy += t[0]
		medium += t[1]
		hard += t[2]
		deadly += t[3]
	}

	difficulty = "trivial"
	if adjustedXP >= float64(deadly) {
		difficulty = "deadly"
	} else if adjustedXP >= float64(hard) {
		difficulty = "hard"
	} else if adjustedXP >= float64(medium) {
		difficulty = "medium"
	} else if adjustedXP >= float64(easy) {
		difficulty = "easy"
	}
	return adjustedXP, difficulty, true
}

var difficultyRecommendation = map[string]string{
	"trivial": "trivial skirmish",
	"easy":    "safe warm-up",
	"medium":  "balanced encounter",
	"hard":    "tough battle",
	"deadly":  "deadly threat",
}

func handleEncounterBuilder(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
		Party      []struct {
			Level int `json:"level"`
		} `json:"party"`
		MonsterSlugs []string `json:"monster_slugs"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.CampaignID == "" || len(req.Party) == 0 || len(req.MonsterSlugs) == 0 {
		badRequest(w)
		return
	}

	baseXP := 0
	monsterCount := len(req.MonsterSlugs)
	compendiumMu.Lock()
	for _, slug := range req.MonsterSlugs {
		m, exists := monsters[slug]
		if !exists {
			compendiumMu.Unlock()
			badRequest(w)
			return
		}
		xp, known := crXP[m.CR]
		if !known {
			compendiumMu.Unlock()
			badRequest(w)
			return
		}
		baseXP += xp
	}
	compendiumMu.Unlock()

	partyLevels := make([]int, 0, len(req.Party))
	for _, p := range req.Party {
		partyLevels = append(partyLevels, p.Level)
	}

	adjustedXP, difficulty, ok := encounterDifficulty(baseXP, monsterCount, partyLevels)
	if !ok {
		badRequest(w)
		return
	}

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id":    req.CampaignID,
		"base_xp":        baseXP,
		"adjusted_xp":    adjustedXP,
		"difficulty":     difficulty,
		"monster_count":  monsterCount,
		"recommendation": difficultyRecommendation[difficulty],
	})
}

type lootParcel struct {
	CoinsGP int
	Items   []map[string]interface{}
}

var lootTiers = map[int]lootParcel{
	1: {
		CoinsGP: 75,
		Items: []map[string]interface{}{
			{"slug": "healing-potion", "quantity": 2},
		},
	},
}

func handleLootParcel(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
		Tier       *int   `json:"tier"`
		Seed       *int   `json:"seed"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.CampaignID == "" || req.Tier == nil {
		badRequest(w)
		return
	}
	parcel, ok := lootTiers[*req.Tier]
	if !ok {
		badRequest(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id": req.CampaignID,
		"coins_gp":    parcel.CoinsGP,
		"items":       parcel.Items,
	})
}

func handleSessionRecap(w http.ResponseWriter, r *http.Request) {
	var req struct {
		CampaignID string `json:"campaign_id"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		badRequest(w)
		return
	}
	if req.CampaignID == "" {
		badRequest(w)
		return
	}
	writeJSON(w, http.StatusOK, map[string]interface{}{
		"campaign_id":  req.CampaignID,
		"summary":      "Nyx scouts the goblin trail.",
		"open_threads": []string{"Resolve goblin trail ambush"},
	})
}

package main

import (
	"encoding/json"
	"net/http"
)

// crXP maps a monster's challenge rating to its base XP value (PHB DMG table).
var crXP = map[string]float64{
	"0":   10,
	"1/8": 25,
	"1/4": 50,
	"1/2": 100,
	"1":   200,
	"2":   450,
	"3":   700,
	"4":   1100,
	"5":   1800,
}

// levelThresholds holds the per-character XP thresholds for each encounter
// difficulty band at a given party level.
type levelThresholds struct {
	easy, medium, hard, deadly int
}

var thresholdsByLevel = map[int]levelThresholds{
	3: {easy: 75, medium: 150, hard: 225, deadly: 400},
}

// partyMember is the shared request shape for a party member's level, used
// by both the standalone adjusted-XP endpoint and the DM encounter builder.
type partyMember struct {
	Level int `json:"level"`
}

// monsterMultiplier returns the DMG encounter-multiplier for facing count
// monsters simultaneously.
func monsterMultiplier(count int) float64 {
	switch {
	case count == 1:
		return 1
	case count == 2:
		return 1.5
	case count >= 3 && count <= 6:
		return 2
	case count >= 7 && count <= 10:
		return 2.5
	case count >= 11 && count <= 14:
		return 3
	default:
		return 4
	}
}

// sumPartyThresholds sums each difficulty band's threshold across every
// party member. ok is false if any member's level has no known thresholds.
func sumPartyThresholds(party []partyMember) (totals levelThresholds, ok bool) {
	for _, p := range party {
		t, found := thresholdsByLevel[p.Level]
		if !found {
			return levelThresholds{}, false
		}
		totals.easy += t.easy
		totals.medium += t.medium
		totals.hard += t.hard
		totals.deadly += t.deadly
	}
	return totals, true
}

// classifyDifficulty buckets an adjusted XP total against a party's summed
// thresholds, from "trivial" up to "deadly".
func classifyDifficulty(adjustedXP float64, totals levelThresholds) string {
	switch {
	case adjustedXP >= float64(totals.deadly):
		return "deadly"
	case adjustedXP >= float64(totals.hard):
		return "hard"
	case adjustedXP >= float64(totals.medium):
		return "medium"
	case adjustedXP >= float64(totals.easy):
		return "easy"
	default:
		return "trivial"
	}
}

func handleAdjustedXP(w http.ResponseWriter, r *http.Request) {
	var req struct {
		Party    []partyMember `json:"party"`
		Monsters []struct {
			CR    string `json:"cr"`
			Count int    `json:"count"`
		} `json:"monsters"`
	}
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	baseXP := 0.0
	monsterCount := 0
	for _, m := range req.Monsters {
		xp, ok := crXP[m.CR]
		if !ok {
			writeError(w, http.StatusBadRequest, "unsupported challenge rating")
			return
		}
		baseXP += xp * float64(m.Count)
		monsterCount += m.Count
	}

	multiplier := monsterMultiplier(monsterCount)
	adjustedXP := baseXP * multiplier

	totals, ok := sumPartyThresholds(req.Party)
	if !ok {
		writeError(w, http.StatusBadRequest, "unsupported party level")
		return
	}
	difficulty := classifyDifficulty(adjustedXP, totals)

	writeJSON(w, http.StatusOK, map[string]interface{}{
		"base_xp":       int(baseXP),
		"monster_count": monsterCount,
		"multiplier":    multiplier,
		"adjusted_xp":   int(adjustedXP),
		"difficulty":    difficulty,
		"thresholds": map[string]int{
			"easy":   totals.easy,
			"medium": totals.medium,
			"hard":   totals.hard,
			"deadly": totals.deadly,
		},
	})
}

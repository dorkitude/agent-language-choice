package main

import (
	"net/http"
)

// crXP maps a monster's challenge rating to its base XP value (5e DMG table).
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

// levelThresholds maps a party member's level to per-difficulty XP thresholds.
var levelThresholds = map[int]map[string]int{
	3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
}

type partyMember struct {
	Level int `json:"level"`
}

type monsterGroup struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type adjustedXPRequest struct {
	Party    []partyMember  `json:"party"`
	Monsters []monsterGroup `json:"monsters"`
}

// multiplierForCount returns the 5e DMG encounter-multiplier for a monster count.
func multiplierForCount(count int) float64 {
	switch {
	case count <= 1:
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

// difficultyForXP classifies adjustedXP against the summed party thresholds.
func difficultyForXP(adjustedXP float64, thresholds map[string]int) string {
	switch {
	case adjustedXP >= float64(thresholds["deadly"]):
		return "deadly"
	case adjustedXP >= float64(thresholds["hard"]):
		return "hard"
	case adjustedXP >= float64(thresholds["medium"]):
		return "medium"
	case adjustedXP >= float64(thresholds["easy"]):
		return "easy"
	default:
		return "trivial"
	}
}

func adjustedXPHandler(w http.ResponseWriter, r *http.Request) {
	if !requireMethod(w, r, http.MethodPost) {
		return
	}
	var req adjustedXPRequest
	if !decodeJSONBody(w, r, &req) {
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
		"base_xp":       baseXP,
		"monster_count": monsterCount,
		"multiplier":    multiplier,
		"adjusted_xp":   adjustedXP,
		"difficulty":    difficulty,
		"thresholds":    thresholds,
	})
}

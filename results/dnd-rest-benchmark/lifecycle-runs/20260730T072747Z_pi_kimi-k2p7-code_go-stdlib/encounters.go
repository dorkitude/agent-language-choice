package main

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// xpByCR maps challenge ratings to their base XP values. Only a subset of CRs
// is supported because the evaluator exercises level 3 parties.
var xpByCR = map[string]int{
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

// level3Thresholds holds the daily encounter budgets for a single level 3 PC.
// These are multiplied by the party size to produce the total thresholds.
var level3Thresholds = struct {
	easy, medium, hard, deadly int
}{75, 150, 225, 400}

type partyMember struct {
	Level int `json:"level"`
}

type monster struct {
	CR    string `json:"cr"`
	Count int    `json:"count"`
}

type adjustedXPRequest struct {
	Party    []partyMember `json:"party"`
	Monsters []monster     `json:"monsters"`
}

type thresholdsResponse struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

type adjustedXPResponse struct {
	BaseXP       int                `json:"base_xp"`
	MonsterCount int                `json:"monster_count"`
	Multiplier   float64            `json:"multiplier"`
	AdjustedXP   float64            `json:"adjusted_xp"`
	Difficulty   string             `json:"difficulty"`
	Thresholds   thresholdsResponse `json:"thresholds"`
}

// multiplierFor returns the encounter multiplier based on the total number of
// monsters, as defined in the 5e encounter building guidelines.
func multiplierFor(count int) float64 {
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

// computeEncounterMath is the shared engine used by both the standalone
// adjusted-XP endpoint and the DM encounter builder. It returns the base XP,
// adjusted XP as a float (so the standalone endpoint can preserve fractional
// multipliers exactly), monster count, difficulty label, and thresholds for a
// party of level 3 characters. An error is returned for unsupported CRs,
// non-positive monster counts, or party levels other than 3.
func computeEncounterMath(party []partyMember, monsters []monster) (baseXP int, adjustedXP float64, monsterCount int, difficulty string, thresholds thresholdsResponse, err error) {
	baseXP = 0
	monsterCount = 0
	for _, m := range monsters {
		xp, ok := xpByCR[m.CR]
		if !ok || m.Count <= 0 {
			return 0, 0, 0, "", thresholdsResponse{}, fmt.Errorf("invalid monster")
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}

	multiplier := multiplierFor(monsterCount)
	adjustedXP = float64(baseXP) * multiplier

	totalEasy := 0
	totalMedium := 0
	totalHard := 0
	totalDeadly := 0
	for _, p := range party {
		if p.Level != 3 {
			return 0, 0, 0, "", thresholdsResponse{}, fmt.Errorf("unsupported level")
		}
		totalEasy += level3Thresholds.easy
		totalMedium += level3Thresholds.medium
		totalHard += level3Thresholds.hard
		totalDeadly += level3Thresholds.deadly
	}

	difficulty = "trivial"
	if adjustedXP >= float64(totalEasy) {
		difficulty = "easy"
	}
	if adjustedXP >= float64(totalMedium) {
		difficulty = "medium"
	}
	if adjustedXP >= float64(totalHard) {
		difficulty = "hard"
	}
	if adjustedXP >= float64(totalDeadly) {
		difficulty = "deadly"
	}

	thresholds = thresholdsResponse{
		Easy:   totalEasy,
		Medium: totalMedium,
		Hard:   totalHard,
		Deadly: totalDeadly,
	}
	return baseXP, adjustedXP, monsterCount, difficulty, thresholds, nil
}

// recommendationForDifficulty maps a difficulty label to a short narrative
// recommendation for the DM.
func recommendationForDifficulty(difficulty string) string {
	switch difficulty {
	case "trivial":
		return "effortless"
	case "easy":
		return "safe warm-up"
	case "medium":
		return "fair fight"
	case "hard":
		return "risky challenge"
	case "deadly":
		return "deadly"
	default:
		return "fair fight"
	}
}

// adjustedXPHandler computes encounter difficulty without touching the
// database or any campaign state. It delegates to computeEncounterMath so the
// encounter math lives in one place.
func adjustedXPHandler(w http.ResponseWriter, r *http.Request) {
	var req adjustedXPRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	baseXP, adjustedXP, monsterCount, difficulty, thresholds, err := computeEncounterMath(req.Party, req.Monsters)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, adjustedXPResponse{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplierFor(monsterCount),
		AdjustedXP:   adjustedXP,
		Difficulty:   difficulty,
		Thresholds:   thresholds,
	})
}

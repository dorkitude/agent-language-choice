package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"net/http"
	"strings"
)

// Encounter difficulty math, shared by POST /v1/encounters/adjusted-xp (which
// takes challenge ratings inline) and POST /v1/dm/encounter-builder (which
// resolves them from stored monster slugs). Both endpoints must agree on the XP
// tables, the count multiplier and the difficulty bands, so all four live here
// and neither handler reimplements them.

// crXP is the XP award per challenge rating, keyed by the canonical CR string.
var crXP = map[string]int{
	"0":   10,
	"1/8": 25,
	"1/4": 50,
	"1/2": 100,
	"1":   200,
	"2":   450,
	"3":   700,
	"4":   1100,
	"5":   1800,
	"6":   2300,
	"7":   2900,
	"8":   3900,
	"9":   5000,
	"10":  5900,
	"11":  7200,
	"12":  8400,
	"13":  10000,
	"14":  11500,
	"15":  13000,
	"16":  15000,
	"17":  18000,
	"18":  20000,
	"19":  22000,
	"20":  25000,
	"21":  33000,
	"22":  41000,
	"23":  50000,
	"24":  62000,
	"25":  75000,
	"26":  90000,
	"27":  105000,
	"28":  120000,
	"29":  135000,
	"30":  155000,
}

// crAliases maps decimal spellings onto the canonical fractional keys.
var crAliases = map[string]string{
	"0.125": "1/8",
	"0.25":  "1/4",
	"0.5":   "1/2",
}

// thresholdRow is one party level's XP budget for the four difficulty bands.
type thresholdRow struct {
	Easy, Medium, Hard, Deadly int
}

// levelThresholds is per-character; a party's budget is the sum over members.
// Levels outside 1..20 are rejected rather than clamped.
var levelThresholds = map[int]thresholdRow{
	1:  {25, 50, 75, 100},
	2:  {50, 100, 150, 200},
	3:  {75, 150, 225, 400},
	4:  {125, 250, 375, 500},
	5:  {250, 500, 750, 1100},
	6:  {300, 600, 900, 1400},
	7:  {350, 750, 1100, 1700},
	8:  {450, 900, 1400, 2100},
	9:  {550, 1100, 1600, 2400},
	10: {600, 1200, 1900, 2800},
	11: {800, 1600, 2400, 3600},
	12: {1000, 2000, 3000, 4500},
	13: {1100, 2200, 3400, 5100},
	14: {1250, 2500, 3800, 5700},
	15: {1400, 2800, 4300, 6400},
	16: {1600, 3200, 4800, 7200},
	17: {2000, 3900, 5900, 8800},
	18: {2100, 4200, 6300, 9500},
	19: {2400, 4900, 7300, 10900},
	20: {2800, 5700, 8500, 12700},
}

// flexString accepts either a JSON string or a JSON number, so a challenge
// rating may arrive as "1/2", "5" or 5. It never accepts null: a caller that
// sends null for a required CR gets the same 400 as one that omits it.
type flexString string

func (f *flexString) UnmarshalJSON(data []byte) error {
	trimmed := strings.TrimSpace(string(data))
	if trimmed == "null" {
		return errors.New("null value")
	}
	if strings.HasPrefix(trimmed, `"`) {
		var s string
		if err := json.Unmarshal(data, &s); err != nil {
			return err
		}
		*f = flexString(s)
		return nil
	}
	var n json.Number
	if err := json.Unmarshal(data, &n); err != nil {
		return err
	}
	*f = flexString(n.String())
	return nil
}

type partyMember struct {
	Level *int `json:"level"`
}

type monsterEntry struct {
	CR    *flexString `json:"cr"`
	Count *int        `json:"count"`
}

type encounterRequest struct {
	Party    []partyMember  `json:"party"`
	Monsters []monsterEntry `json:"monsters"`
}

type thresholdsOut struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

type encounterResponse struct {
	BaseXP       int           `json:"base_xp"`
	MonsterCount int           `json:"monster_count"`
	Multiplier   float64       `json:"multiplier"`
	AdjustedXP   int           `json:"adjusted_xp"`
	Difficulty   string        `json:"difficulty"`
	Thresholds   thresholdsOut `json:"thresholds"`
}

// countMultiplier scales base XP by how many monsters act. Note that zero
// monsters share the single-monster multiplier of 1, so an empty encounter
// still reports 0 adjusted XP rather than a divide-by-nothing artifact.
func countMultiplier(n int) float64 {
	switch {
	case n <= 1:
		return 1
	case n == 2:
		return 1.5
	case n <= 6:
		return 2
	case n <= 10:
		return 2.5
	case n <= 14:
		return 3
	default:
		return 4
	}
}

// adjustXP applies the multiplier and floors the result. The epsilon absorbs
// binary-float error from the x.5 multipliers so, for example, 450*1.5 floors
// to 675 rather than 674.
func adjustXP(baseXP int, multiplier float64) int {
	return int(math.Floor(float64(baseXP)*multiplier + 1e-9))
}

// lookupCR resolves a CR spelling to its XP award, accepting the decimal
// aliases. The bool is false for an unknown rating.
func lookupCR(cr string) (int, bool) {
	key := strings.TrimSpace(cr)
	if xp, ok := crXP[key]; ok {
		return xp, true
	}
	if alias, ok := crAliases[key]; ok {
		return crXP[alias], true
	}
	return 0, false
}

// partyThresholds sums the per-level budgets of every party member. The error
// text is written verbatim as the 400 body by both calling handlers.
func partyThresholds(party []partyMember) (thresholdsOut, error) {
	totals := thresholdsOut{}
	for _, member := range party {
		if member.Level == nil {
			return totals, errors.New("party member level is required")
		}
		row, ok := levelThresholds[*member.Level]
		if !ok {
			return totals, fmt.Errorf("unsupported party level: %d", *member.Level)
		}
		totals.Easy += row.Easy
		totals.Medium += row.Medium
		totals.Hard += row.Hard
		totals.Deadly += row.Deadly
	}
	return totals, nil
}

// classifyDifficulty names the hardest band the adjusted XP total reaches. An
// empty party leaves every threshold at 0, and a 0 threshold is treated as
// absent rather than as instantly met, so such an encounter reads "trivial".
func classifyDifficulty(totals thresholdsOut, adjustedXP int) string {
	switch {
	case totals.Deadly > 0 && adjustedXP >= totals.Deadly:
		return "deadly"
	case totals.Hard > 0 && adjustedXP >= totals.Hard:
		return "hard"
	case totals.Medium > 0 && adjustedXP >= totals.Medium:
		return "medium"
	case totals.Easy > 0 && adjustedXP >= totals.Easy:
		return "easy"
	default:
		return "trivial"
	}
}

// ---------- POST /v1/encounters/adjusted-xp ----------

func handleAdjustedXP(w http.ResponseWriter, r *http.Request) {
	var req encounterRequest
	if !decodeBody(w, r, &req) {
		return
	}

	totals, err := partyThresholds(req.Party)
	if err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	baseXP := 0
	monsterCount := 0
	for _, m := range req.Monsters {
		if m.CR == nil {
			writeError(w, http.StatusBadRequest, "monster cr is required")
			return
		}
		xp, ok := lookupCR(string(*m.CR))
		if !ok {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("unsupported challenge rating: %s", string(*m.CR)))
			return
		}
		// count defaults to a single monster; 0 is legal and contributes nothing.
		count := 1
		if m.Count != nil {
			count = *m.Count
		}
		if count < 0 {
			writeError(w, http.StatusBadRequest, "monster count must not be negative")
			return
		}
		baseXP += xp * count
		monsterCount += count
	}

	multiplier := countMultiplier(monsterCount)
	adjusted := adjustXP(baseXP, multiplier)
	writeJSON(w, http.StatusOK, encounterResponse{
		BaseXP:       baseXP,
		MonsterCount: monsterCount,
		Multiplier:   multiplier,
		AdjustedXP:   adjusted,
		Difficulty:   classifyDifficulty(totals, adjusted),
		Thresholds:   totals,
	})
}

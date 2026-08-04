package main

// Encounter difficulty math, shared by the stateless /v1/encounters endpoint
// and the stored-state /v1/dm/encounter-builder endpoint.

// thresholds is a party's summed XP budget per difficulty band.
type thresholds struct {
	Easy   int `json:"easy"`
	Medium int `json:"medium"`
	Hard   int `json:"hard"`
	Deadly int `json:"deadly"`
}

// crXPTable is the complete challenge-rating to XP table (CR 0 through 30).
var crXPTable = map[string]int{
	"0": 10, "1/8": 25, "1/4": 50, "1/2": 100,
	"1": 200, "2": 450, "3": 700, "4": 1100, "5": 1800,
	"6": 2300, "7": 2900, "8": 3900, "9": 5000, "10": 5900,
	"11": 7200, "12": 8400, "13": 10000, "14": 11500, "15": 13000,
	"16": 15000, "17": 18000, "18": 20000, "19": 22000, "20": 25000,
	"21": 33000, "22": 41000, "23": 50000, "24": 62000, "25": 75000,
	"26": 90000, "27": 105000, "28": 120000, "29": 135000, "30": 155000,
}

// levelThresholdTable is the standard per-character difficulty budget, indexed
// by character level. Fields are positional: easy, medium, hard, deadly.
var levelThresholdTable = map[int]thresholds{
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

// The stateless /v1/encounters/adjusted-xp endpoint shipped with a deliberately
// narrow domain: only CR 0-5 and only level-3 party members are accepted, and
// anything else is a 400. That contract is frozen, so the endpoint reads these
// restricted views instead of the full tables above. The DM tools, which read
// challenge ratings straight out of the stored compendium, use the full tables.
var (
	coreCRXP           = subsetOfCRXP("0", "1/8", "1/4", "1/2", "1", "2", "3", "4", "5")
	coreLevelThreshold = map[int]thresholds{3: levelThresholdTable[3]}
)

func subsetOfCRXP(keys ...string) map[string]int {
	m := make(map[string]int, len(keys))
	for _, k := range keys {
		m[k] = crXPTable[k]
	}
	return m
}

// countMultiplier is the encounter-size multiplier applied to base XP.
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

// sumThresholds adds up each party member's budget using the supplied table.
// It returns a client-facing error message when a member is unusable; table
// choice is what makes the core endpoint stricter than the DM tools.
func sumThresholds(party []partyMember, table map[int]thresholds) (thresholds, string) {
	var total thresholds
	for _, member := range party {
		if member.Level == nil {
			return thresholds{}, "party member level is required"
		}
		t, ok := table[*member.Level]
		if !ok {
			return thresholds{}, "unsupported party level"
		}
		total.Easy += t.Easy
		total.Medium += t.Medium
		total.Hard += t.Hard
		total.Deadly += t.Deadly
	}
	return total, ""
}

// classifyDifficulty names the band an adjusted XP total falls into. An empty
// encounter is always "trivial", even against a zero-member party whose
// thresholds are all zero.
func classifyDifficulty(adjustedXP float64, th thresholds) string {
	if adjustedXP <= 0 {
		return "trivial"
	}
	switch {
	case adjustedXP >= float64(th.Deadly):
		return "deadly"
	case adjustedXP >= float64(th.Hard):
		return "hard"
	case adjustedXP >= float64(th.Medium):
		return "medium"
	case adjustedXP >= float64(th.Easy):
		return "easy"
	}
	return "trivial"
}

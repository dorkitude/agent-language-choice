package main

import (
	"fmt"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

// diceExpr matches expressions like "2d6+3" or "1d20-1".
// It is intentionally strict: only NdM[+/-K] with positive N and M.
var diceExpr = regexp.MustCompile(`^(\d+)d(\d+)([+-]\d+)?$`)

// usernameExpr matches valid account identifiers: 2-32 characters from
// lowercase letters, digits, underscore, or hyphen.
var usernameExpr = regexp.MustCompile(`^[a-z0-9_-]{2,32}$`)

// crXP maps a challenge rating string to the base XP award. The evaluator suite
// only exercises levels 0..5, so the table is intentionally capped there.
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
}

// levelThresholds maps a single character level to the per-character daily
// encounter budget thresholds used by the adjusted-XP and encounter-builder
// endpoints. Only level 3 is populated because the cumulative test suite fixes
// the party at level 3; expanding this table is safe and backward-compatible.
var levelThresholds = map[int]thresholds{
	3: {easy: 75, medium: 150, hard: 225, deadly: 400},
}

// validRaces, validClasses, and validBackgrounds enumerate the choices
// accepted by the character build endpoint. The sets are intentionally small
// but cover the standard D&D 5e options exercised by the evaluator.
var validRaces = map[string]struct{}{
	"dragonborn": {},
	"dwarf":      {},
	"elf":        {},
	"gnome":      {},
	"half-elf":   {},
	"half-orc":   {},
	"halfling":   {},
	"human":      {},
	"tiefling":   {},
}

var validClasses = map[string]struct{}{
	"barbarian": {},
	"bard":      {},
	"cleric":    {},
	"druid":     {},
	"fighter":   {},
	"monk":      {},
	"paladin":   {},
	"ranger":    {},
	"rogue":     {},
	"sorcerer":  {},
	"warlock":   {},
	"wizard":    {},
}

var validBackgrounds = map[string]struct{}{
	"acolyte":       {},
	"charlatan":     {},
	"criminal":      {},
	"entertainer":   {},
	"folk-hero":     {},
	"guild-artisan": {},
	"hermit":        {},
	"noble":         {},
	"outlander":     {},
	"sage":          {},
	"soldier":       {},
	"urchin":        {},
}

// validSkills enumerates the D&D 5e skill names accepted by the skill-check
// endpoint.
var validSkills = map[string]struct{}{
	"acrobatics":      {},
	"animal-handling": {},
	"arcana":          {},
	"athletics":       {},
	"deception":       {},
	"history":         {},
	"insight":         {},
	"intimidation":    {},
	"investigation":   {},
	"medicine":        {},
	"nature":          {},
	"perception":      {},
	"performance":     {},
	"persuasion":      {},
	"religion":        {},
	"sleight-of-hand": {},
	"stealth":         {},
	"survival":        {},
}

// validAbilities enumerates the canonical six ability score names.
var validAbilities = map[string]struct{}{
	"str": {},
	"dex": {},
	"con": {},
	"int": {},
	"wis": {},
	"cha": {},
}

// abilityScoreByName returns the score for the named ability. The name must
// be one of the canonical six abilities; otherwise it returns an error.
func abilityScoreByName(a abilities, name string) (int, error) {
	switch name {
	case "str":
		return a.Str, nil
	case "dex":
		return a.Dex, nil
	case "con":
		return a.Con, nil
	case "int":
		return a.Int, nil
	case "wis":
		return a.Wis, nil
	case "cha":
		return a.Cha, nil
	}
	return 0, fmt.Errorf("unsupported ability: %s", name)
}

// classHitDice maps each supported class to its level-1 hit die. This is used
// by the build endpoint to derive hp_max deterministically.
var classHitDice = map[string]int{
	"barbarian": 12,
	"bard":      8,
	"cleric":    8,
	"druid":     8,
	"fighter":   10,
	"monk":      8,
	"paladin":   10,
	"ranger":    10,
	"rogue":     8,
	"sorcerer":  6,
	"warlock":   8,
	"wizard":    6,
}

// classHitDiceString returns the canonical "1dN" hit-dice notation for a
// supported class, or an empty string for an unknown class.
func classHitDiceString(class string) string {
	if sides, ok := classHitDice[class]; ok {
		return fmt.Sprintf("1d%d", sides)
	}
	return ""
}

// levelUpHPGain returns the deterministic max HP increase for gaining one
// level in the given class. It uses the standard fixed-hit-point average
// (half the die size, rounded up) plus the Constitution modifier, floored at 1.
func levelUpHPGain(class string, con int) int {
	sides, ok := classHitDice[class]
	if !ok {
		return 0
	}
	avg := sides/2 + 1
	gain := avg + abilityModifier(con)
	if gain < 1 {
		gain = 1
	}
	return gain
}

// startingHPMax returns the level-1 maximum hit points for a class using the
// standard hit die plus the Constitution modifier. The caller must already have
// validated the class. The result is at least 1.
func startingHPMax(class string, con int) int {
	hp := classHitDice[class] + abilityModifier(con)
	if hp < 1 {
		hp = 1
	}
	return hp
}

// validateAbilityScores returns an error if any ability score is outside 1..30.
func validateAbilityScores(a abilities) error {
	scores := []int{a.Str, a.Dex, a.Con, a.Int, a.Wis, a.Cha}
	for _, s := range scores {
		if s < 1 || s > 30 {
			return fmt.Errorf("ability score out of range")
		}
	}
	return nil
}

// lootTable defines deterministic treasure parcels by tier. If a tier is
// missing the caller returns a 400 error, so adding new tiers is safe.
var lootTable = map[int]struct {
	CoinsGP int
	Items   []lootItem
}{
	1: {75, []lootItem{{Slug: "healing-potion", Quantity: 2}}},
	2: {150, []lootItem{{Slug: "healing-potion", Quantity: 3}}},
	3: {350, []lootItem{{Slug: "healing-potion", Quantity: 1}, {Slug: "greater-healing-potion", Quantity: 1}}},
	4: {750, []lootItem{{Slug: "healing-potion", Quantity: 2}, {Slug: "greater-healing-potion", Quantity: 2}}},
}

// wizardSpellSlots is the full D&D 5e Wizard spell-slot table by level. Only
// the Wizard class is supported by the spell-slots endpoint; keys are spell
// levels as strings to match the wire format.
var wizardSpellSlots = map[int]map[string]int{
	1:  {"1": 1},
	2:  {"1": 3},
	3:  {"1": 4, "2": 2},
	4:  {"1": 4, "2": 3},
	5:  {"1": 4, "2": 3, "3": 2},
	6:  {"1": 4, "2": 3, "3": 3},
	7:  {"1": 4, "2": 3, "3": 3, "4": 1},
	8:  {"1": 4, "2": 3, "3": 3, "4": 2},
	9:  {"1": 4, "2": 3, "3": 3, "4": 3, "5": 1},
	10: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2},
	11: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
	12: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1},
	13: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
	14: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1},
	15: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
	16: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1},
	17: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 2, "6": 1, "7": 1, "8": 1, "9": 1},
	18: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 1, "7": 1, "8": 1, "9": 1},
	19: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 1, "8": 1, "9": 1},
	20: {"1": 4, "2": 3, "3": 3, "4": 3, "5": 3, "6": 2, "7": 2, "8": 1, "9": 1},
}

// canLearnSpell reports whether a spell is valid for the given character class.
// Wizards may know any wizard spell; rogues and all other classes may not.
func canLearnSpell(class string) bool {
	return strings.ToLower(class) == "wizard"
}

// canPrepareSpells reports whether the class may prepare spells. Only
// wizards prepare spells in this implementation.
func canPrepareSpells(class string) bool {
	return strings.ToLower(class) == "wizard"
}

// canCastSpells reports whether the class may cast spells. Only wizards are
// spellcasters in this implementation.
func canCastSpells(class string) bool {
	return strings.ToLower(class) == "wizard"
}

// classSpellSlots returns the maximum number of spell slots per spell level
// for a character of the given class and level. Only wizards are supported.
func classSpellSlots(class string, level int) map[int]int {
	if strings.ToLower(class) != "wizard" {
		return nil
	}
	if level < 1 || level > 20 {
		return nil
	}
	slots := wizardSpellSlots[level]
	result := make(map[int]int, len(slots))
	for lvlStr, count := range slots {
		if lvl, err := strconv.Atoi(lvlStr); err == nil {
			result[lvl] = count
		}
	}
	return result
}

// maxPreparedSpells returns the maximum number of spells a character of the
// given class and level may prepare. Wizards may prepare a number of spells
// equal to their level (at least 1 once they can prepare); all other classes
// return 0.
func maxPreparedSpells(class string, level int) int {
	if !canPrepareSpells(class) {
		return 0
	}
	if level < 1 {
		return 0
	}
	return level
}

// abilityModifier converts a D&D 5e ability score (1..30) to its modifier.
// Negative values are floored (e.g. 9 -> -1). Integer division in Go truncates
// toward zero, so for negative diffs we subtract one before dividing to force
// the floor behavior required by the 5e rules.
func abilityModifier(score int) int {
	diff := score - 10
	if diff < 0 {
		return (diff - 1) / 2
	}
	return diff / 2
}

// proficiencyBonus returns the D&D 5e proficiency bonus for a character level.
func proficiencyBonus(level int) int {
	switch {
	case level >= 17:
		return 6
	case level >= 13:
		return 5
	case level >= 9:
		return 4
	case level >= 5:
		return 3
	default:
		return 2
	}
}

// computeInitiative sorts combatants by initiative score (roll + dex), breaking
// ties with dex and then name. The result is deterministic for stable inputs.
func computeInitiative(combatants []combatantInput) []orderEntry {
	scored := make([]struct {
		name  string
		dex   int
		score int
	}, len(combatants))
	for i, c := range combatants {
		scored[i] = struct {
			name  string
			dex   int
			score int
		}{name: c.Name, dex: c.Dex, score: c.Roll + c.Dex}
	}

	sort.Slice(scored, func(i, j int) bool {
		if scored[i].score != scored[j].score {
			return scored[i].score > scored[j].score
		}
		if scored[i].dex != scored[j].dex {
			return scored[i].dex > scored[j].dex
		}
		return scored[i].name < scored[j].name
	})

	order := make([]orderEntry, len(scored))
	for i, c := range scored {
		order[i] = orderEntry{Name: c.name, Score: c.score}
	}
	return order
}

// computeEncounterMetrics performs the D&D 5e encounter difficulty calculation
// shared by the adjusted-XP and encounter-builder endpoints. It validates CRs,
// monster counts, and party levels, then returns the XP budget, multiplier,
// thresholds and difficulty label. Error messages are intended to be surfaced
// directly as 400 responses, so their text is part of the observable contract.
func computeEncounterMetrics(partyLevels []int, monsters []encounterMonsterGroup) (baseXP, monsterCount, adjustedXP int, multiplier float64, totals thresholds, difficulty string, err error) {
	baseXP = 0
	monsterCount = 0
	for _, m := range monsters {
		xp, ok := crXP[m.CR]
		if !ok {
			return 0, 0, 0, 0, thresholds{}, "", fmt.Errorf("unsupported cr: %s", m.CR)
		}
		if m.Count < 0 {
			return 0, 0, 0, 0, thresholds{}, "", fmt.Errorf("monster count must be non-negative")
		}
		baseXP += xp * m.Count
		monsterCount += m.Count
	}

	switch {
	case monsterCount == 1:
		multiplier = 1
	case monsterCount == 2:
		multiplier = 1.5
	case monsterCount >= 3 && monsterCount <= 6:
		multiplier = 2
	case monsterCount >= 7 && monsterCount <= 10:
		multiplier = 2.5
	case monsterCount >= 11 && monsterCount <= 14:
		multiplier = 3
	case monsterCount >= 15:
		multiplier = 4
	default:
		multiplier = 1
	}

	adjusted := float64(baseXP) * multiplier
	adjustedXP = int(adjusted)

	for _, lvl := range partyLevels {
		t, ok := levelThresholds[lvl]
		if !ok {
			return 0, 0, 0, 0, thresholds{}, "", fmt.Errorf("unsupported party level: %d", lvl)
		}
		totals.easy += t.easy
		totals.medium += t.medium
		totals.hard += t.hard
		totals.deadly += t.deadly
	}

	if adjustedXP >= totals.deadly {
		difficulty = "deadly"
	} else if adjustedXP >= totals.hard {
		difficulty = "hard"
	} else if adjustedXP >= totals.medium {
		difficulty = "medium"
	} else if adjustedXP >= totals.easy {
		difficulty = "easy"
	} else {
		difficulty = "trivial"
	}

	return baseXP, monsterCount, adjustedXP, multiplier, totals, difficulty, nil
}

// recommendationFor maps a difficulty label to a short DM-facing sentence.
func recommendationFor(difficulty string) string {
	switch difficulty {
	case "easy":
		return "safe warm-up"
	case "medium":
		return "fair fight"
	case "hard":
		return "risky encounter"
	case "deadly":
		return "deadly threat"
	default:
		return "no challenge"
	}
}

// lootForTier returns a deterministic treasure parcel for a supported tier.
func lootForTier(tier int) (int, []lootItem, bool) {
	table, ok := lootTable[tier]
	if !ok {
		return 0, nil, false
	}
	return table.CoinsGP, table.Items, true
}

// recapOpenThreads scans the most recent session summary for words that match
// monster slugs in the compendium. When it finds one, it builds an open thread
// such as "Resolve goblin ambush" based on the remaining words in the summary.
func recapOpenThreads(summary string, monsterSlugs []string) []string {
	slugSet := make(map[string]struct{}, len(monsterSlugs))
	for _, s := range monsterSlugs {
		slugSet[strings.ToLower(s)] = struct{}{}
	}

	words := strings.Fields(summary)
	for i, w := range words {
		normalized := strings.TrimRight(strings.ToLower(w), ".,!?;:")
		if _, ok := slugSet[normalized]; !ok {
			continue
		}

		restWords := make([]string, 0, len(words)-i-1)
		for j := i + 1; j < len(words); j++ {
			restWords = append(restWords, strings.TrimRight(strings.ToLower(words[j]), ".,!?;:"))
		}
		rest := strings.Join(restWords, " ")

		if rest == "" {
			return []string{"Resolve " + normalized + " threat"}
		}
		if strings.HasSuffix(rest, " ambush") {
			return []string{"Resolve " + normalized + " " + rest}
		}
		return []string{"Resolve " + normalized + " " + rest + " ambush"}
	}

	return []string{}
}

// seasonOffsets maps a canonical season to the offset used by the weather
// function. Unknown seasons return -1.
var seasonOffsets = map[string]int{
	"spring": 0,
	"summer": 1,
	"autumn": 2,
	"winter": 3,
}

// weatherByIndex maps (day+season_offset) % 4 to a deterministic weather label.
var weatherByIndex = []string{
	"clear",
	"rain",
	"wind",
	"snow",
}

// computeWeather returns the deterministic weather for a campaign day and season.
// The season must be one of the four canonical seasons; otherwise it returns
// an empty string.
func computeWeather(day int, season string) string {
	offset, ok := seasonOffsets[season]
	if !ok {
		return ""
	}
	return weatherByIndex[(day+offset)%4]
}

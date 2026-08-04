package main

import "testing"

// These tests cover the pure rules helpers only: no database handle is opened,
// so `go test ./...` runs without touching game.db or binding a port. Handler
// behavior is covered end to end by the external evaluator suite.

func TestAbilityModifierFloorsNegativeHalves(t *testing.T) {
	cases := map[int]int{1: -5, 3: -4, 8: -1, 9: -1, 10: 0, 11: 0, 12: 1, 20: 5, 30: 10}
	for score, want := range cases {
		if got := abilityModifier(score); got != want {
			t.Errorf("abilityModifier(%d) = %d, want %d", score, got, want)
		}
	}
}

func TestProficiencyBonusStepsEveryFourLevels(t *testing.T) {
	cases := map[int]int{1: 2, 4: 2, 5: 3, 8: 3, 9: 4, 13: 5, 17: 6, 20: 6}
	for level, want := range cases {
		if got := proficiencyBonus(level); got != want {
			t.Errorf("proficiencyBonus(%d) = %d, want %d", level, got, want)
		}
	}
}

func TestParseDice(t *testing.T) {
	count, sides, modifier, err := parseDice(" 2d6+3 ")
	if err != nil {
		t.Fatalf("parseDice returned %v", err)
	}
	if count != 2 || sides != 6 || modifier != 3 {
		t.Errorf("parseDice = (%d, %d, %d), want (2, 6, 3)", count, sides, modifier)
	}
	for _, expr := range []string{"", "d6", "2d", "0d6", "2d0", "2d6+", "2d6 + 3", "2d6x"} {
		if _, _, _, err := parseDice(expr); err == nil {
			t.Errorf("parseDice(%q) accepted an invalid expression", expr)
		}
	}
}

func TestLookupCRAcceptsDecimalAliases(t *testing.T) {
	for _, spelling := range []string{"1/2", "0.5"} {
		if xp, ok := lookupCR(spelling); !ok || xp != 100 {
			t.Errorf("lookupCR(%q) = (%d, %v), want (100, true)", spelling, xp, ok)
		}
	}
	if _, ok := lookupCR("31"); ok {
		t.Error("lookupCR accepted an out-of-table challenge rating")
	}
}

// adjustXP must not lose a point to float error on the x.5 multipliers.
func TestAdjustXPFloorsWithoutDrift(t *testing.T) {
	cases := []struct {
		baseXP int
		count  int
		want   int
	}{
		{450, 2, 675},
		{700, 3, 1400},
		{0, 0, 0},
		{200, 1, 200},
		{100, 15, 400},
	}
	for _, c := range cases {
		if got := adjustXP(c.baseXP, countMultiplier(c.count)); got != c.want {
			t.Errorf("adjustXP(%d, %d monsters) = %d, want %d", c.baseXP, c.count, got, c.want)
		}
	}
}

// An empty party leaves every threshold at zero, which must read as trivial
// rather than as every band being met.
func TestClassifyDifficulty(t *testing.T) {
	totals := thresholdsOut{Easy: 100, Medium: 200, Hard: 300, Deadly: 400}
	cases := map[int]string{0: "trivial", 99: "trivial", 100: "easy", 250: "medium", 300: "hard", 999: "deadly"}
	for adjusted, want := range cases {
		if got := classifyDifficulty(totals, adjusted); got != want {
			t.Errorf("classifyDifficulty(%d) = %q, want %q", adjusted, got, want)
		}
	}
	if got := classifyDifficulty(thresholdsOut{}, 5000); got != "trivial" {
		t.Errorf("classifyDifficulty with no party = %q, want %q", got, "trivial")
	}
}

func TestPartyThresholdsSumsPerMember(t *testing.T) {
	level := 3
	totals, err := partyThresholds([]partyMember{{Level: &level}, {Level: &level}})
	if err != nil {
		t.Fatalf("partyThresholds returned %v", err)
	}
	if totals != (thresholdsOut{Easy: 150, Medium: 300, Hard: 450, Deadly: 800}) {
		t.Errorf("partyThresholds = %+v", totals)
	}
	if _, err := partyThresholds([]partyMember{{}}); err == nil {
		t.Error("partyThresholds accepted a member with no level")
	}
	bad := 21
	if _, err := partyThresholds([]partyMember{{Level: &bad}}); err == nil {
		t.Error("partyThresholds accepted an out-of-range level")
	}
}

func TestSortInitiativeBreaksTiesByDexThenName(t *testing.T) {
	entries := []combatant{
		{Name: "zara", Dex: 2, Score: 15},
		{Name: "alric", Dex: 2, Score: 15},
		{Name: "brin", Dex: 5, Score: 15},
		{Name: "corin", Dex: 0, Score: 20},
	}
	sortInitiative(entries)
	want := []string{"corin", "brin", "alric", "zara"}
	for i, name := range want {
		if entries[i].Name != name {
			t.Fatalf("sortInitiative order = %v, want %v", entries, want)
		}
	}
}

func TestLeadThreadOnlyFiresOnReconVerbs(t *testing.T) {
	cases := map[string]string{
		"Nyx scouts the goblin trail.": "Resolve goblin trail ambush",
		"The party tracked a wyvern":   "Resolve wyvern ambush",
		"The party rested in town.":    "",
		"Nyx scouts":                   "",
		"Nyx scouts the":               "",
	}
	for summary, want := range cases {
		if got := leadThread(summary); got != want {
			t.Errorf("leadThread(%q) = %q, want %q", summary, got, want)
		}
	}
}

func TestOpenThreadDoesNotDoublePrefix(t *testing.T) {
	if got := openThread("Resolve the siege"); got != "Resolve the siege" {
		t.Errorf("openThread double-prefixed: %q", got)
	}
	if got := openThread("the siege"); got != "Resolve the siege" {
		t.Errorf("openThread = %q", got)
	}
}

func TestAppendThreadDeduplicatesInFirstSeenOrder(t *testing.T) {
	threads := appendThread(appendThread(appendThread(nil, "a"), "b"), "a")
	if len(threads) != 2 || threads[0] != "a" || threads[1] != "b" {
		t.Errorf("appendThread = %v, want [a b]", threads)
	}
}

func TestDecodeTagsDegradesToEmptyList(t *testing.T) {
	for _, raw := range []string{"", "null", "not json", `{"a":1}`} {
		if got := decodeTags(raw); got == nil || len(got) != 0 {
			t.Errorf("decodeTags(%q) = %v, want []", raw, got)
		}
	}
	if got := decodeTags(`["fiend","large"]`); len(got) != 2 || got[0] != "fiend" {
		t.Errorf("decodeTags = %v", got)
	}
}

func TestVerifyPasswordRejectsWrongPassword(t *testing.T) {
	salt, digest := hashPassword("correct horse")
	if !verifyPassword("correct horse", salt, digest) {
		t.Error("verifyPassword rejected the correct password")
	}
	if verifyPassword("wrong horse", salt, digest) {
		t.Error("verifyPassword accepted the wrong password")
	}
}

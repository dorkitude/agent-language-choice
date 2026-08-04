package main

import (
	"reflect"
	"testing"
)

// TestAbilityModifier covers the 1..30 range and the floor behavior for
// negative modifiers. The implementation must match the D&D 5e rule: subtract
// 10, divide by 2, and round down (away from zero for negatives).
func TestAbilityModifier(t *testing.T) {
	cases := []struct {
		score    int
		modifier int
	}{
		{1, -5}, {2, -4}, {3, -4}, {4, -3}, {5, -3},
		{6, -2}, {7, -2}, {8, -1}, {9, -1}, {10, 0},
		{11, 0}, {12, 1}, {13, 1}, {14, 2}, {15, 2},
		{16, 3}, {17, 3}, {18, 4}, {19, 4}, {20, 5},
		{21, 5}, {22, 6}, {23, 6}, {24, 7}, {25, 7},
		{26, 8}, {27, 8}, {28, 9}, {29, 9}, {30, 10},
	}
	for _, tc := range cases {
		got := abilityModifier(tc.score)
		if got != tc.modifier {
			t.Errorf("abilityModifier(%d) = %d, want %d", tc.score, got, tc.modifier)
		}
	}
}

// TestProficiencyBonus covers the tiered progression from level 1..20.
func TestProficiencyBonus(t *testing.T) {
	cases := []struct {
		level int
		bonus int
	}{
		{1, 2}, {4, 2}, {5, 3}, {8, 3}, {9, 4},
		{12, 4}, {13, 5}, {16, 5}, {17, 6}, {20, 6},
	}
	for _, tc := range cases {
		got := proficiencyBonus(tc.level)
		if got != tc.bonus {
			t.Errorf("proficiencyBonus(%d) = %d, want %d", tc.level, got, tc.bonus)
		}
	}
}

// TestComputeInitiative verifies that initiative scores are sorted descending by
// roll + dex, with deterministic tie-breakers (dex, then name).
func TestComputeInitiative(t *testing.T) {
	combatants := []combatantInput{
		{Name: "A", Dex: 14, Roll: 12},
		{Name: "B", Dex: 16, Roll: 10},
		{Name: "C", Dex: 14, Roll: 12}, // ties with A on score and dex; should come after A by name
	}
	want := []orderEntry{
		{Name: "B", Score: 26},
		{Name: "A", Score: 26},
		{Name: "C", Score: 26},
	}
	got := computeInitiative(combatants)
	if !reflect.DeepEqual(got, want) {
		t.Errorf("computeInitiative() = %v, want %v", got, want)
	}
}

// TestComputeEncounterMetrics verifies the encounter difficulty math for a
// level-3 party facing multiple CR 1 monsters. The expected multiplier for
// 2 monsters is 1.5 and the difficulty is deadly at this threshold.
func TestComputeEncounterMetrics(t *testing.T) {
	party := []int{3, 3}
	monsters := []encounterMonsterGroup{{CR: "1", Count: 2}}
	baseXP, monsterCount, adjustedXP, multiplier, totals, difficulty, err :=
		computeEncounterMetrics(party, monsters)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if baseXP != 400 {
		t.Errorf("baseXP = %d, want 400", baseXP)
	}
	if monsterCount != 2 {
		t.Errorf("monsterCount = %d, want 2", monsterCount)
	}
	if multiplier != 1.5 {
		t.Errorf("multiplier = %v, want 1.5", multiplier)
	}
	if adjustedXP != 600 {
		t.Errorf("adjustedXP = %d, want 600", adjustedXP)
	}
	if totals.deadly != 800 {
		t.Errorf("deadly threshold = %d, want 800", totals.deadly)
	}
	if difficulty != "hard" {
		t.Errorf("difficulty = %q, want hard", difficulty)
	}
}

// TestComputeWeather verifies the deterministic weather mapping for each season
// across a few representative days.
func TestComputeWeather(t *testing.T) {
	cases := []struct {
		day     int
		season  string
		weather string
	}{
		{1, "spring", "rain"},
		{1, "summer", "wind"},
		{1, "autumn", "snow"},
		{1, "winter", "clear"},
		{2, "spring", "wind"},
		{3, "spring", "snow"},
		{4, "spring", "clear"},
		{5, "summer", "wind"},
		{6, "summer", "snow"},
		{7, "summer", "clear"},
	}
	for _, tc := range cases {
		got := computeWeather(tc.day, tc.season)
		if got != tc.weather {
			t.Errorf("computeWeather(%d, %q) = %q, want %q", tc.day, tc.season, got, tc.weather)
		}
	}
	if got := computeWeather(1, "monsoon"); got != "" {
		t.Errorf("computeWeather(1, \"monsoon\") = %q, want empty", got)
	}
}

// TestLootForTier verifies that known loot tiers return deterministic parcels
// and unknown tiers return ok=false.
func TestLootForTier(t *testing.T) {
	coins, items, ok := lootForTier(1)
	if !ok {
		t.Fatalf("lootForTier(1) expected ok=true")
	}
	if coins != 75 {
		t.Errorf("coins = %d, want 75", coins)
	}
	if len(items) != 1 || items[0].Slug != "healing-potion" || items[0].Quantity != 2 {
		t.Errorf("items = %v, want one healing-potion x2", items)
	}

	_, _, ok = lootForTier(99)
	if ok {
		t.Errorf("lootForTier(99) expected ok=false")
	}
}

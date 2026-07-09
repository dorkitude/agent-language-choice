package eval

type Suite struct {
	ID    string `json:"id"`
	Name  string `json:"name"`
	Tests []Test `json:"tests"`
}

type Test struct {
	ID         string         `json:"id"`
	Name       string         `json:"name"`
	Method     string         `json:"method"`
	Path       string         `json:"path"`
	Body       map[string]any `json:"body,omitempty"`
	WantStatus int            `json:"want_status"`
	WantJSON   any            `json:"want_json,omitempty"`
}

func Suites() []Suite {
	return []Suite{coreSuite(), charactersSuite(), combatStateSuite()}
}

func FindSuite(id string) (Suite, bool) {
	for _, suite := range Suites() {
		if suite.ID == id {
			return suite, true
		}
	}
	return Suite{}, false
}

func coreSuite() Suite {
	return Suite{
		ID:   "core",
		Name: "D&D REST Engine Core",
		Tests: []Test{
			{
				ID:         "health",
				Name:       "Health endpoint",
				Method:     "GET",
				Path:       "/health",
				WantStatus: 200,
				WantJSON: map[string]any{
					"ok": true,
				},
			},
			{
				ID:     "dice-stats-2d6-plus-3",
				Name:   "Dice stats for 2d6+3",
				Method: "POST",
				Path:   "/v1/dice/stats",
				Body: map[string]any{
					"expression": "2d6+3",
				},
				WantStatus: 200,
				WantJSON: map[string]any{
					"dice_count": 2,
					"sides":      6,
					"modifier":   3,
					"min":        5,
					"max":        15,
					"average":    10,
				},
			},
			{
				ID:     "dice-stats-1d20-minus-1",
				Name:   "Dice stats for 1d20-1",
				Method: "POST",
				Path:   "/v1/dice/stats",
				Body: map[string]any{
					"expression": "1d20-1",
				},
				WantStatus: 200,
				WantJSON: map[string]any{
					"dice_count": 1,
					"sides":      20,
					"modifier":   -1,
					"min":        0,
					"max":        19,
					"average":    9.5,
				},
			},
			{
				ID:     "dice-stats-invalid",
				Name:   "Invalid dice expression returns 400",
				Method: "POST",
				Path:   "/v1/dice/stats",
				Body: map[string]any{
					"expression": "two dice please",
				},
				WantStatus: 400,
			},
			{
				ID:     "ability-check-failure",
				Name:   "Ability check failure margin",
				Method: "POST",
				Path:   "/v1/checks/ability",
				Body: map[string]any{
					"roll":     9,
					"modifier": 5,
					"dc":       15,
				},
				WantStatus: 200,
				WantJSON: map[string]any{
					"total":   14,
					"success": false,
					"margin":  -1,
				},
			},
			{
				ID:     "ability-check-success",
				Name:   "Ability check success margin",
				Method: "POST",
				Path:   "/v1/checks/ability",
				Body: map[string]any{
					"roll":     17,
					"modifier": -1,
					"dc":       15,
				},
				WantStatus: 200,
				WantJSON: map[string]any{
					"total":   16,
					"success": true,
					"margin":  1,
				},
			},
			{
				ID:     "encounter-adjusted-xp",
				Name:   "Encounter adjusted XP and difficulty",
				Method: "POST",
				Path:   "/v1/encounters/adjusted-xp",
				Body: map[string]any{
					"party": []map[string]any{
						{"level": 3},
						{"level": 3},
						{"level": 3},
						{"level": 3},
					},
					"monsters": []map[string]any{
						{"cr": "1", "count": 2},
						{"cr": "2", "count": 1},
					},
				},
				WantStatus: 200,
				WantJSON: map[string]any{
					"base_xp":       850,
					"monster_count": 3,
					"multiplier":    2,
					"adjusted_xp":   1700,
					"difficulty":    "deadly",
					"thresholds": map[string]any{
						"easy":   300,
						"medium": 600,
						"hard":   900,
						"deadly": 1600,
					},
				},
			},
			{
				ID:     "initiative-order",
				Name:   "Initiative order with deterministic tie-breakers",
				Method: "POST",
				Path:   "/v1/initiative/order",
				Body: map[string]any{
					"combatants": []map[string]any{
						{"name": "rogue", "dex": 3, "roll": 14},
						{"name": "ogre", "dex": -1, "roll": 16},
						{"name": "wizard", "dex": 3, "roll": 14},
						{"name": "cleric", "dex": 0, "roll": 17},
					},
				},
				WantStatus: 200,
				WantJSON: map[string]any{
					"order": []map[string]any{
						{"name": "rogue", "score": 17},
						{"name": "wizard", "score": 17},
						{"name": "cleric", "score": 17},
						{"name": "ogre", "score": 15},
					},
				},
			},
		},
	}
}

func charactersSuite() Suite {
	core := coreSuite()
	return Suite{
		ID:    "characters",
		Name:  "D&D REST Engine Character Maintenance",
		Tests: append(core.Tests, characterTests()...),
	}
}

func combatStateSuite() Suite {
	characters := charactersSuite()
	return Suite{
		ID:    "combat-state",
		Name:  "D&D REST Engine Stateful Combat Maintenance",
		Tests: append(characters.Tests, combatStateTests()...),
	}
}

func characterTests() []Test {
	return []Test{
		{
			ID:     "ability-modifier-negative",
			Name:   "Ability modifier floors negative halves",
			Method: "POST",
			Path:   "/v1/characters/ability-modifier",
			Body: map[string]any{
				"score": 9,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"score":    9,
				"modifier": -1,
			},
		},
		{
			ID:     "ability-modifier-high",
			Name:   "Ability modifier for high score",
			Method: "POST",
			Path:   "/v1/characters/ability-modifier",
			Body: map[string]any{
				"score": 20,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"score":    20,
				"modifier": 5,
			},
		},
		{
			ID:     "ability-modifier-invalid",
			Name:   "Ability modifier rejects invalid score",
			Method: "POST",
			Path:   "/v1/characters/ability-modifier",
			Body: map[string]any{
				"score": 0,
			},
			WantStatus: 400,
		},
		{
			ID:     "proficiency-level-boundary",
			Name:   "Proficiency bonus at level boundary",
			Method: "POST",
			Path:   "/v1/characters/proficiency",
			Body: map[string]any{
				"level": 9,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"level":             9,
				"proficiency_bonus": 4,
			},
		},
		{
			ID:     "derived-stats",
			Name:   "Derived character stats",
			Method: "POST",
			Path:   "/v1/characters/derived-stats",
			Body: map[string]any{
				"level": 5,
				"abilities": map[string]any{
					"str": 16,
					"dex": 14,
					"con": 13,
					"int": 8,
					"wis": 12,
					"cha": 10,
				},
				"armor": map[string]any{
					"base":    12,
					"shield":  true,
					"dex_cap": 2,
				},
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"level":             5,
				"proficiency_bonus": 3,
				"hp_max":            35,
				"armor_class":       16,
				"modifiers": map[string]any{
					"str": 3,
					"dex": 2,
					"con": 1,
					"int": -1,
					"wis": 1,
					"cha": 0,
				},
			},
		},
	}
}

func combatStateTests() []Test {
	return []Test{
		{
			ID:     "combat-create-session",
			Name:   "Create deterministic combat session",
			Method: "POST",
			Path:   "/v1/combat/sessions",
			Body: map[string]any{
				"id": "enc-1",
				"combatants": []map[string]any{
					{"name": "fighter", "dex": 1, "roll": 13},
					{"name": "rogue", "dex": 3, "roll": 14},
					{"name": "mage", "dex": 2, "roll": 14},
				},
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"id":         "enc-1",
				"round":      1,
				"turn_index": 0,
				"active": map[string]any{
					"name":  "rogue",
					"score": 17,
				},
				"order": []map[string]any{
					{"name": "rogue", "score": 17},
					{"name": "mage", "score": 16},
					{"name": "fighter", "score": 14},
				},
			},
		},
		{
			ID:     "combat-add-condition",
			Name:   "Add condition to combatant",
			Method: "POST",
			Path:   "/v1/combat/sessions/enc-1/conditions",
			Body: map[string]any{
				"target":          "fighter",
				"condition":       "blessed",
				"duration_rounds": 2,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"target": "fighter",
				"conditions": []map[string]any{
					{"condition": "blessed", "remaining_rounds": 2},
				},
			},
		},
		{
			ID:         "combat-advance-to-mage",
			Name:       "Advance to next turn",
			Method:     "POST",
			Path:       "/v1/combat/sessions/enc-1/advance",
			WantStatus: 200,
			WantJSON: map[string]any{
				"round":      1,
				"turn_index": 1,
				"active": map[string]any{
					"name": "mage",
				},
				"conditions": map[string]any{
					"fighter": []map[string]any{
						{"condition": "blessed", "remaining_rounds": 2},
					},
				},
			},
		},
		{
			ID:         "combat-advance-to-fighter-decrements",
			Name:       "Condition decrements at target turn start",
			Method:     "POST",
			Path:       "/v1/combat/sessions/enc-1/advance",
			WantStatus: 200,
			WantJSON: map[string]any{
				"round":      1,
				"turn_index": 2,
				"active": map[string]any{
					"name": "fighter",
				},
				"conditions": map[string]any{
					"fighter": []map[string]any{
						{"condition": "blessed", "remaining_rounds": 1},
					},
				},
			},
		},
		{
			ID:         "combat-advance-wrap-round",
			Name:       "Round increments when initiative wraps",
			Method:     "POST",
			Path:       "/v1/combat/sessions/enc-1/advance",
			WantStatus: 200,
			WantJSON: map[string]any{
				"round":      2,
				"turn_index": 0,
				"active": map[string]any{
					"name": "rogue",
				},
			},
		},
		{
			ID:         "combat-advance-condition-expires",
			Name:       "Condition expires on second target turn",
			Method:     "POST",
			Path:       "/v1/combat/sessions/enc-1/advance",
			WantStatus: 200,
			WantJSON: map[string]any{
				"round":      2,
				"turn_index": 1,
				"active": map[string]any{
					"name": "mage",
				},
				"conditions": map[string]any{
					"fighter": []map[string]any{
						{"condition": "blessed", "remaining_rounds": 1},
					},
				},
			},
		},
		{
			ID:         "combat-advance-expired-removed",
			Name:       "Expired condition removed when target acts again",
			Method:     "POST",
			Path:       "/v1/combat/sessions/enc-1/advance",
			WantStatus: 200,
			WantJSON: map[string]any{
				"round":      2,
				"turn_index": 2,
				"active": map[string]any{
					"name": "fighter",
				},
				"conditions": map[string]any{
					"fighter": []any{},
				},
			},
		},
	}
}

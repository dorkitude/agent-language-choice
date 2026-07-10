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
	return []Suite{
		coreSuite(),
		charactersSuite(),
		combatStateSuite(),
		authUsersSuite(),
		sqliteStorageSuite(),
		compendiumSuite(),
		campaignStateSuite(),
		phbRulesSuite(),
		dmToolsSuite(),
	}
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

func authUsersSuite() Suite {
	combatState := combatStateSuite()
	return Suite{
		ID:    "auth-users",
		Name:  "D&D REST Engine Auth/User Maintenance",
		Tests: append(combatState.Tests, authUserTests()...),
	}
}

func sqliteStorageSuite() Suite {
	authUsers := authUsersSuite()
	return Suite{
		ID:    "sqlite-storage",
		Name:  "D&D REST Engine SQLite Storage Maintenance",
		Tests: append(authUsers.Tests, sqliteStorageTests()...),
	}
}

func compendiumSuite() Suite {
	sqliteStorage := sqliteStorageSuite()
	return Suite{
		ID:    "compendium",
		Name:  "D&D REST Engine Compendium Maintenance",
		Tests: append(sqliteStorage.Tests, compendiumTests()...),
	}
}

func campaignStateSuite() Suite {
	compendium := compendiumSuite()
	return Suite{
		ID:    "campaign-state",
		Name:  "D&D REST Engine Campaign State Maintenance",
		Tests: append(compendium.Tests, campaignStateTests()...),
	}
}

func phbRulesSuite() Suite {
	campaignState := campaignStateSuite()
	return Suite{
		ID:    "phb-rules",
		Name:  "D&D REST Engine PHB Rules Maintenance",
		Tests: append(campaignState.Tests, phbRulesTests()...),
	}
}

func dmToolsSuite() Suite {
	phbRules := phbRulesSuite()
	return Suite{
		ID:    "dm-tools",
		Name:  "D&D REST Engine DM Tools Maintenance",
		Tests: append(phbRules.Tests, dmToolsTests()...),
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

func authUserTests() []Test {
	return []Test{
		{
			ID:     "auth-register-user",
			Name:   "Register deterministic user",
			Method: "POST",
			Path:   "/v1/auth/register",
			Body: map[string]any{
				"username": "dm",
				"password": "swordfish",
				"role":     "dm",
			},
			WantStatus: 201,
			WantJSON: map[string]any{
				"username": "dm",
				"role":     "dm",
			},
		},
		{
			ID:     "auth-register-duplicate",
			Name:   "Duplicate username returns conflict",
			Method: "POST",
			Path:   "/v1/auth/register",
			Body: map[string]any{
				"username": "dm",
				"password": "swordfish",
				"role":     "dm",
			},
			WantStatus: 409,
		},
		{
			ID:     "auth-login-user",
			Name:   "Login returns deterministic session token",
			Method: "POST",
			Path:   "/v1/auth/login",
			Body: map[string]any{
				"username": "dm",
				"password": "swordfish",
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"username": "dm",
				"token":    "session-dm",
			},
		},
		{
			ID:     "auth-login-bad-password",
			Name:   "Bad login returns unauthorized",
			Method: "POST",
			Path:   "/v1/auth/login",
			Body: map[string]any{
				"username": "dm",
				"password": "wrong",
			},
			WantStatus: 401,
		},
	}
}

func sqliteStorageTests() []Test {
	return []Test{
		{
			ID:         "storage-status",
			Name:       "SQLite storage status",
			Method:     "GET",
			Path:       "/v1/storage/status",
			WantStatus: 200,
			WantJSON: map[string]any{
				"driver":         "sqlite",
				"schema_version": 1,
				"initialized":    true,
			},
		},
		{
			ID:         "storage-reset",
			Name:       "SQLite storage reset",
			Method:     "POST",
			Path:       "/v1/storage/reset",
			WantStatus: 200,
			WantJSON: map[string]any{
				"ok":             true,
				"schema_version": 1,
			},
		},
	}
}

func compendiumTests() []Test {
	return []Test{
		{
			ID:     "compendium-create-monster",
			Name:   "Create monster compendium entry",
			Method: "POST",
			Path:   "/v1/compendium/monsters",
			Body: map[string]any{
				"slug":          "goblin",
				"name":          "Goblin",
				"challenge":     "1/4",
				"armor_class":   15,
				"hit_points":    7,
				"tags":          []any{"humanoid", "goblinoid"},
				"source":        "SRD",
				"xp":            50,
				"initiative":    2,
				"passive_sense": 9,
			},
			WantStatus: 201,
			WantJSON: map[string]any{
				"slug":        "goblin",
				"name":        "Goblin",
				"challenge":   "1/4",
				"armor_class": 15,
				"hit_points":  7,
			},
		},
		{
			ID:         "compendium-get-monster",
			Name:       "Read monster compendium entry",
			Method:     "GET",
			Path:       "/v1/compendium/monsters/goblin",
			WantStatus: 200,
			WantJSON: map[string]any{
				"slug":        "goblin",
				"name":        "Goblin",
				"challenge":   "1/4",
				"armor_class": 15,
				"hit_points":  7,
				"tags":        []any{"humanoid", "goblinoid"},
			},
		},
		{
			ID:     "compendium-create-item",
			Name:   "Create item compendium entry",
			Method: "POST",
			Path:   "/v1/compendium/items",
			Body: map[string]any{
				"slug":     "healing-potion",
				"name":     "Potion of Healing",
				"type":     "potion",
				"rarity":   "common",
				"source":   "SRD",
				"effect":   "regain 2d4+2 hit points",
				"value_gp": 50,
			},
			WantStatus: 201,
			WantJSON: map[string]any{
				"slug":   "healing-potion",
				"name":   "Potion of Healing",
				"type":   "potion",
				"rarity": "common",
			},
		},
		{
			ID:         "compendium-get-item",
			Name:       "Read item compendium entry",
			Method:     "GET",
			Path:       "/v1/compendium/items/healing-potion",
			WantStatus: 200,
			WantJSON: map[string]any{
				"slug":     "healing-potion",
				"name":     "Potion of Healing",
				"type":     "potion",
				"rarity":   "common",
				"effect":   "regain 2d4+2 hit points",
				"value_gp": 50,
			},
		},
	}
}

func campaignStateTests() []Test {
	return []Test{
		{
			ID:     "campaign-create",
			Name:   "Create campaign",
			Method: "POST",
			Path:   "/v1/campaigns",
			Body: map[string]any{
				"id":   "camp-1",
				"name": "Lost Mine",
				"dm":   "dm",
			},
			WantStatus: 201,
			WantJSON: map[string]any{
				"id":   "camp-1",
				"name": "Lost Mine",
				"dm":   "dm",
			},
		},
		{
			ID:     "campaign-add-character",
			Name:   "Add campaign character",
			Method: "POST",
			Path:   "/v1/campaigns/camp-1/characters",
			Body: map[string]any{
				"id":    "char-1",
				"name":  "Nyx",
				"level": 3,
				"class": "rogue",
			},
			WantStatus: 201,
			WantJSON: map[string]any{
				"id":    "char-1",
				"name":  "Nyx",
				"level": 3,
				"class": "rogue",
			},
		},
		{
			ID:     "campaign-add-event",
			Name:   "Append campaign event",
			Method: "POST",
			Path:   "/v1/campaigns/camp-1/events",
			Body: map[string]any{
				"id":      "evt-1",
				"kind":    "note",
				"summary": "Nyx scouts the goblin trail.",
			},
			WantStatus: 201,
			WantJSON: map[string]any{
				"id":   "evt-1",
				"kind": "note",
			},
		},
		{
			ID:         "campaign-state-read",
			Name:       "Read campaign state",
			Method:     "GET",
			Path:       "/v1/campaigns/camp-1/state",
			WantStatus: 200,
			WantJSON: map[string]any{
				"id":   "camp-1",
				"name": "Lost Mine",
				"dm":   "dm",
				"characters": []map[string]any{
					{"id": "char-1", "name": "Nyx", "level": 3, "class": "rogue"},
				},
				"log_count": 1,
			},
		},
	}
}

func phbRulesTests() []Test {
	return []Test{
		{
			ID:     "phb-spell-slots-wizard-5",
			Name:   "PHB spell slots for wizard level 5",
			Method: "POST",
			Path:   "/v1/phb/spell-slots",
			Body: map[string]any{
				"class": "wizard",
				"level": 5,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"class": "wizard",
				"level": 5,
				"slots": map[string]any{
					"1": 4,
					"2": 3,
					"3": 2,
				},
			},
		},
		{
			ID:     "phb-long-rest",
			Name:   "PHB long rest restores hit points and hit dice",
			Method: "POST",
			Path:   "/v1/phb/rests/long",
			Body: map[string]any{
				"level":            5,
				"hp_current":       9,
				"hp_max":           35,
				"hit_dice_spent":   3,
				"exhaustion_level": 1,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"hp_current":       35,
				"hit_dice_spent":   1,
				"exhaustion_level": 0,
			},
		},
		{
			ID:     "phb-equipment-load",
			Name:   "PHB carrying capacity and encumbrance",
			Method: "POST",
			Path:   "/v1/phb/equipment-load",
			Body: map[string]any{
				"strength": 12,
				"weight":   181,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"capacity":   180,
				"weight":     181,
				"encumbered": true,
			},
		},
	}
}

func dmToolsTests() []Test {
	return []Test{
		{
			ID:     "dm-encounter-builder",
			Name:   "DM encounter helper",
			Method: "POST",
			Path:   "/v1/dm/encounter-builder",
			Body: map[string]any{
				"campaign_id": "camp-1",
				"party": []map[string]any{
					{"level": 3},
					{"level": 3},
					{"level": 3},
					{"level": 3},
				},
				"monster_slugs": []any{"goblin", "goblin", "goblin"},
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"campaign_id":    "camp-1",
				"base_xp":        150,
				"adjusted_xp":    300,
				"difficulty":     "easy",
				"monster_count":  3,
				"recommendation": "safe warm-up",
			},
		},
		{
			ID:     "dm-loot-parcel",
			Name:   "DM loot parcel helper",
			Method: "POST",
			Path:   "/v1/dm/loot-parcel",
			Body: map[string]any{
				"campaign_id": "camp-1",
				"tier":        1,
				"seed":        42,
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"campaign_id": "camp-1",
				"coins_gp":    75,
				"items": []map[string]any{
					{"slug": "healing-potion", "quantity": 2},
				},
			},
		},
		{
			ID:     "dm-session-recap",
			Name:   "DM session recap helper",
			Method: "POST",
			Path:   "/v1/dm/session-recap",
			Body: map[string]any{
				"campaign_id": "camp-1",
			},
			WantStatus: 200,
			WantJSON: map[string]any{
				"campaign_id": "camp-1",
				"summary":     "Nyx scouts the goblin trail.",
				"open_threads": []any{
					"Resolve goblin trail ambush",
				},
			},
		},
	}
}

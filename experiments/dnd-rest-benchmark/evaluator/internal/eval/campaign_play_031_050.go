package eval

func sceneStateSuite() Suite {
	base := campaignDocumentSuite()
	return Suite{ID: "031-scene-state", Name: "Campaign Play 031: Scene State", Tests: append(base.Tests,
		playTest("play-create-scene", "DM creates a campaign scene", "POST", "/v1/play/campaigns/play-1/scenes", map[string]any{"id": "cave-entrance", "name": "Cave Entrance"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "cave-entrance", "name": "Cave Entrance", "status": "open"}),
		playTest("play-enter-scene", "DM enters the scene", "POST", "/v1/play/campaigns/play-1/scenes/cave-entrance/enter", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"current_scene_id": "cave-entrance", "name": "Cave Entrance"}),
		playTest("play-read-current-scene", "Member reads the current scene", "GET", "/v1/play/campaigns/play-1/scenes/current", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"id": "cave-entrance", "name": "Cave Entrance", "status": "open"}),
		playTest("play-close-scene", "DM closes the scene", "POST", "/v1/play/campaigns/play-1/scenes/cave-entrance/close", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"id": "cave-entrance", "status": "closed"}),
		playTest("play-read-current-scene-closed", "Closed current scene is not exposed", "GET", "/v1/play/campaigns/play-1/scenes/current", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
	)}
}

func locationGraphSuite() Suite {
	base := sceneStateSuite()
	return Suite{ID: "032-location-graph", Name: "Campaign Play 032: Location Graph", Tests: append(base.Tests,
		playTest("play-create-location-town", "DM creates a location", "POST", "/v1/play/campaigns/play-1/locations", map[string]any{"id": "town", "name": "Phandalin"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "town", "name": "Phandalin"}),
		playTest("play-create-location-cave", "DM creates another location", "POST", "/v1/play/campaigns/play-1/locations", map[string]any{"id": "cave", "name": "Wave Echo Cave"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "cave", "name": "Wave Echo Cave"}),
		playTest("play-create-connection", "DM creates a valid travel edge", "POST", "/v1/play/campaigns/play-1/locations/town/connections", map[string]any{"to_id": "cave", "travel_turns": 1}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"from_id": "town", "to_id": "cave", "travel_turns": 1}),
		playTest("play-read-travel", "Member reads valid destinations", "GET", "/v1/play/campaigns/play-1/locations/town/travel", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"destinations": []any{map[string]any{"id": "cave", "name": "Wave Echo Cave", "travel_turns": 1}}}),
	)}
}

func travelTurnsSuite() Suite {
	base := locationGraphSuite()
	return Suite{ID: "033-travel-turns", Name: "Campaign Play 033: Travel Turns", Tests: append(base.Tests,
		playTest("play-travel-turn", "Active player travels along a valid edge", "POST", "/v1/play/campaigns/play-1/turn/travel", map[string]any{"destination_id": "cave"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"sequence": 6, "kind": "travel", "actor": "player-b", "destination_id": "cave", "travel_turns": 1, "next_actor": "dm"}),
	)}
}

func restTurnsSuite() Suite {
	base := travelTurnsSuite()
	return Suite{ID: "034-rest-turns", Name: "Campaign Play 034: Rest Turns", Tests: append(base.Tests,
		playTest("play-dm-advance-to-rest", "DM advances queue to next player", "POST", "/v1/play/campaigns/play-1/resolutions", map[string]any{"text": "The road narrows as you approach the cave."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"sequence": 7, "kind": "resolution", "actor": "dm", "next_actor": "player-a", "turn_number": 3}),
		playTest("play-rest-turn", "Active player takes a long rest", "POST", "/v1/play/campaigns/play-1/turn/rest", map[string]any{"type": "long"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"sequence": 8, "kind": "rest", "actor": "player-a", "type": "long", "hp_current": 20, "hp_max": 20, "next_actor": "dm"}),
	)}
}

func encounterCreationSuite() Suite {
	base := restTurnsSuite()
	return Suite{ID: "035-encounter-creation", Name: "Campaign Play 035: Encounter Creation", Tests: append(base.Tests,
		playTest("play-create-encounter", "DM creates a campaign encounter", "POST", "/v1/play/campaigns/play-1/encounters", map[string]any{"id": "enc-road", "name": "Road Ambush"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "enc-road", "name": "Road Ambush", "status": "active", "combatants": []any{}}),
	)}
}

func monsterRosterSuite() Suite {
	base := encounterCreationSuite()
	return Suite{ID: "036-monster-roster", Name: "Campaign Play 036: Monster Roster", Tests: append(base.Tests,
		playTest("play-add-monster", "DM adds a monster to the encounter", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/monsters", map[string]any{"monster_id": "goblin-1", "name": "Goblin", "hp_max": 7, "initiative": 15}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"monster_id": "goblin-1", "name": "Goblin", "hp_max": 7, "hp_current": 7, "initiative": 15}),
		playTest("play-remove-monster", "DM removes the monster", "DELETE", "/v1/play/campaigns/play-1/encounters/enc-road/monsters/goblin-1", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"removed": "goblin-1"}),
	)}
}

func partyCombatBindingSuite() Suite {
	base := monsterRosterSuite()
	return Suite{ID: "037-party-combat-binding", Name: "Campaign Play 037: Party/Combat Binding", Tests: append(base.Tests,
		playTest("play-bind-member", "DM binds a party member as combatant", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/combatants", map[string]any{"member": "player-a", "initiative": 14}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"member": "player-a", "character_id": "play-char-a", "name": "Aria", "initiative": 14}),
		playTest("play-unbind-member", "DM unbinds the party member", "DELETE", "/v1/play/campaigns/play-1/encounters/enc-road/combatants/player-a", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"removed": "player-a"}),
	)}
}

func combatTurnAuthoritySuite() Suite {
	base := partyCombatBindingSuite()
	return Suite{ID: "038-combat-turn-authority", Name: "Campaign Play 038: Combat Turn Authority", Tests: append(base.Tests,
		playTest("play-add-monster-for-turn", "DM adds a monster for turn order", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/monsters", map[string]any{"monster_id": "goblin-1", "name": "Goblin", "hp_max": 7, "initiative": 15}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"monster_id": "goblin-1", "name": "Goblin", "hp_max": 7, "hp_current": 7, "initiative": 15}),
		playTest("play-bind-member-for-turn", "DM binds a party member for turn order", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/combatants", map[string]any{"member": "player-a", "initiative": 14}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"member": "player-a", "character_id": "play-char-a", "name": "Aria", "initiative": 14}),
		playTest("play-read-combat-turn", "Member reads current combat turn", "GET", "/v1/play/campaigns/play-1/encounters/enc-road/turn", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"round": 1, "turn_index": 0, "active": map[string]any{"name": "Goblin", "kind": "monster", "initiative": 15}}),
		playTest("play-advance-combat-turn-forbidden", "Non-combatant cannot advance turn", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/turn/advance", nil, map[string]string{"Authorization": playerBAuth}, 409, nil),
		playTest("play-dm-advance-combat-turn", "DM advances combat turn", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/turn/advance", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"round": 1, "turn_index": 1, "active": map[string]any{"name": "Aria", "kind": "player", "initiative": 14}}),
	)}
}

func playerCombatActionsSuite() Suite {
	base := combatTurnAuthoritySuite()
	return Suite{ID: "039-player-combat-actions", Name: "Campaign Play 039: Player Combat Actions", Tests: append(base.Tests,
		playTest("play-player-combat-action", "Current combatant submits an attack", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/actions", map[string]any{"type": "attack", "target": "goblin-1", "text": "I strike with my rapier."}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"sequence": 9, "kind": "combat_action", "actor": "player-a", "type": "attack", "target": "goblin-1", "text": "I strike with my rapier."}),
	)}
}

func damageAndHealingSuite() Suite {
	base := playerCombatActionsSuite()
	return Suite{ID: "040-damage-and-healing", Name: "Campaign Play 040: Damage and Healing", Tests: append(base.Tests,
		playTest("play-damage-monster", "DM damages a monster", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/damage", map[string]any{"target": "goblin-1", "amount": 5}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"target": "goblin-1", "hp_before": 7, "hp_after": 2, "damage": 5}),
		playTest("play-heal-monster", "DM heals a monster", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/heal", map[string]any{"target": "goblin-1", "amount": 3}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"target": "goblin-1", "hp_before": 2, "hp_after": 5, "healing": 3}),
	)}
}

func deathSavesSuite() Suite {
	base := damageAndHealingSuite()
	return Suite{ID: "041-death-saves", Name: "Campaign Play 041: Death Saves", Tests: append(base.Tests,
		playTest("play-damage-character-to-zero", "DM damages a character to 0 HP", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/damage", map[string]any{"amount": 20}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"target": "play-char-a", "hp_before": 20, "hp_after": 0, "damage": 20}),
		playTest("play-character-status-unconscious", "Character status is unconscious at 0 HP", "GET", "/v1/play/campaigns/play-1/characters/play-char-a/status", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-a", "hp_current": 0, "hp_max": 20, "status": "unconscious"}),
		playTest("play-death-save-success-1", "Record first death save success", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/death-saves", map[string]any{"outcome": "success"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"character_id": "play-char-a", "successes": 1, "failures": 0, "status": "unconscious"}),
		playTest("play-death-save-success-2", "Record second death save success", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/death-saves", map[string]any{"outcome": "success"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"character_id": "play-char-a", "successes": 2, "failures": 0, "status": "unconscious"}),
		playTest("play-death-save-success-3", "Three death save successes stabilize", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/death-saves", map[string]any{"outcome": "success"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"character_id": "play-char-a", "successes": 3, "failures": 0, "status": "stable"}),
		playTest("play-death-save-after-stable", "Stable character rejects further rolls", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/death-saves", map[string]any{"outcome": "failure"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
	)}
}

func conditionInteractionsSuite() Suite {
	base := deathSavesSuite()
	return Suite{ID: "042-condition-interactions", Name: "Campaign Play 042: Condition Interactions", Tests: append(base.Tests,
		playTest("play-apply-condition", "DM applies a condition", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/conditions", map[string]any{"target": "goblin-1", "condition": "blinded", "duration_rounds": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"target": "goblin-1", "conditions": []any{map[string]any{"condition": "blinded", "remaining_rounds": 2}}}),
		playTest("play-read-encounter-status", "Member reads encounter status", "GET", "/v1/play/campaigns/play-1/encounters/enc-road/status", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"round": 1, "turn_index": 1, "conditions": map[string]any{"goblin-1": []any{map[string]any{"condition": "blinded", "remaining_rounds": 2}}}}),
	)}
}

func delayAndReadySuite() Suite {
	base := conditionInteractionsSuite()
	return Suite{ID: "043-delay-and-ready", Name: "Campaign Play 043: Delay and Ready", Tests: append(base.Tests,
		playTest("play-add-player-b-combatant", "DM binds player B to the encounter", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/combatants", map[string]any{"member": "player-b", "initiative": 13}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"member": "player-b", "character_id": "play-char-b", "name": "Bram", "initiative": 13}),
		playTest("play-delay-turn", "Current combatant delays to a later position", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/turn/delay", map[string]any{"new_index": 2}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"order": []any{map[string]any{"name": "Goblin"}, map[string]any{"name": "Bram"}, map[string]any{"name": "Aria"}}}),
		playTest("play-ready-action", "Current combatant readies an action", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/turn/ready", map[string]any{"trigger": "when the goblin moves"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"actor": "player-a", "trigger": "when the goblin moves"}),
	)}
}

func encounterRewardsSuite() Suite {
	base := delayAndReadySuite()
	return Suite{ID: "044-encounter-rewards", Name: "Campaign Play 044: Encounter Rewards", Tests: append(base.Tests,
		playTest("play-award-rewards", "DM awards encounter XP and loot", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/rewards", map[string]any{"xp": 150, "loot": []any{map[string]any{"slug": "healing-potion", "quantity": 2}}}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"xp": 150, "loot": []any{map[string]any{"slug": "healing-potion", "quantity": 2}}}),
		playTest("play-close-encounter", "DM closes the encounter", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/close", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"id": "enc-road", "status": "closed", "xp_awarded": 150}),
		playTest("play-duplicate-rewards", "Rewards cannot be awarded twice", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/rewards", map[string]any{"xp": 150, "loot": []any{}}, map[string]string{"Authorization": dmAuth}, 409, nil),
	)}
}

func combatExplorationTransitionSuite() Suite {
	base := encounterRewardsSuite()
	return Suite{ID: "045-combat-exploration-transition", Name: "Campaign Play 045: Combat/Exploration Transition", Tests: append(base.Tests,
		playTest("play-end-combat", "DM ends combat and returns to exploration", "POST", "/v1/play/campaigns/play-1/encounters/enc-road/end", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"campaign_id": "play-1", "status": "active", "phase": "exploration", "current_actor": "dm"}),
	)}
}

func characterOwnershipSuite() Suite {
	base := combatExplorationTransitionSuite()
	return Suite{ID: "046-character-ownership", Name: "Campaign Play 046: Character Ownership", Tests: append(base.Tests,
		playTest("play-read-owner", "Member reads character owner", "GET", "/v1/play/campaigns/play-1/characters/play-char-a/owner", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-a", "owner": "player-a"}),
		playTest("play-claim-owned-forbidden", "Cannot claim an owned character", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/claim", nil, map[string]string{"Authorization": playerBAuth}, 409, nil),
		playTest("play-transfer-by-non-owner-forbidden", "Only the owner may transfer", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/transfer", map[string]any{"new_owner": "player-b"}, map[string]string{"Authorization": playerBAuth}, 403, nil),
	)}
}

func characterCreationChoicesSuite() Suite {
	base := characterOwnershipSuite()
	return Suite{ID: "047-character-creation-choices", Name: "Campaign Play 047: Character Creation Choices", Tests: append(base.Tests,
		playTest("play-build-character", "Owner builds character with valid choices", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/build", map[string]any{"race": "elf", "class": "rogue", "background": "criminal", "abilities": map[string]any{"str": 8, "dex": 16, "con": 12, "int": 13, "wis": 10, "cha": 14}}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-a", "race": "elf", "class": "rogue", "background": "criminal", "level": 1, "hp_max": 9, "proficiency_bonus": 2}),
		playTest("play-build-invalid-race", "Invalid race is rejected", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/build", map[string]any{"race": "dragon", "class": "rogue", "background": "criminal", "abilities": map[string]any{"str": 8, "dex": 16, "con": 12, "int": 13, "wis": 10, "cha": 14}}, map[string]string{"Authorization": playerAAuth}, 400, nil),
	)}
}

func levelProgressionSuite() Suite {
	base := characterCreationChoicesSuite()
	return Suite{ID: "048-level-progression", Name: "Campaign Play 048: Level Progression", Tests: append(base.Tests,
		playTest("play-level-up", "Owner advances character by one level", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/level-up", map[string]any{"level": 2}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-a", "level": 2, "hp_max": 15, "hit_dice": "1d8", "proficiency_bonus": 2}),
		playTest("play-level-up-non-owner", "Non-owner cannot level up", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/level-up", map[string]any{"level": 3}, map[string]string{"Authorization": playerBAuth}, 403, nil),
	)}
}

func skillsAndProficienciesSuite() Suite {
	base := levelProgressionSuite()
	return Suite{ID: "049-skills-and-proficiencies", Name: "Campaign Play 049: Skills and Proficiencies", Tests: append(base.Tests,
		playTest("play-skill-check", "Owner resolves a proficient skill check", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/skill-check", map[string]any{"skill": "stealth", "ability": "dex", "proficient": true, "roll": 15}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-a", "skill": "stealth", "ability": "dex", "modifier": 5, "total": 20}),
	)}
}

func spellbookStateSuite() Suite {
	base := skillsAndProficienciesSuite()
	return Suite{ID: "050-spellbook-state", Name: "Campaign Play 050: Spellbook State", Tests: append(base.Tests,
		playTest("play-rogue-spell-rejected", "Rogue cannot learn a spell", "POST", "/v1/play/campaigns/play-1/characters/play-char-a/spells", map[string]any{"spell_id": "fire-bolt", "name": "Fire Bolt", "level": 0}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-create-wizard-campaign", "DM creates a campaign for a wizard", "POST", "/v1/play/campaigns", map[string]any{"id": "play-2", "name": "Wizard Tower", "max_players": 3}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-2", "name": "Wizard Tower", "owner": "dm", "status": "lobby", "max_players": 3}),
		playTest("play-wizard-joins", "Wizard player joins the new campaign", "POST", "/v1/play/campaigns/play-2/members", map[string]any{"character_id": "play-char-w", "name": "Elara", "class": "wizard"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-char-w", "name": "Elara", "class": "wizard"}),
		playTest("play-wizard-learns-spell", "Wizard learns a valid spell", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/spells", map[string]any{"spell_id": "fire-bolt", "name": "Fire Bolt", "level": 0}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"spell_id": "fire-bolt", "name": "Fire Bolt", "level": 0}),
		playTest("play-duplicate-spell", "Duplicate spell is rejected", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/spells", map[string]any{"spell_id": "fire-bolt", "name": "Fire Bolt", "level": 0}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-list-spellbook", "Member lists the spellbook", "GET", "/v1/play/campaigns/play-2/characters/play-char-w/spells", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"spells": []any{map[string]any{"spell_id": "fire-bolt", "name": "Fire Bolt", "level": 0}}}),
	)}
}

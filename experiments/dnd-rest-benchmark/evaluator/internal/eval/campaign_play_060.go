package eval

func playTestExactJSON(id, name, method, path string, body map[string]any, headers map[string]string, wantStatus int, wantJSON any) Test {
	test := playTest(id, name, method, path, body, headers, wantStatus, wantJSON)
	test.ExactJSON = true
	return test
}

func factionReputationSuite() Suite {
	base := npcAgendasSuite()
	return Suite{ID: "060-faction-reputation", Name: "Campaign Play 060: Faction Reputation", Tests: append(base.Tests,
		playTest("play-faction-create-unauthenticated", "Reject unauthenticated faction creation", "POST", "/v1/play/campaigns/play-2/factions", map[string]any{"faction_id": "faction-harpers", "name": "Harpers"}, nil, 401, nil),
		playTest("play-faction-create-player-forbidden", "Only the DM can create factions", "POST", "/v1/play/campaigns/play-2/factions", map[string]any{"faction_id": "faction-harpers", "name": "Harpers"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-faction-create-invalid", "Faction creation requires nonempty strings", "POST", "/v1/play/campaigns/play-2/factions", map[string]any{"faction_id": "faction-empty", "name": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-faction-create", "DM creates a campaign faction", "POST", "/v1/play/campaigns/play-2/factions", map[string]any{"faction_id": "faction-harpers", "name": "Harpers"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"faction_id": "faction-harpers", "name": "Harpers"}),
		playTest("play-faction-create-duplicate", "Duplicate faction IDs conflict", "POST", "/v1/play/campaigns/play-2/factions", map[string]any{"faction_id": "faction-harpers", "name": "Harpers"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-reputation-player-forbidden", "Players cannot change faction reputation", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 15, "reason": "rescued-prisoners"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-reputation-unknown-faction", "Unknown faction reputation changes return 404", "POST", "/v1/play/campaigns/play-2/factions/faction-missing/reputation", map[string]any{"character_id": "play-char-w", "delta": 15, "reason": "rescued-prisoners"}, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTest("play-reputation-invalid-character", "Reputation changes require a campaign character", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-z", "delta": 15, "reason": "rescued-prisoners"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-reputation-zero-delta", "Reputation delta must be nonzero", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 0, "reason": "rescued-prisoners"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-reputation-delta-too-large", "Reputation delta is bounded per change", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 26, "reason": "rescued-prisoners"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-reputation-invalid-reason", "Reputation changes require a nonempty reason", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 15, "reason": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-reputation-change-wizard", "DM records reputation for the wizard", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 15, "reason": "rescued-prisoners"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 15, "delta": 15, "reason": "rescued-prisoners"}),
		playTestExactJSON("play-reputation-change-cleric", "DM records reputation for the cleric", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-b", "delta": -10, "reason": "angered-cell"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-b", "reputation": -10, "delta": -10, "reason": "angered-cell"}),
		playTestExactJSON("play-reputation-clamp", "Faction reputation totals clamp at 100", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 25, "reason": "secured-alliance"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 40, "delta": 25, "reason": "secured-alliance"}),
		playTestExactJSON("play-reputation-clamp-second", "Repeated positive changes continue toward the cap", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 25, "reason": "returned-relic"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 65, "delta": 25, "reason": "returned-relic"}),
		playTestExactJSON("play-reputation-clamp-third", "Reputation is capped at 100", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 25, "reason": "exposed-traitor"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 90, "delta": 25, "reason": "exposed-traitor"}),
		playTestExactJSON("play-reputation-clamp-fourth", "Reputation does not exceed 100", "POST", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", map[string]any{"character_id": "play-char-w", "delta": 25, "reason": "saved-safehouse"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 100, "delta": 25, "reason": "saved-safehouse"}),
		playTest("play-reputation-read-unknown-faction", "Unknown faction reputation history returns 404", "GET", "/v1/play/campaigns/play-2/factions/faction-missing/reputation", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTestExactJSON("play-reputation-read-dm", "DM sees complete reputation history in insertion order", "GET", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"faction_id": "faction-harpers", "entries": []any{
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 15, "delta": 15, "reason": "rescued-prisoners"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-b", "reputation": -10, "delta": -10, "reason": "angered-cell"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 40, "delta": 25, "reason": "secured-alliance"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 65, "delta": 25, "reason": "returned-relic"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 90, "delta": 25, "reason": "exposed-traitor"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 100, "delta": 25, "reason": "saved-safehouse"},
		}}),
		playTestExactJSON("play-reputation-read-player-a", "Player A sees only their character reputation history", "GET", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"faction_id": "faction-harpers", "entries": []any{
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 15, "delta": 15, "reason": "rescued-prisoners"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 40, "delta": 25, "reason": "secured-alliance"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 65, "delta": 25, "reason": "returned-relic"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 90, "delta": 25, "reason": "exposed-traitor"},
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-w", "reputation": 100, "delta": 25, "reason": "saved-safehouse"},
		}}),
		playTestExactJSON("play-reputation-read-player-b", "Player B sees only their character reputation history", "GET", "/v1/play/campaigns/play-2/factions/faction-harpers/reputation", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"faction_id": "faction-harpers", "entries": []any{
			map[string]any{"faction_id": "faction-harpers", "character_id": "play-char-b", "reputation": -10, "delta": -10, "reason": "angered-cell"},
		}}),
	)}
}

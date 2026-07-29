package eval

func rngLedgerSuite() Suite {
	base := deterministicReplaySuite()
	firstRoll := map[string]any{"roll_id": "initiative", "sides": 20, "result": 3, "sequence": 1}
	secondRoll := map[string]any{"roll_id": "secret-door", "sides": 6, "result": 1, "sequence": 2}
	thirdRoll := map[string]any{"roll_id": "morale", "sides": 100, "result": 46, "sequence": 3}
	finalLedger := map[string]any{
		"seed":  "ember-seed",
		"rolls": []any{firstRoll, secondRoll, thirdRoll},
	}
	return Suite{ID: "092-rng-ledger", Name: "Campaign Play 092: Deterministic RNG Ledger", Tests: append(base.Tests,
		playTest("play-rng-create-campaign", "DM creates a fresh campaign for the RNG ledger", "POST", "/v1/play/campaigns", map[string]any{"id": "play-092", "name": "RNG Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-092", "name": "RNG Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-rng-join-player-a", "Player A joins the RNG campaign", "POST", "/v1/play/campaigns/play-092/members", map[string]any{"character_id": "play-092-char-a", "name": "Rune", "class": "wizard"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-092-char-a", "name": "Rune", "class": "wizard"}),
		playTest("play-rng-ledger-unauthenticated", "Unauthenticated ledger read is rejected", "GET", "/v1/play/campaigns/play-092/rng-ledger", nil, nil, 401, nil),
		playTest("play-rng-ledger-nonmember-forbidden", "Non-members cannot read the RNG ledger", "GET", "/v1/play/campaigns/play-092/rng-ledger", nil, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
		playTest("play-rng-seed-player-forbidden", "Campaign members cannot configure the RNG seed", "PUT", "/v1/play/campaigns/play-092/rng-seed", map[string]any{"seed": "ember-seed"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-rng-seed-missing", "RNG seed requires a nonempty seed", "PUT", "/v1/play/campaigns/play-092/rng-seed", map[string]any{}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-rng-roll-before-seed", "Rolls require a configured RNG seed", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "before-seed", "sides": 20}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-rng-seed-set", "DM configures the exact RNG seed once", "PUT", "/v1/play/campaigns/play-092/rng-seed", map[string]any{"seed": "ember-seed"}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"seed": "ember-seed", "rolls": []any{}}),
		playTest("play-rng-seed-replace-conflict", "Configured RNG seed cannot be replaced", "PUT", "/v1/play/campaigns/play-092/rng-seed", map[string]any{"seed": "other-seed"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-rng-roll-invalid-id", "Roll ID must be nonempty", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "", "sides": 20}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-rng-roll-invalid-sides-low", "Roll sides must be at least two", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "bad-low", "sides": 1}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-rng-roll-invalid-sides-high", "Roll sides must be at most one hundred", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "bad-high", "sides": 101}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTestExactJSON("play-rng-roll-first", "Player appends first deterministic RNG roll", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "initiative", "sides": 20}, map[string]string{"Authorization": playerAAuth}, 201, firstRoll),
		playTestExactJSON("play-rng-roll-second", "DM appends second deterministic RNG roll", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "secret-door", "sides": 6}, map[string]string{"Authorization": dmAuth}, 201, secondRoll),
		playTestExactJSON("play-rng-roll-third", "Player appends third deterministic RNG roll", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "morale", "sides": 100}, map[string]string{"Authorization": playerAAuth}, 201, thirdRoll),
		playTest("play-rng-roll-duplicate-conflict", "Duplicate roll IDs are rejected without appending", "POST", "/v1/play/campaigns/play-092/rng-rolls", map[string]any{"roll_id": "initiative", "sides": 20}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-rng-ledger-read-player", "Campaign member reads exact ordered RNG ledger", "GET", "/v1/play/campaigns/play-092/rng-ledger", nil, map[string]string{"Authorization": playerAAuth}, 200, finalLedger),
		playTestExactJSON("play-rng-ledger-read-dm", "DM reads the same stable RNG ledger after duplicate rejection", "GET", "/v1/play/campaigns/play-092/rng-ledger", nil, map[string]string{"Authorization": dmAuth}, 200, finalLedger),
	)}
}

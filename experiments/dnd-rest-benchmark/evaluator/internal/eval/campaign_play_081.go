package eval

func concurrentTurnSafetySuite() Suite {
	base := idempotencyKeysSuite()
	accepted := map[string]any{"submission_id": "submit-1", "action": "move", "accepted_turn": 1, "next_turn": 2}
	return Suite{ID: "081-concurrent-turn-safety", Name: "Campaign Play 081: Concurrent Turn Safety", Tests: append(base.Tests,
		playTest("play-safe-turn-create-campaign", "DM creates a fresh campaign for safe turn submissions", "POST", "/v1/play/campaigns", map[string]any{"id": "play-081", "name": "Safe Turn Campaign", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-081", "name": "Safe Turn Campaign", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-safe-turn-join-player-a", "Player A joins the safe turn campaign", "POST", "/v1/play/campaigns/play-081/members", map[string]any{"character_id": "play-081-char-a", "name": "Aria", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-081-char-a", "name": "Aria", "class": "rogue"}),
		playTest("play-safe-turn-unauthenticated", "Unauthenticated safe turn submit is rejected", "POST", "/v1/play/campaigns/play-081/safe-turns", map[string]any{"submission_id": "submit-unauth", "expected_turn": 1, "action": "move"}, nil, 401, nil),
		playTest("play-safe-turn-empty-submission-id", "Safe turn submission_id must be nonempty", "POST", "/v1/play/campaigns/play-081/safe-turns", map[string]any{"submission_id": "", "expected_turn": 1, "action": "move"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-safe-turn-empty-action", "Safe turn action must be nonempty", "POST", "/v1/play/campaigns/play-081/safe-turns", map[string]any{"submission_id": "submit-empty-action", "expected_turn": 1, "action": ""}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-safe-turn-nonpositive-expected", "Safe turn expected_turn must be positive", "POST", "/v1/play/campaigns/play-081/safe-turns", map[string]any{"submission_id": "submit-zero", "expected_turn": 0, "action": "move"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTestExactJSON("play-safe-turn-read-initial", "Safe turn state starts at current turn one", "GET", "/v1/play/campaigns/play-081/safe-turns", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"current_turn": 1, "accepted": []any{}}),
		playTestExactJSON("play-safe-turn-accept-current", "Current safe turn submission advances exactly once", "POST", "/v1/play/campaigns/play-081/safe-turns", map[string]any{"submission_id": "submit-1", "expected_turn": 1, "action": "move"}, map[string]string{"Authorization": playerAAuth}, 201, accepted),
		playTestExactJSON("play-safe-turn-stale-conflict", "Stale concurrent safe turn returns current turn without state change", "POST", "/v1/play/campaigns/play-081/safe-turns", map[string]any{"submission_id": "submit-2", "expected_turn": 1, "action": "dash"}, map[string]string{"Authorization": playerAAuth}, 409, map[string]any{"current_turn": 2}),
		playTestExactJSON("play-safe-turn-read-after-stale", "Stale safe turn did not advance or append history", "GET", "/v1/play/campaigns/play-081/safe-turns", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"current_turn": 2, "accepted": []any{accepted}}),
		playTest("play-safe-turn-duplicate-submission", "Duplicate safe turn submission ID conflicts", "POST", "/v1/play/campaigns/play-081/safe-turns", map[string]any{"submission_id": "submit-1", "expected_turn": 2, "action": "move"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-safe-turn-read-nonmember-forbidden", "Non-member cannot read safe turns", "GET", "/v1/play/campaigns/play-081/safe-turns", nil, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
	)}
}

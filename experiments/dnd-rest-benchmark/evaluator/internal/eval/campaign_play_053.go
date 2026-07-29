package eval

func concentrationSuite() Suite {
	base := spellCastingSuite()
	return Suite{ID: "053-concentration", Name: "Campaign Play 053: Concentration", Tests: append(base.Tests,
		playTest("play-concentration-non-owner", "Non-owner cannot start concentration", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/concentration", map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "duration_turns": 2}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTest("play-concentration-invalid-duration", "Concentration requires a positive duration", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/concentration", map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "duration_turns": 0}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-start-concentration", "Owner starts concentration on a prepared spell", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/concentration", map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "duration_turns": 2}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "concentration": map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "remaining_turns": 2}}),
		playTest("play-read-concentration", "Campaign member reads active concentration", "GET", "/v1/play/campaigns/play-2/characters/play-char-w/concentration", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"character_id": "play-char-w", "concentration": map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "remaining_turns": 2}}),
		playTest("play-replace-concentration", "Starting concentration replaces the previous state", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/concentration", map[string]any{"spell_id": "magic-missile", "target": "arcane-lock", "duration_turns": 1}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "concentration": map[string]any{"spell_id": "magic-missile", "target": "arcane-lock", "remaining_turns": 1}}),
		playTest("play-concentration-expires", "Advancing a turn expires concentration at zero", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/concentration/advance-turn", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"character_id": "play-char-w", "concentration": nil}),
		playTest("play-clear-empty-concentration", "Owner can clear concentration idempotently", "DELETE", "/v1/play/campaigns/play-2/characters/play-char-w/concentration", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "concentration": nil}),
	)}
}

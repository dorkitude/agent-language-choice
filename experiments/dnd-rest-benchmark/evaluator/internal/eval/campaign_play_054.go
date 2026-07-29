package eval

func concentrationDamageSuite() Suite {
	base := concentrationSuite()
	return Suite{ID: "054-concentration-damage", Name: "Campaign Play 054: Concentration Damage Checks", Tests: append(base.Tests,
		playTest("play-concentration-damage-non-owner", "Non-owner cannot resolve concentration damage", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/concentration/damage", map[string]any{"damage": 22, "roll": 11}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTest("play-concentration-damage-no-active", "Damage check requires active concentration", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/concentration/damage", map[string]any{"damage": 22, "roll": 11}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-concentration-damage-start", "Owner starts concentration before damage", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/concentration", map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "duration_turns": 3}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "concentration": map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "remaining_turns": 3}}),
		playTest("play-concentration-damage-invalid", "Damage check requires positive damage", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/concentration/damage", map[string]any{"damage": 0, "roll": 20}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-concentration-damage-retained", "Meeting the concentration DC retains concentration", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/concentration/damage", map[string]any{"damage": 22, "roll": 11}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "dc": 11, "roll": 11, "maintained": true, "concentration": map[string]any{"spell_id": "magic-missile", "target": "training-dummy", "remaining_turns": 3}}),
		playTest("play-concentration-damage-lost", "Failing the concentration DC clears concentration", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/concentration/damage", map[string]any{"damage": 25, "roll": 12}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "dc": 13, "roll": 12, "maintained": false, "concentration": nil}),
	)}
}

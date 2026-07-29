package eval

func sessionZeroSettingsSuite() Suite {
	base := recurringDowntimeSuite()
	settings := map[string]any{"rules": "2024", "tone": "heroic", "consent": []any{"no-spiders", "fade-to-black"}}
	return Suite{ID: "073-session-zero-settings", Name: "Campaign Play 073: Session-Zero Settings", Tests: append(base.Tests,
		playTest("play-session-zero-create-campaign", "DM creates a fresh lobby campaign for session-zero settings", "POST", "/v1/play/campaigns", map[string]any{"id": "play-073", "name": "Session Zero", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-073", "name": "Session Zero", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-session-zero-join-player-a", "Player A joins the fresh lobby campaign", "POST", "/v1/play/campaigns/play-073/members", map[string]any{"character_id": "play-073-a", "name": "Seren", "class": "fighter"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-073-a", "name": "Seren", "class": "fighter"}),
		playTest("play-session-zero-join-player-b", "Player B joins the fresh lobby campaign", "POST", "/v1/play/campaigns/play-073/members", map[string]any{"character_id": "play-073-b", "name": "Tovin", "class": "bard"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"username": "player-b", "character_id": "play-073-b", "name": "Tovin", "class": "bard"}),
		playTest("play-session-zero-missing", "Missing session-zero settings return 404", "GET", "/v1/play/campaigns/play-073/session-zero", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTest("play-session-zero-put-unauthenticated", "Unauthenticated session-zero mutation is rejected", "PUT", "/v1/play/campaigns/play-073/session-zero", settings, nil, 401, nil),
		playTest("play-session-zero-put-player-forbidden", "Players cannot mutate session-zero settings", "PUT", "/v1/play/campaigns/play-073/session-zero", settings, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-session-zero-put-empty-rules", "Rules must be a nonempty string", "PUT", "/v1/play/campaigns/play-073/session-zero", map[string]any{"rules": "", "tone": "heroic", "consent": []any{"no-spiders"}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-session-zero-put-empty-tone", "Tone must be a nonempty string", "PUT", "/v1/play/campaigns/play-073/session-zero", map[string]any{"rules": "2024", "tone": "", "consent": []any{"no-spiders"}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-session-zero-put-empty-consent", "Consent must be nonempty", "PUT", "/v1/play/campaigns/play-073/session-zero", map[string]any{"rules": "2024", "tone": "heroic", "consent": []any{}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-session-zero-put-blank-consent", "Consent entries must be nonempty strings", "PUT", "/v1/play/campaigns/play-073/session-zero", map[string]any{"rules": "2024", "tone": "heroic", "consent": []any{"no-spiders", ""}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-session-zero-put-duplicate-consent", "Consent entries must be unique", "PUT", "/v1/play/campaigns/play-073/session-zero", map[string]any{"rules": "2024", "tone": "heroic", "consent": []any{"no-spiders", "no-spiders"}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-session-zero-put-dm", "DM stores exact session-zero settings while lobby", "PUT", "/v1/play/campaigns/play-073/session-zero", settings, map[string]string{"Authorization": dmAuth}, 200, settings),
		playTestExactJSON("play-session-zero-get-player", "Campaign players read exact stored session-zero settings", "GET", "/v1/play/campaigns/play-073/session-zero", nil, map[string]string{"Authorization": playerBAuth}, 200, settings),
		playTestExactJSON("play-session-zero-get-dm", "Campaign DM reads exact stored session-zero settings", "GET", "/v1/play/campaigns/play-073/session-zero", nil, map[string]string{"Authorization": dmAuth}, 200, settings),
		playTest("play-session-zero-start-campaign", "DM starts the session-zero campaign through REST", "POST", "/v1/play/campaigns/play-073/start", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"id": "play-073", "status": "active", "current_actor": "player-a", "turn_number": 1}),
		playTest("play-session-zero-put-after-start", "Started campaigns reject session-zero updates", "PUT", "/v1/play/campaigns/play-073/session-zero", map[string]any{"rules": "2024", "tone": "gritty", "consent": []any{"fade-to-black"}}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTestExactJSON("play-session-zero-get-after-reject", "Rejected post-start update leaves stored settings unchanged", "GET", "/v1/play/campaigns/play-073/session-zero", nil, map[string]string{"Authorization": playerAAuth}, 200, settings),
	)}
}

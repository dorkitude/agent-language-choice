package eval

func spectatorViewSuite() Suite {
	base := agentOnboardingSuite()
	spectatorCreated := map[string]any{
		"spectator_id": "watcher-1",
		"token":        "spectator-watcher-1",
	}
	spectatorView := map[string]any{
		"campaign_id": "play-098",
		"name":        "Spectator Game",
		"status":      "lobby",
		"party_size":  1,
		"story":       "",
	}
	return Suite{ID: "098-spectator-view", Name: "Campaign Play 098: Spectator View", Tests: append(base.Tests,
		playTest("play-spectator-create-campaign", "DM creates a fresh campaign for spectator view", "POST", "/v1/play/campaigns", map[string]any{"id": "play-098", "name": "Spectator Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-098", "name": "Spectator Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-spectator-join-player-a", "Player A joins the spectator campaign", "POST", "/v1/play/campaigns/play-098/members", map[string]any{"character_id": "play-098-a", "name": "Nia", "class": "wizard"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-098-a", "name": "Nia", "class": "wizard"}),
		playTest("play-spectator-private-note-fixture", "DM creates private data that spectator projection must redact", "POST", "/v1/play/campaigns/play-098/notes", map[string]any{"note_id": "spectator-note-1", "text": "The hidden token is dm-private.", "visibility": "private"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"note_id": "spectator-note-1", "text": "The hidden token is dm-private.", "visibility": "private", "owner": "dm"}),
		playTest("play-spectator-chat-fixture", "Player creates chat that spectator projection must redact", "POST", "/v1/play/campaigns/play-098/messages", map[string]any{"text": "Do not expose this party chat."}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"kind": "chat", "actor": "player-a", "text": "Do not expose this party chat."}),
		playTest("play-spectator-create-unauthenticated", "Unauthenticated spectator token creation is rejected", "POST", "/v1/play/campaigns/play-098/spectators", map[string]any{"spectator_id": "watcher-1"}, nil, 401, nil),
		playTest("play-spectator-create-player-forbidden", "Players cannot create spectator tokens", "POST", "/v1/play/campaigns/play-098/spectators", map[string]any{"spectator_id": "watcher-1"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-spectator-create-empty-id", "Spectator IDs must be nonempty", "POST", "/v1/play/campaigns/play-098/spectators", map[string]any{"spectator_id": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-spectator-create-dm", "DM creates exact spectator token", "POST", "/v1/play/campaigns/play-098/spectators", map[string]any{"spectator_id": "watcher-1"}, map[string]string{"Authorization": dmAuth}, 201, spectatorCreated),
		playTest("play-spectator-create-duplicate", "Duplicate spectator IDs conflict", "POST", "/v1/play/campaigns/play-098/spectators", map[string]any{"spectator_id": "watcher-1"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-spectator-view-missing-token", "Spectator view requires a spectator token", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, nil, 401, nil),
		playTest("play-spectator-view-invalid-token", "Invalid spectator token is rejected", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, map[string]string{"Authorization": "Bearer spectator-missing"}, 401, nil),
		playTest("play-spectator-view-dm-session-forbidden", "DM session tokens are forbidden on spectator projection", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, map[string]string{"Authorization": dmAuth}, 403, nil),
		playTest("play-spectator-view-player-session-forbidden", "Player session tokens are forbidden on spectator projection", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTestExactJSON("play-spectator-view-exact-redacted", "Spectator sees exact redacted public projection", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, map[string]string{"Authorization": "Bearer spectator-watcher-1"}, 200, spectatorView),
		playTestExactJSON("play-spectator-view-repeat-stable", "Repeated spectator view is stable and read-only", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, map[string]string{"Authorization": "Bearer spectator-watcher-1"}, 200, spectatorView),
		playTest("play-spectator-token-no-mutation", "Spectator tokens cannot authenticate mutation endpoints", "POST", "/v1/play/campaigns/play-098/messages", map[string]any{"text": "spectator tries to chat"}, map[string]string{"Authorization": "Bearer spectator-watcher-1"}, 401, nil),
		playTestExactJSON("play-spectator-view-after-mutation-attempt", "Rejected spectator mutation does not change projection", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, map[string]string{"Authorization": "Bearer spectator-watcher-1"}, 200, spectatorView),
		playTest("play-spectator-other-create-campaign", "DM creates another spectator campaign", "POST", "/v1/play/campaigns", map[string]any{"id": "play-098-other", "name": "Other Spectator Game", "max_players": 1}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-098-other", "name": "Other Spectator Game", "owner": "dm", "status": "lobby", "max_players": 1}),
		playTestExactJSON("play-spectator-other-token", "DM creates a spectator token for the other campaign", "POST", "/v1/play/campaigns/play-098-other/spectators", map[string]any{"spectator_id": "other-watcher"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"spectator_id": "other-watcher", "token": "spectator-other-watcher"}),
		playTest("play-spectator-global-duplicate", "Spectator IDs are globally unique because tokens contain only the spectator ID", "POST", "/v1/play/campaigns/play-098-other/spectators", map[string]any{"spectator_id": "watcher-1"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-spectator-view-different-campaign-forbidden", "Valid spectator token for a different campaign is forbidden", "GET", "/v1/play/campaigns/play-098/spectator-view", nil, map[string]string{"Authorization": "Bearer spectator-other-watcher"}, 403, nil),
		playTest("play-spectator-view-unknown-campaign", "Unknown campaign with valid-shaped spectator ticket returns not found", "GET", "/v1/play/campaigns/play-098-missing/spectator-view", nil, map[string]string{"Authorization": "Bearer spectator-watcher-1"}, 404, nil),
	)}
}

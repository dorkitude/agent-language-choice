package eval

func rumorsSuite() Suite {
	base := worldEventsSuite()
	return Suite{ID: "067-rumors", Name: "Campaign Play 067: Rumors", Tests: append(base.Tests,
		playTest("play-rumor-player-forbidden", "Players cannot publish rumors", "POST", "/v1/play/campaigns/play-1/rumors", map[string]any{"rumor_id": "rumor-player", "text": "Players cannot publish this."}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-rumor-invalid-id", "Rumor publishing requires a nonempty rumor ID", "POST", "/v1/play/campaigns/play-1/rumors", map[string]any{"rumor_id": "", "text": "A dragon was seen near the cave."}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-rumor-invalid-text", "Rumor publishing requires nonempty text", "POST", "/v1/play/campaigns/play-1/rumors", map[string]any{"rumor_id": "rumor-empty", "text": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-rumor-publish", "DM publishes a public rumor record", "POST", "/v1/play/campaigns/play-1/rumors", map[string]any{"rumor_id": "rumor-cave", "text": "A dragon was seen near the cave."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"rumor_id": "rumor-cave", "text": "A dragon was seen near the cave.", "discovered_by": []any{}}),
		playTest("play-rumor-duplicate-id", "Duplicate rumor IDs conflict", "POST", "/v1/play/campaigns/play-1/rumors", map[string]any{"rumor_id": "rumor-cave", "text": "A second rumor with the same ID."}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-rumor-duplicate-normalized-text", "Duplicate normalized rumor text conflicts", "POST", "/v1/play/campaigns/play-1/rumors", map[string]any{"rumor_id": "rumor-cave-copy", "text": "  a dragon was seen near the cave.  "}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTestExactJSON("play-rumor-publish-second", "DM publishes a second rumor for creation order checks", "POST", "/v1/play/campaigns/play-1/rumors", map[string]any{"rumor_id": "rumor-bridge", "text": "The old bridge creaks at midnight."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"rumor_id": "rumor-bridge", "text": "The old bridge creaks at midnight.", "discovered_by": []any{}}),
		playTest("play-rumor-discover-dm-forbidden", "DM cannot discover player rumors", "POST", "/v1/play/campaigns/play-1/rumors/rumor-cave/discover", nil, map[string]string{"Authorization": dmAuth}, 403, nil),
		playTest("play-rumor-discover-unknown", "Unknown rumor discovery returns 404", "POST", "/v1/play/campaigns/play-1/rumors/rumor-missing/discover", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTestExactJSON("play-rumor-discover-player-a", "Player A discovers the rumor as their character", "POST", "/v1/play/campaigns/play-1/rumors/rumor-cave/discover", nil, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"rumor_id": "rumor-cave", "text": "A dragon was seen near the cave.", "discovered_by": []any{"play-char-a"}}),
		playTest("play-rumor-discover-repeat", "Repeated discovery by the same character conflicts", "POST", "/v1/play/campaigns/play-1/rumors/rumor-cave/discover", nil, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-rumor-discover-player-b", "Player B also discovers the rumor once", "POST", "/v1/play/campaigns/play-1/rumors/rumor-cave/discover", nil, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"rumor_id": "rumor-cave", "text": "A dragon was seen near the cave.", "discovered_by": []any{"play-char-a", "play-char-b"}}),
		playTestExactJSON("play-rumors-read-dm", "DM sees all discoverers in creation order", "GET", "/v1/play/campaigns/play-1/rumors", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"rumors": []any{
			map[string]any{"rumor_id": "rumor-cave", "text": "A dragon was seen near the cave.", "discovered_by": []any{"play-char-a", "play-char-b"}},
			map[string]any{"rumor_id": "rumor-bridge", "text": "The old bridge creaks at midnight.", "discovered_by": []any{}},
		}}),
		playTestExactJSON("play-rumors-read-player-a", "Player A sees only their own discovery identity", "GET", "/v1/play/campaigns/play-1/rumors", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"rumors": []any{
			map[string]any{"rumor_id": "rumor-cave", "text": "A dragon was seen near the cave.", "discovered_by": []any{"play-char-a"}},
			map[string]any{"rumor_id": "rumor-bridge", "text": "The old bridge creaks at midnight.", "discovered_by": []any{}},
		}}),
		playTestExactJSON("play-rumors-read-player-b", "Player B sees only their own discovery identity", "GET", "/v1/play/campaigns/play-1/rumors", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"rumors": []any{
			map[string]any{"rumor_id": "rumor-cave", "text": "A dragon was seen near the cave.", "discovered_by": []any{"play-char-b"}},
			map[string]any{"rumor_id": "rumor-bridge", "text": "The old bridge creaks at midnight.", "discovered_by": []any{}},
		}}),
	)}
}

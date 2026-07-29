package eval

func deterministicReplaySuite() Suite {
	base := backupRestoreSuite()
	finalReplay := map[string]any{
		"story":     "AB",
		"event_ids": []any{"replay-1", "replay-2"},
		"digest":    "replay-1,replay-2|AB",
	}
	return Suite{ID: "091-deterministic-replay", Name: "Campaign Play 091: Deterministic Replay", Tests: append(base.Tests,
		playTest("play-replay-create-campaign", "DM creates a fresh campaign for deterministic replay", "POST", "/v1/play/campaigns", map[string]any{"id": "play-091", "name": "Replay Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-091", "name": "Replay Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-replay-join-player-a", "Player A joins the replay campaign", "POST", "/v1/play/campaigns/play-091/members", map[string]any{"character_id": "play-091-char-a", "name": "Ari", "class": "wizard"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-091-char-a", "name": "Ari", "class": "wizard"}),
		playTestExactJSON("play-replay-append-first", "Campaign member appends the first deterministic replay event", "POST", "/v1/play/campaigns/play-091/replay-events", map[string]any{"event_id": "replay-1", "kind": "append", "text": "A"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"event_id": "replay-1", "kind": "append", "text": "A", "sequence": 1}),
		playTestExactJSON("play-replay-append-second", "Campaign member appends the second deterministic replay event", "POST", "/v1/play/campaigns/play-091/replay-events", map[string]any{"event_id": "replay-2", "kind": "append", "text": "B"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"event_id": "replay-2", "kind": "append", "text": "B", "sequence": 2}),
		playTestExactJSON("play-replay-read-member", "Campaign member reads exact deterministic replay state", "GET", "/v1/play/campaigns/play-091/replay", nil, map[string]string{"Authorization": playerAAuth}, 200, finalReplay),
		playTestExactJSON("play-replay-check-member", "Replay check returns the same exact deterministic state", "GET", "/v1/play/campaigns/play-091/replay/check", nil, map[string]string{"Authorization": playerAAuth}, 200, finalReplay),
		playTest("play-replay-duplicate-event-id", "Duplicate replay event ID is rejected without mutating state", "POST", "/v1/play/campaigns/play-091/replay-events", map[string]any{"event_id": "replay-1", "kind": "append", "text": "Z"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-replay-after-duplicate", "Replay state remains unchanged after duplicate rejection", "GET", "/v1/play/campaigns/play-091/replay/check", nil, map[string]string{"Authorization": dmAuth}, 200, finalReplay),
	)}
}

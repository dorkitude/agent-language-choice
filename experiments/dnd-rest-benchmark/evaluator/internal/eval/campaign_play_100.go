package eval

func capstoneCampaignReplaySuite() Suite {
	base := loadSafeEventFeedSuite()
	campaignID := "play-100"
	document := map[string]any{
		"story":    "Mira charts the obsidian arch after the cellar fight.",
		"dm_notes": "The arch key is hidden under the third stair.",
	}
	publicDocument := map[string]any{
		"story": "Mira charts the obsidian arch after the cellar fight.",
	}
	export1 := map[string]any{
		"version": 1,
		"story":   "Mira charts the obsidian arch after the cellar fight.",
		"status":  "active",
	}
	replay1 := map[string]any{"event_id": "cap-replay-1", "kind": "append", "text": "arch", "sequence": 1}
	replay2 := map[string]any{"event_id": "cap-replay-2", "kind": "append", "text": "-key", "sequence": 2}
	replayState := map[string]any{
		"story":     "arch-key",
		"event_ids": []any{"cap-replay-1", "cap-replay-2"},
		"digest":    "cap-replay-1,cap-replay-2|arch-key",
	}
	feed1 := map[string]any{"event_id": "cap-feed-1", "text": "alpha", "sequence": 1}
	feed2 := map[string]any{"event_id": "cap-feed-2", "text": "beta", "sequence": 2}
	feed3 := map[string]any{"event_id": "cap-feed-3", "text": "gamma", "sequence": 3}

	return Suite{ID: "100-capstone-campaign-replay", Name: "Campaign Play 100: Capstone Campaign Replay", Tests: append(base.Tests,
		playTest("play-capstone-create-campaign", "DM creates a fresh capstone campaign", "POST", "/v1/play/campaigns", map[string]any{"id": campaignID, "name": "Obsidian Arch", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": campaignID, "name": "Obsidian Arch", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-capstone-join-player-a", "Player A joins the capstone campaign", "POST", "/v1/play/campaigns/play-100/members", map[string]any{"character_id": "play-100-char-a", "name": "Mira", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-100-char-a", "name": "Mira", "class": "rogue"}),
		playTest("play-capstone-join-player-b", "Player B joins so the campaign can start", "POST", "/v1/play/campaigns/play-100/members", map[string]any{"character_id": "play-100-char-b", "name": "Oren", "class": "cleric"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"username": "player-b", "character_id": "play-100-char-b", "name": "Oren", "class": "cleric"}),
		playTest("play-capstone-start-unauthenticated", "Unauthenticated campaign start is rejected", "POST", "/v1/play/campaigns/play-100/start", nil, nil, 401, nil),
		playTest("play-capstone-start-player-forbidden", "Player cannot start the campaign", "POST", "/v1/play/campaigns/play-100/start", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-capstone-start-dm", "DM starts the capstone campaign", "POST", "/v1/play/campaigns/play-100/start", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"id": campaignID, "status": "active", "current_actor": "player-a", "turn_number": 1}),
		playTest("play-capstone-narrate-player-forbidden", "Player cannot perform a DM narration mutation", "POST", "/v1/play/campaigns/play-100/narrations", map[string]any{"text": "I narrate over the DM."}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-capstone-narrate-dm", "DM narrates the opening capstone turn", "POST", "/v1/play/campaigns/play-100/narrations", map[string]any{"text": "A black arch hums beneath the old cellar."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"sequence": 1, "kind": "narration", "actor": "dm", "text": "A black arch hums beneath the old cellar."}),
		playTest("play-capstone-action-dm-forbidden", "DM cannot perform the active player's action mutation", "POST", "/v1/play/campaigns/play-100/actions", map[string]any{"type": "search", "text": "I inspect the arch."}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-capstone-action-player", "Authenticated active player submits an action", "POST", "/v1/play/campaigns/play-100/actions", map[string]any{"type": "search", "text": "I inspect the arch."}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"sequence": 2, "kind": "action", "actor": "player-a", "type": "search", "text": "I inspect the arch.", "next_actor": "dm"}),
		playTest("play-capstone-resolution-player-forbidden", "Player cannot resolve the DM turn", "POST", "/v1/play/campaigns/play-100/resolutions", map[string]any{"text": "You find the key mark."}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-capstone-resolution-dm", "DM resolves the player action", "POST", "/v1/play/campaigns/play-100/resolutions", map[string]any{"text": "You find the key mark."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"sequence": 3, "kind": "resolution", "actor": "dm", "text": "You find the key mark.", "next_actor": "player-b", "turn_number": 2}),
		playTest("play-capstone-create-encounter", "DM creates a minimal campaign combat encounter", "POST", "/v1/play/campaigns/play-100/encounters", map[string]any{"id": "cap-enc-1", "name": "Cellar Skirmish"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "cap-enc-1", "name": "Cellar Skirmish", "status": "active", "combatants": []any{}}),
		playTest("play-capstone-add-monster", "DM adds a monster to the capstone combat", "POST", "/v1/play/campaigns/play-100/encounters/cap-enc-1/monsters", map[string]any{"monster_id": "cap-shadow-1", "name": "Shadow", "hp_max": 16, "initiative": 12}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"monster_id": "cap-shadow-1", "name": "Shadow", "hp_max": 16, "hp_current": 16, "initiative": 12}),
		playTestExactJSON("play-capstone-end-combat", "DM ends combat and returns to an exact exploration state", "POST", "/v1/play/campaigns/play-100/encounters/cap-enc-1/end", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"campaign_id": campaignID, "status": "active", "phase": "exploration", "current_actor": "dm"}),
		playTest("play-capstone-document-player-update-forbidden", "Player cannot update private DM document notes", "PUT", "/v1/play/campaigns/play-100/document", map[string]any{"story": "No", "dm_notes": "No"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTestExactJSON("play-capstone-document-dm-update", "DM writes public story and private notes", "PUT", "/v1/play/campaigns/play-100/document", document, map[string]string{"Authorization": dmAuth}, 200, document),
		playTestExactJSON("play-capstone-document-player-redacted", "Player reads exact public document without DM notes", "GET", "/v1/play/campaigns/play-100/document", nil, map[string]string{"Authorization": playerAAuth}, 200, publicDocument),
		playTestExactJSON("play-capstone-document-dm-read", "DM reads exact public document plus private notes", "GET", "/v1/play/campaigns/play-100/document", nil, map[string]string{"Authorization": dmAuth}, 200, document),
		playTest("play-capstone-export-player-forbidden", "Player cannot create a versioned export", "POST", "/v1/play/campaigns/play-100/exports", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTestExactJSON("play-capstone-export-create", "DM creates exact versioned export from terminal story", "POST", "/v1/play/campaigns/play-100/exports", nil, map[string]string{"Authorization": dmAuth}, 201, export1),
		playTestExactJSON("play-capstone-export-read", "DM reads exact immutable export version", "GET", "/v1/play/campaigns/play-100/exports/1", nil, map[string]string{"Authorization": dmAuth}, 200, export1),
		playTestExactJSON("play-capstone-replay-append-1", "Player appends first deterministic replay event", "POST", "/v1/play/campaigns/play-100/replay-events", map[string]any{"event_id": "cap-replay-1", "kind": "append", "text": "arch"}, map[string]string{"Authorization": playerAAuth}, 201, replay1),
		playTestExactJSON("play-capstone-replay-append-2", "DM appends second deterministic replay event", "POST", "/v1/play/campaigns/play-100/replay-events", map[string]any{"event_id": "cap-replay-2", "kind": "append", "text": "-key"}, map[string]string{"Authorization": dmAuth}, 201, replay2),
		playTestExactJSON("play-capstone-replay-read", "Member reads exact deterministic replay state", "GET", "/v1/play/campaigns/play-100/replay", nil, map[string]string{"Authorization": playerAAuth}, 200, replayState),
		playTestExactJSON("play-capstone-replay-check", "Replay check returns the exact same state", "GET", "/v1/play/campaigns/play-100/replay/check", nil, map[string]string{"Authorization": dmAuth}, 200, replayState),
		playTestExactJSON("play-capstone-feed-append-1", "Player appends first load-safe feed event", "POST", "/v1/play/campaigns/play-100/feed-events", map[string]any{"event_id": "cap-feed-1", "text": "alpha"}, map[string]string{"Authorization": playerAAuth}, 201, feed1),
		playTestExactJSON("play-capstone-feed-append-2", "DM appends second load-safe feed event", "POST", "/v1/play/campaigns/play-100/feed-events", map[string]any{"event_id": "cap-feed-2", "text": "beta"}, map[string]string{"Authorization": dmAuth}, 201, feed2),
		playTestExactJSON("play-capstone-feed-page-1", "First capstone feed page is exact", "GET", "/v1/play/campaigns/play-100/event-feed?cursor=0&limit=2", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"events": []any{feed1, feed2}, "next_cursor": 2}),
		playTestExactJSON("play-capstone-feed-append-3", "Append after feed read remains sequential", "POST", "/v1/play/campaigns/play-100/feed-events", map[string]any{"event_id": "cap-feed-3", "text": "gamma"}, map[string]string{"Authorization": playerAAuth}, 201, feed3),
		playTestExactJSON("play-capstone-feed-page-2", "Second capstone feed page retrieves the interleaved append", "GET", "/v1/play/campaigns/play-100/event-feed?cursor=2&limit=2", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"events": []any{feed3}, "next_cursor": 3}),
		playTestExactJSON("play-capstone-terminal-turn-state", "Terminal campaign state remains exactly exploration with DM current actor", "GET", "/v1/play/campaigns/play-100/turn", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"campaign_id": campaignID, "current_actor": "dm", "phase": "exploration", "turn_number": 2, "queue": []any{"player-a", "dm", "player-b", "dm"}, "overdue": false, "logical_deadline": 3}),
	)}
}

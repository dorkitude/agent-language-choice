package eval

func rateLimitsSuite() Suite {
	base := paginationSearchSuite()
	rateA1 := map[string]any{"event_id": "rate-1", "actor": "player-a"}
	rateA2 := map[string]any{"event_id": "rate-2", "actor": "player-a"}
	rateB1 := map[string]any{"event_id": "rate-3", "actor": "player-b"}
	return Suite{ID: "087-rate-limits", Name: "Campaign Play 087: Rate Limits", Tests: append(base.Tests,
		playTest("play-rate-create-campaign", "DM creates a fresh campaign for rate limits", "POST", "/v1/play/campaigns", map[string]any{"id": "play-087", "name": "Rate Limit Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-087", "name": "Rate Limit Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-rate-join-player-a", "Player A joins the rate-limit campaign", "POST", "/v1/play/campaigns/play-087/members", map[string]any{"character_id": "play-087-a", "name": "Mira", "class": "ranger"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-087-a", "name": "Mira", "class": "ranger"}),
		playTest("play-rate-join-player-b", "Player B joins the rate-limit campaign", "POST", "/v1/play/campaigns/play-087/members", map[string]any{"character_id": "play-087-b", "name": "Bram", "class": "cleric"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"username": "player-b", "character_id": "play-087-b", "name": "Bram", "class": "cleric"}),
		playTestExactJSON("play-rate-player-a-first", "Player A records first accepted rate event", "POST", "/v1/play/campaigns/play-087/rate-events", map[string]any{"event_id": "rate-1"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"event_id": "rate-1", "actor": "player-a", "remaining": 1}),
		playTestExactJSON("play-rate-player-a-second", "Player A records second accepted rate event", "POST", "/v1/play/campaigns/play-087/rate-events", map[string]any{"event_id": "rate-2"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"event_id": "rate-2", "actor": "player-a", "remaining": 0}),
		playTestExactJSON("play-rate-player-a-third-limited", "Player A third event is rate limited", "POST", "/v1/play/campaigns/play-087/rate-events", map[string]any{"event_id": "rate-limited"}, map[string]string{"Authorization": playerAAuth}, 429, map[string]any{"limit": 2, "remaining": 0}),
		playTestExactJSON("play-rate-events-after-limit", "Rejected third Player A event is not recorded", "GET", "/v1/play/campaigns/play-087/rate-events", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"events": []any{rateA1, rateA2}, "remaining": 0}),
		playTestExactJSON("play-rate-player-b-independent", "Player B has independent rate allowance", "POST", "/v1/play/campaigns/play-087/rate-events", map[string]any{"event_id": "rate-3"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"event_id": "rate-3", "actor": "player-b", "remaining": 1}),
		playTestExactJSON("play-rate-events-player-b-remaining", "Player B reads all accepted events and their own remaining allowance", "GET", "/v1/play/campaigns/play-087/rate-events", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"events": []any{rateA1, rateA2, rateB1}, "remaining": 1}),
		playTest("play-rate-duplicate-campaign-event-id", "Rate event IDs are unique within a campaign", "POST", "/v1/play/campaigns/play-087/rate-events", map[string]any{"event_id": "rate-3"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-rate-empty-event-id", "Rate events require nonempty IDs", "POST", "/v1/play/campaigns/play-087/rate-events", map[string]any{"event_id": ""}, map[string]string{"Authorization": playerBAuth}, 400, nil),
	)}
}

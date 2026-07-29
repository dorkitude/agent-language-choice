package eval

func serviceMetricsSuite() Suite {
	base := rateLimitsSuite()
	initialMetrics := map[string]any{"accepted_rate_events": 0, "rejected_rate_events": 0, "projection_events": 0, "uptime_ticks": 1}
	finalMetrics := map[string]any{"accepted_rate_events": 2, "rejected_rate_events": 1, "projection_events": 1, "uptime_ticks": 1}
	return Suite{ID: "088-service-metrics", Name: "Campaign Play 088: Service Metrics", Tests: append(base.Tests,
		playTest("play-metrics-create-campaign", "DM creates a fresh campaign for service metrics", "POST", "/v1/play/campaigns", map[string]any{"id": "play-088", "name": "Metrics Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-088", "name": "Metrics Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-metrics-join-player-a", "Player A joins the metrics campaign", "POST", "/v1/play/campaigns/play-088/members", map[string]any{"character_id": "play-088-a", "name": "Mira", "class": "ranger"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-088-a", "name": "Mira", "class": "ranger"}),
		playTestExactJSON("play-metrics-initial", "Fresh campaign metrics start at zero with one uptime tick", "GET", "/v1/play/campaigns/play-088/metrics", nil, map[string]string{"Authorization": dmAuth}, 200, initialMetrics),
		playTestExactJSON("play-metrics-append-projection", "Accepted projection append increments projection metrics once", "POST", "/v1/play/campaigns/play-088/projection-events", map[string]any{"event_id": "metrics-projection-1", "kind": "increment-danger"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"event_id": "metrics-projection-1", "kind": "increment-danger", "sequence": 1}),
		playTestExactJSON("play-metrics-rate-first", "First accepted rate event increments accepted metrics", "POST", "/v1/play/campaigns/play-088/rate-events", map[string]any{"event_id": "metrics-rate-1"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"event_id": "metrics-rate-1", "actor": "player-a", "remaining": 1}),
		playTestExactJSON("play-metrics-rate-second", "Second accepted rate event increments accepted metrics", "POST", "/v1/play/campaigns/play-088/rate-events", map[string]any{"event_id": "metrics-rate-2"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"event_id": "metrics-rate-2", "actor": "player-a", "remaining": 0}),
		playTestExactJSON("play-metrics-rate-third-rejected", "Third rate event increments rejected metrics once", "POST", "/v1/play/campaigns/play-088/rate-events", map[string]any{"event_id": "metrics-rate-3"}, map[string]string{"Authorization": playerAAuth}, 429, map[string]any{"limit": 2, "remaining": 0}),
		playTestExactJSON("play-metrics-final", "Owner reads exact aggregate metrics without campaign content", "GET", "/v1/play/campaigns/play-088/metrics", nil, map[string]string{"Authorization": dmAuth}, 200, finalMetrics),
		playTest("play-metrics-player-forbidden", "Player cannot read owner-only metrics", "GET", "/v1/play/campaigns/play-088/metrics", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
	)}
}

package eval

func readinessHealthSuite() Suite {
	base := serviceMetricsSuite()
	return Suite{ID: "089-readiness-health", Name: "Campaign Play 089: Readiness/Health", Tests: append(base.Tests,
		playTestExactJSON("play-healthz-initial", "Public healthz reports liveness before maintenance", "GET", "/healthz", nil, nil, 200, map[string]any{"status": "ok"}),
		playTestExactJSON("play-readyz-initial", "Public readyz reports ready before maintenance", "GET", "/readyz", nil, nil, 200, map[string]any{"status": "ready", "schema_version": 2}),
		playTest("play-service-mode-create-campaign", "DM creates a fresh campaign for service-mode control", "POST", "/v1/play/campaigns", map[string]any{"id": "play-089", "name": "Readiness Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-089", "name": "Readiness Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-service-mode-join-player-a", "Player A joins the readiness campaign", "POST", "/v1/play/campaigns/play-089/members", map[string]any{"character_id": "play-089-a", "name": "Mira", "class": "ranger"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-089-a", "name": "Mira", "class": "ranger"}),
		playTest("play-service-mode-player-forbidden", "Player cannot change service mode", "POST", "/v1/play/campaigns/play-089/service-mode", map[string]any{"maintenance": true}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTestExactJSON("play-service-mode-enable", "DM enables global maintenance mode", "POST", "/v1/play/campaigns/play-089/service-mode", map[string]any{"maintenance": true}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"maintenance": true}),
		playTestExactJSON("play-healthz-during-maintenance", "Public healthz remains live during maintenance", "GET", "/healthz", nil, nil, 200, map[string]any{"status": "ok"}),
		playTestExactJSON("play-readyz-during-maintenance", "Public readyz reports maintenance with schema version", "GET", "/readyz", nil, nil, 503, map[string]any{"status": "maintenance", "schema_version": 2}),
		playTestExactJSON("play-service-mode-disable", "DM disables global maintenance mode", "POST", "/v1/play/campaigns/play-089/service-mode", map[string]any{"maintenance": false}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"maintenance": false}),
		playTestExactJSON("play-readyz-after-maintenance", "Public readyz reports ready after maintenance is disabled", "GET", "/readyz", nil, nil, 200, map[string]any{"status": "ready", "schema_version": 2}),
	)}
}

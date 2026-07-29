package eval

func agentOnboardingSuite() Suite {
	base := apiSchemaEndpointSuite()
	dmOnboarding := map[string]any{
		"role":       "dm",
		"next_steps": []any{"configure-safety", "invite-players", "start-campaign"},
		"can_mutate": true,
	}
	playerOnboarding := map[string]any{
		"role":       "player",
		"next_steps": []any{"review-party", "take-turn", "submit-action"},
		"can_mutate": true,
	}
	return Suite{ID: "097-agent-onboarding", Name: "Campaign Play 097: Agent Onboarding", Tests: append(base.Tests,
		playTest("play-onboarding-create-campaign", "DM creates a fresh campaign for onboarding", "POST", "/v1/play/campaigns", map[string]any{"id": "play-097", "name": "Onboarding Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-097", "name": "Onboarding Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-onboarding-join-player-a", "Player A joins the onboarding campaign", "POST", "/v1/play/campaigns/play-097/members", map[string]any{"character_id": "play-097-a", "name": "Iris", "class": "ranger"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-097-a", "name": "Iris", "class": "ranger"}),
		playTest("play-onboarding-unauthenticated", "Unauthenticated onboarding read is rejected", "GET", "/v1/play/campaigns/play-097/onboarding", nil, nil, 401, nil),
		playTest("play-onboarding-unknown", "Unknown campaign onboarding read returns 404", "GET", "/v1/play/campaigns/play-missing/onboarding", nil, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTest("play-onboarding-nonmember", "Authenticated nonmember onboarding read is forbidden", "GET", "/v1/play/campaigns/play-097/onboarding", nil, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTestExactJSON("play-onboarding-dm", "Campaign owner reads exact DM onboarding", "GET", "/v1/play/campaigns/play-097/onboarding", nil, map[string]string{"Authorization": dmAuth}, 200, dmOnboarding),
		playTestExactJSON("play-onboarding-dm-repeat", "Repeated DM onboarding read is stable", "GET", "/v1/play/campaigns/play-097/onboarding", nil, map[string]string{"Authorization": dmAuth}, 200, dmOnboarding),
		playTestExactJSON("play-onboarding-player", "Player member reads exact player onboarding", "GET", "/v1/play/campaigns/play-097/onboarding", nil, map[string]string{"Authorization": playerAAuth}, 200, playerOnboarding),
		playTestExactJSON("play-onboarding-player-repeat", "Repeated player onboarding read is stable", "GET", "/v1/play/campaigns/play-097/onboarding", nil, map[string]string{"Authorization": playerAAuth}, 200, playerOnboarding),
	)}
}

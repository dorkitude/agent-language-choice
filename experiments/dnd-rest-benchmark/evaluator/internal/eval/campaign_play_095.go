package eval

func fixtureSeedingSuite() Suite {
	base := safetyBoundariesSuite()
	fixture := canonicalFixtureStateJSON()
	return Suite{ID: "095-fixture-seeding", Name: "Campaign Play 095: Fixture Seeding", Tests: append(base.Tests,
		playTest("play-fixture-create-campaign", "DM creates a fresh campaign for fixture seeding", "POST", "/v1/play/campaigns", map[string]any{"id": "play-095", "name": "Fixture Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-095", "name": "Fixture Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-fixture-join-player-a", "Player A joins the fixture campaign", "POST", "/v1/play/campaigns/play-095/members", map[string]any{"character_id": "play-095-a", "name": "Nia", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-095-a", "name": "Nia", "class": "rogue"}),
		playTest("play-fixture-state-absent", "Fixture state is absent before seeding", "GET", "/v1/play/campaigns/play-095/fixture-state", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTest("play-fixture-seed-unauthenticated", "Unauthenticated fixture seed is rejected", "POST", "/v1/play/campaigns/play-095/fixture-seeds", map[string]any{"fixture_id": "canonical-v1"}, nil, 401, nil),
		playTest("play-fixture-read-unauthenticated", "Unauthenticated fixture state read is rejected", "GET", "/v1/play/campaigns/play-095/fixture-state", nil, nil, 401, nil),
		playTest("play-fixture-seed-nonmember-forbidden", "Non-members cannot seed fixture state", "POST", "/v1/play/campaigns/play-095/fixture-seeds", map[string]any{"fixture_id": "canonical-v1"}, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
		playTest("play-fixture-read-nonmember-forbidden", "Non-members cannot read fixture state", "GET", "/v1/play/campaigns/play-095/fixture-state", nil, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
		playTest("play-fixture-seed-player-forbidden", "Players cannot seed fixture state", "POST", "/v1/play/campaigns/play-095/fixture-seeds", map[string]any{"fixture_id": "canonical-v1"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-fixture-seed-missing-id", "Fixture seed requires fixture_id", "POST", "/v1/play/campaigns/play-095/fixture-seeds", map[string]any{"id": "canonical-v1"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-fixture-seed-invalid-id", "Fixture ID must be canonical-v1", "POST", "/v1/play/campaigns/play-095/fixture-seeds", map[string]any{"fixture_id": "other-v1"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-fixture-state-still-absent-after-invalid", "Invalid fixture seed does not create state", "GET", "/v1/play/campaigns/play-095/fixture-state", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTestExactJSON("play-fixture-seed-first", "First canonical fixture seed creates exact state", "POST", "/v1/play/campaigns/play-095/fixture-seeds", map[string]any{"fixture_id": "canonical-v1"}, map[string]string{"Authorization": dmAuth}, 201, fixture),
		playTestExactJSON("play-fixture-state-player", "Campaign player reads exact seeded fixture state", "GET", "/v1/play/campaigns/play-095/fixture-state", nil, map[string]string{"Authorization": playerAAuth}, 200, fixture),
		playTestExactJSON("play-fixture-seed-repeat", "Repeating canonical fixture seed is idempotent", "POST", "/v1/play/campaigns/play-095/fixture-seeds", map[string]any{"fixture_id": "canonical-v1"}, map[string]string{"Authorization": dmAuth}, 200, fixture),
		playTestExactJSON("play-fixture-state-dm-after-repeat", "Repeated seed leaves stable exact state without duplicates", "GET", "/v1/play/campaigns/play-095/fixture-state", nil, map[string]string{"Authorization": dmAuth}, 200, fixture),
	)}
}

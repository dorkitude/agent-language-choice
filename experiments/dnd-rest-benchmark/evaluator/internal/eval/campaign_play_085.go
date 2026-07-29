package eval

func schemaMigrationSuite() Suite {
	base := importValidationSuite()
	legacy := map[string]any{"schema_version": 1, "story": "Legacy story"}
	migrated := map[string]any{"schema_version": 2, "story": "Legacy story", "campaign_name": "Legacy Game"}
	return Suite{ID: "085-schema-migration", Name: "Campaign Play 085: Schema Migration", Tests: append(base.Tests,
		playTest("play-migration-create-campaign", "DM creates a fresh campaign for schema migration", "POST", "/v1/play/campaigns", map[string]any{"id": "play-085", "name": "Legacy Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-085", "name": "Legacy Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-migration-player-forbidden", "Player cannot migrate campaign state", "POST", "/v1/play/campaigns/play-085/migrations", legacy, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-migration-state-player-forbidden", "Player cannot read migrated campaign state", "GET", "/v1/play/campaigns/play-085/migration-state", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-migration-invalid-empty-story", "Empty story returns 400", "POST", "/v1/play/campaigns/play-085/migrations", map[string]any{"schema_version": 1, "story": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-migration-state-absent-after-invalid", "Invalid first migration leaves no migrated state", "GET", "/v1/play/campaigns/play-085/migration-state", nil, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTestExactJSON("play-migration-valid-first", "Valid version 1 migration returns deterministic version 2 state", "POST", "/v1/play/campaigns/play-085/migrations", legacy, map[string]string{"Authorization": dmAuth}, 201, migrated),
		playTestExactJSON("play-migration-state-after-first", "DM reads exact migrated state after valid migration", "GET", "/v1/play/campaigns/play-085/migration-state", nil, map[string]string{"Authorization": dmAuth}, 200, migrated),
		playTestExactJSON("play-migration-idempotent-rerun", "Repeating the same version 1 migration is idempotent", "POST", "/v1/play/campaigns/play-085/migrations", legacy, map[string]string{"Authorization": dmAuth}, 200, migrated),
		playTest("play-migration-incompatible-version", "Incompatible schema version returns 400", "POST", "/v1/play/campaigns/play-085/migrations", map[string]any{"schema_version": 3, "story": "Mutated story"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-migration-state-unchanged-after-incompatible", "Incompatible migration does not mutate migrated state", "GET", "/v1/play/campaigns/play-085/migration-state", nil, map[string]string{"Authorization": dmAuth}, 200, migrated),
	)}
}

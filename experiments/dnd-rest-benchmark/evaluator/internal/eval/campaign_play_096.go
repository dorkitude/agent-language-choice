package eval

func apiSchemaEndpointSuite() Suite {
	base := fixtureSeedingSuite()
	fixture := canonicalFixtureStateJSON()
	schema := apiSchemaExpectedJSON()
	return Suite{ID: "096-api-schema-endpoint", Name: "Campaign Play 096: API Schema Endpoint", Tests: append(base.Tests,
		playTest("play-schema-create-campaign", "DM creates a fresh campaign for schema state checks", "POST", "/v1/play/campaigns", map[string]any{"id": "play-096", "name": "Schema Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-096", "name": "Schema Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-schema-join-player-a", "Player A joins the schema campaign", "POST", "/v1/play/campaigns/play-096/members", map[string]any{"character_id": "play-096-a", "name": "Sera", "class": "fighter"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-096-a", "name": "Sera", "class": "fighter"}),
		playTestExactJSON("play-schema-fixture-seed-before", "Fixture state exists before schema reads", "POST", "/v1/play/campaigns/play-096/fixture-seeds", map[string]any{"fixture_id": "canonical-v1"}, map[string]string{"Authorization": dmAuth}, 201, fixture),
		playTestExactJSON("play-schema-fixture-read-before", "Fixture state before schema read is exact", "GET", "/v1/play/campaigns/play-096/fixture-state", nil, map[string]string{"Authorization": playerAAuth}, 200, fixture),
		playTestExactJSON("play-schema-public-no-auth", "Public schema requires no authorization", "GET", "/v1/schema", nil, nil, 200, schema),
		playTestExactJSON("play-schema-repeat-stable", "Repeated schema read returns the exact same response", "GET", "/v1/schema", nil, nil, 200, schema),
		playTestExactJSON("play-schema-fixture-read-after", "Schema reads do not mutate campaign fixture state", "GET", "/v1/play/campaigns/play-096/fixture-state", nil, map[string]string{"Authorization": playerAAuth}, 200, fixture),
	)}
}

type apiSchemaEndpoint struct {
	Method string `json:"method"`
	Path   string `json:"path"`
	Auth   string `json:"auth"`
}

type apiSchemaDocument struct {
	Version   string              `json:"version"`
	Endpoints []apiSchemaEndpoint `json:"endpoints"`
}

func apiSchemaResponse() apiSchemaDocument {
	return apiSchemaDocument{
		Version:   "2026-07-29",
		Endpoints: apiSchemaEndpoints(),
	}
}

func apiSchemaExpectedJSON() map[string]any {
	endpoints := make([]any, 0, len(apiSchemaEndpoints()))
	for _, endpoint := range apiSchemaEndpoints() {
		endpoints = append(endpoints, map[string]any{
			"method": endpoint.Method,
			"path":   endpoint.Path,
			"auth":   endpoint.Auth,
		})
	}
	return map[string]any{"version": "2026-07-29", "endpoints": endpoints}
}

func apiSchemaEndpoints() []apiSchemaEndpoint {
	return []apiSchemaEndpoint{
		{Method: "GET", Path: "/v1/play/campaigns/{id}/rng-ledger", Auth: "member"},
		{Method: "GET", Path: "/v1/schema", Auth: "public"},
		{Method: "POST", Path: "/v1/play/campaigns", Auth: "dm"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/fixture-seeds", Auth: "dm"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/members", Auth: "member"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/moderation/reports", Auth: "member"},
		{Method: "POST", Path: "/v1/play/campaigns/{id}/rng-rolls", Auth: "member"},
		{Method: "PUT", Path: "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution", Auth: "dm"},
		{Method: "PUT", Path: "/v1/play/campaigns/{id}/rng-seed", Auth: "dm"},
		{Method: "PUT", Path: "/v1/play/campaigns/{id}/safety-boundaries", Auth: "dm"},
	}
}

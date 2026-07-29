package eval

func paginationSearchSuite() Suite {
	base := schemaMigrationSuite()
	recordOne := map[string]any{"record_id": "record-1", "text": "Goblin cave"}
	recordTwo := map[string]any{"record_id": "record-2", "text": "Hidden Shrine"}
	recordThree := map[string]any{"record_id": "record-3", "text": "goblin tracks"}
	return Suite{ID: "086-pagination-search", Name: "Campaign Play 086: Pagination/Search", Tests: append(base.Tests,
		playTest("play-search-create-campaign", "DM creates a fresh campaign for search records", "POST", "/v1/play/campaigns", map[string]any{"id": "play-086", "name": "Search Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-086", "name": "Search Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-search-join-player-a", "Player A joins the search campaign", "POST", "/v1/play/campaigns/play-086/members", map[string]any{"character_id": "play-086-a", "name": "Mira", "class": "ranger"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-086-a", "name": "Mira", "class": "ranger"}),
		playTest("play-search-player-mutation-forbidden", "Player cannot create search records", "POST", "/v1/play/campaigns/play-086/search-records", recordOne, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTestExactJSON("play-search-create-record-1", "DM creates the first exact search record", "POST", "/v1/play/campaigns/play-086/search-records", recordOne, map[string]string{"Authorization": dmAuth}, 201, recordOne),
		playTestExactJSON("play-search-create-record-2", "DM creates the second exact search record", "POST", "/v1/play/campaigns/play-086/search-records", recordTwo, map[string]string{"Authorization": dmAuth}, 201, recordTwo),
		playTestExactJSON("play-search-create-record-3", "DM creates the third exact search record", "POST", "/v1/play/campaigns/play-086/search-records", recordThree, map[string]string{"Authorization": dmAuth}, 201, recordThree),
		playTest("play-search-duplicate-id-invalid", "Duplicate search record ID returns 400", "POST", "/v1/play/campaigns/play-086/search-records", recordOne, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-search-duplicate-text-invalid", "Duplicate search record text returns 400", "POST", "/v1/play/campaigns/play-086/search-records", map[string]any{"record_id": "record-duplicate-text", "text": "Hidden Shrine"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-search-empty-text-invalid", "Empty search text returns 400", "POST", "/v1/play/campaigns/play-086/search-records", map[string]any{"record_id": "record-empty", "text": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-search-page-1", "Default pagination returns stable first page", "GET", "/v1/play/campaigns/play-086/search-records", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"records": []any{recordOne, recordTwo}, "next_cursor": 2}),
		playTestExactJSON("play-search-page-2", "Cursor pagination returns stable second page", "GET", "/v1/play/campaigns/play-086/search-records?cursor=2", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"records": []any{recordThree}, "next_cursor": nil}),
		playTestExactJSON("play-search-case-insensitive", "Search filter is case-insensitive and preserves creation order", "GET", "/v1/play/campaigns/play-086/search-records?q=GOBLIN&limit=3", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"records": []any{recordOne, recordThree}, "next_cursor": nil}),
		playTestExactJSON("play-search-no-match", "No-match search returns an empty page", "GET", "/v1/play/campaigns/play-086/search-records?q=dragon", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"records": []any{}, "next_cursor": nil}),
		playTest("play-search-invalid-limit-low", "Limit below range returns 400", "GET", "/v1/play/campaigns/play-086/search-records?limit=0", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-search-invalid-limit-high", "Limit above range returns 400", "GET", "/v1/play/campaigns/play-086/search-records?limit=4", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-search-invalid-cursor-negative", "Negative cursor returns 400", "GET", "/v1/play/campaigns/play-086/search-records?cursor=-1", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
	)}
}

package eval

func loadSafeEventFeedSuite() Suite {
	base := spectatorViewSuite()
	feed1 := map[string]any{"event_id": "feed-1", "text": "A", "sequence": 1}
	feed2 := map[string]any{"event_id": "feed-2", "text": "B", "sequence": 2}
	feed3 := map[string]any{"event_id": "feed-3", "text": "C", "sequence": 3}
	feed4 := map[string]any{"event_id": "feed-4", "text": "D", "sequence": 4}
	return Suite{ID: "099-load-safe-event-feed", Name: "Campaign Play 099: Load-Safe Event Feed", Tests: append(base.Tests,
		playTest("play-feed-create-campaign", "DM creates a fresh campaign for load-safe feed", "POST", "/v1/play/campaigns", map[string]any{"id": "play-099", "name": "Feed Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-099", "name": "Feed Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-feed-join-player-a", "Player A joins the feed campaign", "POST", "/v1/play/campaigns/play-099/members", map[string]any{"character_id": "play-099-a", "name": "Nia", "class": "wizard"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-099-a", "name": "Nia", "class": "wizard"}),
		playTest("play-feed-post-unauthenticated", "Unauthenticated feed append is rejected", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-unauth", "text": "blocked"}, nil, 401, nil),
		playTest("play-feed-read-unauthenticated", "Unauthenticated feed read is rejected", "GET", "/v1/play/campaigns/play-099/event-feed", nil, nil, 401, nil),
		playTest("play-feed-post-nonmember", "Authenticated nonmembers cannot append feed events", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-stranger", "text": "blocked"}, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
		playTest("play-feed-read-nonmember", "Authenticated nonmembers cannot read feed events", "GET", "/v1/play/campaigns/play-099/event-feed", nil, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
		playTest("play-feed-empty-event-id", "Feed event IDs must be nonempty", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "", "text": "A"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-feed-empty-text", "Feed event text must be nonempty", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-empty-text", "text": ""}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-feed-invalid-cursor-negative", "Negative feed cursor returns 400", "GET", "/v1/play/campaigns/play-099/event-feed?cursor=-1", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-feed-invalid-cursor-noninteger", "Non-integer feed cursor returns 400", "GET", "/v1/play/campaigns/play-099/event-feed?cursor=one", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-feed-invalid-limit-low", "Feed limit below range returns 400", "GET", "/v1/play/campaigns/play-099/event-feed?limit=0", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-feed-invalid-limit-high", "Feed limit above range returns 400", "GET", "/v1/play/campaigns/play-099/event-feed?limit=4", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-feed-invalid-limit-noninteger", "Non-integer feed limit returns 400", "GET", "/v1/play/campaigns/play-099/event-feed?limit=two", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTestExactJSON("play-feed-initial-empty-defaults", "Default feed read starts empty and read-only", "GET", "/v1/play/campaigns/play-099/event-feed", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"events": []any{}, "next_cursor": 0}),
		playTestExactJSON("play-feed-append-1", "Player appends first feed event", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-1", "text": "A"}, map[string]string{"Authorization": playerAAuth}, 201, feed1),
		playTest("play-feed-duplicate-id", "Duplicate feed event IDs conflict", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-1", "text": "A again"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-feed-append-2", "DM as campaign member appends second feed event", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-2", "text": "B"}, map[string]string{"Authorization": dmAuth}, 201, feed2),
		playTestExactJSON("play-feed-append-3", "Player appends third feed event", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-3", "text": "C"}, map[string]string{"Authorization": playerAAuth}, 201, feed3),
		playTestExactJSON("play-feed-page-before-interleaved-append", "First page returns the first two events", "GET", "/v1/play/campaigns/play-099/event-feed?cursor=0&limit=2", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"events": []any{feed1, feed2}, "next_cursor": 2}),
		playTestExactJSON("play-feed-append-4-after-read", "Append after first read receives the fourth sequence", "POST", "/v1/play/campaigns/play-099/feed-events", map[string]any{"event_id": "feed-4", "text": "D"}, map[string]string{"Authorization": dmAuth}, 201, feed4),
		playTestExactJSON("play-feed-page-after-interleaved-append", "Cursor two returns pre-existing third event then interleaved append", "GET", "/v1/play/campaigns/play-099/event-feed?cursor=2&limit=2", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"events": []any{feed3, feed4}, "next_cursor": 4}),
		playTestExactJSON("play-feed-empty-at-current-length", "Cursor at current length returns empty with same next cursor", "GET", "/v1/play/campaigns/play-099/event-feed?cursor=4", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"events": []any{}, "next_cursor": 4}),
		playTestExactJSON("play-feed-repeat-read-is-stable", "Repeating the second page proves reads do not mutate", "GET", "/v1/play/campaigns/play-099/event-feed?cursor=2&limit=2", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"events": []any{feed3, feed4}, "next_cursor": 4}),
		playTestExactJSON("play-feed-cursor-past-end", "Cursor beyond current length returns empty with requested cursor", "GET", "/v1/play/campaigns/play-099/event-feed?cursor=9&limit=3", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"events": []any{}, "next_cursor": 9}),
	)}
}

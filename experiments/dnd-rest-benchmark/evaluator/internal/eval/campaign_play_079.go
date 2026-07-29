package eval

func eventProjectionsSuite() Suite {
	base := actorAuditTrailSuite()
	firstEvent := map[string]any{"sequence": 1, "event_id": "event-2", "kind": "increment-danger"}
	secondEvent := map[string]any{"sequence": 2, "event_id": "event-1", "kind": "set-story", "value": "The road is clear."}
	thirdEvent := map[string]any{"sequence": 3, "event_id": "event-3", "kind": "increment-danger"}
	finalProjection := map[string]any{"story": "The road is clear.", "danger": 2, "applied_event_ids": []any{"event-2", "event-1", "event-3"}}
	return Suite{ID: "079-event-projections", Name: "Campaign Play 079: Event Projections", Tests: append(base.Tests,
		playTest("play-projection-create-campaign", "DM creates a fresh campaign for projection events", "POST", "/v1/play/campaigns", map[string]any{"id": "play-079", "name": "Projection Campaign", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-079", "name": "Projection Campaign", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-projection-join-player-a", "Player A joins the projection campaign", "POST", "/v1/play/campaigns/play-079/members", map[string]any{"character_id": "play-079-char-a", "name": "Aria", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-079-char-a", "name": "Aria", "class": "rogue"}),
		playTest("play-projection-unauthenticated", "Unauthenticated projection append is rejected", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-unauth", "kind": "increment-danger"}, nil, 401, nil),
		playTest("play-projection-empty-event-id", "Projection event_id must be nonempty", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "", "kind": "increment-danger"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-projection-invalid-kind", "Projection event kind must be known", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-invalid-kind", "kind": "clear-story"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-projection-set-story-missing-value", "set-story requires a value", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-missing-value", "kind": "set-story"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-projection-set-story-empty-value", "set-story value must be nonempty", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-empty-value", "kind": "set-story", "value": ""}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-projection-increment-value-forbidden", "increment-danger omits value", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-value-forbidden", "kind": "increment-danger", "value": "bad"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-projection-dm-append-forbidden", "DM reads projections but does not append projection events", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-dm", "kind": "increment-danger"}, map[string]string{"Authorization": dmAuth}, 403, nil),
		playTestExactJSON("play-projection-append-increment-first", "Player appends first projection event with non-lexical event ID", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-2", "kind": "increment-danger"}, map[string]string{"Authorization": playerAAuth}, 201, firstEvent),
		playTestExactJSON("play-projection-after-first", "Projection rebuilds after first append", "GET", "/v1/play/campaigns/play-079/projection", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"story": "", "danger": 1, "applied_event_ids": []any{"event-2"}}),
		playTestExactJSON("play-projection-append-story-second", "Player appends set-story after earlier event ID", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-1", "kind": "set-story", "value": "The road is clear."}, map[string]string{"Authorization": playerAAuth}, 201, secondEvent),
		playTest("play-projection-duplicate-event-id", "Duplicate projection event_id conflicts", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-1", "kind": "increment-danger"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-projection-append-increment-third", "Player appends another mixed projection event", "POST", "/v1/play/campaigns/play-079/projection-events", map[string]any{"event_id": "event-3", "kind": "increment-danger"}, map[string]string{"Authorization": playerAAuth}, 201, thirdEvent),
		playTestExactJSON("play-projection-read-player", "Campaign member reads exact ordered projection", "GET", "/v1/play/campaigns/play-079/projection", nil, map[string]string{"Authorization": playerAAuth}, 200, finalProjection),
		playTestExactJSON("play-projection-rebuild-dm", "Explicit rebuild returns the same exact projection", "GET", "/v1/play/campaigns/play-079/projection/rebuild", nil, map[string]string{"Authorization": dmAuth}, 200, finalProjection),
		playTest("play-projection-read-nonmember-forbidden", "Non-member cannot read projection", "GET", "/v1/play/campaigns/play-079/projection", nil, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
	)}
}

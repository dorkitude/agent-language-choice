package eval

func gmDelegationSuite() Suite {
	base := campaignInvitationsSuite()
	activeDelegation := map[string]any{"username": "player-b", "powers": []any{"narrate"}, "active": true}
	inactiveDelegation := map[string]any{"username": "player-b", "powers": []any{"narrate"}, "active": false}
	return Suite{ID: "077-gm-delegation", Name: "Campaign Play 077: GM Delegation", Tests: append(base.Tests,
		playTest("play-delegation-create-campaign", "DM creates a fresh campaign for delegation", "POST", "/v1/play/campaigns", map[string]any{"id": "play-077", "name": "Delegation Campaign", "max_players": 3}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-077", "name": "Delegation Campaign", "owner": "dm", "status": "lobby", "max_players": 3}),
		playTest("play-delegation-join-player-a", "Player A joins as a nondelegated campaign member", "POST", "/v1/play/campaigns/play-077/members", map[string]any{"character_id": "play-077-char-a", "name": "Aria", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-077-char-a", "name": "Aria", "class": "rogue"}),
		playTest("play-delegation-join-player-b", "Player B joins as the delegation target", "POST", "/v1/play/campaigns/play-077/members", map[string]any{"character_id": "play-077-char-b", "name": "Bram", "class": "cleric"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"username": "player-b", "character_id": "play-077-char-b", "name": "Bram", "class": "cleric"}),
		playTest("play-delegation-unauthenticated", "Unauthenticated delegation grant is rejected", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "player-b", "powers": []any{"narrate"}}, nil, 401, nil),
		playTest("play-delegation-player-forbidden", "Campaign members cannot grant delegation", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "player-b", "powers": []any{"narrate"}}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-delegation-target-must-be-member", "Delegation target must already be a campaign member", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "stranger", "powers": []any{"narrate"}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-delegation-empty-powers", "Delegation powers must be nonempty", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "player-b", "powers": []any{}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-delegation-duplicate-powers", "Delegation powers must be unique", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "player-b", "powers": []any{"narrate", "narrate"}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-delegation-invalid-power", "Delegation powers must be valid", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "player-b", "powers": []any{"resolve"}}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-delegation-nondelegated-narration-forbidden", "Nondelegated campaign member cannot narrate", "POST", "/v1/play/campaigns/play-077/narrations", map[string]any{"text": "Player A tries to narrate."}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTestExactJSON("play-delegation-grant", "Owner grants narrate delegation to Player B", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "player-b", "powers": []any{"narrate"}}, map[string]string{"Authorization": dmAuth}, 201, activeDelegation),
		playTest("play-delegation-duplicate-active", "Duplicate active delegate conflicts", "POST", "/v1/play/campaigns/play-077/delegations", map[string]any{"username": "player-b", "powers": []any{"narrate"}}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-delegation-delegate-narrates", "Active delegated narrator may use existing narrations endpoint", "POST", "/v1/play/campaigns/play-077/narrations", map[string]any{"text": "Player B narrates the old road."}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"sequence": 1, "kind": "narration", "actor": "player-b", "text": "Player B narrates the old road."}),
		playTest("play-delegation-audit-player-forbidden", "Non-owner cannot read delegation audit", "GET", "/v1/play/campaigns/play-077/delegations/audit", nil, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTestExactJSON("play-delegation-revoke", "Owner revokes active delegation", "DELETE", "/v1/play/campaigns/play-077/delegations/player-b", nil, map[string]string{"Authorization": dmAuth}, 200, inactiveDelegation),
		playTest("play-delegation-after-revoke-narration-forbidden", "Revoked delegate cannot narrate", "POST", "/v1/play/campaigns/play-077/narrations", map[string]any{"text": "Player B tries after revoke."}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTestExactJSON("play-delegation-audit-owner", "Owner reads immutable delegation audit in order", "GET", "/v1/play/campaigns/play-077/delegations/audit", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"entries": []any{
			map[string]any{"username": "player-b", "action": "granted", "powers": []any{"narrate"}},
			map[string]any{"username": "player-b", "action": "revoked", "powers": []any{"narrate"}},
		}}),
	)}
}

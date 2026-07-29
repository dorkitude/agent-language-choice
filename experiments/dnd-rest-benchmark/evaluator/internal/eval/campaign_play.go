package eval

// Tickets 017-030 intentionally use a /v1/play namespace.  The established
// benchmark contracts remain callable without auth, while the new agent-play
// surface can enforce actor identity and campaign-scoped authorization.

const (
	dmAuth      = "Bearer session-dm"
	playerAAuth = "Bearer session-player-a"
	playerBAuth = "Bearer session-player-b"
)

func playTest(id, name, method, path string, body map[string]any, headers map[string]string, wantStatus int, wantJSON any) Test {
	return Test{ID: id, Name: name, Method: method, Path: path, Body: body, Headers: headers, WantStatus: wantStatus, WantJSON: wantJSON}
}

func playTestExactKeys(id, name, method, path string, body map[string]any, headers map[string]string, wantStatus int, wantJSON any, exactJSONKeys []string) Test {
	test := playTest(id, name, method, path, body, headers, wantStatus, wantJSON)
	test.ExactJSONKeys = exactJSONKeys
	return test
}

func dmCampaignOwnershipSuite() Suite {
	base := analyticsReportingSuite()
	return Suite{ID: "017-dm-campaign-ownership", Name: "Campaign Play 017: DM Campaign Ownership", Tests: append(base.Tests,
		playTest("play-create-campaign-unauthenticated", "Reject unauthenticated campaign owner", "POST", "/v1/play/campaigns", map[string]any{"id": "play-1", "name": "Ashen Road", "max_players": 2}, nil, 401, nil),
		playTest("play-create-campaign-player-forbidden", "Reject player campaign owner", "POST", "/v1/play/campaigns", map[string]any{"id": "play-1", "name": "Ashen Road", "max_players": 2}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-create-campaign-dm", "DM owns a new campaign", "POST", "/v1/play/campaigns", map[string]any{"id": "play-1", "name": "Ashen Road", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-1", "name": "Ashen Road", "owner": "dm", "status": "lobby", "max_players": 2}),
	)}
}

func partyMembershipSuite() Suite {
	base := dmCampaignOwnershipSuite()
	return Suite{ID: "018-party-membership", Name: "Campaign Play 018: Party Membership", Tests: append(base.Tests,
		playTest("play-register-player-a", "Register first player", "POST", "/v1/auth/register", map[string]any{"username": "player-a", "password": "swordfish", "role": "player"}, nil, 201, map[string]any{"username": "player-a", "role": "player"}),
		playTest("play-register-player-b", "Register second player", "POST", "/v1/auth/register", map[string]any{"username": "player-b", "password": "swordfish", "role": "player"}, nil, 201, map[string]any{"username": "player-b", "role": "player"}),
		playTest("play-join-player-a", "Player A joins with an owned character", "POST", "/v1/play/campaigns/play-1/members", map[string]any{"character_id": "play-char-a", "name": "Aria", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-char-a", "name": "Aria", "class": "rogue"}),
		playTest("play-join-player-b", "Player B joins with an owned character", "POST", "/v1/play/campaigns/play-1/members", map[string]any{"character_id": "play-char-b", "name": "Bram", "class": "cleric"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"username": "player-b", "character_id": "play-char-b", "name": "Bram", "class": "cleric"}),
		playTest("play-join-duplicate-character", "Reject duplicate party membership", "POST", "/v1/play/campaigns/play-1/members", map[string]any{"character_id": "play-char-a", "name": "Aria", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
	)}
}

func campaignStartSuite() Suite {
	base := partyMembershipSuite()
	return Suite{ID: "019-campaign-start", Name: "Campaign Play 019: Campaign Start", Tests: append(base.Tests,
		playTest("play-start-player-forbidden", "Only the DM starts the campaign", "POST", "/v1/play/campaigns/play-1/start", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-start-dm", "DM starts a populated campaign", "POST", "/v1/play/campaigns/play-1/start", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"id": "play-1", "status": "active", "current_actor": "player-a", "turn_number": 1}),
		playTest("play-start-idempotency", "Reject duplicate campaign start", "POST", "/v1/play/campaigns/play-1/start", nil, map[string]string{"Authorization": dmAuth}, 409, nil),
	)}
}

func gmNarrationSuite() Suite {
	base := campaignStartSuite()
	return Suite{ID: "020-gm-narration", Name: "Campaign Play 020: GM Narration", Tests: append(base.Tests,
		playTest("play-narrate-player-forbidden", "Player cannot narrate for the DM", "POST", "/v1/play/campaigns/play-1/narrations", map[string]any{"text": "The road opens before you."}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-narrate-dm", "DM appends narrated event", "POST", "/v1/play/campaigns/play-1/narrations", map[string]any{"text": "Dawn breaks over the Ashen Road."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"sequence": 1, "kind": "narration", "actor": "dm", "text": "Dawn breaks over the Ashen Road."}),
	)}
}

func roleAuthorizationSuite() Suite {
	base := gmNarrationSuite()
	return Suite{ID: "021-role-authorization", Name: "Campaign Play 021: Role Authorization", Tests: append(base.Tests,
		playTest("play-read-status-unauthenticated", "Reject unauthenticated play state", "GET", "/v1/play/campaigns/play-1/turn", nil, nil, 401, nil),
		playTest("play-read-status-nonmember", "Reject an unrelated player", "GET", "/v1/play/campaigns/play-1/turn", nil, map[string]string{"Authorization": "Bearer session-stranger"}, 403, nil),
		playTest("play-dm-can-read-status", "DM reads campaign turn", "GET", "/v1/play/campaigns/play-1/turn", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"campaign_id": "play-1", "current_actor": "player-a", "phase": "player", "turn_number": 1}),
	)}
}

func explorationTurnQueueSuite() Suite {
	base := roleAuthorizationSuite()
	return Suite{ID: "022-exploration-turn-queue", Name: "Campaign Play 022: Exploration Turn Queue", Tests: append(base.Tests,
		playTest("play-turn-queue-order", "Turn endpoint reports deterministic party order", "GET", "/v1/play/campaigns/play-1/turn", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"current_actor": "player-a", "queue": []any{"player-a", "dm", "player-b", "dm"}, "turn_number": 1}),
	)}
}

func playerTurnContextSuite() Suite {
	base := explorationTurnQueueSuite()
	return Suite{ID: "023-player-turn-context", Name: "Campaign Play 023: Player Turn Context", Tests: append(base.Tests,
		playTest("play-player-a-turn-context", "Active player receives permitted context", "GET", "/v1/play/campaigns/play-1/my-turn", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"is_my_turn": true, "character": map[string]any{"id": "play-char-a", "name": "Aria"}, "current_actor": "player-a", "recent_events": []any{map[string]any{"kind": "narration"}}}),
		playTest("play-player-b-turn-context", "Waiting player sees no DM-private data", "GET", "/v1/play/campaigns/play-1/my-turn", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"is_my_turn": false, "character": map[string]any{"id": "play-char-b", "name": "Bram"}, "current_actor": "player-a"}),
	)}
}

func gmTurnContextSuite() Suite {
	base := playerTurnContextSuite()
	return Suite{ID: "024-gm-turn-context", Name: "Campaign Play 024: GM Turn Context", Tests: append(base.Tests,
		playTest("play-gm-status-player-forbidden", "Player cannot read GM status", "GET", "/v1/play/campaigns/play-1/gm/status", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-gm-status-dm", "DM gets role-specific campaign context", "GET", "/v1/play/campaigns/play-1/gm/status", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"needs_attention": false, "current_actor": "player-a", "party": []any{map[string]any{"username": "player-a"}, map[string]any{"username": "player-b"}}, "recent_events": []any{map[string]any{"kind": "narration"}}}),
	)}
}

func playerActionSuite() Suite {
	base := gmTurnContextSuite()
	return Suite{ID: "025-player-action-submission", Name: "Campaign Play 025: Player Action Submission", Tests: append(base.Tests,
		playTest("play-action-waiting-player-forbidden", "Waiting player cannot act", "POST", "/v1/play/campaigns/play-1/actions", map[string]any{"type": "search", "text": "I examine the trail."}, map[string]string{"Authorization": playerBAuth}, 409, nil),
		playTest("play-action-active-player", "Active player action advances to the DM", "POST", "/v1/play/campaigns/play-1/actions", map[string]any{"type": "search", "text": "I examine the trail."}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"sequence": 2, "kind": "action", "actor": "player-a", "type": "search", "text": "I examine the trail.", "next_actor": "dm"}),
	)}
}

func gmResolutionSuite() Suite {
	base := playerActionSuite()
	return Suite{ID: "026-gm-resolution", Name: "Campaign Play 026: GM Resolution", Tests: append(base.Tests,
		playTest("play-resolution-player-forbidden", "Player cannot resolve a DM turn", "POST", "/v1/play/campaigns/play-1/resolutions", map[string]any{"text": "You find a broken arrow."}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-resolution-dm", "DM resolves action and advances queue", "POST", "/v1/play/campaigns/play-1/resolutions", map[string]any{"text": "You find a broken arrow."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"sequence": 3, "kind": "resolution", "actor": "dm", "text": "You find a broken arrow.", "next_actor": "player-b", "turn_number": 2}),
	)}
}

func turnTimeoutSuite() Suite {
	base := gmResolutionSuite()
	return Suite{ID: "027-turn-timeout-policy", Name: "Campaign Play 027: Turn Timeout Policy", Tests: append(base.Tests,
		playTest("play-turn-not-overdue", "Fresh logical turn is not overdue", "GET", "/v1/play/campaigns/play-1/turn", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"current_actor": "player-b", "overdue": false, "logical_deadline": 3}),
		playTest("play-nudge-player", "DM sends a deterministic turn nudge", "POST", "/v1/play/campaigns/play-1/turn/nudge", map[string]any{"message": "Bram, the party is waiting."}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"actor": "dm", "target": "player-b", "message": "Bram, the party is waiting.", "nudge_count": 1}),
	)}
}

func partyChatSuite() Suite {
	base := turnTimeoutSuite()
	return Suite{ID: "028-party-chat", Name: "Campaign Play 028: Party Chat", Tests: append(base.Tests,
		playTest("play-party-chat", "Party member posts chat without advancing turn", "POST", "/v1/play/campaigns/play-1/messages", map[string]any{"text": "I can tend the wound after we search."}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"sequence": 5, "kind": "chat", "actor": "player-b", "text": "I can tend the wound after we search.", "current_actor": "player-b"}),
	)}
}

func partyObservationSuite() Suite {
	base := partyChatSuite()
	return Suite{ID: "029-party-observations", Name: "Campaign Play 029: Party Observations", Tests: append(base.Tests,
		playTest("play-party-observation", "Party member records an attributed observation", "POST", "/v1/play/campaigns/play-1/observations", map[string]any{"type": "world", "text": "The arrow bears goblin fletching."}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"sequence": 6, "kind": "observation", "actor": "player-b", "type": "world", "text": "The arrow bears goblin fletching."}),
	)}
}

func campaignDocumentSuite() Suite {
	base := partyObservationSuite()
	return Suite{ID: "030-campaign-document", Name: "Campaign Play 030: Campaign Document", Tests: append(base.Tests,
		playTest("play-document-player-update-forbidden", "Player cannot update DM campaign document", "PUT", "/v1/play/campaigns/play-1/document", map[string]any{"story": "Nope", "dm_notes": "Nope"}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTest("play-document-dm-update", "DM updates public story and private notes", "PUT", "/v1/play/campaigns/play-1/document", map[string]any{"story": "Aria found a goblin arrow on the Ashen Road.", "dm_notes": "The goblins watch from the ridge."}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"story": "Aria found a goblin arrow on the Ashen Road.", "dm_notes": "The goblins watch from the ridge."}),
		playTest("play-document-player-filtered", "Player sees public document only", "GET", "/v1/play/campaigns/play-1/document", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"story": "Aria found a goblin arrow on the Ashen Road."}),
	)}
}

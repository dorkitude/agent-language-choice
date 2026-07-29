package eval

func actorAuditTrailSuite() Suite {
	base := gmDelegationSuite()
	dmAudit := map[string]any{"kind": "note", "actor": "dm", "role": "DM", "timestamp": 1, "correlation_id": "corr-dm"}
	playerAudit := map[string]any{"kind": "note", "actor": "player-a", "role": "player", "timestamp": 2, "correlation_id": "corr-player-a"}
	return Suite{ID: "078-actor-audit-trail", Name: "Campaign Play 078: Actor Audit Trail", Tests: append(base.Tests,
		playTest("play-audit-create-campaign", "DM creates a fresh campaign for actor audit", "POST", "/v1/play/campaigns", map[string]any{"id": "play-078", "name": "Actor Audit Campaign", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-078", "name": "Actor Audit Campaign", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-audit-join-player-a", "Player A joins the actor audit campaign", "POST", "/v1/play/campaigns/play-078/members", map[string]any{"character_id": "play-078-char-a", "name": "Aria", "class": "rogue"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-078-char-a", "name": "Aria", "class": "rogue"}),
		playTest("play-audit-unauthenticated", "Unauthenticated audit mutation is rejected", "POST", "/v1/play/campaigns/play-078/audit-events", map[string]any{"kind": "note", "correlation_id": "corr-unauth"}, nil, 401, nil),
		playTest("play-audit-empty-kind", "Audit event kind must be nonempty", "POST", "/v1/play/campaigns/play-078/audit-events", map[string]any{"kind": "", "correlation_id": "corr-empty-kind"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-audit-empty-correlation", "Audit event correlation_id must be nonempty", "POST", "/v1/play/campaigns/play-078/audit-events", map[string]any{"kind": "note", "correlation_id": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-audit-create-dm", "DM creates exact actor audit event", "POST", "/v1/play/campaigns/play-078/audit-events", map[string]any{"kind": "note", "correlation_id": "corr-dm"}, map[string]string{"Authorization": dmAuth}, 201, dmAudit),
		playTestExactJSON("play-audit-create-player", "Player creates exact actor audit event with incremented timestamp", "POST", "/v1/play/campaigns/play-078/audit-events", map[string]any{"kind": "note", "correlation_id": "corr-player-a"}, map[string]string{"Authorization": playerAAuth}, 201, playerAudit),
		playTest("play-audit-duplicate-correlation", "Duplicate audit correlation_id conflicts per campaign", "POST", "/v1/play/campaigns/play-078/audit-events", map[string]any{"kind": "note", "correlation_id": "corr-dm"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-audit-read-player-forbidden", "Players cannot read actor audit trail", "GET", "/v1/play/campaigns/play-078/audit-events", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTestExactJSON("play-audit-read-dm", "DM reads immutable actor audit trail in timestamp order", "GET", "/v1/play/campaigns/play-078/audit-events", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"entries": []any{dmAudit, playerAudit}}),
	)}
}

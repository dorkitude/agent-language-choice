package eval

func relationshipGraphSuite() Suite {
	base := npcDialogueSuite()
	return Suite{ID: "062-relationship-graph", Name: "Campaign Play 062: Relationship Graph", Tests: append(base.Tests,
		playTest("play-relationship-create-player-forbidden", "Players cannot create relationship edges", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust", "score": 25}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-relationship-invalid-self", "Relationship edges require different entities", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "npc-guide", "kind": "trust", "score": 25}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-relationship-invalid-kind", "Relationship kind must be nonempty", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "", "score": 25}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-relationship-invalid-score", "Relationship score must be bounded", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust", "score": 101}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-relationship-missing-score", "Relationship score is required", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-relationship-missing-source", "Unknown relationship source returns 404", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-missing", "target_id": "play-char-w", "kind": "trust", "score": 25}, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTest("play-relationship-missing-target", "Unknown relationship target returns 404", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "play-char-missing", "kind": "trust", "score": 25}, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTestExactJSON("play-relationship-create", "DM creates a relationship edge", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust", "score": 25}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust", "score": 25}),
		playTest("play-relationship-duplicate", "Duplicate directed relationship edges conflict", "POST", "/v1/play/campaigns/play-2/relationships", map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust", "score": 25}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-relationship-update-player-forbidden", "Players cannot update relationship edges", "PUT", "/v1/play/campaigns/play-2/relationships/npc-guide/play-char-w/trust", map[string]any{"score": 60}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-relationship-update-missing-edge", "Unknown relationship edge update returns 404", "PUT", "/v1/play/campaigns/play-2/relationships/play-char-w/npc-guide/trust", map[string]any{"score": 60}, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTest("play-relationship-update-invalid-score", "Relationship update score must be bounded", "PUT", "/v1/play/campaigns/play-2/relationships/npc-guide/play-char-w/trust", map[string]any{"score": -101}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-relationship-update", "DM updates a relationship edge", "PUT", "/v1/play/campaigns/play-2/relationships/npc-guide/play-char-w/trust", map[string]any{"score": 60}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust", "score": 60}),
		playTestExactJSON("play-relationship-read-player", "Campaign members read the exact relationship graph", "GET", "/v1/play/campaigns/play-2/relationships", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"edges": []any{
			map[string]any{"source_id": "npc-guide", "target_id": "play-char-w", "kind": "trust", "score": 60},
		}}),
	)}
}

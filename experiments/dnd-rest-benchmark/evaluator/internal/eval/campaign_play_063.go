package eval

func secretsAndCluesSuite() Suite {
	base := relationshipGraphSuite()
	return Suite{ID: "063-secrets-and-clues", Name: "Campaign Play 063: Secrets and Clues", Tests: append(base.Tests,
		playTest("play-clue-create-player-forbidden", "Players cannot create clues", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-player", "text": "Players cannot write this.", "audience": "party"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-clue-invalid-id", "Clue creation requires a nonempty clue ID", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "party"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-clue-invalid-text", "Clue creation requires nonempty text", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-empty-text", "text": "", "audience": "party"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-clue-invalid-audience", "Clue audience must be known", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-invalid-audience", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "private"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-clue-character-missing-character", "Character audience requires a character ID", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-no-character", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "character"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-clue-character-unknown-character", "Character audience requires a campaign member character", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-unknown-character", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "character", "character_id": "play-char-missing"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-clue-party-rejects-character", "Party audience omits character ID", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-party-character", "text": "The cave entrance lies east of Phandalin.", "audience": "party", "character_id": "play-char-w"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-clue-hidden-rejects-character", "Hidden audience omits character ID", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-hidden-character", "text": "Venomfang watches from Thundertree.", "audience": "hidden", "character_id": "play-char-w"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-clue-create-character", "DM creates a character clue", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-letter", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "character", "character_id": "play-char-w"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"clue_id": "clue-letter", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "character", "character_id": "play-char-w"}),
		playTest("play-clue-duplicate", "Duplicate clue IDs conflict per campaign", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-letter", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "character", "character_id": "play-char-w"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTestExactJSON("play-clue-create-party", "DM creates a party clue", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-party", "text": "The cave entrance lies east of Phandalin.", "audience": "party"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"clue_id": "clue-party", "text": "The cave entrance lies east of Phandalin.", "audience": "party"}),
		playTestExactJSON("play-clue-create-hidden", "DM creates a hidden clue", "POST", "/v1/play/campaigns/play-2/clues", map[string]any{"clue_id": "clue-hidden", "text": "Venomfang watches from Thundertree.", "audience": "hidden"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"clue_id": "clue-hidden", "text": "Venomfang watches from Thundertree.", "audience": "hidden"}),
		playTestExactJSON("play-clue-read-dm", "DM sees all clues in insertion order", "GET", "/v1/play/campaigns/play-2/clues", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"clues": []any{
			map[string]any{"clue_id": "clue-letter", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "character", "character_id": "play-char-w"},
			map[string]any{"clue_id": "clue-party", "text": "The cave entrance lies east of Phandalin.", "audience": "party"},
			map[string]any{"clue_id": "clue-hidden", "text": "Venomfang watches from Thundertree.", "audience": "hidden"},
		}}),
		playTestExactJSON("play-clue-read-player-a", "Target player sees party and own character clues", "GET", "/v1/play/campaigns/play-2/clues", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"clues": []any{
			map[string]any{"clue_id": "clue-letter", "text": "The Black Spider seeks Wave Echo Cave.", "audience": "character", "character_id": "play-char-w"},
			map[string]any{"clue_id": "clue-party", "text": "The cave entrance lies east of Phandalin.", "audience": "party"},
		}}),
		playTestExactJSON("play-clue-read-player-b", "Other player sees only party clues", "GET", "/v1/play/campaigns/play-2/clues", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"clues": []any{
			map[string]any{"clue_id": "clue-party", "text": "The cave entrance lies east of Phandalin.", "audience": "party"},
		}}),
	)}
}

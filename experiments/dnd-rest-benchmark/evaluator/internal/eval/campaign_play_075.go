package eval

func privacyControlsSuite() Suite {
	base := contentTagsSuite()
	privateNote := map[string]any{"note_id": "note-a", "text": "secret", "visibility": "private", "owner": "player-a"}
	partyNote := map[string]any{"note_id": "note-party", "text": "check the north door", "visibility": "party", "owner": "player-b"}
	whisper := map[string]any{"whisper_id": "whisper-a", "from_character_id": "play-char-a", "to_character_id": "play-char-b", "text": "meet at dawn"}
	sheetA := map[string]any{"character_id": "play-char-a", "owner": "player-a", "name": "Aria", "class": "rogue", "level": 1, "proficiency_bonus": 2, "hp_max": 10, "armor_class": 10}
	sheetB := map[string]any{"character_id": "play-char-b", "owner": "player-b", "name": "Bram", "class": "cleric", "level": 1, "proficiency_bonus": 2, "hp_max": 10, "armor_class": 10}
	return Suite{ID: "075-privacy-controls", Name: "Campaign Play 075: Privacy Controls", Tests: append(base.Tests,
		playTest("play-note-unauthenticated", "Unauthenticated note creation is rejected", "POST", "/v1/play/campaigns/play-1/notes", map[string]any{"note_id": "note-unauth", "text": "secret", "visibility": "private"}, nil, 401, nil),
		playTest("play-note-empty-id", "Notes require nonempty note IDs", "POST", "/v1/play/campaigns/play-1/notes", map[string]any{"note_id": "", "text": "secret", "visibility": "private"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-note-empty-text", "Notes require nonempty text", "POST", "/v1/play/campaigns/play-1/notes", map[string]any{"note_id": "note-empty-text", "text": "", "visibility": "private"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-note-bad-visibility", "Notes require private or party visibility", "POST", "/v1/play/campaigns/play-1/notes", map[string]any{"note_id": "note-bad-visibility", "text": "secret", "visibility": "public"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTestExactJSON("play-note-create-private", "Player A creates an owner-private note", "POST", "/v1/play/campaigns/play-1/notes", map[string]any{"note_id": "note-a", "text": "secret", "visibility": "private"}, map[string]string{"Authorization": playerAAuth}, 201, privateNote),
		playTest("play-note-duplicate", "Duplicate note IDs conflict", "POST", "/v1/play/campaigns/play-1/notes", map[string]any{"note_id": "note-a", "text": "another secret", "visibility": "private"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-note-create-party", "Player B creates a party-visible note", "POST", "/v1/play/campaigns/play-1/notes", map[string]any{"note_id": "note-party", "text": "check the north door", "visibility": "party"}, map[string]string{"Authorization": playerBAuth}, 201, partyNote),
		playTestExactJSON("play-notes-read-owner", "Private note owner reads private and party notes", "GET", "/v1/play/campaigns/play-1/notes", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"notes": []any{privateNote, partyNote}}),
		playTestExactJSON("play-notes-read-other-player", "Other members cannot read owner-private notes", "GET", "/v1/play/campaigns/play-1/notes", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"notes": []any{partyNote}}),
		playTestExactJSON("play-notes-read-dm", "DM reads all private and party notes", "GET", "/v1/play/campaigns/play-1/notes", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"notes": []any{privateNote, partyNote}}),
		playTest("play-note-get-private-other-player-forbidden", "Other members cannot fetch a private note by ID", "GET", "/v1/play/campaigns/play-1/notes/note-a", nil, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTestExactJSON("play-note-get-private-owner", "Private note owner fetches exact note", "GET", "/v1/play/campaigns/play-1/notes/note-a", nil, map[string]string{"Authorization": playerAAuth}, 200, privateNote),
		playTest("play-note-update-other-player-forbidden", "Only the note owner may update a note", "PUT", "/v1/play/campaigns/play-1/notes/note-a", map[string]any{"text": "stolen", "visibility": "party"}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTestExactJSON("play-note-after-rejected-update", "Rejected note update leaves private note unchanged", "GET", "/v1/play/campaigns/play-1/notes/note-a", nil, map[string]string{"Authorization": dmAuth}, 200, privateNote),
		playTest("play-whisper-empty-id", "Whispers require nonempty IDs", "POST", "/v1/play/campaigns/play-1/whispers", map[string]any{"whisper_id": "", "to_character_id": "play-char-b", "text": "meet at dawn"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-whisper-empty-text", "Whispers require nonempty text", "POST", "/v1/play/campaigns/play-1/whispers", map[string]any{"whisper_id": "whisper-empty-text", "to_character_id": "play-char-b", "text": ""}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-whisper-bad-recipient", "Whisper recipients must be campaign member characters", "POST", "/v1/play/campaigns/play-1/whispers", map[string]any{"whisper_id": "whisper-bad-recipient", "to_character_id": "play-char-missing", "text": "meet at dawn"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTestExactJSON("play-whisper-create", "Player A whispers to Player B's character", "POST", "/v1/play/campaigns/play-1/whispers", map[string]any{"whisper_id": "whisper-a", "to_character_id": "play-char-b", "text": "meet at dawn"}, map[string]string{"Authorization": playerAAuth}, 201, whisper),
		playTest("play-whisper-duplicate", "Duplicate whisper IDs conflict", "POST", "/v1/play/campaigns/play-1/whispers", map[string]any{"whisper_id": "whisper-a", "to_character_id": "play-char-b", "text": "again"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTestExactJSON("play-whispers-read-sender", "Whisper sender reads sent whisper", "GET", "/v1/play/campaigns/play-1/whispers", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"whispers": []any{whisper}}),
		playTestExactJSON("play-whispers-read-recipient", "Whisper recipient reads received whisper", "GET", "/v1/play/campaigns/play-1/whispers", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"whispers": []any{whisper}}),
		playTestExactJSON("play-whispers-read-dm", "DM reads all whispers", "GET", "/v1/play/campaigns/play-1/whispers", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"whispers": []any{whisper}}),
		playTestExactJSON("play-sheet-owner-a", "Character owner reads exact basic sheet fields", "GET", "/v1/play/campaigns/play-1/characters/play-char-a/sheet", nil, map[string]string{"Authorization": playerAAuth}, 200, sheetA),
		playTest("play-sheet-other-member-forbidden", "Other campaign members cannot read a character sheet", "GET", "/v1/play/campaigns/play-1/characters/play-char-a/sheet", nil, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTestExactJSON("play-sheet-dm-b", "DM reads exact basic sheet fields for any character", "GET", "/v1/play/campaigns/play-1/characters/play-char-b/sheet", nil, map[string]string{"Authorization": dmAuth}, 200, sheetB),
	)}
}

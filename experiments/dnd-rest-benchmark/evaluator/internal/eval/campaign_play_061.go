package eval

func npcDialogueSuite() Suite {
	base := factionReputationSuite()
	return Suite{ID: "061-npc-dialogue", Name: "Campaign Play 061: NPC Dialogue", Tests: append(base.Tests,
		playTest("play-dialogue-player-forbidden", "Players cannot append NPC dialogue", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "dialogue-player", "speaker": "Sildar", "text": "I should not write this.", "visibility": "public"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-dialogue-unknown-npc", "Unknown NPC dialogue append returns 404", "POST", "/v1/play/campaigns/play-2/npcs/npc-missing/dialogue", map[string]any{"dialogue_id": "dialogue-missing", "speaker": "Sildar", "text": "No one hears this.", "visibility": "public"}, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTest("play-dialogue-invalid-id", "Dialogue creation requires a nonempty dialogue ID", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "", "speaker": "Sildar", "text": "Welcome to Phandalin.", "visibility": "public"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-dialogue-invalid-speaker", "Dialogue creation requires a nonempty speaker", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "dialogue-no-speaker", "speaker": "", "text": "Welcome to Phandalin.", "visibility": "public"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-dialogue-invalid-text", "Dialogue creation requires nonempty text", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "dialogue-no-text", "speaker": "Sildar", "text": "", "visibility": "public"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-dialogue-invalid-visibility", "Dialogue visibility must be public or private", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "dialogue-hidden", "speaker": "Sildar", "text": "This is not valid.", "visibility": "hidden"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-dialogue-create-public", "DM appends public NPC dialogue", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "dialogue-welcome", "speaker": "Sildar", "text": "Welcome to Phandalin.", "visibility": "public"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"dialogue_id": "dialogue-welcome", "speaker": "Sildar", "text": "Welcome to Phandalin.", "visibility": "public"}),
		playTest("play-dialogue-duplicate", "Duplicate dialogue IDs conflict per NPC", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "dialogue-welcome", "speaker": "Sildar", "text": "Welcome again.", "visibility": "public"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTestExactJSON("play-dialogue-create-private", "DM appends private NPC dialogue", "POST", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", map[string]any{"dialogue_id": "dialogue-secret", "speaker": "Sildar", "text": "Gundren was taken to Cragmaw.", "visibility": "private"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"dialogue_id": "dialogue-secret", "speaker": "Sildar", "text": "Gundren was taken to Cragmaw.", "visibility": "private"}),
		playTest("play-dialogue-read-unknown-npc", "Unknown NPC dialogue history returns 404", "GET", "/v1/play/campaigns/play-2/npcs/npc-missing/dialogue", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTestExactJSON("play-dialogue-read-dm", "DM sees all NPC dialogue in insertion order", "GET", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"npc_id": "npc-guide", "entries": []any{
			map[string]any{"dialogue_id": "dialogue-welcome", "speaker": "Sildar", "text": "Welcome to Phandalin.", "visibility": "public"},
			map[string]any{"dialogue_id": "dialogue-secret", "speaker": "Sildar", "text": "Gundren was taken to Cragmaw.", "visibility": "private"},
		}}),
		playTestExactJSON("play-dialogue-read-player", "Players see only public NPC dialogue", "GET", "/v1/play/campaigns/play-2/npcs/npc-guide/dialogue", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"npc_id": "npc-guide", "entries": []any{
			map[string]any{"dialogue_id": "dialogue-welcome", "speaker": "Sildar", "text": "Welcome to Phandalin.", "visibility": "public"},
		}}),
	)}
}

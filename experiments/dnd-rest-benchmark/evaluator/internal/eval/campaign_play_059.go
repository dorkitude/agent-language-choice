package eval

func npcAgendasSuite() Suite {
	base := lootDistributionSuite()
	return Suite{ID: "059-npc-agendas", Name: "Campaign Play 059: NPC Agendas", Tests: append(base.Tests,
		playTest("play-npc-create-unauthenticated", "Reject unauthenticated NPC creation", "POST", "/v1/play/campaigns/play-2/npcs", map[string]any{"npc_id": "npc-guide", "name": "Sildar", "agenda": "find-gundren", "public_status": "searching"}, nil, 401, nil),
		playTest("play-npc-create-player-forbidden", "Only the DM can create NPC agendas", "POST", "/v1/play/campaigns/play-2/npcs", map[string]any{"npc_id": "npc-guide", "name": "Sildar", "agenda": "find-gundren", "public_status": "searching"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-npc-create-invalid", "NPC creation requires nonempty fields", "POST", "/v1/play/campaigns/play-2/npcs", map[string]any{"npc_id": "npc-empty", "name": "Sildar", "agenda": "", "public_status": "searching"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-npc-create", "DM creates a private NPC agenda with public status", "POST", "/v1/play/campaigns/play-2/npcs", map[string]any{"npc_id": "npc-guide", "name": "Sildar", "agenda": "find-gundren", "public_status": "searching"}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"npc_id": "npc-guide", "name": "Sildar", "agenda": "find-gundren", "public_status": "searching"}),
		playTest("play-npc-create-duplicate", "Duplicate NPC IDs conflict", "POST", "/v1/play/campaigns/play-2/npcs", map[string]any{"npc_id": "npc-guide", "name": "Sildar", "agenda": "find-gundren", "public_status": "searching"}, map[string]string{"Authorization": dmAuth}, 409, nil),
		playTest("play-npc-update-player-forbidden", "Players cannot update NPC agendas", "PUT", "/v1/play/campaigns/play-2/npcs/npc-guide/agenda", map[string]any{"agenda": "reach-cragmaw", "public_status": "traveling"}, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-npc-update-unknown", "Unknown NPC agenda update returns 404", "PUT", "/v1/play/campaigns/play-2/npcs/npc-missing/agenda", map[string]any{"agenda": "reach-cragmaw", "public_status": "traveling"}, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTest("play-npc-update-invalid", "NPC agenda update requires nonempty fields", "PUT", "/v1/play/campaigns/play-2/npcs/npc-guide/agenda", map[string]any{"agenda": "reach-cragmaw", "public_status": ""}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-npc-update", "DM updates NPC agenda and public status", "PUT", "/v1/play/campaigns/play-2/npcs/npc-guide/agenda", map[string]any{"agenda": "reach-cragmaw", "public_status": "traveling"}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"npc_id": "npc-guide", "name": "Sildar", "agenda": "reach-cragmaw", "public_status": "traveling"}),
		playTest("play-npc-read-unknown", "Unknown NPC read returns 404", "GET", "/v1/play/campaigns/play-2/npcs/npc-missing", nil, map[string]string{"Authorization": playerAAuth}, 404, nil),
		playTest("play-npc-read-dm", "DM reads private NPC agenda", "GET", "/v1/play/campaigns/play-2/npcs/npc-guide", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"npc_id": "npc-guide", "name": "Sildar", "agenda": "reach-cragmaw", "public_status": "traveling"}),
		playTestExactKeys("play-npc-read-player-filtered", "Player reads only public NPC fields", "GET", "/v1/play/campaigns/play-2/npcs/npc-guide", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"npc_id": "npc-guide", "name": "Sildar", "public_status": "traveling"}, []string{"npc_id", "name", "public_status"}),
	)}
}

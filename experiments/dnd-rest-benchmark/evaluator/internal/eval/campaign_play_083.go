package eval

func versionedExportSuite() Suite {
	base := transactionRecoverySuite()
	version1 := map[string]any{"version": 1, "story": "The party reaches the glass gate.", "status": "active"}
	version2 := map[string]any{"version": 2, "story": "The glass gate opens to a blue stair.", "status": "active"}
	return Suite{ID: "083-versioned-export", Name: "Campaign Play 083: Versioned Export", Tests: append(base.Tests,
		playTest("play-export-create-campaign", "DM creates a fresh campaign for versioned exports", "POST", "/v1/play/campaigns", map[string]any{"id": "play-083", "name": "Glass Gate", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-083", "name": "Glass Gate", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-export-join-player-a", "Player A joins the export campaign", "POST", "/v1/play/campaigns/play-083/members", map[string]any{"character_id": "play-083-char-a", "name": "Iri", "class": "wizard"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"username": "player-a", "character_id": "play-083-char-a", "name": "Iri", "class": "wizard"}),
		playTest("play-export-join-player-b", "Player B joins the export campaign", "POST", "/v1/play/campaigns/play-083/members", map[string]any{"character_id": "play-083-char-b", "name": "Tovin", "class": "fighter"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"username": "player-b", "character_id": "play-083-char-b", "name": "Tovin", "class": "fighter"}),
		playTest("play-export-start", "DM starts the export campaign", "POST", "/v1/play/campaigns/play-083/start", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"id": "play-083", "status": "active", "current_actor": "player-a", "turn_number": 1}),
		playTest("play-export-player-create-forbidden", "Player cannot create a campaign export", "POST", "/v1/play/campaigns/play-083/exports", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-export-list-player-forbidden", "Player cannot list campaign exports", "GET", "/v1/play/campaigns/play-083/exports", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-export-read-player-forbidden", "Player cannot read a campaign export", "GET", "/v1/play/campaigns/play-083/exports/1", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-export-set-story-one", "DM changes story through campaign document endpoint", "PUT", "/v1/play/campaigns/play-083/document", map[string]any{"story": "The party reaches the glass gate.", "dm_notes": "The hinge is trapped."}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"story": "The party reaches the glass gate.", "dm_notes": "The hinge is trapped."}),
		playTestExactJSON("play-export-version-one", "DM exports immutable version one from current story and status", "POST", "/v1/play/campaigns/play-083/exports", nil, map[string]string{"Authorization": dmAuth}, 201, version1),
		playTest("play-export-set-story-two", "DM mutates story after version one", "PUT", "/v1/play/campaigns/play-083/document", map[string]any{"story": "The glass gate opens to a blue stair.", "dm_notes": "The stair descends."}, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"story": "The glass gate opens to a blue stair.", "dm_notes": "The stair descends."}),
		playTestExactJSON("play-export-version-two", "DM exports immutable version two from mutated story", "POST", "/v1/play/campaigns/play-083/exports", nil, map[string]string{"Authorization": dmAuth}, 201, version2),
		playTestExactJSON("play-export-read-version-one-unchanged", "Version one remains unchanged after story mutation", "GET", "/v1/play/campaigns/play-083/exports/1", nil, map[string]string{"Authorization": dmAuth}, 200, version1),
		playTestExactJSON("play-export-read-version-two", "Version two returns the exact second snapshot", "GET", "/v1/play/campaigns/play-083/exports/2", nil, map[string]string{"Authorization": dmAuth}, 200, version2),
		playTestExactJSON("play-export-list-ordered", "DM lists exact exports ordered by version", "GET", "/v1/play/campaigns/play-083/exports", nil, map[string]string{"Authorization": dmAuth}, 200, map[string]any{"exports": []any{version1, version2}}),
		playTest("play-export-unknown-version", "Unknown export version returns 404", "GET", "/v1/play/campaigns/play-083/exports/99", nil, map[string]string{"Authorization": dmAuth}, 404, nil),
	)}
}

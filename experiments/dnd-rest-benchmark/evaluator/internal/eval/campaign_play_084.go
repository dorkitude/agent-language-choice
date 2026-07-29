package eval

func importValidationSuite() Suite {
	base := versionedExportSuite()
	firstImport := map[string]any{"version": 1, "story": "Imported", "status": "lobby"}
	secondImport := map[string]any{"version": 1, "story": "Second import", "status": "started"}
	return Suite{ID: "084-import-validation", Name: "Campaign Play 084: Import Validation", Tests: append(base.Tests,
		playTest("play-import-create-campaign", "DM creates a fresh campaign for import validation", "POST", "/v1/play/campaigns", map[string]any{"id": "play-084", "name": "Imported Game", "max_players": 2}, map[string]string{"Authorization": dmAuth}, 201, map[string]any{"id": "play-084", "name": "Imported Game", "owner": "dm", "status": "lobby", "max_players": 2}),
		playTest("play-import-player-forbidden", "Player cannot import campaign state", "POST", "/v1/play/campaigns/play-084/imports", firstImport, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-import-state-player-forbidden", "Player cannot read imported campaign state", "GET", "/v1/play/campaigns/play-084/import-state", nil, map[string]string{"Authorization": playerAAuth}, 403, nil),
		playTest("play-import-invalid-version", "Invalid import version returns 400", "POST", "/v1/play/campaigns/play-084/imports", map[string]any{"version": 2, "story": "Imported", "status": "lobby"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTest("play-import-state-absent-after-invalid", "Invalid first import leaves no imported state", "GET", "/v1/play/campaigns/play-084/import-state", nil, map[string]string{"Authorization": dmAuth}, 404, nil),
		playTestExactJSON("play-import-valid-first", "Valid import applies story and lobby status exactly", "POST", "/v1/play/campaigns/play-084/imports", firstImport, map[string]string{"Authorization": dmAuth}, 200, firstImport),
		playTestExactJSON("play-import-state-after-first", "DM reads exact imported state after valid import", "GET", "/v1/play/campaigns/play-084/import-state", nil, map[string]string{"Authorization": dmAuth}, 200, firstImport),
		playTest("play-import-invalid-status", "Invalid import status returns 400", "POST", "/v1/play/campaigns/play-084/imports", map[string]any{"version": 1, "story": "Bad status", "status": "active"}, map[string]string{"Authorization": dmAuth}, 400, nil),
		playTestExactJSON("play-import-state-unchanged-after-invalid-status", "Invalid status does not mutate imported state", "GET", "/v1/play/campaigns/play-084/import-state", nil, map[string]string{"Authorization": dmAuth}, 200, firstImport),
		playTestExactJSON("play-import-valid-second", "Second valid import replaces imported state atomically", "POST", "/v1/play/campaigns/play-084/imports", secondImport, map[string]string{"Authorization": dmAuth}, 200, secondImport),
		playTestExactJSON("play-import-state-after-second", "DM reads exact second imported state", "GET", "/v1/play/campaigns/play-084/import-state", nil, map[string]string{"Authorization": dmAuth}, 200, secondImport),
	)}
}

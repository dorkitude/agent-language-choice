package eval

func spellCastingSuite() Suite {
	base := spellPreparationSuite()
	return Suite{ID: "052-spell-casting", Name: "Campaign Play 052: Spell Casting", Tests: append(base.Tests,
		playTest("play-wizard-learns-magic-missile", "Wizard learns a level-one spell", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/spells", map[string]any{"spell_id": "magic-missile", "name": "Magic Missile", "level": 1}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"spell_id": "magic-missile", "name": "Magic Missile", "level": 1}),
		playTest("play-wizard-prepares-magic-missile", "Wizard prepares magic missile", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/prepared-spells", map[string]any{"spell_ids": []any{"magic-missile"}}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "prepared_spells": []any{"magic-missile"}, "max_prepared": 1}),
		playTest("play-cast-non-owner", "Non-owner cannot cast a prepared spell", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/casts", map[string]any{"spell_id": "magic-missile", "target": "training-dummy"}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTest("play-cast-unprepared", "Casting an unprepared spell is rejected", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/casts", map[string]any{"spell_id": "fire-bolt", "target": "training-dummy"}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-cast-magic-missile", "Owner casts a prepared level-one spell", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/casts", map[string]any{"spell_id": "magic-missile", "target": "training-dummy"}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"character_id": "play-char-w", "spell_id": "magic-missile", "target": "training-dummy", "slot_level": 1, "slots_remaining": 0, "sequence": 1}),
		playTest("play-cast-exhausted", "Casting again is rejected when slots are exhausted", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/casts", map[string]any{"spell_id": "magic-missile", "target": "training-dummy"}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-member-reads-casts", "Campaign member reads the cast log", "GET", "/v1/play/campaigns/play-2/characters/play-char-w/casts", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"casts": []any{map[string]any{"character_id": "play-char-w", "spell_id": "magic-missile", "target": "training-dummy", "slot_level": 1, "slots_remaining": 0, "sequence": 1}}}),
	)}
}

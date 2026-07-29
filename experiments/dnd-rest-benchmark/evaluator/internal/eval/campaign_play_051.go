package eval

func spellPreparationSuite() Suite {
	base := spellbookStateSuite()
	return Suite{ID: "051-spell-preparation", Name: "Campaign Play 051: Spell Preparation", Tests: append(base.Tests,
		playTest("play-wizard-party-observer-joins", "Another campaign member may observe preparation", "POST", "/v1/play/campaigns/play-2/members", map[string]any{"character_id": "play-char-b", "name": "Bram", "class": "cleric"}, map[string]string{"Authorization": playerBAuth}, 201, map[string]any{"username": "player-b", "character_id": "play-char-b", "name": "Bram", "class": "cleric"}),
		playTest("play-rogue-prepare-rejected", "A rogue cannot prepare an unknown spell", "PUT", "/v1/play/campaigns/play-1/characters/play-char-a/prepared-spells", map[string]any{"spell_ids": []any{"fire-bolt"}}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-wizard-prepare-non-owner", "A member cannot prepare another character's spells", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/prepared-spells", map[string]any{"spell_ids": []any{"fire-bolt"}}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTest("play-wizard-prepare-unknown", "A wizard cannot prepare an unknown spell", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/prepared-spells", map[string]any{"spell_ids": []any{"mage-hand"}}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-wizard-prepare-over-limit", "Preparation cannot exceed the level-one limit", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/prepared-spells", map[string]any{"spell_ids": []any{"fire-bolt", "mage-hand"}}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-wizard-prepares-known-spell", "Owner prepares a known wizard spell", "PUT", "/v1/play/campaigns/play-2/characters/play-char-w/prepared-spells", map[string]any{"spell_ids": []any{"fire-bolt"}}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "prepared_spells": []any{"fire-bolt"}, "max_prepared": 1}),
		playTest("play-member-reads-prepared-spells", "Campaign member reads prepared spells", "GET", "/v1/play/campaigns/play-2/characters/play-char-w/prepared-spells", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"character_id": "play-char-w", "prepared_spells": []any{"fire-bolt"}, "max_prepared": 1}),
	)}
}

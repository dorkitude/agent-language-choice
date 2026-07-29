package eval

func currencyAndTradeSuite() Suite {
	base := consumablesSuite()
	return Suite{ID: "057-currency-and-trade", Name: "Campaign Play 057: Currency and Trade", Tests: append(base.Tests,
		playTest("play-currency-read-source", "Campaign member reads deterministic starting gold", "GET", "/v1/play/campaigns/play-2/characters/play-char-w/currency", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "gold": 10}),
		playTest("play-currency-read-recipient-member", "Campaign member reads another character balance", "GET", "/v1/play/campaigns/play-2/characters/play-char-b/currency", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-b", "gold": 10}),
		playTest("play-currency-transfer-non-owner", "Non-owner cannot transfer from another character", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/currency/transfers", map[string]any{"to_character_id": "play-char-b", "gold": 3}, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTest("play-currency-transfer-invalid-destination", "Transfers require a different campaign destination character", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/currency/transfers", map[string]any{"to_character_id": "play-char-w", "gold": 3}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-currency-transfer-invalid-amount", "Transfers require positive gold", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/currency/transfers", map[string]any{"to_character_id": "play-char-b", "gold": 0}, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-currency-transfer-valid", "Owner transfers gold atomically to another character", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/currency/transfers", map[string]any{"to_character_id": "play-char-b", "gold": 3}, map[string]string{"Authorization": playerAAuth}, 201, map[string]any{"from_character_id": "play-char-w", "to_character_id": "play-char-b", "gold": 3, "from_gold": 7, "to_gold": 13, "transfer_id": 1}),
		playTest("play-currency-transfer-underflow", "Insufficient funds reject without partial balance changes", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/currency/transfers", map[string]any{"to_character_id": "play-char-b", "gold": 99}, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-currency-source-after-underflow", "Source balance is unchanged after rejected transfer", "GET", "/v1/play/campaigns/play-2/characters/play-char-w/currency", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"character_id": "play-char-w", "gold": 7}),
		playTest("play-currency-recipient-visible-after-underflow", "Recipient balance remains publicly visible to campaign members", "GET", "/v1/play/campaigns/play-2/characters/play-char-b/currency", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-b", "gold": 13}),
	)}
}

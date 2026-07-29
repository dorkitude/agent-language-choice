package eval

func consumablesSuite() Suite {
	base := equipmentAndAttunementSuite()
	return Suite{ID: "056-consumables", Name: "Campaign Play 056: Consumables", Tests: append(base.Tests,
		playTest("play-consume-prepare-single-potion", "Public inventory removal leaves one potion to consume", "DELETE", "/v1/play/campaigns/play-2/characters/play-char-w/inventory/items/healing-potion", map[string]any{"quantity": 2}, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "item_id": "healing-potion", "quantity": 2, "total_quantity": 1}),
		playTest("play-consume-non-owner", "Non-owner cannot consume a character item", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/inventory/items/healing-potion/consume", nil, map[string]string{"Authorization": playerBAuth}, 403, nil),
		playTest("play-consume-non-consumable", "Non-consumable inventory items are rejected", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/inventory/items/torch/consume", nil, map[string]string{"Authorization": playerAAuth}, 400, nil),
		playTest("play-consume-healing-potion", "Owner consumes one healing potion and applies its effect", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/inventory/items/healing-potion/consume", nil, map[string]string{"Authorization": playerAAuth}, 200, map[string]any{"character_id": "play-char-w", "item_id": "healing-potion", "quantity_consumed": 1, "total_quantity": 0, "effect": map[string]any{"type": "healing", "hp_restored": 5}}),
		playTest("play-consume-healing-potion-empty", "Repeating consumption after the stack is empty is a conflict", "POST", "/v1/play/campaigns/play-2/characters/play-char-w/inventory/items/healing-potion/consume", nil, map[string]string{"Authorization": playerAAuth}, 409, nil),
		playTest("play-consume-final-inventory", "Zero-quantity consumed stacks are omitted from inventory", "GET", "/v1/play/campaigns/play-2/characters/play-char-w/inventory/items", nil, map[string]string{"Authorization": playerBAuth}, 200, map[string]any{"character_id": "play-char-w", "items": []any{map[string]any{"item_id": "amulet-of-health", "quantity": 1}, map[string]any{"item_id": "leather-armor", "quantity": 1}, map[string]any{"item_id": "ring-of-protection", "quantity": 1}, map[string]any{"item_id": "torch", "quantity": 1}}}),
	)}
}

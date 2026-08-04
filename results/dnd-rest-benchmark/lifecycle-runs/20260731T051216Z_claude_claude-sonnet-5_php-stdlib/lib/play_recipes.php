<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped crafting recipes with deterministic
// ingredient requirements backed by the public inventory item catalog)
// ---------------------------------------------------------------------------

function validate_recipe_payload($body): ?array {
    if ($body === null
        || !isset($body['recipe_id'], $body['name'], $body['ingredients'], $body['output_item'], $body['output_quantity'])
        || !is_string($body['recipe_id']) || $body['recipe_id'] === ''
        || !is_string($body['name']) || $body['name'] === ''
        || !is_array($body['ingredients'])
        || !is_string($body['output_item']) || !in_array($body['output_item'], VALID_INVENTORY_ITEM_IDS, true)
        || !is_valid_int_range($body['output_quantity'], 1, PHP_INT_MAX)) {
        return null;
    }

    if (count($body['ingredients']) === 0) {
        return null;
    }

    $ingredients = [];
    foreach ($body['ingredients'] as $itemId => $quantity) {
        if (!is_string($itemId) || !in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
            return null;
        }
        if (!is_valid_int_range($quantity, 1, PHP_INT_MAX)) {
            return null;
        }
        $ingredients[$itemId] = (int)$quantity;
    }

    return [
        'recipe_id' => $body['recipe_id'],
        'name' => $body['name'],
        'ingredients' => $ingredients,
        'output_item' => $body['output_item'],
        'output_quantity' => (int)$body['output_quantity'],
    ];
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/recipes$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create recipes');
    }

    $body = read_json_body();
    $validated = validate_recipe_payload($body);
    if ($validated === null) {
        bad_request();
    }
    $recipeId = $validated['recipe_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?');
    $stmt->execute([$campaignId, $recipeId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('recipe id already exists in this campaign');
    }

    $recipe = [
        'recipe_id' => $recipeId,
        'name' => $validated['name'],
        'ingredients' => $validated['ingredients'],
        'output_item' => $validated['output_item'],
        'output_quantity' => $validated['output_quantity'],
    ];

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_recipes WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_recipes (campaign_id, recipe_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $recipeId, $seq, json_encode($recipe)]);

    send_json($recipe, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/recipes$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_actor($db);

    require_play_campaign($db, $campaignId);

    $stmt = $db->prepare('SELECT data FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $recipes = [];
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $recipes[] = json_decode($row['data'], true);
    }

    send_json(['recipes' => $recipes], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/recipes/([^/]+)/craft$#', $path, $pm)) {
    $campaignId = $pm[1];
    $recipeId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    if ($actor['username'] === $campaign['owner']) {
        forbidden('only a player may craft');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?');
    $stmt->execute([$campaignId, $recipeId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('recipe not found');
    }
    $recipe = json_decode($row['data'], true);

    $body = read_json_body();
    if ($body === null || !isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
        bad_request();
    }
    $charId = $body['character_id'];

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$username, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $username);
    if ($actor['username'] !== $owner) {
        forbidden('only the character owner may craft for this character');
    }

    $items = $member['inventory_items'] ?? [];
    foreach ($recipe['ingredients'] as $itemId => $quantity) {
        if ((int)($items[$itemId] ?? 0) < $quantity) {
            conflict('insufficient ingredients');
        }
    }

    foreach ($recipe['ingredients'] as $itemId => $quantity) {
        $remaining = (int)($items[$itemId] ?? 0) - $quantity;
        if ($remaining > 0) {
            $items[$itemId] = $remaining;
        } else {
            unset($items[$itemId]);
        }
    }

    $outputItem = $recipe['output_item'];
    $items[$outputItem] = (int)($items[$outputItem] ?? 0) + $recipe['output_quantity'];
    $member['inventory_items'] = $items;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $username]);

    send_json([
        'character_id' => $charId,
        'recipe_id' => $recipeId,
        'output_item' => $recipe['output_item'],
        'output_quantity' => $recipe['output_quantity'],
    ], 201);
}

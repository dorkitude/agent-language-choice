<?php
declare(strict_types=1);

// Routes: Play (settlement-scoped DM-managed shops with deterministic stock,
// prices, and player buy/sell operations against campaign inventory/gold)
// ---------------------------------------------------------------------------

function require_play_shop(PDO $db, string $campaignId, string $settlementId, string $shopId): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
    $stmt->execute([$campaignId, $settlementId, $shopId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('shop not found');
    }
    return json_decode($row['data'], true);
}

function validate_shop_payload($body): ?array {
    if ($body === null
        || !isset($body['shop_id'], $body['name'], $body['stock'], $body['buy_price'], $body['sell_price'])
        || !is_string($body['shop_id']) || $body['shop_id'] === ''
        || !is_string($body['name']) || $body['name'] === ''
        || !is_array($body['stock'])
        || !is_valid_int_range($body['buy_price'], 1, PHP_INT_MAX)
        || !is_valid_int_range($body['sell_price'], 0, PHP_INT_MAX)) {
        return null;
    }

    if (count($body['stock']) === 0) {
        return null;
    }

    $stock = [];
    foreach ($body['stock'] as $itemId => $quantity) {
        if (!is_string($itemId) || !in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
            return null;
        }
        if (!is_valid_int_range($quantity, 1, PHP_INT_MAX)) {
            return null;
        }
        $stock[$itemId] = (int)$quantity;
    }

    return [
        'shop_id' => $body['shop_id'],
        'name' => $body['name'],
        'stock' => $stock,
        'buy_price' => (int)$body['buy_price'],
        'sell_price' => (int)$body['sell_price'],
    ];
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops$#', $path, $pm)) {
    $campaignId = $pm[1];
    $settlementId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create shops');
    }

    require_play_settlement($db, $campaignId, $settlementId);

    $body = read_json_body();
    $validated = validate_shop_payload($body);
    if ($validated === null) {
        bad_request();
    }
    $shopId = $validated['shop_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
    $stmt->execute([$campaignId, $settlementId, $shopId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('shop id already exists in this settlement');
    }

    $shop = [
        'shop_id' => $shopId,
        'name' => $validated['name'],
        'stock' => $validated['stock'],
        'buy_price' => $validated['buy_price'],
        'sell_price' => $validated['sell_price'],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $settlementId, $shopId, json_encode($shop)]);

    send_json($shop, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $settlementId = $pm[2];
    $shopId = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    $isDm = $actor['username'] === $campaign['owner'];

    if (!$isDm) {
        $stmt = $db->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        $ownCharacterId = $stmt->fetchColumn();
        if ($ownCharacterId === false) {
            forbidden('only the owner or a party member may view shops');
        }

        $settlement = require_play_settlement($db, $campaignId, $settlementId);
        if (!in_array($ownCharacterId, $settlement['discovered_by'], true)) {
            not_found('shop not found');
        }
    } else {
        require_play_settlement($db, $campaignId, $settlementId);
    }

    $shop = require_play_shop($db, $campaignId, $settlementId, $shopId);
    send_json($shop, 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/buy$#', $path, $pm)) {
    $campaignId = $pm[1];
    $settlementId = $pm[2];
    $shopId = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    if ($actor['username'] === $campaign['owner']) {
        forbidden('only a player may buy from a shop');
    }

    require_play_settlement($db, $campaignId, $settlementId);
    $shop = require_play_shop($db, $campaignId, $settlementId, $shopId);

    $body = read_json_body();
    if ($body === null || !isset($body['character_id'], $body['item_id'], $body['quantity'])
        || !is_string($body['character_id']) || $body['character_id'] === ''
        || !is_string($body['item_id'])
        || !is_valid_int_range($body['quantity'], 1, PHP_INT_MAX)) {
        bad_request();
    }
    $charId = $body['character_id'];
    $itemId = $body['item_id'];
    $quantity = (int)$body['quantity'];

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$username, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $username);
    if ($actor['username'] !== $owner) {
        forbidden('only the character owner may buy for this character');
    }

    if (!in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
        bad_request('invalid item id');
    }

    $stock = (int)($shop['stock'][$itemId] ?? 0);
    $gold = (int)($member['gold'] ?? 10);
    $cost = $shop['buy_price'] * $quantity;

    if ($stock < $quantity || $gold < $cost) {
        conflict('insufficient stock or funds');
    }

    $stockAfter = $stock - $quantity;
    $shop['stock'][$itemId] = $stockAfter;

    $goldAfter = $gold - $cost;
    $member['gold'] = $goldAfter;

    $items = $member['inventory_items'] ?? [];
    $items[$itemId] = (int)($items[$itemId] ?? 0) + $quantity;
    $member['inventory_items'] = $items;

    $db->beginTransaction();
    try {
        $stmt = $db->prepare('UPDATE play_campaign_shops SET data = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
        $stmt->execute([json_encode($shop), $campaignId, $settlementId, $shopId]);

        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($member), $campaignId, $username]);

        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }

    send_json([
        'character_id' => $charId,
        'item_id' => $itemId,
        'quantity' => $quantity,
        'gold' => $goldAfter,
        'stock' => $stockAfter,
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/sell$#', $path, $pm)) {
    $campaignId = $pm[1];
    $settlementId = $pm[2];
    $shopId = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    if ($actor['username'] === $campaign['owner']) {
        forbidden('only a player may sell to a shop');
    }

    require_play_settlement($db, $campaignId, $settlementId);
    $shop = require_play_shop($db, $campaignId, $settlementId, $shopId);

    $body = read_json_body();
    if ($body === null || !isset($body['character_id'], $body['item_id'], $body['quantity'])
        || !is_string($body['character_id']) || $body['character_id'] === ''
        || !is_string($body['item_id'])
        || !is_valid_int_range($body['quantity'], 1, PHP_INT_MAX)) {
        bad_request();
    }
    $charId = $body['character_id'];
    $itemId = $body['item_id'];
    $quantity = (int)$body['quantity'];

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$username, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $username);
    if ($actor['username'] !== $owner) {
        forbidden('only the character owner may sell for this character');
    }

    if (!in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
        bad_request('invalid item id');
    }

    $items = $member['inventory_items'] ?? [];
    $held = (int)($items[$itemId] ?? 0);

    if ($held < $quantity) {
        conflict('insufficient inventory');
    }

    $heldAfter = $held - $quantity;
    if ($heldAfter > 0) {
        $items[$itemId] = $heldAfter;
    } else {
        unset($items[$itemId]);
    }
    $member['inventory_items'] = $items;

    $goldAfter = (int)($member['gold'] ?? 10) + $shop['sell_price'] * $quantity;
    $member['gold'] = $goldAfter;

    $stockAfter = (int)($shop['stock'][$itemId] ?? 0) + $quantity;
    $shop['stock'][$itemId] = $stockAfter;

    $db->beginTransaction();
    try {
        $stmt = $db->prepare('UPDATE play_campaign_shops SET data = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
        $stmt->execute([json_encode($shop), $campaignId, $settlementId, $shopId]);

        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($member), $campaignId, $username]);

        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }

    send_json([
        'character_id' => $charId,
        'item_id' => $itemId,
        'quantity' => $quantity,
        'gold' => $goldAfter,
        'stock' => $stockAfter,
    ], 200);
}

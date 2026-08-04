<?php
declare(strict_types=1);

// Campaign helpers shared by every /v1/campaigns/{id}/... route below.
// ---------------------------------------------------------------------------

// Sends 404 and exits if the campaign doesn't exist; otherwise returns
// normally. Used by sub-resource routes that only need the existence check
// (the campaign's own fields aren't part of the response).
function require_campaign_exists(PDO $db, string $campaignId): void {
    $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        not_found('campaign not found');
    }
}

// Fetches and decodes a campaign's stored data, or returns null if absent.
function load_campaign(PDO $db, string $campaignId): ?array {
    $stmt = $db->prepare('SELECT data FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row === false ? null : json_decode($row['data'], true);
}

// ---------------------------------------------------------------------------
// Routes: Campaigns (roster + event log)
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/campaigns') {
    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'], $body['dm'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name']) || !is_string($body['dm'])) {
        bad_request();
    }
    $id = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('campaign already exists');
    }

    $campaign = [
        'id' => $id,
        'name' => $body['name'],
        'dm' => $body['dm'],
    ];

    $stmt = $db->prepare('INSERT INTO campaigns (id, data) VALUES (?, ?)');
    $stmt->execute([$id, json_encode($campaign)]);

    send_json($campaign, 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/characters$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'], $body['level'], $body['class'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name']) || !is_valid_int_range($body['level'], 1, 20)
        || !is_string($body['class'])) {
        bad_request();
    }

    $charId = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $charId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('character already exists');
    }

    $character = [
        'id' => $charId,
        'name' => $body['name'],
        'level' => (int)$body['level'],
        'class' => $body['class'],
    ];

    $stmt = $db->prepare('INSERT INTO campaign_characters (campaign_id, id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $charId, json_encode($character)]);

    send_json($character, 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/events$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['kind'], $body['summary'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['kind']) || !is_string($body['summary'])) {
        bad_request();
    }

    $evtId = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $evtId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('event already exists');
    }

    $event = [
        'id' => $evtId,
        'kind' => $body['kind'],
        'summary' => $body['summary'],
    ];

    $stmt = $db->prepare('INSERT INTO campaign_events (campaign_id, id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $evtId, json_encode($event)]);

    send_json([
        'id' => $event['id'],
        'kind' => $event['kind'],
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/state$#', $path, $pm)) {
    $campaignId = $pm[1];
    $campaign = load_campaign($db, $campaignId);
    if ($campaign === null) {
        not_found('campaign not found');
    }

    $characters = [];
    $stmt = $db->prepare('SELECT data FROM campaign_characters WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $charRow) {
        $characters[] = json_decode($charRow['data'], true);
    }

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $logCount = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    send_json([
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => $logCount,
    ]);
}

const QUEST_STATUSES = ['active', 'completed', 'blocked'];

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/quests$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['title'], $body['status'], $body['milestones'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['title'])
        || !is_string($body['status']) || !in_array($body['status'], QUEST_STATUSES, true)
        || !is_array($body['milestones'])) {
        bad_request();
    }
    foreach ($body['milestones'] as $milestone) {
        if (!is_string($milestone)) {
            bad_request();
        }
    }

    $questId = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaign_quests WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $questId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('quest already exists');
    }

    $quest = [
        'id' => $questId,
        'title' => $body['title'],
        'status' => $body['status'],
        'milestones' => array_values($body['milestones']),
        'completed' => [],
    ];

    $stmt = $db->prepare('INSERT INTO campaign_quests (campaign_id, id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $questId, json_encode($quest)]);

    send_json([
        'id' => $quest['id'],
        'title' => $quest['title'],
        'status' => $quest['status'],
        'milestones_total' => count($quest['milestones']),
        'milestones_done' => count($quest['completed']),
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/quests/([^/]+)/progress$#', $path, $pm)) {
    $campaignId = $pm[1];
    $questId = $pm[2];
    $stmt = $db->prepare('SELECT data FROM campaign_quests WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $questId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('quest not found');
    }
    $quest = json_decode($row['data'], true);

    $body = read_json_body();
    if ($body === null || !isset($body['completed']) || !is_array($body['completed'])) {
        bad_request();
    }
    foreach ($body['completed'] as $milestone) {
        if (!is_string($milestone)) {
            bad_request();
        }
    }

    $completed = $quest['completed'];
    foreach ($body['completed'] as $milestone) {
        if (in_array($milestone, $quest['milestones'], true) && !in_array($milestone, $completed, true)) {
            $completed[] = $milestone;
        }
    }
    $quest['completed'] = $completed;

    $stmt = $db->prepare('UPDATE campaign_quests SET data = ? WHERE campaign_id = ? AND id = ?');
    $stmt->execute([json_encode($quest), $campaignId, $questId]);

    send_json([
        'id' => $quest['id'],
        'status' => $quest['status'],
        'milestones_total' => count($quest['milestones']),
        'milestones_done' => count($quest['completed']),
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/quests/summary$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $counts = ['active' => 0, 'completed' => 0, 'blocked' => 0];
    $stmt = $db->prepare('SELECT data FROM campaign_quests WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $questRow) {
        $quest = json_decode($questRow['data'], true);
        if (isset($counts[$quest['status']])) {
            $counts[$quest['status']]++;
        }
    }

    send_json([
        'campaign_id' => $campaignId,
        'active' => $counts['active'],
        'completed' => $counts['completed'],
        'blocked' => $counts['blocked'],
    ]);
}

// ---------------------------------------------------------------------------
// Routes: NPCs and factions
// ---------------------------------------------------------------------------

const FACTION_STANCES = ['friendly', 'neutral', 'hostile'];

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/factions$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'], $body['stance'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name'])
        || !is_string($body['stance']) || !in_array($body['stance'], FACTION_STANCES, true)) {
        bad_request();
    }

    $factionId = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaign_factions WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $factionId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('faction already exists');
    }

    $faction = [
        'id' => $factionId,
        'name' => $body['name'],
        'stance' => $body['stance'],
    ];

    $stmt = $db->prepare('INSERT INTO campaign_factions (campaign_id, id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $factionId, json_encode($faction)]);

    send_json($faction, 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/npcs$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'], $body['faction_id'], $body['disposition'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name'])
        || !is_string($body['faction_id']) || $body['faction_id'] === ''
        || !is_valid_int_range($body['disposition'], -2147483648, 2147483647)) {
        bad_request();
    }

    $factionId = $body['faction_id'];
    $stmt = $db->prepare('SELECT id FROM campaign_factions WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $factionId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        bad_request('unknown faction_id');
    }

    $npcId = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaign_npcs WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $npcId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('npc already exists');
    }

    $npc = [
        'id' => $npcId,
        'name' => $body['name'],
        'faction_id' => $factionId,
        'disposition' => (int)$body['disposition'],
    ];

    $stmt = $db->prepare('INSERT INTO campaign_npcs (campaign_id, id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $npcId, json_encode($npc)]);

    send_json($npc, 201);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/relationships$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_factions WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $factionCount = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $npcCount = 0;
    $friendlyCount = 0;
    $stmt = $db->prepare('SELECT data FROM campaign_npcs WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $npcRow) {
        $npc = json_decode($npcRow['data'], true);
        $npcCount++;
        if ($npc['disposition'] > 0) {
            $friendlyCount++;
        }
    }

    send_json([
        'campaign_id' => $campaignId,
        'factions' => $factionCount,
        'npcs' => $npcCount,
        'friendly_npcs' => $friendlyCount,
    ]);
}

// ---------------------------------------------------------------------------
// Routes: campaign inventory and equipment
// ---------------------------------------------------------------------------

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/inventory$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['item_slug'], $body['quantity'], $body['owner'])
        || !is_valid_slug($body['item_slug'])
        || !is_valid_int_range($body['quantity'], 1, 1000000)
        || !is_string($body['owner']) || $body['owner'] === '') {
        bad_request();
    }

    $itemSlug = $body['item_slug'];
    $owner = $body['owner'];
    $quantity = (int)$body['quantity'];

    $stmt = $db->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
    $stmt->execute([$campaignId, $itemSlug, $owner]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row !== false) {
        $newQuantity = (int)$row['quantity'] + $quantity;
        $stmt = $db->prepare('UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$newQuantity, $campaignId, $itemSlug, $owner]);
    } else {
        $stmt = $db->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $itemSlug, $owner, $quantity]);
    }

    send_json([
        'item_slug' => $itemSlug,
        'quantity' => $quantity,
        'owner' => $owner,
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/characters/([^/]+)/equipment$#', $path, $pm)) {
    $campaignId = $pm[1];
    $characterId = $pm[2];
    require_campaign_exists($db, $campaignId);

    $stmt = $db->prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $characterId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        not_found('character not found');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['item_slug'], $body['quantity'])
        || !is_valid_slug($body['item_slug'])
        || !is_valid_int_range($body['quantity'], 1, 1000000)) {
        bad_request();
    }

    $itemSlug = $body['item_slug'];
    $quantity = (int)$body['quantity'];

    $stmt = $db->prepare('SELECT quantity FROM campaign_equipment WHERE campaign_id = ? AND character_id = ? AND item_slug = ?');
    $stmt->execute([$campaignId, $characterId, $itemSlug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row !== false) {
        $newQuantity = (int)$row['quantity'] + $quantity;
        $stmt = $db->prepare('UPDATE campaign_equipment SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_slug = ?');
        $stmt->execute([$newQuantity, $campaignId, $characterId, $itemSlug]);
    } else {
        $stmt = $db->prepare('INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $characterId, $itemSlug, $quantity]);
    }

    send_json([
        'character_id' => $characterId,
        'item_slug' => $itemSlug,
        'quantity' => $quantity,
    ], 200);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/inventory/summary$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_inventory WHERE campaign_id = ? AND owner = ?');
    $stmt->execute([$campaignId, 'party']);
    $partyItems = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_equipment WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $assignedItems = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND owner = ? AND item_slug = ?');
    $stmt->execute([$campaignId, 'party', 'healing-potion']);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    $partyPotions = $row !== false ? (int)$row['quantity'] : 0;

    $stmt = $db->prepare('SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_equipment WHERE campaign_id = ? AND item_slug = ?');
    $stmt->execute([$campaignId, 'healing-potion']);
    $assignedPotions = (int)$stmt->fetch(PDO::FETCH_ASSOC)['total'];

    send_json([
        'campaign_id' => $campaignId,
        'party_items' => $partyItems,
        'assigned_items' => $assignedItems,
        'healing_potions_available' => max(0, $partyPotions - $assignedPotions),
    ]);
}

// ---------------------------------------------------------------------------

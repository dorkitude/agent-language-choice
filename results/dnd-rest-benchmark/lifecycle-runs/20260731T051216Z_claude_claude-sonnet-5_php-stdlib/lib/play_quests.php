<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped quest records gated by prerequisite quests)
// ---------------------------------------------------------------------------

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/quests$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create quests');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['quest_id'], $body['title'])
        || !is_string($body['quest_id']) || $body['quest_id'] === ''
        || !is_string($body['title']) || $body['title'] === '') {
        bad_request();
    }
    $questId = $body['quest_id'];
    $title = $body['title'];

    $dependsOn = $body['depends_on'] ?? [];
    if (!is_array($dependsOn) || !array_is_list($dependsOn)) {
        bad_request('depends_on must be an array of quest ids');
    }
    foreach ($dependsOn as $dep) {
        if (!is_string($dep) || $dep === '') {
            bad_request('depends_on must be an array of quest ids');
        }
    }
    if (count($dependsOn) !== count(array_unique($dependsOn))) {
        bad_request('depends_on must contain unique quest ids');
    }
    if (in_array($questId, $dependsOn, true)) {
        bad_request('depends_on cannot include the quest\'s own id');
    }
    foreach ($dependsOn as $dep) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
        $stmt->execute([$campaignId, $dep]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            bad_request('depends_on must name existing quests in this campaign');
        }
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
    $stmt->execute([$campaignId, $questId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('quest id already exists in this campaign');
    }

    $quest = [
        'quest_id' => $questId,
        'title' => $title,
        'depends_on' => array_values($dependsOn),
        'state' => 'locked',
    ];

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_quests WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_quests (campaign_id, quest_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $questId, $seq, json_encode($quest)]);

    send_json($quest, 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/quests/([^/]+)/state$#', $path, $pm)) {
    $campaignId = $pm[1];
    $questId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may change quest state');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
    $stmt->execute([$campaignId, $questId]);
    $row = $stmt->fetchColumn();
    if ($row === false) {
        not_found('quest not found');
    }
    $quest = json_decode($row, true);

    $body = read_json_body();
    if ($body === null || !isset($body['state']) || !is_string($body['state'])) {
        bad_request();
    }
    $newState = $body['state'];
    if (!in_array($newState, ['active', 'completed'], true)) {
        bad_request('state must be active or completed');
    }

    $currentState = $quest['state'];
    if ($currentState === 'locked' && $newState === 'active') {
        foreach ($quest['depends_on'] as $dep) {
            $stmt = $db->prepare('SELECT data FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
            $stmt->execute([$campaignId, $dep]);
            $depRow = $stmt->fetchColumn();
            $depQuest = $depRow === false ? null : json_decode($depRow, true);
            if ($depQuest === null || $depQuest['state'] !== 'completed') {
                conflict('all dependencies must be completed before activation');
            }
        }
    } elseif ($currentState === 'active' && $newState === 'completed') {
        // allowed
    } else {
        conflict('invalid state transition');
    }

    $quest['state'] = $newState;
    $stmt = $db->prepare('UPDATE play_campaign_quests SET data = ? WHERE campaign_id = ? AND quest_id = ?');
    $stmt->execute([json_encode($quest), $campaignId, $questId]);

    send_json($quest, 200);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards$#', $path, $pm)) {
    $campaignId = $pm[1];
    $questId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may configure quest rewards');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
    $stmt->execute([$campaignId, $questId]);
    $row = $stmt->fetchColumn();
    if ($row === false) {
        not_found('quest not found');
    }
    $quest = json_decode($row, true);

    $body = read_json_body();
    if ($body === null || !isset($body['xp'], $body['items'])
        || !is_valid_int_range($body['xp'], 0, PHP_INT_MAX)
        || !is_array($body['items'])
        || ($body['items'] !== [] && array_is_list($body['items']))) {
        bad_request();
    }
    $xp = (int)$body['xp'];
    $items = $body['items'];
    foreach ($items as $itemId => $quantity) {
        if (!is_string($itemId) || !in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)
            || !is_valid_int_range($quantity, 1, PHP_INT_MAX)) {
            bad_request('items must map valid catalog item ids to positive integer quantities');
        }
    }

    if (!in_array($quest['state'], ['locked', 'active'], true)) {
        conflict('quest rewards cannot be configured once completed');
    }

    $quest['rewards'] = ['xp' => $xp, 'items' => (object)$items];
    $stmt = $db->prepare('UPDATE play_campaign_quests SET data = ? WHERE campaign_id = ? AND quest_id = ?');
    $stmt->execute([json_encode($quest), $campaignId, $questId]);

    send_json($quest, 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards/award$#', $path, $pm)) {
    $campaignId = $pm[1];
    $questId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may award quest rewards');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
    $stmt->execute([$campaignId, $questId]);
    $row = $stmt->fetchColumn();
    if ($row === false) {
        not_found('quest not found');
    }
    $quest = json_decode($row, true);

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_quest_awards WHERE campaign_id = ? AND quest_id = ?');
    $stmt->execute([$campaignId, $questId]);
    $alreadyAwarded = $stmt->fetch(PDO::FETCH_ASSOC) !== false;

    if ($quest['state'] !== 'completed' || !isset($quest['rewards']) || $alreadyAwarded) {
        conflict('quest rewards are not ready to award');
    }

    $xp = (int)$quest['rewards']['xp'];
    $items = (array)$quest['rewards']['items'];

    $stmt = $db->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $charIds = $stmt->fetchAll(PDO::FETCH_COLUMN);

    $db->beginTransaction();
    try {
        foreach ($charIds as $charId) {
            $stmt = $db->prepare('SELECT xp, items FROM play_campaign_character_rewards WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$campaignId, $charId]);
            $existing = $stmt->fetch(PDO::FETCH_ASSOC);
            $curXp = $existing === false ? 0 : (int)$existing['xp'];
            $curItems = $existing === false ? [] : json_decode($existing['items'], true);

            $curXp += $xp;
            foreach ($items as $itemId => $quantity) {
                $curItems[$itemId] = (int)($curItems[$itemId] ?? 0) + (int)$quantity;
            }

            $stmt = $db->prepare('INSERT INTO play_campaign_character_rewards (campaign_id, character_id, xp, items) VALUES (?, ?, ?, ?)
                ON CONFLICT(campaign_id, character_id) DO UPDATE SET xp = excluded.xp, items = excluded.items');
            $stmt->execute([$campaignId, $charId, $curXp, json_encode($curItems)]);

            $stmt = $db->prepare('SELECT username, data FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
            $stmt->execute([$campaignId, $charId]);
            $memberRow = $stmt->fetch(PDO::FETCH_ASSOC);
            if ($memberRow !== false) {
                $member = json_decode($memberRow['data'], true);
                $inventoryItems = $member['inventory_items'] ?? [];
                foreach ($items as $itemId => $quantity) {
                    $inventoryItems[$itemId] = (int)($inventoryItems[$itemId] ?? 0) + (int)$quantity;
                }
                $member['inventory_items'] = $inventoryItems;

                $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
                $stmt->execute([json_encode($member), $campaignId, $memberRow['username']]);
            }
        }

        $stmt = $db->prepare('INSERT INTO play_campaign_quest_awards (campaign_id, quest_id) VALUES (?, ?)');
        $stmt->execute([$campaignId, $questId]);

        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }

    send_json([
        'quest_id' => $questId,
        'awarded' => true,
        'xp' => $xp,
        'items' => empty($items) ? new stdClass() : $items,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/rewards$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isDm = $actor['username'] === $campaign['owner'];
    if (!$isDm && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view character rewards');
    }

    if (find_play_character($db, $campaignId, $charId) === null) {
        not_found('character not found');
    }

    $stmt = $db->prepare('SELECT xp, items FROM play_campaign_character_rewards WHERE campaign_id = ? AND character_id = ?');
    $stmt->execute([$campaignId, $charId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);

    $xp = $row === false ? 0 : (int)$row['xp'];
    $items = $row === false ? [] : json_decode($row['items'], true);

    send_json([
        'character_id' => $charId,
        'xp' => $xp,
        'items' => empty($items) ? new stdClass() : $items,
    ], 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/quests$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isDm = $actor['username'] === $campaign['owner'];
    if (!$isDm && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view quests');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_quests WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_COLUMN);
    $quests = array_map(fn($row) => json_decode($row, true), $rows);

    send_json(['quests' => $quests], 200);
}

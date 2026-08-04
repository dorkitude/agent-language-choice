<?php
declare(strict_types=1);

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may create an encounter');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name']) || $body['name'] === '') {
        bad_request();
    }
    $encounterId = $body['id'];

    if (($campaign['encounter'] ?? null) !== null && $campaign['encounter']['status'] === 'active') {
        conflict('campaign is already in combat');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (isset($encounters[$encounterId])) {
        conflict('encounter id already exists');
    }

    $encounter = [
        'id' => $encounterId,
        'name' => $body['name'],
        'status' => 'active',
        'combatants' => [],
    ];

    $campaign['pre_combat_actor'] = $campaign['current_actor'] ?? null;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    $campaign['encounter'] = $encounter;

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($encounter, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may add a monster');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $body = read_json_body();
    if ($body === null || !isset($body['monster_id'], $body['name'], $body['hp_max'], $body['initiative'])
        || !is_string($body['monster_id']) || $body['monster_id'] === ''
        || !is_string($body['name']) || $body['name'] === ''
        || !is_int($body['hp_max'])
        || !is_int($body['initiative'])) {
        bad_request();
    }
    $monsterId = $body['monster_id'];

    $monsters = $encounter['monsters'] ?? [];
    if (isset($monsters[$monsterId])) {
        conflict('monster id already exists');
    }

    $monster = [
        'monster_id' => $monsterId,
        'name' => $body['name'],
        'hp_max' => $body['hp_max'],
        'initiative' => $body['initiative'],
        'hp_current' => $body['hp_max'],
    ];

    $monsters[$monsterId] = $monster;
    $encounter['monsters'] = $monsters;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($monster, 201);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $monsterId = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may remove a monster');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $monsters = $encounter['monsters'] ?? [];
    if (!isset($monsters[$monsterId])) {
        not_found('monster not found');
    }

    unset($monsters[$monsterId]);
    $encounter['monsters'] = $monsters;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json(['removed' => $monsterId], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may bind a combatant');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $body = read_json_body();
    if ($body === null || !isset($body['member'], $body['initiative'])
        || !is_string($body['member']) || $body['member'] === ''
        || !is_int($body['initiative'])) {
        bad_request();
    }
    $memberName = $body['member'];

    $stmt = $db->prepare('SELECT data FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $memberName]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        bad_request('unknown member');
    }
    $member = json_decode($row['data'], true);

    $combatants = $encounter['combatants'] ?? [];
    if (isset($combatants[$memberName])) {
        conflict('member already bound to this encounter');
    }

    $combatant = [
        'member' => $memberName,
        'character_id' => $member['character_id'],
        'name' => $member['name'],
        'initiative' => $body['initiative'],
    ];

    $combatants[$memberName] = $combatant;
    $encounter['combatants'] = $combatants;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($combatant, 201);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $memberName = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may unbind a combatant');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $combatants = $encounter['combatants'] ?? [];
    if (!isset($combatants[$memberName])) {
        not_found('combatant not found');
    }

    unset($combatants[$memberName]);
    $encounter['combatants'] = $combatants;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json(['removed' => $memberName], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/damage$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may apply damage');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $body = read_json_body();
    if ($body === null || !isset($body['target'], $body['amount'])
        || !is_string($body['target']) || $body['target'] === ''
        || !is_int($body['amount']) || $body['amount'] < 0) {
        bad_request();
    }
    $target = $body['target'];
    $amount = $body['amount'];

    $result = apply_encounter_hp_change($db, $campaignId, $encounter, $target, -$amount);
    if ($result === null) {
        not_found('target not found');
    }
    [$encounter, $hpBefore, $hpAfter] = $result;

    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'target' => $target,
        'hp_before' => $hpBefore,
        'hp_after' => $hpAfter,
        'damage' => $amount,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/heal$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may apply healing');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $body = read_json_body();
    if ($body === null || !isset($body['target'], $body['amount'])
        || !is_string($body['target']) || $body['target'] === ''
        || !is_int($body['amount']) || $body['amount'] < 0) {
        bad_request();
    }
    $target = $body['target'];
    $amount = $body['amount'];

    $result = apply_encounter_hp_change($db, $campaignId, $encounter, $target, $amount);
    if ($result === null) {
        not_found('target not found');
    }
    [$encounter, $hpBefore, $hpAfter] = $result;

    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'target' => $target,
        'hp_before' => $hpBefore,
        'hp_after' => $hpAfter,
        'healing' => $amount,
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this encounter turn');
        }
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $order = build_encounter_turn_order($encounter);
    if (count($order) === 0) {
        not_found('encounter has no combatants');
    }

    $round = $encounter['round'] ?? 1;
    $turnIndex = ($encounter['turn_index'] ?? 0) % count($order);

    send_json([
        'round' => $round,
        'turn_index' => $turnIndex,
        'active' => turn_order_public($order[$turnIndex]),
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/advance$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $order = build_encounter_turn_order($encounter);
    if (count($order) === 0) {
        not_found('encounter has no combatants');
    }

    $round = $encounter['round'] ?? 1;
    $turnIndex = ($encounter['turn_index'] ?? 0) % count($order);
    $current = $order[$turnIndex];

    $isOwner = $actor['username'] === $campaign['owner'];
    $isCurrentCombatant = $current['kind'] === 'player' && $current['member'] === $actor['username'];
    if (!$isOwner && !$isCurrentCombatant) {
        conflict('only the owner or the current combatant may advance the turn');
    }

    $turnIndex++;
    if ($turnIndex >= count($order)) {
        $turnIndex = 0;
        $round++;
    }

    $encounter['round'] = $round;
    $encounter['turn_index'] = $turnIndex;
    $encounter = decrement_encounter_conditions($encounter, $order[$turnIndex]['target']);
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'round' => $round,
        'turn_index' => $turnIndex,
        'active' => turn_order_public($order[$turnIndex]),
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/conditions$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may apply a condition');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $body = read_json_body();
    if ($body === null || !isset($body['target'], $body['condition'], $body['duration_rounds'])
        || !is_string($body['target']) || $body['target'] === ''
        || !is_string($body['condition']) || $body['condition'] === ''
        || !is_valid_int_range($body['duration_rounds'], 1, PHP_INT_MAX)) {
        bad_request();
    }
    $target = $body['target'];

    if (!encounter_target_exists($encounter, $target)) {
        not_found('target not found');
    }

    $conditions = $encounter['conditions'] ?? [];
    if (!isset($conditions[$target])) {
        $conditions[$target] = [];
    }
    $conditions[$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];
    $encounter['conditions'] = $conditions;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'target' => $target,
        'conditions' => encounter_conditions_public($encounter, $target),
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/status$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this encounter status');
        }
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $order = build_encounter_turn_order($encounter);

    $round = $encounter['round'] ?? 1;
    $turnIndex = count($order) > 0 ? ($encounter['turn_index'] ?? 0) % count($order) : 0;

    send_json([
        'round' => $round,
        'turn_index' => $turnIndex,
        'active' => count($order) > 0 ? turn_order_public($order[$turnIndex]) : null,
        'order' => array_map('turn_order_public', $order),
        'conditions' => encounter_conditions_map($encounter),
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/actions$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $body = read_json_body();
    $validTypes = ['attack', 'help', 'dodge', 'ready'];
    if ($body === null || !isset($body['type']) || !is_string($body['type'])
        || !in_array($body['type'], $validTypes, true)) {
        bad_request('invalid action type');
    }
    if (isset($body['target']) && !is_string($body['target'])) {
        bad_request();
    }
    if (isset($body['text']) && !is_string($body['text'])) {
        bad_request();
    }

    $order = build_encounter_turn_order($encounter);
    if (count($order) === 0) {
        not_found('encounter has no combatants');
    }

    $turnIndex = ($encounter['turn_index'] ?? 0) % count($order);
    $current = $order[$turnIndex];

    $isCurrentCombatant = $current['kind'] === 'player' && $current['member'] === $actor['username'];
    if (!$isCurrentCombatant) {
        conflict('only the current combatant may submit an action');
    }

    $sequence = next_narration_sequence($db, $campaignId);

    $event = [
        'sequence' => $sequence,
        'kind' => 'combat_action',
        'actor' => $actor['username'],
        'type' => $body['type'],
        'target' => $body['target'] ?? null,
        'text' => $body['text'] ?? null,
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, json_encode($event)]);

    send_json($event, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/delay$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $order = build_encounter_turn_order($encounter);
    if (count($order) === 0) {
        not_found('encounter has no combatants');
    }

    $turnIndex = ($encounter['turn_index'] ?? 0) % count($order);
    $current = $order[$turnIndex];

    $isOwner = $actor['username'] === $campaign['owner'];
    $isCurrentCombatant = $current['kind'] === 'player' && $current['member'] === $actor['username'];
    if (!$isOwner && !$isCurrentCombatant) {
        conflict('only the owner or the current combatant may delay the turn');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['new_index']) || !is_valid_int_range($body['new_index'], 0, count($order) - 1)) {
        bad_request('invalid new_index');
    }
    $newIndex = (int)$body['new_index'];

    $targets = array_map(function ($e) {
        return $e['target'];
    }, $order);
    $currentTarget = $current['target'];
    $remaining = array_values(array_filter($targets, function ($t) use ($currentTarget) {
        return $t !== $currentTarget;
    }));
    array_splice($remaining, $newIndex, 0, [$currentTarget]);

    $encounter['turn_order'] = $remaining;
    $encounter['turn_index'] = $newIndex;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    $newOrder = build_encounter_turn_order($encounter);

    send_json([
        'order' => array_map('turn_order_public', $newOrder),
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/ready$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $body = read_json_body();
    if ($body === null || !isset($body['trigger']) || !is_string($body['trigger']) || $body['trigger'] === '') {
        bad_request('invalid trigger');
    }

    $order = build_encounter_turn_order($encounter);
    if (count($order) === 0) {
        not_found('encounter has no combatants');
    }

    $turnIndex = ($encounter['turn_index'] ?? 0) % count($order);
    $current = $order[$turnIndex];

    $isCurrentCombatant = $current['kind'] === 'player' && $current['member'] === $actor['username'];
    if (!$isCurrentCombatant) {
        conflict('only the current combatant may ready an action');
    }

    send_json([
        'actor' => $actor['username'],
        'trigger' => $body['trigger'],
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/rewards$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may award rewards');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    if (isset($encounter['rewards'])) {
        conflict('rewards already awarded for this encounter');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['xp']) || !is_int($body['xp']) || $body['xp'] < 0) {
        bad_request('invalid xp');
    }

    $loot = [];
    if (isset($body['loot'])) {
        if (!is_array($body['loot'])) {
            bad_request('invalid loot');
        }
        foreach ($body['loot'] as $entry) {
            if (!is_array($entry) || !isset($entry['slug'], $entry['quantity'])
                || !is_valid_slug($entry['slug'])
                || !is_int($entry['quantity']) || $entry['quantity'] < 1) {
                bad_request('invalid loot entry');
            }
            $loot[] = [
                'slug' => $entry['slug'],
                'quantity' => $entry['quantity'],
            ];
        }
    }

    $reward = [
        'encounter_id' => $encounterId,
        'xp' => $body['xp'],
        'loot' => $loot,
        'awarded_by' => $actor['username'],
    ];

    $encounter['rewards'] = $reward;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($reward, 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/close$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may close the encounter');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    $encounter['status'] = 'closed';
    $xpAwarded = $encounter['rewards']['xp'] ?? 0;
    $encounters[$encounterId] = $encounter;
    $campaign['encounters'] = $encounters;
    if (($campaign['encounter']['id'] ?? null) === $encounterId) {
        $campaign['encounter'] = $encounter;
    }

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'id' => $encounterId,
        'status' => 'closed',
        'xp_awarded' => $xpAwarded,
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/end$#', $path, $pm)) {
    $campaignId = $pm[1];
    $encounterId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may end the encounter');
    }

    $encounters = $campaign['encounters'] ?? [];
    if (!isset($encounters[$encounterId])) {
        not_found('encounter not found');
    }
    $encounter = $encounters[$encounterId];

    if (!array_key_exists('pre_combat_actor', $campaign)) {
        conflict('campaign is not in combat');
    }

    if ($encounter['status'] === 'active') {
        $encounter['status'] = 'closed';
        $encounters[$encounterId] = $encounter;
        $campaign['encounters'] = $encounters;
        if (($campaign['encounter']['id'] ?? null) === $encounterId) {
            $campaign['encounter'] = $encounter;
        }
    }

    $campaign['current_actor'] = $campaign['pre_combat_actor'] ?? $campaign['owner'];
    unset($campaign['pre_combat_actor']);

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'campaign_id' => $campaign['id'],
        'status' => $campaign['status'],
        'phase' => 'exploration',
        'current_actor' => $campaign['current_actor'],
    ], 200);
}

// ---------------------------------------------------------------------------

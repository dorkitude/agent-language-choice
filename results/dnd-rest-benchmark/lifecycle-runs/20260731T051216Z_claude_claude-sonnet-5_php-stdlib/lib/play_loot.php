<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped loot distribution)
// ---------------------------------------------------------------------------

function require_play_loot(PDO $db, string $campaignId, string $lootId): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
    $stmt->execute([$campaignId, $lootId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('loot not found');
    }
    return json_decode($row['data'], true);
}

function save_play_loot(PDO $db, string $campaignId, string $lootId, array $loot): void {
    $stmt = $db->prepare('UPDATE play_campaign_loot SET data = ? WHERE campaign_id = ? AND loot_id = ?');
    $stmt->execute([json_encode($loot), $campaignId, $lootId]);
}

function is_play_campaign_member(PDO $db, string $campaignId, string $username): bool {
    $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $username]);
    return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/loot$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create loot');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['loot_id'], $body['item_id'], $body['quantity'])
        || !is_string($body['loot_id']) || $body['loot_id'] === ''
        || !is_string($body['item_id'])
        || !is_valid_int_range($body['quantity'], 1, PHP_INT_MAX)) {
        bad_request();
    }
    $lootId = $body['loot_id'];
    $itemId = $body['item_id'];
    $quantity = (int)$body['quantity'];

    if (!in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
        bad_request('invalid item id');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
    $stmt->execute([$campaignId, $lootId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('loot id already exists in this campaign');
    }

    $loot = [
        'loot_id' => $lootId,
        'item_id' => $itemId,
        'quantity' => $quantity,
        'status' => 'open',
        'recipient_character_id' => null,
        'votes' => [],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_loot (campaign_id, loot_id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $lootId, json_encode($loot)]);

    send_json([
        'loot_id' => $lootId,
        'item_id' => $itemId,
        'quantity' => $quantity,
        'status' => 'open',
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/loot/([^/]+)/votes$#', $path, $pm)) {
    $campaignId = $pm[1];
    $lootId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if (!is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only an authenticated campaign player may vote on loot');
    }

    $loot = require_play_loot($db, $campaignId, $lootId);

    $body = read_json_body();
    if ($body === null || !isset($body['recipient_character_id'])
        || !is_string($body['recipient_character_id']) || $body['recipient_character_id'] === '') {
        bad_request();
    }
    $recipientCharId = $body['recipient_character_id'];

    if (find_play_character($db, $campaignId, $recipientCharId) === null) {
        bad_request('recipient must be a character in this campaign');
    }

    $votes = $loot['votes'] ?? [];
    if (isset($votes[$actor['username']])) {
        conflict('this player has already voted on this loot');
    }

    $votes[$actor['username']] = $recipientCharId;
    $loot['votes'] = $votes;
    save_play_loot($db, $campaignId, $lootId, $loot);

    $votesForRecipient = 0;
    foreach ($votes as $v) {
        if ($v === $recipientCharId) {
            $votesForRecipient++;
        }
    }

    send_json([
        'loot_id' => $lootId,
        'voter' => $actor['username'],
        'recipient_character_id' => $recipientCharId,
        'votes_for_recipient' => $votesForRecipient,
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/loot/([^/]+)/assign$#', $path, $pm)) {
    $campaignId = $pm[1];
    $lootId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may assign loot');
    }

    $loot = require_play_loot($db, $campaignId, $lootId);

    if ($loot['status'] !== 'open') {
        conflict('loot is not open for assignment');
    }

    $tally = [];
    foreach (($loot['votes'] ?? []) as $recipientCharId) {
        $tally[$recipientCharId] = ($tally[$recipientCharId] ?? 0) + 1;
    }

    if (count($tally) === 0) {
        conflict('loot has no votes');
    }

    arsort($tally);
    $counts = array_values($tally);
    if (count($counts) > 1 && $counts[0] === $counts[1]) {
        conflict('loot vote is tied');
    }
    $winner = array_key_first($tally);
    $winnerVotes = $tally[$winner];

    $found = find_play_character($db, $campaignId, $winner);
    if ($found === null) {
        conflict('recipient character no longer exists in this campaign');
    }
    [$recipientUsername, $recipientMember] = $found;

    $items = $recipientMember['inventory_items'] ?? [];
    $items[$loot['item_id']] = (int)($items[$loot['item_id']] ?? 0) + (int)$loot['quantity'];
    $recipientMember['inventory_items'] = $items;

    $db->beginTransaction();
    try {
        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($recipientMember), $campaignId, $recipientUsername]);

        $loot['status'] = 'assigned';
        $loot['recipient_character_id'] = $winner;
        $loot['assigned_votes'] = $winnerVotes;
        save_play_loot($db, $campaignId, $lootId, $loot);

        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }

    send_json([
        'loot_id' => $lootId,
        'recipient_character_id' => $winner,
        'item_id' => $loot['item_id'],
        'quantity' => $loot['quantity'],
        'votes' => $winnerVotes,
        'status' => 'assigned',
    ], 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/loot/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $lootId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner'] && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view this loot record');
    }

    $loot = require_play_loot($db, $campaignId, $lootId);

    $tally = [];
    foreach (($loot['votes'] ?? []) as $recipientCharId) {
        $tally[$recipientCharId] = ($tally[$recipientCharId] ?? 0) + 1;
    }

    send_json([
        'loot_id' => $loot['loot_id'],
        'item_id' => $loot['item_id'],
        'quantity' => $loot['quantity'],
        'status' => $loot['status'],
        'recipient_character_id' => $loot['recipient_character_id'],
        'votes' => empty($tally) ? new stdClass() : $tally,
    ], 200);
}

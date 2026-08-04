<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped factions & character reputation)
// ---------------------------------------------------------------------------

function require_play_faction(PDO $db, string $campaignId, string $factionId): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?');
    $stmt->execute([$campaignId, $factionId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('faction not found');
    }
    return json_decode($row['data'], true);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/factions$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create factions');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['faction_id'], $body['name'])
        || !is_string($body['faction_id']) || $body['faction_id'] === ''
        || !is_string($body['name']) || $body['name'] === '') {
        bad_request();
    }
    $factionId = $body['faction_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?');
    $stmt->execute([$campaignId, $factionId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('faction id already exists in this campaign');
    }

    $faction = [
        'faction_id' => $factionId,
        'name' => $body['name'],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_factions (campaign_id, faction_id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $factionId, json_encode($faction)]);

    send_json($faction, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation$#', $path, $pm)) {
    $campaignId = $pm[1];
    $factionId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may change reputation');
    }

    require_play_faction($db, $campaignId, $factionId);

    $body = read_json_body();
    if ($body === null
        || !isset($body['character_id'], $body['delta'], $body['reason'])
        || !is_string($body['character_id']) || $body['character_id'] === ''
        || !is_valid_int_range($body['delta'], -25, 25) || (int)$body['delta'] === 0
        || !is_string($body['reason']) || $body['reason'] === '') {
        bad_request();
    }
    $characterId = $body['character_id'];
    $delta = (int)$body['delta'];
    $reason = $body['reason'];

    if (find_play_character($db, $campaignId, $characterId) === null) {
        bad_request('character_id must identify a campaign member character');
    }

    $stmt = $db->prepare('SELECT total FROM play_campaign_reputation_totals WHERE campaign_id = ? AND faction_id = ? AND character_id = ?');
    $stmt->execute([$campaignId, $factionId, $characterId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    $current = $row === false ? 0 : (int)$row['total'];
    $newTotal = max(-100, min(100, $current + $delta));

    $entry = [
        'faction_id' => $factionId,
        'character_id' => $characterId,
        'reputation' => $newTotal,
        'delta' => $delta,
        'reason' => $reason,
    ];

    $db->beginTransaction();
    try {
        $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ?');
        $stmt->execute([$campaignId, $factionId]);
        $seq = (int)$stmt->fetchColumn();

        $stmt = $db->prepare('INSERT INTO play_campaign_reputation_history (campaign_id, faction_id, seq, data) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $factionId, $seq, json_encode($entry)]);

        $stmt = $db->prepare('INSERT INTO play_campaign_reputation_totals (campaign_id, faction_id, character_id, total) VALUES (?, ?, ?, ?)
            ON CONFLICT(campaign_id, faction_id, character_id) DO UPDATE SET total = excluded.total');
        $stmt->execute([$campaignId, $factionId, $characterId, $newTotal]);

        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }

    send_json($entry, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation$#', $path, $pm)) {
    $campaignId = $pm[1];
    $factionId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner'] && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view faction reputation');
    }

    require_play_faction($db, $campaignId, $factionId);

    $stmt = $db->prepare('SELECT data FROM play_campaign_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId, $factionId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $ownCharacterId = null;
    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        $memberRow = $stmt->fetch(PDO::FETCH_ASSOC);
        $ownCharacterId = $memberRow === false ? null : $memberRow['character_id'];
    }

    $entries = [];
    foreach ($rows as $row) {
        $entry = json_decode($row['data'], true);
        if ($actor['username'] !== $campaign['owner'] && $entry['character_id'] !== $ownCharacterId) {
            continue;
        }
        $entries[] = $entry;
    }

    send_json([
        'faction_id' => $factionId,
        'entries' => $entries,
    ], 200);
}

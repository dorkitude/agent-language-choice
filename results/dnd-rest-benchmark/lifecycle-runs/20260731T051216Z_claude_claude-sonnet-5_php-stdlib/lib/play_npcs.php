<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped NPC agendas)
// ---------------------------------------------------------------------------

function require_play_npc(PDO $db, string $campaignId, string $npcId): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $stmt->execute([$campaignId, $npcId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('npc not found');
    }
    return json_decode($row['data'], true);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create npcs');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['npc_id'], $body['name'], $body['agenda'], $body['public_status'])
        || !is_string($body['npc_id']) || $body['npc_id'] === ''
        || !is_string($body['name']) || $body['name'] === ''
        || !is_string($body['agenda']) || $body['agenda'] === ''
        || !is_string($body['public_status']) || $body['public_status'] === '') {
        bad_request();
    }
    $npcId = $body['npc_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $stmt->execute([$campaignId, $npcId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('npc id already exists in this campaign');
    }

    $npc = [
        'npc_id' => $npcId,
        'name' => $body['name'],
        'agenda' => $body['agenda'],
        'public_status' => $body['public_status'],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_npcs (campaign_id, npc_id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $npcId, json_encode($npc)]);

    send_json($npc, 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/agenda$#', $path, $pm)) {
    $campaignId = $pm[1];
    $npcId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may update an npc agenda');
    }

    $npc = require_play_npc($db, $campaignId, $npcId);

    $body = read_json_body();
    if ($body === null
        || !isset($body['agenda'], $body['public_status'])
        || !is_string($body['agenda']) || $body['agenda'] === ''
        || !is_string($body['public_status']) || $body['public_status'] === '') {
        bad_request();
    }

    $npc['agenda'] = $body['agenda'];
    $npc['public_status'] = $body['public_status'];

    $stmt = $db->prepare('UPDATE play_campaign_npcs SET data = ? WHERE campaign_id = ? AND npc_id = ?');
    $stmt->execute([json_encode($npc), $campaignId, $npcId]);

    send_json($npc, 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $npcId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner'] && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view this npc');
    }

    $npc = require_play_npc($db, $campaignId, $npcId);

    if ($actor['username'] === $campaign['owner']) {
        send_json($npc, 200);
    }

    send_json([
        'npc_id' => $npc['npc_id'],
        'name' => $npc['name'],
        'public_status' => $npc['public_status'],
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue$#', $path, $pm)) {
    $campaignId = $pm[1];
    $npcId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may append npc dialogue');
    }

    require_play_npc($db, $campaignId, $npcId);

    $body = read_json_body();
    if ($body === null
        || !isset($body['dialogue_id'], $body['speaker'], $body['text'], $body['visibility'])
        || !is_string($body['dialogue_id']) || $body['dialogue_id'] === ''
        || !is_string($body['speaker']) || $body['speaker'] === ''
        || !is_string($body['text']) || $body['text'] === ''
        || !is_string($body['visibility']) || ($body['visibility'] !== 'public' && $body['visibility'] !== 'private')) {
        bad_request();
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?');
    $stmt->execute([$campaignId, $npcId, $body['dialogue_id']]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('dialogue id already exists for this npc');
    }

    $entry = [
        'dialogue_id' => $body['dialogue_id'],
        'speaker' => $body['speaker'],
        'text' => $body['text'],
        'visibility' => $body['visibility'],
    ];

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?');
    $stmt->execute([$campaignId, $npcId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, seq, dialogue_id, data) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$campaignId, $npcId, $seq, $entry['dialogue_id'], json_encode($entry)]);

    send_json($entry, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue$#', $path, $pm)) {
    $campaignId = $pm[1];
    $npcId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner'] && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view this npc dialogue');
    }

    require_play_npc($db, $campaignId, $npcId);

    $stmt = $db->prepare('SELECT data FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId, $npcId]);
    $rows = $stmt->fetchAll(PDO::FETCH_COLUMN);

    $entries = array_map(fn($row) => json_decode($row, true), $rows);

    if ($actor['username'] !== $campaign['owner']) {
        $entries = array_values(array_filter($entries, fn($e) => $e['visibility'] === 'public'));
    }

    send_json([
        'npc_id' => $npcId,
        'entries' => $entries,
    ], 200);
}

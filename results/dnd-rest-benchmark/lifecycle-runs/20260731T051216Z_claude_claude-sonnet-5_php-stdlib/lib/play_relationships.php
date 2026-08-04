<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped relationship graph among characters & NPCs)
// ---------------------------------------------------------------------------

function is_play_campaign_entity(PDO $db, string $campaignId, string $entityId): bool {
    if (find_play_character($db, $campaignId, $entityId) !== null) {
        return true;
    }
    $stmt = $db->prepare('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $stmt->execute([$campaignId, $entityId]);
    return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
}

function require_play_relationship(PDO $db, string $campaignId, string $sourceId, string $targetId, string $kind): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
    $stmt->execute([$campaignId, $sourceId, $targetId, $kind]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('relationship not found');
    }
    return json_decode($row['data'], true);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/relationships$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create relationship edges');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['source_id'], $body['target_id'], $body['kind'], $body['score'])
        || !is_string($body['source_id']) || $body['source_id'] === ''
        || !is_string($body['target_id']) || $body['target_id'] === ''
        || !is_string($body['kind']) || $body['kind'] === ''
        || !is_valid_int_range($body['score'], -100, 100)
        || $body['source_id'] === $body['target_id']) {
        bad_request();
    }
    $sourceId = $body['source_id'];
    $targetId = $body['target_id'];
    $kind = $body['kind'];
    $score = (int)$body['score'];

    if (!is_play_campaign_entity($db, $campaignId, $sourceId)) {
        not_found('source_id must identify an existing campaign entity');
    }
    if (!is_play_campaign_entity($db, $campaignId, $targetId)) {
        not_found('target_id must identify an existing campaign entity');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
    $stmt->execute([$campaignId, $sourceId, $targetId, $kind]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('relationship edge already exists');
    }

    $edge = [
        'source_id' => $sourceId,
        'target_id' => $targetId,
        'kind' => $kind,
        'score' => $score,
    ];

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_relationships WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, seq, data) VALUES (?, ?, ?, ?, ?, ?)');
    $stmt->execute([$campaignId, $sourceId, $targetId, $kind, $seq, json_encode($edge)]);

    send_json($edge, 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/relationships/([^/]+)/([^/]+)/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $sourceId = $pm[2];
    $targetId = $pm[3];
    $kind = $pm[4];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may update relationship edges');
    }

    $edge = require_play_relationship($db, $campaignId, $sourceId, $targetId, $kind);

    $body = read_json_body();
    if ($body === null
        || !isset($body['score'])
        || !is_valid_int_range($body['score'], -100, 100)) {
        bad_request();
    }

    $edge['score'] = (int)$body['score'];

    $stmt = $db->prepare('UPDATE play_campaign_relationships SET data = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
    $stmt->execute([json_encode($edge), $campaignId, $sourceId, $targetId, $kind]);

    send_json($edge, 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/relationships$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner'] && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view relationships');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_COLUMN);

    $edges = array_map(fn($row) => json_decode($row, true), $rows);

    send_json(['edges' => $edges], 200);
}

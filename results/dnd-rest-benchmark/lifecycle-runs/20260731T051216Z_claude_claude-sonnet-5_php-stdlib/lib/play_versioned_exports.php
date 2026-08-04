<?php
declare(strict_types=1);

// Routes: Play campaign versioned exports (DM-only immutable story snapshots)
// ---------------------------------------------------------------------------

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/exports$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may create a campaign export');
    }

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM play_campaign_exports WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $version = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'] + 1;

    $document = $campaign['document'] ?? ['story' => '', 'dm_notes' => ''];

    $export = [
        'version' => $version,
        'story' => $document['story'],
        'status' => $campaign['status'],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_exports (campaign_id, version, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $version, json_encode($export)]);

    send_json($export, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/exports$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may list campaign exports');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC');
    $stmt->execute([$campaignId]);
    $exports = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $stmt->fetchAll(PDO::FETCH_ASSOC));

    send_json(['exports' => array_values($exports)]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/exports/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $versionParam = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may read a campaign export');
    }

    if (!ctype_digit($versionParam) || !is_valid_int_range((int)$versionParam, 1, 2147483647)) {
        not_found('export not found');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_exports WHERE campaign_id = ? AND version = ?');
    $stmt->execute([$campaignId, (int)$versionParam]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('export not found');
    }

    send_json(json_decode($row['data'], true));
}

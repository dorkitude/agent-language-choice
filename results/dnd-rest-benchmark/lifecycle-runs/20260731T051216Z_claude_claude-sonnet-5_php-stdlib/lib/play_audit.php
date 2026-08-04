<?php
declare(strict_types=1);

// Routes: Play campaign actor audit trail
// ---------------------------------------------------------------------------

function next_audit_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) AS max_seq FROM play_campaign_audit_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/audit-events$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner && !is_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('must be a campaign member to create audit events');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['kind'], $body['correlation_id'])
        || !is_string($body['kind']) || $body['kind'] === ''
        || !is_string($body['correlation_id']) || $body['correlation_id'] === '') {
        bad_request();
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?');
    $stmt->execute([$campaignId, $body['correlation_id']]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('correlation_id already used in this campaign');
    }

    $seq = next_audit_sequence($db, $campaignId);
    $entry = [
        'kind' => $body['kind'],
        'actor' => $actor['username'],
        'role' => $isOwner ? 'DM' : 'player',
        'timestamp' => $seq,
        'correlation_id' => $body['correlation_id'],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_audit_events (campaign_id, seq, correlation_id, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $seq, $body['correlation_id'], json_encode($entry)]);

    send_json($entry, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/audit-events$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign owner may read the audit trail');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    $entries = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);

    send_json(['entries' => array_values($entries)]);
}

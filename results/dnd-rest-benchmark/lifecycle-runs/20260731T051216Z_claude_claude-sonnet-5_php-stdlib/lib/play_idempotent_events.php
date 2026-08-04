<?php
declare(strict_types=1);

// Routes: Play campaign idempotent events
// ---------------------------------------------------------------------------

function next_idempotent_event_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_idempotent_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

function idempotent_event_row_to_json(array $row): array {
    return [
        'event_id' => $row['event_id'],
        'value' => $row['value'],
        'sequence' => (int)$row['sequence'],
        'idempotency_key' => $row['idempotency_key'],
    ];
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/idempotent-events$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner && !is_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('must be a campaign member to create idempotent events');
    }

    $idempotencyKey = trim($_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? '');
    if ($idempotencyKey === '') {
        bad_request('Idempotency-Key header is required');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['event_id'], $body['value'])
        || !is_string($body['event_id']) || trim($body['event_id']) === ''
        || !is_string($body['value']) || trim($body['value']) === '') {
        bad_request('event_id and value are required nonempty strings');
    }
    $eventId = $body['event_id'];
    $value = $body['value'];

    $stmt = $db->prepare('SELECT * FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?');
    $stmt->execute([$campaignId, $idempotencyKey]);
    $existingByKey = $stmt->fetch(PDO::FETCH_ASSOC);

    if ($existingByKey !== false) {
        if ($existingByKey['event_id'] === $eventId && $existingByKey['value'] === $value) {
            send_json(idempotent_event_row_to_json($existingByKey), 200);
        }
        conflict('idempotency key already used with a different event_id or value');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?');
    $stmt->execute([$campaignId, $eventId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('event_id already used in this campaign');
    }

    $sequence = next_idempotent_event_sequence($db, $campaignId);
    $stmt = $db->prepare('INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, idempotency_key, value) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, $eventId, $idempotencyKey, $value]);

    send_json([
        'event_id' => $eventId,
        'value' => $value,
        'sequence' => $sequence,
        'idempotency_key' => $idempotencyKey,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/idempotent-events$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner && !is_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('must be a campaign member to read idempotent events');
    }

    $stmt = $db->prepare('SELECT * FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    send_json([
        'events' => array_map('idempotent_event_row_to_json', $rows),
    ]);
}

<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped world events scheduled by the DM for a
// future campaign turn and resolved exactly once when that turn is reached)
// ---------------------------------------------------------------------------

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/world-events$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may schedule world events');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['event_id'], $body['turn_number'], $body['title'], $body['text'])
        || !is_string($body['event_id']) || $body['event_id'] === ''
        || !is_string($body['title']) || $body['title'] === ''
        || !is_string($body['text']) || $body['text'] === ''
        || !is_valid_int_range($body['turn_number'], 0, PHP_INT_MAX)) {
        bad_request();
    }
    $eventId = $body['event_id'];
    $turnNumber = (int)$body['turn_number'];
    $title = $body['title'];
    $text = $body['text'];

    $currentTurn = (int)($campaign['turn_number'] ?? 1);
    if ($turnNumber < $currentTurn) {
        bad_request('turn_number must be greater than or equal to the campaign\'s current turn_number');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?');
    $stmt->execute([$campaignId, $eventId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('event id already exists in this campaign');
    }

    $event = [
        'event_id' => $eventId,
        'turn_number' => $turnNumber,
        'title' => $title,
        'text' => $text,
        'status' => 'scheduled',
    ];

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_world_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_world_events (campaign_id, event_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $eventId, $seq, json_encode($event)]);

    send_json($event, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/world-events/([^/]+)/resolve$#', $path, $pm)) {
    $campaignId = $pm[1];
    $eventId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may resolve world events');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?');
    $stmt->execute([$campaignId, $eventId]);
    $row = $stmt->fetchColumn();
    if ($row === false) {
        not_found('world event not found');
    }
    $event = json_decode($row, true);

    $body = read_json_body();
    if ($body === null || !isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
        bad_request();
    }
    $text = $body['text'];

    $currentTurn = (int)($campaign['turn_number'] ?? 1);
    if ($currentTurn !== (int)$event['turn_number']) {
        conflict('campaign is not on the event\'s scheduled turn');
    }
    if ($event['status'] === 'resolved') {
        conflict('world event is already resolved');
    }

    $event['status'] = 'resolved';
    $event['resolution'] = [
        'turn_number' => $event['turn_number'],
        'text' => $text,
    ];

    $stmt = $db->prepare('UPDATE play_campaign_world_events SET data = ? WHERE campaign_id = ? AND event_id = ?');
    $stmt->execute([json_encode($event), $campaignId, $eventId]);

    send_json($event, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/world-events$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isDm = $actor['username'] === $campaign['owner'];
    if (!$isDm && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view world events');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_COLUMN);
    $events = array_map(fn($row) => json_decode($row, true), $rows);
    usort($events, fn($a, $b) => $a['turn_number'] <=> $b['turn_number']);

    send_json(['events' => $events], 200);
}

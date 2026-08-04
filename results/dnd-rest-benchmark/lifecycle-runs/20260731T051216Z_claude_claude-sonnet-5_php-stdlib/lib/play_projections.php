<?php
declare(strict_types=1);

// Routes: Play campaign event projections
// ---------------------------------------------------------------------------

function next_projection_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_projection_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

function load_projection_events(PDO $db, string $campaignId): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    return array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);
}

function build_projection(array $events): array {
    $story = '';
    $danger = 0;
    $appliedEventIds = [];
    foreach ($events as $event) {
        if ($event['kind'] === 'set-story') {
            $story = $event['value'];
        } elseif ($event['kind'] === 'increment-danger') {
            $danger += 1;
        }
        $appliedEventIds[] = $event['event_id'];
    }
    return [
        'story' => $story,
        'danger' => $danger,
        'applied_event_ids' => $appliedEventIds,
    ];
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/projection-events$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    $isMember = is_campaign_member($db, $campaignId, $actor['username']);
    if (!$isOwner && !$isMember) {
        forbidden('must be a campaign member to append projection events');
    }
    if ($isOwner) {
        forbidden('the campaign dm may not append projection events');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['event_id'], $body['kind'])
        || !is_string($body['event_id']) || $body['event_id'] === ''
        || !is_string($body['kind'])) {
        bad_request();
    }

    $kind = $body['kind'];
    if ($kind !== 'set-story' && $kind !== 'increment-danger') {
        bad_request('kind must be set-story or increment-danger');
    }

    if ($kind === 'set-story') {
        if (!isset($body['value']) || !is_string($body['value']) || $body['value'] === '') {
            bad_request('value is required and must be a nonempty string for set-story');
        }
    } else {
        if (isset($body['value'])) {
            bad_request('value must be omitted for increment-danger');
        }
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?');
    $stmt->execute([$campaignId, $body['event_id']]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('event_id already used in this campaign');
    }

    $sequence = next_projection_sequence($db, $campaignId);
    $entry = [
        'sequence' => $sequence,
        'event_id' => $body['event_id'],
        'kind' => $kind,
    ];
    if ($kind === 'set-story') {
        $entry['value'] = $body['value'];
    }

    $stmt = $db->prepare('INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, $body['event_id'], json_encode($entry)]);

    send_json($entry, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/projection$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner && !is_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('must be a campaign member to read the projection');
    }

    $events = load_projection_events($db, $campaignId);
    send_json(build_projection($events));
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/projection/rebuild$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner && !is_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('must be a campaign member to rebuild the projection');
    }

    $events = load_projection_events($db, $campaignId);
    send_json(build_projection($events));
}

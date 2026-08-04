<?php
declare(strict_types=1);

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/scenes$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may create a scene');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name']) || $body['name'] === '') {
        bad_request();
    }
    $sceneId = $body['id'];

    if (isset($campaign['scenes'][$sceneId])) {
        conflict('scene already exists');
    }

    $scene = [
        'id' => $sceneId,
        'name' => $body['name'],
        'status' => 'open',
    ];

    $campaign['scenes'][$sceneId] = $scene;

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($scene, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/enter$#', $path, $pm)) {
    $campaignId = $pm[1];
    $sceneId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may enter a scene');
    }

    $scene = $campaign['scenes'][$sceneId] ?? null;
    if ($scene === null) {
        not_found('scene not found');
    }
    if ($scene['status'] !== 'open') {
        conflict('closed scenes may not be entered');
    }

    $campaign['current_scene_id'] = $sceneId;

    $sequence = next_narration_sequence($db, $campaignId);
    $sceneEvent = [
        'sequence' => $sequence,
        'kind' => 'scene',
        'actor' => $actor['username'],
        'scene_id' => $sceneId,
    ];
    $stmt = $db->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, json_encode($sceneEvent)]);

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'current_scene_id' => $sceneId,
        'name' => $scene['name'],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/close$#', $path, $pm)) {
    $campaignId = $pm[1];
    $sceneId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may close a scene');
    }

    $scene = $campaign['scenes'][$sceneId] ?? null;
    if ($scene === null) {
        not_found('scene not found');
    }

    $scene['status'] = 'closed';
    $campaign['scenes'][$sceneId] = $scene;

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'id' => $scene['id'],
        'status' => $scene['status'],
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/scenes/current$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view the current scene');
        }
    }

    $currentSceneId = $campaign['current_scene_id'] ?? null;
    $scene = $currentSceneId !== null ? ($campaign['scenes'][$currentSceneId] ?? null) : null;
    if ($scene === null || $scene['status'] !== 'open') {
        not_found('no current scene');
    }

    send_json([
        'id' => $scene['id'],
        'name' => $scene['name'],
        'status' => $scene['status'],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/locations$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may create a location');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name']) || $body['name'] === '') {
        bad_request();
    }
    $locationId = $body['id'];

    if (isset($campaign['locations'][$locationId])) {
        conflict('location already exists');
    }

    $location = [
        'id' => $locationId,
        'name' => $body['name'],
    ];

    $campaign['locations'][$locationId] = $location;

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($location, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/locations/([^/]+)/connections$#', $path, $pm)) {
    $campaignId = $pm[1];
    $fromId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may create a connection');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['to_id'], $body['travel_turns'])
        || !is_string($body['to_id']) || $body['to_id'] === ''
        || !is_valid_int_range($body['travel_turns'], 1, 1000)) {
        bad_request();
    }
    $toId = $body['to_id'];
    $travelTurns = (int)$body['travel_turns'];

    if (!isset($campaign['locations'][$fromId]) || !isset($campaign['locations'][$toId])) {
        bad_request('location not found');
    }

    if (!isset($campaign['connections'][$fromId])) {
        $campaign['connections'][$fromId] = [];
    }
    if (isset($campaign['connections'][$fromId][$toId])) {
        bad_request('connection already exists');
    }

    $campaign['connections'][$fromId][$toId] = $travelTurns;

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'from_id' => $fromId,
        'to_id' => $toId,
        'travel_turns' => $travelTurns,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/locations/([^/]+)/travel$#', $path, $pm)) {
    $campaignId = $pm[1];
    $locId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view travel');
        }
    }

    $destinations = [];
    $connections = $campaign['connections'][$locId] ?? [];
    foreach ($connections as $toId => $travelTurns) {
        $destination = $campaign['locations'][$toId] ?? null;
        if ($destination === null) {
            continue;
        }
        $destinations[] = [
            'id' => $destination['id'],
            'name' => $destination['name'],
            'travel_turns' => $travelTurns,
        ];
    }

    send_json(['destinations' => $destinations]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/turn/travel$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['destination_id']) || !is_string($body['destination_id']) || $body['destination_id'] === '') {
        bad_request();
    }
    $destinationId = $body['destination_id'];

    if ($actor['username'] !== ($campaign['current_actor'] ?? null)) {
        conflict('only the active player may travel');
    }

    $currentLocationId = $campaign['current_location_id'] ?? array_key_first($campaign['locations'] ?? []);
    $connections = $campaign['connections'][$currentLocationId] ?? [];
    if ($currentLocationId === null || !isset($connections[$destinationId])) {
        conflict('destination is not a valid outbound connection');
    }
    $travelTurns = $connections[$destinationId];

    $sequence = next_narration_sequence($db, $campaignId);

    $event = [
        'sequence' => $sequence,
        'kind' => 'travel',
        'actor' => $actor['username'],
        'destination_id' => $destinationId,
        'travel_turns' => $travelTurns,
        'next_actor' => 'dm',
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, json_encode($event)]);

    $campaign['last_actor'] = $actor['username'];
    $campaign['current_actor'] = $campaign['owner'];
    $campaign['current_location_id'] = $destinationId;
    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($event, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/turn/rest$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['type']) || !is_string($body['type'])
        || !in_array($body['type'], ['short', 'long'], true)) {
        bad_request();
    }
    $restType = $body['type'];

    if ($actor['username'] !== ($campaign['current_actor'] ?? null)) {
        conflict('only the active player may rest');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $actor['username']]);
    $memberRow = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($memberRow === false) {
        conflict('only a party member may rest');
    }
    $member = json_decode($memberRow['data'], true);

    $hpMax = (int)($member['hp_max'] ?? 20);
    $hpCurrent = (int)($member['hp_current'] ?? $hpMax);
    if ($restType === 'long') {
        $hpCurrent = $hpMax;
    }
    $member['hp_max'] = $hpMax;
    $member['hp_current'] = $hpCurrent;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $actor['username']]);

    $sequence = next_narration_sequence($db, $campaignId);

    $event = [
        'sequence' => $sequence,
        'kind' => 'rest',
        'actor' => $actor['username'],
        'type' => $restType,
        'hp_current' => $hpCurrent,
        'hp_max' => $hpMax,
        'next_actor' => 'dm',
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, json_encode($event)]);

    $campaign['last_actor'] = $actor['username'];
    $campaign['current_actor'] = $campaign['owner'];
    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($event, 201);
}

// Finds a play campaign member by character_id, returning [$username, $member]
// or null if no member in the campaign has that character_id.
function find_play_character(PDO $db, string $campaignId, string $charId): ?array {
    $stmt = $db->prepare('SELECT username, data FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $stmt->execute([$campaignId, $charId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [$row['username'], json_decode($row['data'], true)];
}


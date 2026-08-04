<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped recurring downtime activities that campaign
// members allocate to owned characters and progress repeatedly)
// ---------------------------------------------------------------------------

function validate_downtime_activity_payload($body): ?array {
    if ($body === null
        || !isset($body['activity_id'], $body['name'], $body['cycles_required'])
        || !is_string($body['activity_id']) || $body['activity_id'] === ''
        || !is_string($body['name']) || $body['name'] === ''
        || !is_valid_int_range($body['cycles_required'], 1, 10)) {
        return null;
    }

    return [
        'activity_id' => $body['activity_id'],
        'name' => $body['name'],
        'cycles_required' => (int)$body['cycles_required'],
    ];
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/downtime/activities$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create downtime activities');
    }

    $body = read_json_body();
    $validated = validate_downtime_activity_payload($body);
    if ($validated === null) {
        bad_request();
    }
    $activityId = $validated['activity_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
    $stmt->execute([$campaignId, $activityId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('activity id already exists in this campaign');
    }

    $activity = [
        'activity_id' => $activityId,
        'name' => $validated['name'],
        'cycles_required' => $validated['cycles_required'],
    ];

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_downtime_activities WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $activityId, $seq, json_encode($activity)]);

    send_json($activity, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$username, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $username);
    if ($actor['username'] !== $owner) {
        forbidden('only the character owner may allocate downtime for this character');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['activity_id']) || !is_string($body['activity_id']) || $body['activity_id'] === '') {
        bad_request();
    }
    $activityId = $body['activity_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
    $stmt->execute([$campaignId, $activityId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        not_found('activity not found');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
    $stmt->execute([$campaignId, $charId, $activityId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('allocation already exists for this character and activity');
    }

    $allocation = [
        'character_id' => $charId,
        'activity_id' => $activityId,
        'cycles_completed' => 0,
        'completions' => 0,
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $charId, $activityId, json_encode($allocation)]);

    send_json($allocation, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)/progress$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $activityId = $pm[3];
    $actor = require_actor($db);

    require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$username, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $username);
    if ($actor['username'] !== $owner) {
        forbidden('only the character owner may progress downtime for this character');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
    $stmt->execute([$campaignId, $activityId]);
    $activityRow = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($activityRow === false) {
        not_found('activity not found');
    }
    $activity = json_decode($activityRow['data'], true);

    $stmt = $db->prepare('SELECT data FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
    $stmt->execute([$campaignId, $charId, $activityId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('allocation not found');
    }
    $allocation = json_decode($row['data'], true);

    $allocation['cycles_completed'] = (int)$allocation['cycles_completed'] + 1;
    if ($allocation['cycles_completed'] >= (int)$activity['cycles_required']) {
        $allocation['cycles_completed'] = 0;
        $allocation['completions'] = (int)$allocation['completions'] + 1;
    }

    $stmt = $db->prepare('UPDATE play_campaign_downtime_allocations SET data = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
    $stmt->execute([json_encode($allocation), $campaignId, $charId, $activityId]);

    send_json($allocation, 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $activityId = $pm[3];
    require_actor($db);

    require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
    $stmt->execute([$campaignId, $activityId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        not_found('activity not found');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
    $stmt->execute([$campaignId, $charId, $activityId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('allocation not found');
    }

    send_json(json_decode($row['data'], true), 200);
}

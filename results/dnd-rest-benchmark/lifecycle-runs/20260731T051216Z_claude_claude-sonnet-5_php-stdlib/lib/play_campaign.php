<?php
declare(strict_types=1);

// Routes: Play (protected campaign-play surface)
// ---------------------------------------------------------------------------

// Loads a play campaign, sending 404 and exiting if it doesn't exist. Nearly
// every /v1/play/campaigns/{id}/... route starts with this lookup.
function require_play_campaign(PDO $db, string $campaignId): array {
    $stmt = $db->prepare('SELECT data FROM play_campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('campaign not found');
    }
    return json_decode($row['data'], true);
}

// Fetches the most recent narration/action/resolution events for a campaign,
// oldest-first (the storage query is newest-first for the LIMIT to work).
function recent_narrations(PDO $db, string $campaignId, int $limit): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_narrations WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?');
    $stmt->bindValue(1, $campaignId, PDO::PARAM_STR);
    $stmt->bindValue(2, $limit, PDO::PARAM_INT);
    $stmt->execute();
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    return array_values(array_reverse(array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows)));
}

// Returns the next sequence number for a campaign's narration/event log.
function next_narration_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_narrations WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

if ($method === 'POST' && $path === '/v1/play/campaigns') {
    $actor = require_actor($db);
    if ($actor['role'] !== 'dm') {
        forbidden('only a dm may create a play campaign');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['name'], $body['max_players'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['name'])
        || !is_valid_int_range($body['max_players'], 1, 20)) {
        bad_request();
    }
    $id = $body['id'];
    $maxPlayers = (int)$body['max_players'];

    $stmt = $db->prepare('SELECT id FROM play_campaigns WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('campaign already exists');
    }

    $campaign = [
        'id' => $id,
        'name' => $body['name'],
        'owner' => $actor['username'],
        'status' => 'lobby',
        'max_players' => $maxPlayers,
    ];

    $stmt = $db->prepare('INSERT INTO play_campaigns (id, data) VALUES (?, ?)');
    $stmt->execute([$id, json_encode($campaign)]);

    send_json($campaign, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/members$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);
    if ($actor['role'] !== 'player') {
        forbidden('only a player may join a campaign');
    }

    $campaign = require_play_campaign($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['character_id'], $body['name'], $body['class'])
        || !is_string($body['character_id']) || $body['character_id'] === ''
        || !is_string($body['name']) || $body['name'] === ''
        || !is_string($body['class']) || $body['class'] === '') {
        bad_request();
    }
    $characterId = $body['character_id'];

    $stmt = $db->prepare('SELECT username, character_id FROM play_campaign_members WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $members = $stmt->fetchAll(PDO::FETCH_ASSOC);

    foreach ($members as $member) {
        if ($member['username'] === $actor['username']) {
            conflict('player already joined this campaign');
        }
        if ($member['character_id'] === $characterId) {
            conflict('character id already in use');
        }
    }
    if (count($members) >= (int)$campaign['max_players']) {
        conflict('campaign party is full');
    }

    $membership = [
        'username' => $actor['username'],
        'character_id' => $characterId,
        'name' => $body['name'],
        'class' => $body['class'],
        'gold' => 10,
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_members (campaign_id, username, character_id, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $actor['username'], $characterId, json_encode($membership)]);

    send_json($membership, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/start$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may start this campaign');
    }

    if ($campaign['status'] !== 'lobby') {
        conflict('campaign is not in lobby status');
    }

    $stmt = $db->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
    $stmt->execute([$campaignId]);
    $members = $stmt->fetchAll(PDO::FETCH_ASSOC);
    if (count($members) < 2) {
        conflict('campaign needs at least two party members to start');
    }

    $campaign['status'] = 'active';
    $campaign['current_actor'] = $members[0]['username'];
    $campaign['turn_number'] = 1;
    $campaign['queue'] = [$members[0]['username'], $campaign['owner'], $members[1]['username'], $campaign['owner']];

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'id' => $campaign['id'],
        'status' => $campaign['status'],
        'current_actor' => $campaign['current_actor'],
        'turn_number' => $campaign['turn_number'],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/narrations$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner'] && !has_delegated_power($db, $campaignId, $actor['username'], 'narrate')) {
        forbidden('only the dm owner may narrate this campaign');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
        bad_request();
    }

    $sequence = next_narration_sequence($db, $campaignId);

    $event = [
        'sequence' => $sequence,
        'kind' => 'narration',
        'actor' => $actor['username'],
        'text' => $body['text'],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, json_encode($event)]);

    send_json($event, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/actions$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['role'] !== 'player' || $actor['username'] !== ($campaign['current_actor'] ?? null)) {
        conflict('only the active player may submit an action');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['type'], $body['text'])
        || !is_string($body['type']) || $body['type'] === ''
        || !is_string($body['text']) || $body['text'] === '') {
        bad_request();
    }

    $sequence = next_narration_sequence($db, $campaignId);

    $event = [
        'sequence' => $sequence,
        'kind' => 'action',
        'actor' => $actor['username'],
        'type' => $body['type'],
        'text' => $body['text'],
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

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/resolutions$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        conflict('only the owner may resolve this turn');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['text']) || !is_string($body['text']) || $body['text'] === '') {
        bad_request();
    }

    $stmt = $db->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
    $stmt->execute([$campaignId]);
    $members = array_column($stmt->fetchAll(PDO::FETCH_ASSOC), 'username');

    $turnNumber = (int)($campaign['turn_number'] ?? 1);
    $nextActor = $members[1] ?? ($members[0] ?? null);
    if ($turnNumber >= 2) {
        $nextActor = $members[0] ?? null;
    }

    $sequence = next_narration_sequence($db, $campaignId);

    $campaign['turn_number'] = (int)($campaign['turn_number'] ?? 1) + 1;
    $campaign['current_actor'] = $nextActor;

    $event = [
        'sequence' => $sequence,
        'kind' => 'resolution',
        'actor' => 'dm',
        'text' => $body['text'],
        'next_actor' => $nextActor,
        'turn_number' => $campaign['turn_number'],
    ];

    $stmt = $db->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, json_encode($event)]);

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($event, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/turn$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this campaign turn');
        }
    }

    $currentActor = $campaign['current_actor'] ?? null;
    if ($currentActor === null) {
        $phase = $campaign['status'];
    } elseif ($currentActor === $campaign['owner']) {
        $phase = 'dm';
    } else {
        $phase = 'player';
    }

    $turnNumber = (int)($campaign['turn_number'] ?? 1);

    send_json([
        'campaign_id' => $campaign['id'],
        'current_actor' => $currentActor,
        'phase' => $phase,
        'turn_number' => $campaign['turn_number'] ?? null,
        'queue' => $campaign['queue'] ?? null,
        'overdue' => false,
        'logical_deadline' => $turnNumber + TURN_TIMEOUT_WINDOW,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/turn/nudge$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may nudge this turn');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['message']) || !is_string($body['message']) || $body['message'] === '') {
        bad_request();
    }

    $campaign['nudge_count'] = (int)($campaign['nudge_count'] ?? 0) + 1;

    $sequence = next_narration_sequence($db, $campaignId);
    $nudgeEvent = [
        'sequence' => $sequence,
        'kind' => 'nudge',
        'actor' => $actor['username'],
        'target' => $campaign['current_actor'] ?? null,
        'message' => $body['message'],
    ];
    $stmt = $db->prepare('INSERT INTO play_campaign_narrations (campaign_id, sequence, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sequence, json_encode($nudgeEvent)]);

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'campaign_id' => $campaign['id'],
        'actor' => $actor['username'],
        'target' => $campaign['current_actor'] ?? null,
        'message' => $body['message'],
        'nudge_count' => $campaign['nudge_count'],
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/my-turn$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);
    if ($actor['role'] !== 'player') {
        forbidden('only a player may view their turn context');
    }

    $campaign = require_play_campaign($db, $campaignId);

    $stmt = $db->prepare('SELECT data FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $actor['username']]);
    $memberRow = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($memberRow === false) {
        forbidden('only a party member may view this campaign turn');
    }
    $member = json_decode($memberRow['data'], true);

    $currentActor = $campaign['current_actor'] ?? null;
    $isMyTurn = $currentActor !== null && $currentActor === $actor['username'];

    $recentEvents = recent_narrations($db, $campaignId, 5);

    send_json([
        'campaign_id' => $campaign['id'],
        'is_my_turn' => $isMyTurn,
        'current_actor' => $currentActor,
        'character' => [
            'id' => $member['character_id'],
            'name' => $member['name'],
        ],
        'recent_events' => array_values($recentEvents),
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/gm/status$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may view gm status');
    }

    $currentActor = $campaign['current_actor'] ?? null;
    $needsAttention = $currentActor !== null && $currentActor === $campaign['owner'];

    $stmt = $db->prepare('SELECT data FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
    $stmt->execute([$campaignId]);
    $memberRows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    $party = array_map(function ($r) {
        $m = json_decode($r['data'], true);
        return [
            'username' => $m['username'],
            'character_id' => $m['character_id'],
            'name' => $m['name'],
            'class' => $m['class'],
        ];
    }, $memberRows);

    $recentEvents = recent_narrations($db, $campaignId, 5);

    send_json([
        'campaign_id' => $campaign['id'],
        'needs_attention' => $needsAttention,
        'current_actor' => $currentActor,
        'party' => array_values($party),
        'recent_events' => array_values($recentEvents),
    ]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/document$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may update this campaign document');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['story'], $body['dm_notes'])
        || !is_string($body['story']) || !is_string($body['dm_notes'])) {
        bad_request();
    }

    $campaign['document'] = [
        'story' => $body['story'],
        'dm_notes' => $body['dm_notes'],
    ];

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json([
        'campaign_id' => $campaign['id'],
        'story' => $campaign['document']['story'],
        'dm_notes' => $campaign['document']['dm_notes'],
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/document$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this campaign document');
        }
    }

    $document = $campaign['document'] ?? ['story' => '', 'dm_notes' => ''];

    $response = [
        'campaign_id' => $campaign['id'],
        'story' => $document['story'],
    ];
    if ($isOwner) {
        $response['dm_notes'] = $document['dm_notes'];
    }

    send_json($response);
}

// Validates a session-zero settings payload: rules/tone nonempty strings,
// consent a nonempty array of unique nonempty strings (order preserved).
function is_valid_session_zero_settings($body): bool {
    if (!is_array($body)) {
        return false;
    }
    if (!isset($body['rules'], $body['tone'], $body['consent'])) {
        return false;
    }
    if (!is_string($body['rules']) || $body['rules'] === '') {
        return false;
    }
    if (!is_string($body['tone']) || $body['tone'] === '') {
        return false;
    }
    $consent = $body['consent'];
    if (!is_array($consent) || $consent === [] || !array_is_list($consent)) {
        return false;
    }
    $seen = [];
    foreach ($consent as $item) {
        if (!is_string($item) || $item === '') {
            return false;
        }
        if (isset($seen[$item])) {
            return false;
        }
        $seen[$item] = true;
    }
    return true;
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/session-zero$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may set session-zero settings');
    }

    if ($campaign['status'] !== 'lobby') {
        conflict('session-zero settings can only be changed while the campaign is in lobby');
    }

    $body = read_json_body();
    if (!is_valid_session_zero_settings($body)) {
        bad_request();
    }

    $settings = [
        'rules' => $body['rules'],
        'tone' => $body['tone'],
        'consent' => array_values($body['consent']),
    ];

    $campaign['session_zero'] = $settings;

    $stmt = $db->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
    $stmt->execute([json_encode($campaign), $campaignId]);

    send_json($settings);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/session-zero$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view session-zero settings');
        }
    }

    if (!isset($campaign['session_zero'])) {
        not_found('session-zero settings not set');
    }

    send_json($campaign['session_zero']);
}

// Validates a content payload: content_id/kind/text nonempty strings, tags a
// nonempty array of unique nonempty strings (order preserved).
function is_valid_content_payload($body): bool {
    if (!is_array($body)) {
        return false;
    }
    if (!isset($body['content_id'], $body['kind'], $body['text'], $body['tags'])) {
        return false;
    }
    if (!is_string($body['content_id']) || $body['content_id'] === '') {
        return false;
    }
    if (!is_string($body['kind']) || $body['kind'] === '') {
        return false;
    }
    if (!is_string($body['text']) || $body['text'] === '') {
        return false;
    }
    $tags = $body['tags'];
    if (!is_array($tags) || $tags === [] || !array_is_list($tags)) {
        return false;
    }
    $seen = [];
    foreach ($tags as $tag) {
        if (!is_string($tag) || $tag === '') {
            return false;
        }
        if (isset($seen[$tag])) {
            return false;
        }
        $seen[$tag] = true;
    }
    return true;
}

// Validates a tag replacement payload: tags may be empty, but when present
// each must be a unique nonempty string (order preserved).
function is_valid_tags_payload($body): bool {
    if (!is_array($body) || !isset($body['tags'])) {
        return false;
    }
    $tags = $body['tags'];
    if (!is_array($tags) || (!array_is_list($tags) && $tags !== [])) {
        return false;
    }
    $seen = [];
    foreach ($tags as $tag) {
        if (!is_string($tag) || $tag === '') {
            return false;
        }
        if (isset($seen[$tag])) {
            return false;
        }
        $seen[$tag] = true;
    }
    return true;
}

function next_content_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) AS max_seq FROM play_campaign_content WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/content$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may create content');
    }

    $body = read_json_body();
    if (!is_valid_content_payload($body)) {
        bad_request();
    }

    $contentId = $body['content_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?');
    $stmt->execute([$campaignId, $contentId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('content id already exists');
    }

    $content = [
        'content_id' => $contentId,
        'kind' => $body['kind'],
        'text' => $body['text'],
        'tags' => array_values($body['tags']),
    ];

    $seq = next_content_sequence($db, $campaignId);
    $stmt = $db->prepare('INSERT INTO play_campaign_content (campaign_id, content_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $contentId, $seq, json_encode($content)]);

    send_json($content, 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/content/([^/]+)/tags$#', $path, $pm)) {
    $campaignId = $pm[1];
    $contentId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may replace content tags');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?');
    $stmt->execute([$campaignId, $contentId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('content not found');
    }

    $body = read_json_body();
    if (!is_valid_tags_payload($body)) {
        bad_request();
    }

    $content = json_decode($row['data'], true);
    $content['tags'] = array_values($body['tags']);

    $stmt = $db->prepare('UPDATE play_campaign_content SET data = ? WHERE campaign_id = ? AND content_id = ?');
    $stmt->execute([json_encode($content), $campaignId, $contentId]);

    send_json($content);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/content$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view campaign content');
        }
    }

    $excludeTag = null;
    if (isset($_GET['exclude_tag'])) {
        $excludeTag = $_GET['exclude_tag'];
        if (!is_string($excludeTag) || $excludeTag === '') {
            bad_request();
        }
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_content WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $records = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);

    if (!$isOwner && $excludeTag !== null) {
        $records = array_values(array_filter($records, function ($record) use ($excludeTag) {
            return !in_array($excludeTag, $record['tags'], true);
        }));
    }

    send_json(['content' => array_values($records)]);
}


<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped calendar the DM initializes once, advances in
// bounded day increments, and exposes to authenticated campaign members with
// deterministic weather)
// ---------------------------------------------------------------------------

const CALENDAR_SEASON_OFFSETS = ['spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3];
const CALENDAR_WEATHER_MAP = [0 => 'clear', 1 => 'rain', 2 => 'wind', 3 => 'snow'];

function calendar_weather(int $day, string $season): string {
    $offset = CALENDAR_SEASON_OFFSETS[$season];
    return CALENDAR_WEATHER_MAP[($day + $offset) % 4];
}

function calendar_response(array $calendar): array {
    return [
        'day' => (int)$calendar['day'],
        'season' => $calendar['season'],
        'weather' => calendar_weather((int)$calendar['day'], $calendar['season']),
    ];
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/calendar$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may initialize the calendar');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['day'], $body['season'])
        || !is_valid_int_range($body['day'], 1, PHP_INT_MAX)
        || !is_string($body['season'])
        || !array_key_exists($body['season'], CALENDAR_SEASON_OFFSETS)) {
        bad_request();
    }
    $day = (int)$body['day'];
    $season = $body['season'];

    $stmt = $db->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('calendar is already initialized for this campaign');
    }

    $stmt = $db->prepare('INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $day, $season]);

    send_json(calendar_response(['day' => $day, 'season' => $season]), 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/calendar/advance$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may advance the calendar');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['days'])
        || !is_valid_int_range($body['days'], 1, 30)) {
        bad_request();
    }
    $days = (int)$body['days'];

    $stmt = $db->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $calendar = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($calendar === false) {
        not_found('calendar not initialized for this campaign');
    }

    $newDay = (int)$calendar['day'] + $days;

    $stmt = $db->prepare('UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?');
    $stmt->execute([$newDay, $campaignId]);

    send_json(calendar_response(['day' => $newDay, 'season' => $calendar['season']]), 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/calendar$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isDm = $actor['username'] === $campaign['owner'];
    if (!$isDm && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view the calendar');
    }

    $stmt = $db->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $calendar = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($calendar === false) {
        not_found('calendar not initialized for this campaign');
    }

    send_json(calendar_response($calendar), 200);
}

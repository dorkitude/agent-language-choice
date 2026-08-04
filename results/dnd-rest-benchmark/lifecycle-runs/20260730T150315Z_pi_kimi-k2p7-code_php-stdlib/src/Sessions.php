<?php

declare(strict_types=1);

/**
 * Campaign session scheduling and attendance tracking.
 */

function createCampaignSession(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['id', 'starts_at', 'duration_minutes', 'agenda'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $startsAt = $input['starts_at'];
    if (!is_string($id) || $id === '' || !is_string($startsAt) || $startsAt === '') {
        sendError(400, 'invalid fields');
    }

    $durationMinutes = filter_var($input['duration_minutes'], FILTER_VALIDATE_INT);
    if ($durationMinutes === false || $durationMinutes <= 0) {
        sendError(400, 'invalid fields');
    }

    $agenda = $input['agenda'];
    if (!is_array($agenda)) {
        sendError(400, 'invalid fields');
    }
    foreach ($agenda as $item) {
        if (!is_string($item)) {
            sendError(400, 'invalid fields');
        }
    }

    if (getSessionById($id) !== null) {
        sendError(409, 'session id already exists');
    }

    $stmt = db()->prepare('INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $startsAt, $durationMinutes, json_encode($agenda)]);

    return [
        'id' => $id,
        'starts_at' => $startsAt,
        'duration_minutes' => $durationMinutes,
        'agenda_count' => count($agenda),
    ];
}

function getSessionById(string $id): ?array
{
    $stmt = db()->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM sessions WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'id' => $row['id'],
        'campaign_id' => $row['campaign_id'],
        'starts_at' => $row['starts_at'],
        'duration_minutes' => (int) $row['duration_minutes'],
        'agenda' => json_decode($row['agenda_json'], true),
    ];
}

function recordAttendance(string $campaignId, string $sessionId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $session = getSessionById($sessionId);
    if ($session === null || $session['campaign_id'] !== $campaignId) {
        sendError(404, 'session not found');
    }

    $required = ['present', 'absent'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $present = $input['present'];
    $absent = $input['absent'];
    if (!is_array($present) || !is_array($absent)) {
        sendError(400, 'invalid fields');
    }
    foreach ($present as $p) {
        if (!is_string($p)) {
            sendError(400, 'invalid fields');
        }
    }
    foreach ($absent as $a) {
        if (!is_string($a)) {
            sendError(400, 'invalid fields');
        }
    }

    $existing = getAttendanceBySession($sessionId);
    if ($existing !== null) {
        $stmt = db()->prepare('UPDATE session_attendance SET present_json = ?, absent_json = ? WHERE session_id = ?');
        $stmt->execute([json_encode($present), json_encode($absent), $sessionId]);
    } else {
        $stmt = db()->prepare('INSERT INTO session_attendance (session_id, present_json, absent_json) VALUES (?, ?, ?)');
        $stmt->execute([$sessionId, json_encode($present), json_encode($absent)]);
    }

    return [
        'session_id' => $sessionId,
        'present_count' => count($present),
        'absent_count' => count($absent),
    ];
}

function getAttendanceBySession(string $sessionId): ?array
{
    $stmt = db()->prepare('SELECT present_json, absent_json FROM session_attendance WHERE session_id = ?');
    $stmt->execute([$sessionId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'present' => json_decode($row['present_json'], true),
        'absent' => json_decode($row['absent_json'], true),
    ];
}

function getNextSession(string $campaignId): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $stmt = db()->prepare('SELECT id, starts_at, agenda_json FROM sessions WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1');
    $stmt->execute([$campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        sendError(404, 'session not found');
    }

    $agenda = json_decode($row['agenda_json'], true);
    return [
        'id' => $row['id'],
        'starts_at' => $row['starts_at'],
        'agenda_count' => is_array($agenda) ? count($agenda) : 0,
    ];
}

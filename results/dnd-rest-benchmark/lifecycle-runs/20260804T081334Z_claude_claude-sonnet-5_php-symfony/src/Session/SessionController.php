<?php

namespace App\Session;

use App\Storage\Database;
use App\Support\Json;
use App\Support\Validators;
use PDO;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for campaign session-scheduling endpoints (/v1/campaigns/{id}/sessions/*). */
final class SessionController
{
    public function create(array $body, string $campaignId): JsonResponse
    {
        $id = $body['id'] ?? null;
        $startsAt = $body['starts_at'] ?? null;
        $durationMinutes = $body['duration_minutes'] ?? null;
        $agenda = $body['agenda'] ?? null;

        if (!Validators::isValidId($id) || !is_string($startsAt) || $startsAt === ''
            || !Validators::isValidInt($durationMinutes) || (int) $durationMinutes <= 0
            || !is_array($agenda)) {
            return Json::error('invalid request');
        }
        foreach ($agenda as $item) {
            if (!is_string($item) || $item === '') {
                return Json::error('invalid request');
            }
        }
        $durationMinutes = (int) $durationMinutes;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT id FROM campaign_sessions WHERE id = ?');
        $stmt->execute([$id]);
        if ($stmt->fetchColumn() !== false) {
            return Json::error('session already exists', 409);
        }

        $insert = $db->prepare(
            'INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda, present, absent)
             VALUES (?, ?, ?, ?, ?, ?, ?)'
        );
        $insert->execute([
            $id,
            $campaignId,
            $startsAt,
            $durationMinutes,
            json_encode(array_values($agenda)),
            json_encode([]),
            json_encode([]),
        ]);

        return new JsonResponse([
            'id' => $id,
            'starts_at' => $startsAt,
            'duration_minutes' => $durationMinutes,
            'agenda_count' => count($agenda),
        ], 201);
    }

    public function recordAttendance(array $body, string $campaignId, string $sessionId): JsonResponse
    {
        $present = $body['present'] ?? null;
        $absent = $body['absent'] ?? null;

        if (!is_array($present) || !is_array($absent)) {
            return Json::error('invalid request');
        }
        foreach ([...$present, ...$absent] as $item) {
            if (!is_string($item) || $item === '') {
                return Json::error('invalid request');
            }
        }

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaign_sessions WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$sessionId, $campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('session not found', 404);
        }

        $update = $db->prepare('UPDATE campaign_sessions SET present = ?, absent = ? WHERE id = ?');
        $update->execute([json_encode(array_values($present)), json_encode(array_values($absent)), $sessionId]);

        return new JsonResponse([
            'session_id' => $sessionId,
            'present_count' => count($present),
            'absent_count' => count($absent),
        ]);
    }

    public function next(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare(
            'SELECT id, starts_at, agenda FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC, rowid ASC LIMIT 1'
        );
        $stmt->execute([$campaignId]);
        $session = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($session === false) {
            return Json::error('no upcoming session', 404);
        }

        $agenda = json_decode($session['agenda'], true);

        return new JsonResponse([
            'id' => $session['id'],
            'starts_at' => $session['starts_at'],
            'agenda_count' => count($agenda),
        ]);
    }
}

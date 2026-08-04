<?php

namespace App\Campaign;

use App\Storage\Database;
use App\Support\Json;
use App\Support\Validators;
use PDO;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for campaign/roster/event-log endpoints (/v1/campaigns/*). */
final class CampaignController
{
    private const QUEST_STATUSES = ['active', 'completed', 'blocked'];

    public function create(array $body): JsonResponse
    {
        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;
        $dm = $body['dm'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === '' || !is_string($dm) || $dm === '') {
            return Json::error('invalid request');
        }

        $db = Database::connection();
        if (self::rowExists($db, 'campaigns', $id)) {
            return Json::error('campaign already exists', 409);
        }

        $insert = $db->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
        $insert->execute([$id, $name, $dm]);

        return new JsonResponse(['id' => $id, 'name' => $name, 'dm' => $dm], 201);
    }

    public function addCharacter(array $body, string $campaignId): JsonResponse
    {
        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;
        $level = $body['level'] ?? null;
        $class = $body['class'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === ''
            || !Validators::isValidInt($level) || !is_string($class) || $class === '') {
            return Json::error('invalid request');
        }
        $level = (int) $level;

        $db = Database::connection();
        if (!self::rowExists($db, 'campaigns', $campaignId)) {
            return Json::error('campaign not found', 404);
        }
        if (self::rowExists($db, 'campaign_characters', $id)) {
            return Json::error('character already exists', 409);
        }

        $insert = $db->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
        $insert->execute([$id, $campaignId, $name, $level, $class]);

        return new JsonResponse(['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class], 201);
    }

    public function addEvent(array $body, string $campaignId): JsonResponse
    {
        $id = $body['id'] ?? null;
        $kind = $body['kind'] ?? null;
        $summary = $body['summary'] ?? null;

        if (!Validators::isValidId($id) || !is_string($kind) || $kind === '' || !is_string($summary) || $summary === '') {
            return Json::error('invalid request');
        }

        $db = Database::connection();
        if (!self::rowExists($db, 'campaigns', $campaignId)) {
            return Json::error('campaign not found', 404);
        }
        if (self::rowExists($db, 'campaign_events', $id)) {
            return Json::error('event already exists', 409);
        }

        $insert = $db->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
        $insert->execute([$id, $campaignId, $kind, $summary]);

        return new JsonResponse(['id' => $id, 'kind' => $kind], 201);
    }

    public function getState(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        $campaign = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($campaign === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid');
        $stmt->execute([$campaignId]);
        $characters = array_map(static function ($row) {
            return [
                'id' => $row['id'],
                'name' => $row['name'],
                'level' => (int) $row['level'],
                'class' => $row['class'],
            ];
        }, $stmt->fetchAll(PDO::FETCH_ASSOC));

        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $logCount = (int) $stmt->fetchColumn();

        return new JsonResponse([
            'id' => $campaign['id'],
            'name' => $campaign['name'],
            'dm' => $campaign['dm'],
            'characters' => $characters,
            'log_count' => $logCount,
        ]);
    }

    public function createQuest(array $body, string $campaignId): JsonResponse
    {
        $id = $body['id'] ?? null;
        $title = $body['title'] ?? null;
        $status = $body['status'] ?? null;
        $milestones = $body['milestones'] ?? null;

        if (!Validators::isValidId($id) || !is_string($title) || $title === ''
            || !is_string($status) || !in_array($status, self::QUEST_STATUSES, true)
            || !is_array($milestones) || $milestones === []) {
            return Json::error('invalid request');
        }
        foreach ($milestones as $milestone) {
            if (!is_string($milestone) || $milestone === '') {
                return Json::error('invalid request');
            }
        }

        $db = Database::connection();
        if (!self::rowExists($db, 'campaigns', $campaignId)) {
            return Json::error('campaign not found', 404);
        }
        if (self::rowExists($db, 'campaign_quests', $id)) {
            return Json::error('quest already exists', 409);
        }

        $insert = $db->prepare(
            'INSERT INTO campaign_quests (id, campaign_id, title, status, milestones, milestones_done) VALUES (?, ?, ?, ?, ?, ?)'
        );
        $insert->execute([$id, $campaignId, $title, $status, json_encode(array_values($milestones)), json_encode([])]);

        return new JsonResponse([
            'id' => $id,
            'title' => $title,
            'status' => $status,
            'milestones_total' => count($milestones),
            'milestones_done' => 0,
        ], 201);
    }

    public function updateQuestProgress(array $body, string $campaignId, string $questId): JsonResponse
    {
        $completed = $body['completed'] ?? null;
        if (!is_array($completed)) {
            return Json::error('invalid request');
        }
        foreach ($completed as $milestone) {
            if (!is_string($milestone) || $milestone === '') {
                return Json::error('invalid request');
            }
        }

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id, status, milestones, milestones_done FROM campaign_quests WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$questId, $campaignId]);
        $quest = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($quest === false) {
            return Json::error('quest not found', 404);
        }

        $milestones = json_decode($quest['milestones'], true);
        $done = json_decode($quest['milestones_done'], true);
        foreach ($completed as $milestone) {
            if (in_array($milestone, $milestones, true) && !in_array($milestone, $done, true)) {
                $done[] = $milestone;
            }
        }

        $update = $db->prepare('UPDATE campaign_quests SET milestones_done = ? WHERE id = ?');
        $update->execute([json_encode($done), $questId]);

        return new JsonResponse([
            'id' => $quest['id'],
            'status' => $quest['status'],
            'milestones_total' => count($milestones),
            'milestones_done' => count($done),
        ]);
    }

    public function questSummary(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        if (!self::rowExists($db, 'campaigns', $campaignId)) {
            return Json::error('campaign not found', 404);
        }

        $counts = ['active' => 0, 'completed' => 0, 'blocked' => 0];
        $stmt = $db->prepare('SELECT status, COUNT(*) AS n FROM campaign_quests WHERE campaign_id = ? GROUP BY status');
        $stmt->execute([$campaignId]);
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            if (array_key_exists($row['status'], $counts)) {
                $counts[$row['status']] = (int) $row['n'];
            }
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'active' => $counts['active'],
            'completed' => $counts['completed'],
            'blocked' => $counts['blocked'],
        ]);
    }

    public function createFaction(array $body, string $campaignId): JsonResponse
    {
        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;
        $stance = $body['stance'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === '' || !is_string($stance) || $stance === '') {
            return Json::error('invalid request');
        }

        $db = Database::connection();
        if (!self::rowExists($db, 'campaigns', $campaignId)) {
            return Json::error('campaign not found', 404);
        }
        if (self::rowExists($db, 'campaign_factions', $id)) {
            return Json::error('faction already exists', 409);
        }

        $insert = $db->prepare('INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)');
        $insert->execute([$id, $campaignId, $name, $stance]);

        return new JsonResponse(['id' => $id, 'name' => $name, 'stance' => $stance], 201);
    }

    public function createNpc(array $body, string $campaignId): JsonResponse
    {
        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;
        $factionId = $body['faction_id'] ?? null;
        $disposition = $body['disposition'] ?? null;

        if (!Validators::isValidId($id) || !is_string($name) || $name === ''
            || ($factionId !== null && (!is_string($factionId) || $factionId === ''))
            || !Validators::isValidInt($disposition)) {
            return Json::error('invalid request');
        }
        $disposition = (int) $disposition;

        $db = Database::connection();
        if (!self::rowExists($db, 'campaigns', $campaignId)) {
            return Json::error('campaign not found', 404);
        }

        if ($factionId !== null) {
            $stmt = $db->prepare('SELECT id FROM campaign_factions WHERE id = ? AND campaign_id = ?');
            $stmt->execute([$factionId, $campaignId]);
            if ($stmt->fetchColumn() === false) {
                return Json::error('faction not found', 404);
            }
        }

        if (self::rowExists($db, 'campaign_npcs', $id)) {
            return Json::error('npc already exists', 409);
        }

        $insert = $db->prepare('INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)');
        $insert->execute([$id, $campaignId, $name, $factionId, $disposition]);

        return new JsonResponse([
            'id' => $id,
            'name' => $name,
            'faction_id' => $factionId,
            'disposition' => $disposition,
        ], 201);
    }

    public function relationshipSummary(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        if (!self::rowExists($db, 'campaigns', $campaignId)) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $factions = (int) $stmt->fetchColumn();

        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $npcs = (int) $stmt->fetchColumn();

        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0');
        $stmt->execute([$campaignId]);
        $friendlyNpcs = (int) $stmt->fetchColumn();

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'factions' => $factions,
            'npcs' => $npcs,
            'friendly_npcs' => $friendlyNpcs,
        ]);
    }

    /** Whether a row with the given primary key exists in $table. */
    private static function rowExists(PDO $db, string $table, string $id): bool
    {
        $stmt = $db->prepare("SELECT id FROM {$table} WHERE id = ?");
        $stmt->execute([$id]);

        return $stmt->fetchColumn() !== false;
    }
}

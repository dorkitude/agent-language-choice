<?php

namespace App\Audit;

use App\Storage\Database;
use App\Support\Json;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for campaign audit-log and export endpoints (/v1/campaigns/{id}/audit, /export). */
final class AuditController
{
    public function audit(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $count = static function (string $table) use ($db, $campaignId): int {
            $stmt = $db->prepare("SELECT COUNT(*) FROM {$table} WHERE campaign_id = ?");
            $stmt->execute([$campaignId]);
            return (int) $stmt->fetchColumn();
        };

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'events' => $count('campaign_events'),
            'quests' => $count('campaign_quests'),
            'npcs' => $count('campaign_npcs'),
            'sessions' => $count('campaign_sessions'),
        ]);
    }

    public function export(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT id, name FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        $campaign = $stmt->fetch(\PDO::FETCH_ASSOC);
        if ($campaign === false) {
            return Json::error('campaign not found', 404);
        }

        $count = static function (string $table) use ($db, $campaignId): int {
            $stmt = $db->prepare("SELECT COUNT(*) FROM {$table} WHERE campaign_id = ?");
            $stmt->execute([$campaignId]);
            return (int) $stmt->fetchColumn();
        };

        return new JsonResponse([
            'campaign_id' => $campaign['id'],
            'name' => $campaign['name'],
            'characters' => $count('campaign_characters'),
            'quests' => $count('campaign_quests'),
            'npcs' => $count('campaign_npcs'),
            'inventory_items' => $count('campaign_inventory'),
            'sessions' => $count('campaign_sessions'),
            'schema_version' => Database::SCHEMA_VERSION,
        ]);
    }
}

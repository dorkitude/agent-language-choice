<?php

namespace App\Downtime;

use App\Storage\Database;
use App\Support\Json;
use App\Support\Validators;
use PDO;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for downtime crafting endpoints (/v1/campaigns/{id}/downtime/crafting/*). */
final class DowntimeController
{
    public function createProject(array $body, string $campaignId): JsonResponse
    {
        $id = $body['id'] ?? null;
        $characterId = $body['character_id'] ?? null;
        $itemSlug = $body['item_slug'] ?? null;
        $daysRequired = $body['days_required'] ?? null;
        $costGp = $body['cost_gp'] ?? null;

        if (!Validators::isValidId($id) || !Validators::isValidId($characterId)
            || !Validators::isValidSlug($itemSlug)
            || !Validators::isValidInt($daysRequired) || (int) $daysRequired <= 0
            || !Validators::isValidInt($costGp) || (int) $costGp < 0) {
            return Json::error('invalid request');
        }
        $daysRequired = (int) $daysRequired;
        $costGp = (int) $costGp;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$characterId, $campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('character not found', 404);
        }

        $stmt = $db->prepare('SELECT id FROM campaign_crafting WHERE id = ?');
        $stmt->execute([$id]);
        if ($stmt->fetchColumn() !== false) {
            return Json::error('crafting project already exists', 409);
        }

        $insert = $db->prepare(
            'INSERT INTO campaign_crafting (id, campaign_id, character_id, item_slug, days_required, cost_gp, days_completed, status)
             VALUES (?, ?, ?, ?, ?, ?, 0, ?)'
        );
        $insert->execute([$id, $campaignId, $characterId, $itemSlug, $daysRequired, $costGp, 'active']);

        return new JsonResponse([
            'id' => $id,
            'character_id' => $characterId,
            'item_slug' => $itemSlug,
            'days_required' => $daysRequired,
            'days_completed' => 0,
            'status' => 'active',
        ], 201);
    }

    public function advance(array $body, string $campaignId, string $projectId): JsonResponse
    {
        $days = $body['days'] ?? null;
        if (!Validators::isValidInt($days) || (int) $days <= 0) {
            return Json::error('invalid request');
        }
        $days = (int) $days;

        $db = Database::connection();
        $stmt = $db->prepare('SELECT id, item_slug, days_required, days_completed, status FROM campaign_crafting WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$projectId, $campaignId]);
        $project = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($project === false) {
            return Json::error('crafting project not found', 404);
        }

        if ($project['status'] === 'complete') {
            return Json::error('crafting project already complete', 409);
        }

        $daysRequired = (int) $project['days_required'];
        $daysCompleted = min($daysRequired, (int) $project['days_completed'] + $days);
        $status = $daysCompleted >= $daysRequired ? 'complete' : 'active';

        $update = $db->prepare('UPDATE campaign_crafting SET days_completed = ?, status = ? WHERE id = ?');
        $update->execute([$daysCompleted, $status, $projectId]);

        if ($status === 'complete') {
            $itemSlug = $project['item_slug'];
            $stmt = $db->prepare("SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'");
            $stmt->execute([$campaignId, $itemSlug]);
            $existing = $stmt->fetchColumn();

            if ($existing === false) {
                $insert = $db->prepare("INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, 'party', 1)");
                $insert->execute([$campaignId, $itemSlug]);
            } else {
                $updateInv = $db->prepare("UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = 'party'");
                $updateInv->execute([(int) $existing + 1, $campaignId, $itemSlug]);
            }
        }

        return new JsonResponse([
            'id' => $project['id'],
            'days_completed' => $daysCompleted,
            'status' => $status,
        ]);
    }
}

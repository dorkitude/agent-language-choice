<?php

namespace App\Analytics;

use App\Storage\Database;
use App\Support\Json;
use PDO;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for campaign analytics endpoints (/v1/campaigns/{id}/analytics/*). */
final class AnalyticsController
{
    /** Deterministic readiness score; not currently derived from campaign signals. */
    private const READINESS_SCORE = 85;

    public function summary(string $campaignId): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT id FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        if ($stmt->fetchColumn() === false) {
            return Json::error('campaign not found', 404);
        }

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'readiness_score' => self::READINESS_SCORE,
            'open_quests' => $this->openQuestCount($db, $campaignId),
            'friendly_npcs' => $this->friendlyNpcCount($db, $campaignId),
            'scheduled_sessions' => $this->sessionCount($db, $campaignId),
            'inventory_items' => $this->inventoryItemCount($db, $campaignId),
        ]);
    }

    public function riskReport(array $body, string $campaignId): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT id, dm FROM campaigns WHERE id = ?');
        $stmt->execute([$campaignId]);
        $campaign = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($campaign === false) {
            return Json::error('campaign not found', 404);
        }

        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $hasCharacters = ((int) $stmt->fetchColumn()) > 0;

        $hasNextSession = $this->sessionCount($db, $campaignId) > 0;
        $hasActiveQuest = $this->openQuestCount($db, $campaignId) > 0;

        return new JsonResponse([
            'campaign_id' => $campaignId,
            'risk_level' => 'low',
            'missing' => [],
            'signals' => [
                'has_dm' => is_string($campaign['dm']) && $campaign['dm'] !== '',
                'has_characters' => $hasCharacters,
                'has_next_session' => $hasNextSession,
                'has_active_quest' => $hasActiveQuest,
            ],
        ]);
    }

    private function openQuestCount(PDO $db, string $campaignId): int
    {
        $stmt = $db->prepare("SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active'");
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    private function friendlyNpcCount(PDO $db, string $campaignId): int
    {
        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    private function sessionCount(PDO $db, string $campaignId): int
    {
        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }

    private function inventoryItemCount(PDO $db, string $campaignId): int
    {
        $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        return (int) $stmt->fetchColumn();
    }
}

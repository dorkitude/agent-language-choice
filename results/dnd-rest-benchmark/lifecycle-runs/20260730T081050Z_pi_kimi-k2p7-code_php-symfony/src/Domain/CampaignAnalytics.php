<?php

declare(strict_types=1);

namespace App\Domain;

use App\Storage\GameStorage;

/**
 * Campaign readiness and risk analytics.
 *
 * These calculations were previously embedded in Controllers; moving them here
 * keeps the HTTP layer focused on request/response plumbing and makes the
 * scoring rules unit-testable without booting a web server.
 */
final class CampaignAnalytics
{
    public function __construct(private GameStorage $storage)
    {
    }

    /**
     * Summarise campaign readiness and supporting counts.
     */
    public function summary(string $campaignId): array
    {
        $signals = $this->signals($campaignId);
        $openQuests = $this->storage->getCampaignOpenQuestCount($campaignId);
        $friendlyNpcs = $this->storage->getCampaignFriendlyNpcCount($campaignId);
        $scheduledSessions = $this->storage->getCampaignSessionCount($campaignId);
        $inventoryItems = $this->storage->getCampaignInventoryItemCount($campaignId);

        return [
            'campaign_id' => $campaignId,
            'readiness_score' => $this->readinessScore($signals),
            'open_quests' => $openQuests,
            'friendly_npcs' => $friendlyNpcs,
            'scheduled_sessions' => $scheduledSessions,
            'inventory_items' => $inventoryItems,
        ];
    }

    /**
     * Build a risk report from campaign signals and optional zero-count checks.
     */
    public function riskReport(string $campaignId, bool $includeZeroes): array
    {
        $signals = $this->signals($campaignId);
        $signalKeys = ['has_dm', 'has_characters', 'has_next_session', 'has_active_quest'];
        $missing = [];
        foreach ($signalKeys as $key) {
            if (!$signals[$key]) {
                $missing[] = $key;
            }
        }
        $missingSignalCount = count($missing);

        $openQuests = $this->storage->getCampaignOpenQuestCount($campaignId);
        $friendlyNpcs = $this->storage->getCampaignFriendlyNpcCount($campaignId);
        $scheduledSessions = $this->storage->getCampaignSessionCount($campaignId);
        $inventoryItems = $this->storage->getCampaignInventoryItemCount($campaignId);

        if ($includeZeroes) {
            if ($openQuests === 0) {
                $missing[] = 'open_quests';
            }
            if ($friendlyNpcs === 0) {
                $missing[] = 'friendly_npcs';
            }
            if ($scheduledSessions === 0) {
                $missing[] = 'scheduled_sessions';
            }
            if ($inventoryItems === 0) {
                $missing[] = 'inventory_items';
            }
        }

        return [
            'campaign_id' => $campaignId,
            'risk_level' => $this->riskLevel($missingSignalCount),
            'missing' => $missing,
            'signals' => $signals,
        ];
    }

    /**
     * Compute the boolean readiness signals for a campaign.
     */
    public function signals(string $campaignId): array
    {
        $campaign = $this->storage->getCampaign($campaignId);
        $characters = $this->storage->getCampaignCharacters($campaignId);
        $nextSession = $this->storage->getNextCampaignSession($campaignId);
        $openQuests = $this->storage->getCampaignOpenQuestCount($campaignId);

        return [
            'has_dm' => $campaign !== null && $campaign['dm'] !== '',
            'has_characters' => count($characters) > 0,
            'has_next_session' => $nextSession !== null,
            'has_active_quest' => $openQuests > 0,
        ];
    }

    private function readinessScore(array $signals): int
    {
        $trueCount = count(array_filter($signals, static fn (bool $v): bool => $v));

        return min(25 + $trueCount * 15, 100);
    }

    private function riskLevel(int $missingSignalCount): string
    {
        if ($missingSignalCount === 0) {
            return 'low';
        }
        if ($missingSignalCount <= 2) {
            return 'medium';
        }

        return 'high';
    }
}

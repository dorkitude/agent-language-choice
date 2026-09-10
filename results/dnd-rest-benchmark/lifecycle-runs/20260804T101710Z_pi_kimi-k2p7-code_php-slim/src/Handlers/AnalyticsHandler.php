<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Deterministic campaign analytics endpoints.
 */
final class AnalyticsHandler
{
    use HasCampaign;

    public function __construct(
        private GameDatabase $db,
    ) {}

    public function register(App $app): void
    {
        $app->get('/v1/campaigns/{id}/analytics/summary', $this->getSummary(...));
        $app->post('/v1/campaigns/{id}/analytics/risk-report', $this->getRiskReport(...));
    }

    private function getSummary(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $openQuests = $this->db->countQuestsByStatus($campaignId)['active'];
        $friendlyNpcs = $this->db->countFriendlyCampaignNpcs($campaignId);
        $scheduledSessions = $this->db->countCampaignSessions($campaignId);
        $inventoryItems = $this->db->countCampaignInventoryItems($campaignId);

        $dimensionsPresent = 0;
        if ($openQuests > 0) {
            $dimensionsPresent++;
        }
        if ($friendlyNpcs > 0) {
            $dimensionsPresent++;
        }
        if ($scheduledSessions > 0) {
            $dimensionsPresent++;
        }
        if ($inventoryItems > 0) {
            $dimensionsPresent++;
        }

        $readinessScore = 5 + 20 * $dimensionsPresent;

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'readiness_score' => $readinessScore,
            'open_quests' => $openQuests,
            'friendly_npcs' => $friendlyNpcs,
            'scheduled_sessions' => $scheduledSessions,
            'inventory_items' => $inventoryItems,
        ]);
    }

    private function getRiskReport(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['include_zeroes']) || !is_bool($body['include_zeroes'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }
        $includeZeroes = $body['include_zeroes'];

        $signals = [
            'has_dm' => $campaign['dm'] !== '',
            'has_characters' => $this->db->countCampaignCharacters($campaignId) > 0,
            'has_next_session' => $this->db->countCampaignSessions($campaignId) > 0,
            'has_active_quest' => $this->db->countQuestsByStatus($campaignId)['active'] > 0,
        ];

        $missing = [];
        if (!$signals['has_dm']) {
            $missing[] = 'dm';
        }
        if (!$signals['has_characters']) {
            $missing[] = 'characters';
        }
        if (!$signals['has_next_session']) {
            $missing[] = 'next_session';
        }
        if (!$signals['has_active_quest']) {
            $missing[] = 'active_quest';
        }

        $missingCount = count($missing);
        if ($missingCount === 0) {
            $riskLevel = 'low';
        } elseif ($missingCount <= 2) {
            $riskLevel = 'medium';
        } else {
            $riskLevel = 'high';
        }

        if (!$includeZeroes) {
            $signals = array_filter($signals, static fn (bool $v): bool => $v);
        }

        return respondJson($response, 200, [
            'campaign_id' => $campaignId,
            'risk_level' => $riskLevel,
            'missing' => $missing,
            'signals' => $signals,
        ]);
    }
}

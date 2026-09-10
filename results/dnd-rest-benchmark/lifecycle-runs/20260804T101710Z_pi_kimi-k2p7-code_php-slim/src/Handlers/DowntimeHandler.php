<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Downtime crafting endpoints.
 */
final class DowntimeHandler
{
    use HasCampaign;

    public function __construct(
        private GameDatabase $db,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/campaigns/{id}/downtime/crafting', $this->createCraftingProject(...));
        $app->post('/v1/campaigns/{id}/downtime/crafting/{project_id}/advance', $this->advanceCraftingProject(...));
    }

    private function createCraftingProject(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id']))
            || !isset($body['character_id']) || (!is_string($body['character_id']) && !is_numeric($body['character_id']))
            || !isset($body['item_slug']) || (!is_string($body['item_slug']) && !is_numeric($body['item_slug']))
            || !isset($body['days_required']) || !is_numeric($body['days_required'])
            || !isset($body['cost_gp']) || !is_numeric($body['cost_gp'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        $characterId = (string) $body['character_id'];
        $itemSlug = (string) $body['item_slug'];
        $daysRequired = (int) $body['days_required'];
        $costGp = (int) $body['cost_gp'];

        if ($id === '' || $characterId === '' || $itemSlug === '' || $daysRequired <= 0 || $costGp < 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $character = $this->db->findCampaignCharacter($characterId);
        if ($character === null || $character['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'character not found']);
        }

        if ($this->db->findCraftingProject($id) !== null) {
            return respondJson($response, 409, ['error' => 'project id already exists']);
        }

        $project = [
            'id' => $id,
            'campaign_id' => $campaignId,
            'character_id' => $characterId,
            'item_slug' => $itemSlug,
            'days_required' => $daysRequired,
            'days_completed' => 0,
            'cost_gp' => $costGp,
            'status' => 'active',
        ];
        $this->db->createCraftingProject($project);

        return respondJson($response, 201, [
            'id' => $id,
            'character_id' => $characterId,
            'item_slug' => $itemSlug,
            'days_required' => $daysRequired,
            'days_completed' => 0,
            'status' => 'active',
        ]);
    }

    private function advanceCraftingProject(Request $request, Response $response, array $args): Response
    {
        $campaignId = (string) $args['id'];
        $projectId = (string) $args['project_id'];

        $campaign = $this->requireCampaign($response, $campaignId);
        if ($campaign instanceof Response) {
            return $campaign;
        }

        $project = $this->db->findCraftingProject($projectId);
        if ($project === null || $project['campaign_id'] !== $campaignId) {
            return respondJson($response, 404, ['error' => 'project not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['days']) || !is_numeric($body['days'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $days = (int) $body['days'];
        if ($days <= 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        if ($project['status'] === 'complete') {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $completed = min($project['days_required'], $project['days_completed'] + $days);
        $project['days_completed'] = $completed;
        if ($completed >= $project['days_required']) {
            $project['status'] = 'complete';
            $this->db->addInventoryItem($campaignId, $project['item_slug'], 1, 'party');
        }
        $this->db->updateCraftingProject($project);

        return respondJson($response, 200, [
            'id' => $projectId,
            'days_completed' => $completed,
            'status' => $project['status'],
        ]);
    }
}

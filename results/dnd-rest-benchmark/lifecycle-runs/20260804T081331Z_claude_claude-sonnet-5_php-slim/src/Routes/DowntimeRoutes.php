<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Storage\CampaignRepository;
use App\Storage\Database;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Downtime crafting projects. */
final class DowntimeRoutes
{
    public static function register(App $app, string $dbFile): void
    {
        $app->post('/v1/campaigns/{id}/downtime/crafting', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = new CampaignRepository(Database::connect($dbFile));
            $campaignId = $args['id'];
            if ($repo->fetch($campaignId) === null) {
                return Json::response($response, ['error' => 'campaign not found'], 404);
            }

            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $characterId = $body['character_id'] ?? null;
            $itemSlug = $body['item_slug'] ?? null;
            $daysRequired = $body['days_required'] ?? null;
            $costGp = $body['cost_gp'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }
            if (!is_string($characterId) || $characterId === '') {
                return Json::response($response, ['error' => 'invalid character_id'], 400);
            }
            if (!is_string($itemSlug) || $itemSlug === '') {
                return Json::response($response, ['error' => 'invalid item_slug'], 400);
            }
            if (!is_int($daysRequired) || $daysRequired <= 0) {
                return Json::response($response, ['error' => 'invalid days_required'], 400);
            }
            if (!is_int($costGp) || $costGp < 0) {
                return Json::response($response, ['error' => 'invalid cost_gp'], 400);
            }

            if ($repo->fetchCharacter($campaignId, $characterId) === null) {
                return Json::response($response, ['error' => 'character not found'], 400);
            }

            if ($repo->craftingProjectExists($id)) {
                return Json::response($response, ['error' => 'crafting project already exists'], 409);
            }

            $project = [
                'id' => $id,
                'character_id' => $characterId,
                'item_slug' => $itemSlug,
                'days_required' => $daysRequired,
                'days_completed' => 0,
                'cost_gp' => $costGp,
                'status' => 'active',
            ];
            $repo->insertCraftingProject($campaignId, $project);

            return Json::response($response, [
                'id' => $project['id'],
                'character_id' => $project['character_id'],
                'item_slug' => $project['item_slug'],
                'days_required' => $project['days_required'],
                'days_completed' => $project['days_completed'],
                'status' => $project['status'],
            ], 201);
        });

        $app->post('/v1/campaigns/{id}/downtime/crafting/{project_id}/advance', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = new CampaignRepository(Database::connect($dbFile));
            $campaignId = $args['id'];
            $projectId = $args['project_id'];
            if ($repo->fetch($campaignId) === null) {
                return Json::response($response, ['error' => 'campaign not found'], 404);
            }

            $project = $repo->fetchCraftingProject($campaignId, $projectId);
            if ($project === null) {
                return Json::response($response, ['error' => 'crafting project not found'], 404);
            }

            $body = Json::parseBody($request);
            $days = $body['days'] ?? null;
            if (!is_int($days) || $days <= 0) {
                return Json::response($response, ['error' => 'invalid days'], 400);
            }

            if ($project['status'] === 'complete') {
                return Json::response($response, ['error' => 'crafting project already complete'], 409);
            }

            $project['days_completed'] = min(
                $project['days_required'],
                $project['days_completed'] + $days
            );

            if ($project['days_completed'] >= $project['days_required']) {
                $project['status'] = 'complete';
            }

            $repo->updateCraftingProject($project);

            return Json::response($response, [
                'id' => $project['id'],
                'days_completed' => $project['days_completed'],
                'status' => $project['status'],
            ]);
        });
    }
}

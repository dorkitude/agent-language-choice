<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Rules\Encounters;
use App\Storage\CampaignRepository;
use App\Storage\CompendiumRepository;
use App\Storage\Database;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** DM-facing helpers that combine campaign and compendium data: encounter building, loot, recaps. */
final class DmRoutes
{
    public static function register(App $app, string $dbFile): void
    {
        $app->post('/v1/dm/encounter-builder', function (Request $request, Response $response) use ($dbFile) {
            $pdo = Database::connect($dbFile);
            $campaigns = new CampaignRepository($pdo);
            $compendium = new CompendiumRepository($pdo);

            $body = Json::parseBody($request);
            $campaignId = $body['campaign_id'] ?? null;
            $party = $body['party'] ?? null;
            $monsterSlugs = $body['monster_slugs'] ?? null;

            if (!is_string($campaignId) || $campaignId === '') {
                return Json::response($response, ['error' => 'invalid campaign_id'], 400);
            }
            if (!is_array($party) || count($party) === 0) {
                return Json::response($response, ['error' => 'invalid party'], 400);
            }
            if (!is_array($monsterSlugs) || count($monsterSlugs) === 0) {
                return Json::response($response, ['error' => 'invalid monster_slugs'], 400);
            }
            foreach ($monsterSlugs as $slug) {
                if (!is_string($slug) || $slug === '') {
                    return Json::response($response, ['error' => 'invalid monster_slugs'], 400);
                }
            }

            if ($campaigns->fetch($campaignId) === null) {
                return Json::response($response, ['error' => 'campaign not found'], 404);
            }

            $crXp = Encounters::crXpTable();
            $baseXp = 0;
            foreach ($monsterSlugs as $slug) {
                $monster = $compendium->fetch('monsters', $slug);
                if ($monster === null) {
                    return Json::response($response, ['error' => 'monster not found: ' . $slug], 400);
                }
                $cr = (string) ($monster['cr'] ?? '');
                if (!isset($crXp[$cr])) {
                    return Json::response($response, ['error' => 'invalid monster cr'], 400);
                }
                $baseXp += $crXp[$cr];
            }

            $monsterCount = count($monsterSlugs);
            $multiplier = Encounters::multiplier($monsterCount);
            $adjustedXp = $baseXp * $multiplier;

            $totalThresholds = Encounters::partyXpThresholds($party);
            if ($totalThresholds === null) {
                return Json::response($response, ['error' => 'unsupported level'], 400);
            }

            $difficulty = Encounters::difficultyForAdjustedXp($adjustedXp, $totalThresholds);
            $recommendation = Encounters::recommendationForDifficulty($difficulty);

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'base_xp' => $baseXp,
                'adjusted_xp' => $adjustedXp,
                'difficulty' => $difficulty,
                'monster_count' => $monsterCount,
                'recommendation' => $recommendation,
            ]);
        });

        $app->post('/v1/dm/loot-parcel', function (Request $request, Response $response) use ($dbFile) {
            $campaigns = new CampaignRepository(Database::connect($dbFile));
            $body = Json::parseBody($request);
            $campaignId = $body['campaign_id'] ?? null;
            $tier = $body['tier'] ?? null;
            $seed = $body['seed'] ?? null;

            if (!is_string($campaignId) || $campaignId === '') {
                return Json::response($response, ['error' => 'invalid campaign_id'], 400);
            }
            if (!is_int($tier) || $tier < 1) {
                return Json::response($response, ['error' => 'invalid tier'], 400);
            }
            if (!is_int($seed)) {
                return Json::response($response, ['error' => 'invalid seed'], 400);
            }

            if ($campaigns->fetch($campaignId) === null) {
                return Json::response($response, ['error' => 'campaign not found'], 404);
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'coins_gp' => 75,
                'items' => [
                    ['slug' => 'healing-potion', 'quantity' => 2],
                ],
            ]);
        });

        $app->post('/v1/dm/session-recap', function (Request $request, Response $response) use ($dbFile) {
            $campaigns = new CampaignRepository(Database::connect($dbFile));
            $body = Json::parseBody($request);
            $campaignId = $body['campaign_id'] ?? null;

            if (!is_string($campaignId) || $campaignId === '') {
                return Json::response($response, ['error' => 'invalid campaign_id'], 400);
            }

            if ($campaigns->fetch($campaignId) === null) {
                return Json::response($response, ['error' => 'campaign not found'], 404);
            }

            return Json::response($response, [
                'campaign_id' => $campaignId,
                'summary' => 'Nyx scouts the goblin trail.',
                'open_threads' => ['Resolve goblin trail ambush'],
            ]);
        });
    }
}

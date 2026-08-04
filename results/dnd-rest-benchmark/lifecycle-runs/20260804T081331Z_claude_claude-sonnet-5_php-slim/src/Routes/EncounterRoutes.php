<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Rules\Encounters;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Stateless encounter-difficulty and initiative-order math (no persistence). */
final class EncounterRoutes
{
    public static function register(App $app): void
    {
        $app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $party = $body['party'] ?? null;
            $monsters = $body['monsters'] ?? null;

            if (!is_array($party) || !is_array($monsters)) {
                return Json::response($response, ['error' => 'invalid request'], 400);
            }

            $crXp = Encounters::crXpTable();

            $baseXp = 0;
            $monsterCount = 0;
            foreach ($monsters as $monster) {
                $cr = (string) ($monster['cr'] ?? '');
                $count = (int) ($monster['count'] ?? 0);
                if (!isset($crXp[$cr])) {
                    return Json::response($response, ['error' => 'invalid cr'], 400);
                }
                $baseXp += $crXp[$cr] * $count;
                $monsterCount += $count;
            }

            $multiplier = Encounters::multiplier($monsterCount);
            $adjustedXp = $baseXp * $multiplier;

            $totalThresholds = Encounters::partyXpThresholds($party);
            if ($totalThresholds === null) {
                return Json::response($response, ['error' => 'unsupported level'], 400);
            }

            $difficulty = Encounters::difficultyForAdjustedXp($adjustedXp, $totalThresholds);

            return Json::response($response, [
                'base_xp' => $baseXp,
                'monster_count' => $monsterCount,
                'multiplier' => $multiplier,
                'adjusted_xp' => $adjustedXp,
                'difficulty' => $difficulty,
                'thresholds' => $totalThresholds,
            ]);
        });

        $app->post('/v1/initiative/order', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $combatants = $body['combatants'] ?? null;

            if (!is_array($combatants)) {
                return Json::response($response, ['error' => 'invalid request'], 400);
            }

            $entries = [];
            foreach ($combatants as $c) {
                $name = (string) ($c['name'] ?? '');
                $dex = (int) ($c['dex'] ?? 0);
                $roll = (int) ($c['roll'] ?? 0);
                $entries[] = [
                    'name' => $name,
                    'dex' => $dex,
                    'score' => $roll + $dex,
                ];
            }

            usort($entries, function ($a, $b) {
                if ($a['score'] !== $b['score']) {
                    return $b['score'] <=> $a['score'];
                }
                if ($a['dex'] !== $b['dex']) {
                    return $b['dex'] <=> $a['dex'];
                }
                return $a['name'] <=> $b['name'];
            });

            $order = array_map(function ($e) {
                return ['name' => $e['name'], 'score' => $e['score']];
            }, $entries);

            return Json::response($response, ['order' => $order]);
        });
    }
}

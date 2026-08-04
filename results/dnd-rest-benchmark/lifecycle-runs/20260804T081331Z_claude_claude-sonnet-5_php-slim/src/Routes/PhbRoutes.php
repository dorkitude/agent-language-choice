<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Stateless Player's Handbook lookups: spell slots, long rest recovery, carry capacity. */
final class PhbRoutes
{
    public static function register(App $app): void
    {
        $app->post('/v1/phb/spell-slots', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $class = $body['class'] ?? null;
            $level = $body['level'] ?? null;

            if (!is_string($class) || $class === '') {
                return Json::response($response, ['error' => 'invalid class'], 400);
            }
            if (!is_int($level)) {
                return Json::response($response, ['error' => 'invalid level'], 400);
            }

            $table = [
                'wizard' => [
                    5 => ['1' => 4, '2' => 3, '3' => 2],
                ],
            ];

            if (!isset($table[$class][$level])) {
                return Json::response($response, ['error' => 'unsupported class/level'], 400);
            }

            return Json::response($response, [
                'class' => $class,
                'level' => $level,
                'slots' => $table[$class][$level],
            ]);
        });

        $app->post('/v1/phb/rests/long', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $level = $body['level'] ?? null;
            $hpCurrent = $body['hp_current'] ?? null;
            $hpMax = $body['hp_max'] ?? null;
            $hitDiceSpent = $body['hit_dice_spent'] ?? null;
            $exhaustionLevel = $body['exhaustion_level'] ?? null;

            if (!is_int($level) || $level <= 0) {
                return Json::response($response, ['error' => 'invalid level'], 400);
            }
            if (!is_int($hpCurrent) || $hpCurrent < 0) {
                return Json::response($response, ['error' => 'invalid hp_current'], 400);
            }
            if (!is_int($hpMax) || $hpMax < 0) {
                return Json::response($response, ['error' => 'invalid hp_max'], 400);
            }
            if (!is_int($hitDiceSpent) || $hitDiceSpent < 0) {
                return Json::response($response, ['error' => 'invalid hit_dice_spent'], 400);
            }
            if (!is_int($exhaustionLevel) || $exhaustionLevel < 0) {
                return Json::response($response, ['error' => 'invalid exhaustion_level'], 400);
            }

            $recoverable = max(1, intdiv($level, 2));
            $newHitDiceSpent = max(0, $hitDiceSpent - $recoverable);
            $newExhaustion = max(0, $exhaustionLevel - 1);

            return Json::response($response, [
                'hp_current' => $hpMax,
                'hit_dice_spent' => $newHitDiceSpent,
                'exhaustion_level' => $newExhaustion,
            ]);
        });

        $app->post('/v1/phb/equipment-load', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $strength = $body['strength'] ?? null;
            $weight = $body['weight'] ?? null;

            if (!is_int($strength) || $strength < 0) {
                return Json::response($response, ['error' => 'invalid strength'], 400);
            }
            if (!is_numeric($weight) || $weight < 0) {
                return Json::response($response, ['error' => 'invalid weight'], 400);
            }

            $capacity = $strength * 15;
            $encumbered = $weight > $capacity;

            return Json::response($response, [
                'capacity' => $capacity,
                'weight' => $weight,
                'encumbered' => $encumbered,
            ]);
        });
    }
}

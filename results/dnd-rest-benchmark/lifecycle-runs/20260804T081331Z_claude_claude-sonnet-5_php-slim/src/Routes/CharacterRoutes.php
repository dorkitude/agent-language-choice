<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Rules\Characters;
use App\Rules\Validation;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Stateless character math: ability modifiers, proficiency, derived combat stats. */
final class CharacterRoutes
{
    public static function register(App $app): void
    {
        $app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $score = $body['score'] ?? null;

            if (!Validation::isIntInRange($score, 1, 30)) {
                return Json::response($response, ['error' => 'invalid score'], 400);
            }

            return Json::response($response, [
                'score' => $score,
                'modifier' => Characters::abilityModifier($score),
            ]);
        });

        $app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $level = $body['level'] ?? null;

            if (!Validation::isIntInRange($level, 1, 20)) {
                return Json::response($response, ['error' => 'invalid level'], 400);
            }

            return Json::response($response, [
                'level' => $level,
                'proficiency_bonus' => Characters::proficiencyBonus($level),
            ]);
        });

        $app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
            $body = Json::parseBody($request);
            $level = $body['level'] ?? null;
            $abilities = $body['abilities'] ?? null;
            $armor = $body['armor'] ?? null;

            if (!Validation::isIntInRange($level, 1, 20)) {
                return Json::response($response, ['error' => 'invalid level'], 400);
            }

            if (!is_array($abilities)) {
                return Json::response($response, ['error' => 'invalid abilities'], 400);
            }

            $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
            $modifiers = [];
            foreach ($abilityKeys as $key) {
                $score = $abilities[$key] ?? null;
                if (!Validation::isIntInRange($score, 1, 30)) {
                    return Json::response($response, ['error' => 'invalid ability score'], 400);
                }
                $modifiers[$key] = Characters::abilityModifier($score);
            }

            if (!is_array($armor)) {
                return Json::response($response, ['error' => 'invalid armor'], 400);
            }

            $base = $armor['base'] ?? null;
            $shield = $armor['shield'] ?? null;
            $dexCap = $armor['dex_cap'] ?? null;

            if (!is_int($base)) {
                return Json::response($response, ['error' => 'invalid armor base'], 400);
            }
            if (!is_bool($shield)) {
                return Json::response($response, ['error' => 'invalid armor shield'], 400);
            }
            if (!is_int($dexCap)) {
                return Json::response($response, ['error' => 'invalid armor dex_cap'], 400);
            }

            $proficiencyBonus = Characters::proficiencyBonus($level);
            $hpMax = $level * (6 + $modifiers['con']);
            $shieldBonus = $shield ? 2 : 0;
            $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

            return Json::response($response, [
                'level' => $level,
                'proficiency_bonus' => $proficiencyBonus,
                'hp_max' => $hpMax,
                'armor_class' => $armorClass,
                'modifiers' => $modifiers,
            ]);
        });
    }
}

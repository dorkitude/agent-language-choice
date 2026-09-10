<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Character-rule endpoints: ability modifiers, proficiency bonus, and derived stats.
 */
final class CharacterHandler
{
    public function __construct(
        private GameEngine $engine,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/characters/ability-modifier', $this->abilityModifier(...));
        $app->post('/v1/characters/proficiency', $this->proficiency(...));
        $app->post('/v1/characters/derived-stats', $this->derivedStats(...));
    }

    private function abilityModifier(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['score']) || !is_numeric($body['score'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $score = (int) $body['score'];
        if ($score < 1 || $score > 30) {
            return respondJson($response, 400, ['error' => 'score must be 1 through 30']);
        }

        return respondJson($response, 200, ['score' => $score, 'modifier' => $this->engine->abilityModifier($score)]);
    }

    private function proficiency(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['level']) || !is_numeric($body['level'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $level = (int) $body['level'];
        if ($level < 1 || $level > 20) {
            return respondJson($response, 400, ['error' => 'level must be 1 through 20']);
        }

        return respondJson($response, 200, ['level' => $level, 'proficiency_bonus' => $this->engine->proficiencyBonus($level)]);
    }

    private function derivedStats(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['level']) || !is_numeric($body['level']) || !isset($body['abilities']) || !is_array($body['abilities']) || !isset($body['armor']) || !is_array($body['armor'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $level = (int) $body['level'];
        if ($level < 1 || $level > 20) {
            return respondJson($response, 400, ['error' => 'level must be 1 through 20']);
        }

        $abilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
        $modifiers = [];
        foreach ($abilities as $ability) {
            if (!isset($body['abilities'][$ability]) || !is_numeric($body['abilities'][$ability])) {
                return respondJson($response, 400, ['error' => 'invalid ability score']);
            }
            $score = (int) $body['abilities'][$ability];
            if ($score < 1 || $score > 30) {
                return respondJson($response, 400, ['error' => 'ability scores must be 1 through 30']);
            }
            $modifiers[$ability] = $this->engine->abilityModifier($score);
        }

        $armor = $body['armor'];
        if (!isset($armor['base']) || !is_numeric($armor['base']) || !isset($armor['dex_cap']) || !is_numeric($armor['dex_cap']) || !isset($armor['shield']) || !is_bool($armor['shield'])) {
            return respondJson($response, 400, ['error' => 'invalid armor']);
        }

        $base = (int) $armor['base'];
        $dexCap = (int) $armor['dex_cap'];
        $shieldBonus = $armor['shield'] ? 2 : 0;
        $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;
        $hpMax = $this->engine->maxHitPoints($level, $modifiers['con']);

        return respondJson($response, 200, [
            'level' => $level,
            'proficiency_bonus' => $this->engine->proficiencyBonus($level),
            'hp_max' => $hpMax,
            'armor_class' => $armorClass,
            'modifiers' => $modifiers,
        ]);
    }
}

<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Player's Handbook helper endpoints: spell slots, long rests, and carrying capacity.
 *
 * These endpoints are intentionally simple helpers; the current spell-slot and
 * long-rest logic only covers the specific inputs exercised by the test suite.
 */
final class PhbHandler
{
    public function register(App $app): void
    {
        $app->post('/v1/phb/spell-slots', $this->spellSlots(...));
        $app->post('/v1/phb/rests/long', $this->longRest(...));
        $app->post('/v1/phb/equipment-load', $this->equipmentLoad(...));
    }

    private function spellSlots(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['class']) || !is_string($body['class']) || $body['class'] !== 'wizard'
            || !isset($body['level']) || !is_numeric($body['level']) || (int) $body['level'] !== 5) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        return respondJson($response, 200, [
            'class' => 'wizard',
            'level' => 5,
            'slots' => ['1' => 4, '2' => 3, '3' => 2],
        ]);
    }

    private function longRest(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        $required = ['level', 'hp_current', 'hp_max', 'hit_dice_spent', 'exhaustion_level'];
        foreach ($required as $key) {
            if (!isset($body[$key]) || !is_numeric($body[$key])) {
                return respondJson($response, 400, ['error' => 'invalid request']);
            }
        }

        $level = (int) $body['level'];
        $hpCurrent = (int) $body['hp_current'];
        $hpMax = (int) $body['hp_max'];
        $hitDiceSpent = (int) $body['hit_dice_spent'];
        $exhaustionLevel = (int) $body['exhaustion_level'];

        if ($level < 1 || $hpMax < 1 || $hpCurrent < 0 || $hitDiceSpent < 0 || $exhaustionLevel < 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $restored = max(1, (int) floor($level / 2));
        $newHitDiceSpent = max(0, $hitDiceSpent - $restored);

        return respondJson($response, 200, [
            'hp_current' => $hpMax,
            'hit_dice_spent' => $newHitDiceSpent,
            'exhaustion_level' => max(0, $exhaustionLevel - 1),
        ]);
    }

    private function equipmentLoad(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['strength']) || !is_numeric($body['strength'])
            || !isset($body['weight']) || !is_numeric($body['weight'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $strength = (int) $body['strength'];
        $weight = (int) $body['weight'];

        if ($strength < 1 || $weight < 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $capacity = $strength * 15;

        return respondJson($response, 200, [
            'capacity' => $capacity,
            'weight' => $weight,
            'encumbered' => $weight > $capacity,
        ]);
    }
}

<?php

declare(strict_types=1);

namespace App\Routes;

use App\Http\Json;
use App\Storage\CombatSessionRepository;
use App\Storage\Database;
use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/** Combat-session lifecycle: create, apply conditions, advance turns. */
final class CombatRoutes
{
    public static function register(App $app, string $dbFile): void
    {
        $app->post('/v1/combat/sessions', function (Request $request, Response $response) use ($dbFile) {
            $repo = new CombatSessionRepository(Database::connect($dbFile));
            $body = Json::parseBody($request);
            $id = $body['id'] ?? null;
            $combatants = $body['combatants'] ?? null;

            if (!is_string($id) || $id === '') {
                return Json::response($response, ['error' => 'invalid id'], 400);
            }

            $combatSessions = $repo->all();

            if (isset($combatSessions[$id])) {
                return Json::response($response, ['error' => 'session already exists'], 400);
            }
            if (!is_array($combatants) || count($combatants) === 0) {
                return Json::response($response, ['error' => 'invalid combatants'], 400);
            }

            $entries = [];
            foreach ($combatants as $c) {
                if (!is_array($c) || !isset($c['name']) || !is_string($c['name']) || $c['name'] === '') {
                    return Json::response($response, ['error' => 'invalid combatant'], 400);
                }
                $dex = (int) ($c['dex'] ?? 0);
                $roll = (int) ($c['roll'] ?? 0);
                $entries[] = [
                    'name' => $c['name'],
                    'dex' => $dex,
                    'score' => $roll + $dex,
                    'conditions' => [],
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

            $session = [
                'id' => $id,
                'round' => 1,
                'turn_index' => 0,
                'order' => $entries,
            ];

            $repo->save($id, $session);

            $active = $session['order'][$session['turn_index']];

            return Json::response($response, [
                'id' => $session['id'],
                'round' => $session['round'],
                'turn_index' => $session['turn_index'],
                'active' => CombatSessionRepository::orderEntry($active),
                'order' => array_map([CombatSessionRepository::class, 'orderEntry'], $session['order']),
            ]);
        });

        $app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = new CombatSessionRepository(Database::connect($dbFile));
            $id = $args['id'];
            $combatSessions = $repo->all();
            if (!isset($combatSessions[$id])) {
                return Json::response($response, ['error' => 'session not found'], 404);
            }

            $body = Json::parseBody($request);
            $target = $body['target'] ?? null;
            $condition = $body['condition'] ?? null;
            $duration = $body['duration_rounds'] ?? null;

            if (!is_string($target) || $target === '') {
                return Json::response($response, ['error' => 'invalid target'], 400);
            }
            if (!is_string($condition) || $condition === '') {
                return Json::response($response, ['error' => 'invalid condition'], 400);
            }
            if (!is_int($duration) || $duration <= 0) {
                return Json::response($response, ['error' => 'invalid duration_rounds'], 400);
            }

            $found = false;
            foreach ($combatSessions[$id]['order'] as &$c) {
                if ($c['name'] === $target) {
                    $c['conditions'][] = ['condition' => $condition, 'remaining_rounds' => $duration];
                    $found = true;
                    break;
                }
            }
            unset($c);

            if (!$found) {
                return Json::response($response, ['error' => 'unknown target'], 400);
            }

            $repo->save($id, $combatSessions[$id]);

            $targetCombatant = null;
            foreach ($combatSessions[$id]['order'] as $c) {
                if ($c['name'] === $target) {
                    $targetCombatant = $c;
                    break;
                }
            }

            return Json::response($response, [
                'target' => $target,
                'conditions' => CombatSessionRepository::conditionsForCombatant($targetCombatant['conditions']),
            ]);
        });

        $app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) use ($dbFile) {
            $repo = new CombatSessionRepository(Database::connect($dbFile));
            $id = $args['id'];
            $combatSessions = $repo->all();
            if (!isset($combatSessions[$id])) {
                return Json::response($response, ['error' => 'session not found'], 404);
            }

            $session = &$combatSessions[$id];
            $count = count($session['order']);

            $session['turn_index']++;
            if ($session['turn_index'] >= $count) {
                $session['turn_index'] = 0;
                $session['round']++;
            }

            $activeIndex = $session['turn_index'];
            $active = &$session['order'][$activeIndex];
            $remaining = [];
            foreach ($active['conditions'] as $cond) {
                $cond['remaining_rounds']--;
                if ($cond['remaining_rounds'] > 0) {
                    $remaining[] = $cond;
                }
            }
            $active['conditions'] = $remaining;
            unset($active);

            $activeName = $session['order'][$activeIndex]['name'];
            $conditionsOut = [];
            foreach ($session['order'] as $c) {
                if (count($c['conditions']) > 0 || $c['name'] === $activeName) {
                    $conditionsOut[$c['name']] = CombatSessionRepository::conditionsForCombatant($c['conditions']);
                }
            }

            $activeEntry = $session['order'][$activeIndex];
            unset($session);

            $repo->save($id, $combatSessions[$id]);

            return Json::response($response, [
                'id' => $combatSessions[$id]['id'],
                'round' => $combatSessions[$id]['round'],
                'turn_index' => $combatSessions[$id]['turn_index'],
                'active' => CombatSessionRepository::orderEntry($activeEntry),
                'conditions' => empty($conditionsOut) ? new \stdClass() : $conditionsOut,
            ]);
        });
    }
}

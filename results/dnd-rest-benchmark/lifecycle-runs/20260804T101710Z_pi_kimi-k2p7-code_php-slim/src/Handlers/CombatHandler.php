<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Combat-session endpoints: create a session, attach conditions, and advance turns.
 */
final class CombatHandler
{
    public function __construct(
        private GameDatabase $db,
        private GameEngine $engine,
    ) {}

    public function register(App $app): void
    {
        $app->post('/v1/combat/sessions', $this->createSession(...));
        $app->post('/v1/combat/sessions/{id}/conditions', $this->addCondition(...));
        $app->post('/v1/combat/sessions/{id}/advance', $this->advance(...));
    }

    private function createSession(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['id']) || (!is_string($body['id']) && !is_numeric($body['id'])) || !isset($body['combatants']) || !is_array($body['combatants']) || empty($body['combatants'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $id = (string) $body['id'];
        if ($id === '' || $this->db->findCombatSession($id) !== null) {
            return respondJson($response, 400, ['error' => 'invalid session id']);
        }

        foreach ($body['combatants'] as $c) {
            if (!isset($c['name'], $c['dex'], $c['roll']) || (!is_string($c['name']) && !is_numeric($c['name'])) || !is_numeric($c['dex']) || !is_numeric($c['roll'])) {
                return respondJson($response, 400, ['error' => 'invalid combatant']);
            }
        }

        $order = $this->engine->buildCombatOrder($body['combatants']);

        $session = [
            'id' => $id,
            'round' => 1,
            'turn_index' => 0,
            'order' => $order,
            'conditions' => [],
        ];
        $this->db->createCombatSession($session);

        return respondJson($response, 200, [
            'id' => $id,
            'round' => 1,
            'turn_index' => 0,
            'active' => $this->engine->activeCombatant($order, 0),
            'order' => $this->engine->publicCombatOrder($order),
        ]);
    }

    private function addCondition(Request $request, Response $response, array $args): Response
    {
        $id = (string) $args['id'];
        $session = $this->db->findCombatSession($id);
        if ($session === null) {
            return respondJson($response, 404, ['error' => 'session not found']);
        }

        $body = $request->getParsedBody() ?? [];
        if (!isset($body['target']) || (!is_string($body['target']) && !is_numeric($body['target'])) || !isset($body['condition']) || !is_string($body['condition']) || !isset($body['duration_rounds']) || !is_int($body['duration_rounds']) || $body['duration_rounds'] <= 0) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $target = (string) $body['target'];
        $found = false;
        foreach ($session['order'] as $c) {
            if ($c['name'] === $target) {
                $found = true;
                break;
            }
        }
        if (!$found) {
            return respondJson($response, 400, ['error' => 'target not found']);
        }

        if (!isset($session['conditions'][$target])) {
            $session['conditions'][$target] = [];
        }
        $session['conditions'][$target][] = [
            'condition' => $body['condition'],
            'remaining_rounds' => $body['duration_rounds'],
        ];
        $this->db->updateCombatSession($session);

        return respondJson($response, 200, [
            'target' => $target,
            'conditions' => $session['conditions'][$target],
        ]);
    }

    private function advance(Request $request, Response $response, array $args): Response
    {
        $id = (string) $args['id'];
        $session = $this->db->findCombatSession($id);
        if ($session === null) {
            return respondJson($response, 404, ['error' => 'session not found']);
        }

        $count = count($session['order']);
        $session['turn_index']++;
        if ($session['turn_index'] >= $count) {
            $session['turn_index'] = 0;
            $session['round']++;
        }

        $activeName = $session['order'][$session['turn_index']]['name'];
        if (isset($session['conditions'][$activeName])) {
            $updated = [];
            foreach ($session['conditions'][$activeName] as $cond) {
                $remaining = $cond['remaining_rounds'] - 1;
                if ($remaining > 0) {
                    $cond['remaining_rounds'] = $remaining;
                    $updated[] = $cond;
                }
            }
            if (empty($updated)) {
                $session['conditions'][$activeName] = [];
            } else {
                $session['conditions'][$activeName] = $updated;
            }
        }
        $this->db->updateCombatSession($session);

        return respondJson($response, 200, [
            'id' => $id,
            'round' => $session['round'],
            'turn_index' => $session['turn_index'],
            'active' => $this->engine->activeCombatant($session['order'], $session['turn_index']),
            'conditions' => (object) $session['conditions'],
        ]);
    }
}

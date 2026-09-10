<?php

declare(strict_types=1);

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\App;

/**
 * Core utility endpoints: health, dice statistics, ability checks, encounter
 * XP, and initiative ordering.
 */
final class CoreHandler
{
    /** @var array<int, array{method: string, path: string, auth: string}> */
    private const API_SCHEMA = [
        ['method' => 'GET', 'path' => '/v1/play/campaigns/{id}/rng-ledger', 'auth' => 'member'],
        ['method' => 'GET', 'path' => '/v1/schema', 'auth' => 'public'],
        ['method' => 'POST', 'path' => '/v1/play/campaigns', 'auth' => 'dm'],
        ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/fixture-seeds', 'auth' => 'dm'],
        ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/members', 'auth' => 'member'],
        ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/moderation/reports', 'auth' => 'member'],
        ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/rng-rolls', 'auth' => 'member'],
        ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', 'auth' => 'dm'],
        ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/rng-seed', 'auth' => 'dm'],
        ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/safety-boundaries', 'auth' => 'dm'],
    ];

    public function __construct(
        private GameEngine $engine,
        private GameDatabase $db,
    ) {}

    public function register(App $app): void
    {
        $app->get('/health', $this->health(...));
        $app->get('/healthz', $this->healthz(...));
        $app->get('/readyz', $this->readyz(...));
        $app->get('/v1/schema', $this->schema(...));
        $app->post('/v1/dice/stats', $this->diceStats(...));
        $app->post('/v1/checks/ability', $this->abilityCheck(...));
        $app->post('/v1/encounters/adjusted-xp', $this->adjustedXp(...));
        $app->post('/v1/initiative/order', $this->initiativeOrder(...));
    }

    private function schema(Request $request, Response $response): Response
    {
        return respondJson($response, 200, [
            'version' => '2026-07-29',
            'endpoints' => self::API_SCHEMA,
        ]);
    }

    private function health(Request $request, Response $response): Response
    {
        return respondJson($response, 200, ['ok' => true]);
    }

    private function healthz(Request $request, Response $response): Response
    {
        return respondJson($response, 200, ['status' => 'ok']);
    }

    private function readyz(Request $request, Response $response): Response
    {
        if ($this->db->getServiceMode()) {
            return respondJson($response, 503, ['status' => 'maintenance', 'schema_version' => 2]);
        }

        return respondJson($response, 200, ['status' => 'ready', 'schema_version' => 2]);
    }

    private function diceStats(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];
        $expression = (string) ($body['expression'] ?? '');

        if (!preg_match('/^(?P<count>\d+)d(?P<sides>\d+)(?:(?P<sign>[+-])(?P<modifier>\d+))?$/', $expression, $m)) {
            return respondJson($response, 400, ['error' => 'invalid expression']);
        }

        $count = (int) $m['count'];
        $sides = (int) $m['sides'];
        $modifier = isset($m['modifier']) ? (int) ($m['sign'] . $m['modifier']) : 0;

        if ($count <= 0 || $sides <= 0) {
            return respondJson($response, 400, ['error' => 'count and sides must be positive']);
        }

        $min = $count + $modifier;
        $max = $count * $sides + $modifier;
        $average = ($min + $max) / 2;

        return respondJson($response, 200, [
            'dice_count' => $count,
            'sides' => $sides,
            'modifier' => $modifier,
            'min' => $min,
            'max' => $max,
            'average' => $average,
        ]);
    }

    private function abilityCheck(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        if (!isset($body['roll'], $body['modifier'], $body['dc']) || !is_numeric($body['roll']) || !is_numeric($body['modifier']) || !is_numeric($body['dc'])) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        $roll = (int) $body['roll'];
        $modifier = (int) $body['modifier'];
        $dc = (int) $body['dc'];
        $total = $roll + $modifier;

        return respondJson($response, 200, [
            'total' => $total,
            'success' => $total >= $dc,
            'margin' => $total - $dc,
        ]);
    }

    private function adjustedXp(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];

        $party = $body['party'] ?? [];
        $monsters = $body['monsters'] ?? [];

        if (!is_array($party) || !is_array($monsters) || empty($party) || empty($monsters)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        try {
            $result = $this->engine->computeAdjustedXp($party, $monsters);
        } catch (InvalidArgumentException $e) {
            return respondJson($response, 400, ['error' => 'invalid monster']);
        }

        return respondJson($response, 200, $result);
    }

    private function initiativeOrder(Request $request, Response $response): Response
    {
        $body = $request->getParsedBody() ?? [];
        $combatants = $body['combatants'] ?? [];

        if (!is_array($combatants) || empty($combatants)) {
            return respondJson($response, 400, ['error' => 'invalid request']);
        }

        foreach ($combatants as $c) {
            if (!isset($c['name'], $c['dex'], $c['roll']) || !is_numeric($c['dex']) || !is_numeric($c['roll'])) {
                return respondJson($response, 400, ['error' => 'invalid combatant']);
            }
        }

        $order = $this->engine->buildCombatOrder($combatants);
        return respondJson($response, 200, ['order' => $this->engine->publicCombatOrder($order)]);
    }
}

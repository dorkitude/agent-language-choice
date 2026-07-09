<?php

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;

/**
 * Encode a numeric value as an int when it is integral, otherwise a float.
 * Keeps responses like {"average": 10} instead of {"average": 10.0}.
 */
function num(int|float $v): int|float
{
    if (is_int($v)) {
        return $v;
    }
    return (fmod($v, 1.0) === 0.0) ? (int) $v : $v;
}

/** Decode the JSON request body into an array, or null on failure. */
function jsonBody(Request $request): ?array
{
    $data = json_decode($request->getContent(), true);
    return is_array($data) ? $data : null;
}

function badRequest(string $message = 'invalid request'): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

function health(Request $request): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function diceStats(Request $request): JsonResponse
{
    $body = jsonBody($request);
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        return badRequest('invalid expression');
    }

    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($body['expression']), $m)) {
        return badRequest('invalid expression');
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return badRequest('invalid expression');
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = $count * ($sides + 1) / 2 + $modifier;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => num($average),
    ]);
}

function abilityCheck(Request $request): JsonResponse
{
    $body = jsonBody($request);
    if ($body === null
        || !isset($body['roll'], $body['modifier'], $body['dc'])
        || !is_int($body['roll']) || !is_int($body['modifier']) || !is_int($body['dc'])) {
        return badRequest('invalid check');
    }

    $total = $body['roll'] + $body['modifier'];
    $margin = $total - $body['dc'];

    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $body['dc'],
        'margin' => $margin,
    ]);
}

function adjustedXp(Request $request): JsonResponse
{
    $crXp = [
        '0' => 10,
        '1/8' => 25,
        '1/4' => 50,
        '1/2' => 100,
        '1' => 200,
        '2' => 450,
        '3' => 700,
        '4' => 1100,
        '5' => 1800,
    ];

    // Per-member encounter thresholds by character level.
    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $body = jsonBody($request);
    if ($body === null
        || !isset($body['party'], $body['monsters'])
        || !is_array($body['party']) || !is_array($body['monsters'])) {
        return badRequest('invalid encounter');
    }

    // Sum party thresholds across members.
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])) {
            return badRequest('invalid party member');
        }
        $level = $member['level'];
        if (!isset($levelThresholds[$level])) {
            return badRequest('unsupported level: ' . $level);
        }
        foreach ($levelThresholds[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    // Sum monster XP and count.
    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count'])) {
            return badRequest('invalid monster');
        }
        $cr = (string) $monster['cr'];
        if (!isset($crXp[$cr])) {
            return badRequest('unsupported cr: ' . $cr);
        }
        if (!is_int($monster['count']) || $monster['count'] < 0) {
            return badRequest('invalid monster count');
        }
        $baseXp += $crXp[$cr] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $multiplier = match (true) {
        $monsterCount <= 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = $baseXp * $multiplier;

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $level) {
        if ($adjustedXp >= $thresholds[$level]) {
            $difficulty = $level;
        }
    }

    return new JsonResponse([
        'base_xp' => num($baseXp),
        'monster_count' => $monsterCount,
        'multiplier' => num($multiplier),
        'adjusted_xp' => num($adjustedXp),
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => num($thresholds['easy']),
            'medium' => num($thresholds['medium']),
            'hard' => num($thresholds['hard']),
            'deadly' => num($thresholds['deadly']),
        ],
    ]);
}

function initiativeOrder(Request $request): JsonResponse
{
    $body = jsonBody($request);
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return badRequest('invalid combatants');
    }

    $combatants = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name']) || !is_int($c['dex']) || !is_int($c['roll'])) {
            return badRequest('invalid combatant');
        }
        $combatants[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }

    usort($combatants, function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: ($a['name'] <=> $b['name']);
    });

    $order = array_map(
        static fn (array $c): array => ['name' => $c['name'], 'score' => $c['score']],
        $combatants
    );

    return new JsonResponse(['order' => $order]);
}

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_handler' => 'health'], [], [], '', [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_handler' => 'diceStats'], [], [], '', [], ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_handler' => 'abilityCheck'], [], [], '', [], ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_handler' => 'adjustedXp'], [], [], '', [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_handler' => 'initiativeOrder'], [], [], '', [], ['POST']));

$request = Request::createFromGlobals();
$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->match($request->getPathInfo());
    $handler = $parameters['_handler'];
    $response = $handler($request);
} catch (ResourceNotFoundException) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (MethodNotAllowedException) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
}

$response->send();

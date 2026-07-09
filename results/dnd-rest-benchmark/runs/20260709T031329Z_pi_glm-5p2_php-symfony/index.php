<?php
require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

/* --------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------ */

function err400(string $message = 'bad request'): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

function is_number(mixed $v): bool
{
    return is_int($v) || is_float($v);
}

function readJson(Request $request): ?array
{
    $raw = $request->getContent();
    if ($raw === '') {
        return null;
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

/* --------------------------------------------------------------------------
 * Endpoint handlers
 * ------------------------------------------------------------------------ */

function health(): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function diceStats(array $body): JsonResponse
{
    if (!isset($body['expression']) || !is_string($body['expression'])) {
        return err400();
    }
    $expr = $body['expression'];
    if (!preg_match('/^(\d+)d(\d+)(?:([+-]\d+))?$/', $expr, $m)) {
        return err400();
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) ? (int) $m[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        return err400();
    }
    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;
    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function abilityCheck(array $body): JsonResponse
{
    foreach (['roll', 'modifier', 'dc'] as $k) {
        if (!array_key_exists($k, $body) || !is_number($body[$k])) {
            return err400();
        }
    }
    $total = $body['roll'] + $body['modifier'];
    $dc = $body['dc'];
    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

function multiplierFor(int $count): float
{
    if ($count <= 1) {
        return 1.0;
    }
    if ($count === 2) {
        return 1.5;
    }
    if ($count <= 6) {
        return 2.0;
    }
    if ($count <= 10) {
        return 2.5;
    }
    if ($count <= 14) {
        return 3.0;
    }
    return 4.0;
}

function adjustedXp(array $body): JsonResponse
{
    $xpTable = [
        '0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100,
        '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800,
    ];
    // Full D&D 5e encounter-difficulty XP thresholds by level (level 3 from spec).
    $thresholdTable = [
        1  => ['easy' => 25,   'medium' => 50,   'hard' => 75,   'deadly' => 100],
        2  => ['easy' => 50,   'medium' => 100,  'hard' => 150,  'deadly' => 200],
        3  => ['easy' => 75,   'medium' => 150,  'hard' => 225,  'deadly' => 400],
        4  => ['easy' => 125,  'medium' => 250,  'hard' => 375,  'deadly' => 500],
        5  => ['easy' => 250,  'medium' => 500,  'hard' => 750,  'deadly' => 1100],
        6  => ['easy' => 300,  'medium' => 600,  'hard' => 900,  'deadly' => 1400],
        7  => ['easy' => 350,  'medium' => 750,  'hard' => 1100, 'deadly' => 1700],
        8  => ['easy' => 450,  'medium' => 900,  'hard' => 1400, 'deadly' => 2100],
        9  => ['easy' => 550,  'medium' => 1100, 'hard' => 1600, 'deadly' => 2400],
        10 => ['easy' => 600,  'medium' => 1200, 'hard' => 1900, 'deadly' => 2800],
        11 => ['easy' => 800,  'medium' => 1600, 'hard' => 2400, 'deadly' => 3600],
        12 => ['easy' => 1000, 'medium' => 2000, 'hard' => 3000, 'deadly' => 4500],
        13 => ['easy' => 1100, 'medium' => 2200, 'hard' => 3400, 'deadly' => 5100],
        14 => ['easy' => 1250, 'medium' => 2500, 'hard' => 3800, 'deadly' => 5700],
        15 => ['easy' => 1400, 'medium' => 2800, 'hard' => 4300, 'deadly' => 6400],
        16 => ['easy' => 1600, 'medium' => 3200, 'hard' => 4800, 'deadly' => 7200],
        17 => ['easy' => 2000, 'medium' => 3900, 'hard' => 5900, 'deadly' => 8800],
        18 => ['easy' => 2100, 'medium' => 4200, 'hard' => 6300, 'deadly' => 9500],
        19 => ['easy' => 2400, 'medium' => 4700, 'hard' => 7200, 'deadly' => 10900],
        20 => ['easy' => 2800, 'medium' => 5700, 'hard' => 8500, 'deadly' => 12700],
    ];

    if (!isset($body['party']) || !is_array($body['party'])
        || !isset($body['monsters']) || !is_array($body['monsters'])) {
        return err400();
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !array_key_exists('cr', $monster) || !array_key_exists('count', $monster)) {
            return err400();
        }
        $cr = (string) $monster['cr'];
        if (!array_key_exists($cr, $xpTable)) {
            return err400();
        }
        if (!is_number($monster['count'])) {
            return err400();
        }
        $count = (int) $monster['count'];
        if ($count < 0) {
            return err400();
        }
        $baseXp += $xpTable[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = multiplierFor($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    $easy = $medium = $hard = $deadly = 0;
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !array_key_exists('level', $member) || !is_number($member['level'])) {
            return err400();
        }
        $level = (int) $member['level'];
        if (!isset($thresholdTable[$level])) {
            return err400();
        }
        $easy += $thresholdTable[$level]['easy'];
        $medium += $thresholdTable[$level]['medium'];
        $hard += $thresholdTable[$level]['hard'];
        $deadly += $thresholdTable[$level]['deadly'];
    }

    if ($adjustedXp >= $deadly) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $hard) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $medium) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $easy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => $easy,
            'medium' => $medium,
            'hard' => $hard,
            'deadly' => $deadly,
        ],
    ]);
}

function initiativeOrder(array $body): JsonResponse
{
    if (!isset($body['combatants']) || !is_array($body['combatants'])) {
        return err400();
    }
    $list = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c)
            || !array_key_exists('name', $c) || !is_string($c['name'])
            || !array_key_exists('dex', $c) || !is_number($c['dex'])
            || !array_key_exists('roll', $c) || !is_number($c['roll'])) {
            return err400();
        }
        $list[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }
    // Sort: score desc, then dex desc, then name asc.
    usort($list, function (array $a, array $b): int {
        return [$b['score'], $b['dex'], $a['name']] <=> [$a['score'], $a['dex'], $b['name']];
    });
    $order = array_map(static function (array $c): array {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $list);
    return new JsonResponse(['order' => $order]);
}

/* --------------------------------------------------------------------------
 * Routing & dispatch
 * ------------------------------------------------------------------------ */

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_handler' => 'health'], methods: ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_handler' => 'diceStats'], methods: ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_handler' => 'abilityCheck'], methods: ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_handler' => 'adjustedXp'], methods: ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_handler' => 'initiativeOrder'], methods: ['POST']));

$request = Request::createFromGlobals();
$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $match = $matcher->match($request->getPathInfo());
    $handler = $match['_handler'];
    if ($handler === 'health') {
        $response = health();
    } else {
        $body = readJson($request);
        if ($body === null) {
            $response = err400('invalid json');
        } else {
            $response = match ($handler) {
                'diceStats' => diceStats($body),
                'abilityCheck' => abilityCheck($body),
                'adjustedXp' => adjustedXp($body),
                'initiativeOrder' => initiativeOrder($body),
                default => new JsonResponse(['error' => 'not found'], 404),
            };
        }
    }
} catch (ResourceNotFoundException $e) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (MethodNotAllowedException $e) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
}

$response->send();

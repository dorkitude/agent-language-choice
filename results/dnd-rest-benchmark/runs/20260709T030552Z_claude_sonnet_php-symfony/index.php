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

function jsonBody(Request $request): array
{
    $data = json_decode($request->getContent() ?: '{}', true);
    return is_array($data) ? $data : [];
}

function diceStats(Request $request): JsonResponse
{
    $data = jsonBody($request);
    $expression = $data['expression'] ?? null;
    if (!is_string($expression)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($expression), $m)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) ? (int) $m[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function abilityCheck(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!isset($data['roll'], $data['modifier'], $data['dc'])) {
        return new JsonResponse(['error' => 'missing fields'], 400);
    }
    $roll = $data['roll'];
    $modifier = $data['modifier'];
    $dc = $data['dc'];

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return new JsonResponse([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

function adjustedXp(Request $request): JsonResponse
{
    $data = jsonBody($request);
    $party = $data['party'] ?? [];
    $monsters = $data['monsters'] ?? [];

    if (!is_array($party) || !is_array($monsters)) {
        return new JsonResponse(['error' => 'invalid request'], 400);
    }

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

    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        $cr = (string) ($monster['cr'] ?? '');
        $count = (int) ($monster['count'] ?? 0);
        if (!isset($crXp[$cr])) {
            return new JsonResponse(['error' => 'unsupported cr'], 400);
        }
        $baseXp += $crXp[$cr] * $count;
        $monsterCount += $count;
    }

    if ($monsterCount === 1) {
        $multiplier = 1;
    } elseif ($monsterCount === 2) {
        $multiplier = 1.5;
    } elseif ($monsterCount >= 3 && $monsterCount <= 6) {
        $multiplier = 2;
    } elseif ($monsterCount >= 7 && $monsterCount <= 10) {
        $multiplier = 2.5;
    } elseif ($monsterCount >= 11 && $monsterCount <= 14) {
        $multiplier = 3;
    } else {
        $multiplier = 4;
    }

    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        $level = (int) ($member['level'] ?? 0);
        if (!isset($levelThresholds[$level])) {
            return new JsonResponse(['error' => 'unsupported level'], 400);
        }
        foreach ($levelThresholds[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $difficulty = 'trivial';
    if ($adjustedXp >= $thresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $thresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $thresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $thresholds['easy']) {
        $difficulty = 'easy';
    }

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

function initiativeOrder(Request $request): JsonResponse
{
    $data = jsonBody($request);
    $combatants = $data['combatants'] ?? [];
    if (!is_array($combatants)) {
        return new JsonResponse(['error' => 'invalid request'], 400);
    }

    $entries = [];
    foreach ($combatants as $combatant) {
        $name = $combatant['name'] ?? '';
        $dex = (int) ($combatant['dex'] ?? 0);
        $roll = (int) ($combatant['roll'] ?? 0);
        $entries[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($entries, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] - $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] - $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $order = array_map(function ($entry) {
        return ['name' => $entry['name'], 'score' => $entry['score']];
    }, $entries);

    return new JsonResponse(['order' => $order]);
}

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_controller' => 'health'], [], [], null, [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => 'dice_stats'], [], [], null, [], ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_controller' => 'ability_check'], [], [], null, [], ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => 'adjusted_xp'], [], [], null, [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_controller' => 'initiative_order'], [], [], null, [], ['POST']));

$request = Request::createFromGlobals();
$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->match($request->getPathInfo());
    $controller = $parameters['_controller'];

    $response = match ($controller) {
        'health' => new JsonResponse(['ok' => true]),
        'dice_stats' => diceStats($request),
        'ability_check' => abilityCheck($request),
        'adjusted_xp' => adjustedXp($request),
        'initiative_order' => initiativeOrder($request),
        default => new JsonResponse(['error' => 'not found'], 404),
    };
} catch (MethodNotAllowedException $e) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
} catch (ResourceNotFoundException $e) {
    $response = new JsonResponse(['error' => 'not found'], 404);
}

$response->send();

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

function jsonBody(Request $request): array
{
    try {
        $data = json_decode($request->getContent(), true, 512, JSON_THROW_ON_ERROR);
    } catch (\JsonException) {
        throw new \InvalidArgumentException('invalid json');
    }
    if (!is_array($data)) {
        throw new \InvalidArgumentException('invalid json');
    }
    return $data;
}

$health = static fn (Request $request): JsonResponse => new JsonResponse(['ok' => true]);

$diceStats = static function (Request $request): JsonResponse {
    $data = jsonBody($request);
    $expression = $data['expression'] ?? '';
    if (!preg_match('/^([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?$/', $expression, $matches)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }
    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = 0;
    if (isset($matches[3])) {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier = -$modifier;
        }
    }
    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = intdiv($min + $max, 2);
    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
};

$abilityCheck = static function (Request $request): JsonResponse {
    $data = jsonBody($request);
    if (!isset($data['roll'], $data['modifier'], $data['dc']) || !is_int($data['roll']) || !is_int($data['modifier']) || !is_int($data['dc'])) {
        return new JsonResponse(['error' => 'invalid request'], 400);
    }
    $total = $data['roll'] + $data['modifier'];
    $success = $total >= $data['dc'];
    $margin = $total - $data['dc'];
    return new JsonResponse([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
};

$adjustedXp = static function (Request $request): JsonResponse {
    $xpByCr = [
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
    $thresholdsByLevel = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];
    $multipliers = [
        ['max' => 1, 'value' => 1],
        ['max' => 2, 'value' => 1.5],
        ['max' => 6, 'value' => 2],
        ['max' => 10, 'value' => 2.5],
        ['max' => 14, 'value' => 3],
        ['max' => PHP_INT_MAX, 'value' => 4],
    ];

    $data = jsonBody($request);
    if (!isset($data['party'], $data['monsters']) || !is_array($data['party']) || !is_array($data['monsters'])) {
        return new JsonResponse(['error' => 'invalid request'], 400);
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])) {
            return new JsonResponse(['error' => 'invalid request'], 400);
        }
        $level = $member['level'];
        if (!isset($thresholdsByLevel[$level])) {
            return new JsonResponse(['error' => 'unsupported level'], 400);
        }
        foreach ($thresholdsByLevel[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count']) || !is_string($monster['cr']) || !is_int($monster['count'])) {
            return new JsonResponse(['error' => 'invalid request'], 400);
        }
        $cr = $monster['cr'];
        $count = $monster['count'];
        if (!isset($xpByCr[$cr]) || $count < 0) {
            return new JsonResponse(['error' => 'invalid request'], 400);
        }
        $baseXp += $xpByCr[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = 1;
    foreach ($multipliers as $m) {
        if ($monsterCount <= $m['max']) {
            $multiplier = $m['value'];
            break;
        }
    }
    $adjustedXp = (int) round($baseXp * $multiplier);

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
};

$initiativeOrder = static function (Request $request): JsonResponse {
    $data = jsonBody($request);
    if (!isset($data['combatants']) || !is_array($data['combatants'])) {
        return new JsonResponse(['error' => 'invalid request'], 400);
    }
    $combatants = [];
    foreach ($data['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll']) || !is_string($c['name']) || !is_int($c['dex']) || !is_int($c['roll'])) {
            return new JsonResponse(['error' => 'invalid request'], 400);
        }
        $combatants[] = [
            'name' => $c['name'],
            'score' => $c['roll'] + $c['dex'],
            'dex' => $c['dex'],
        ];
    }
    usort($combatants, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });
    $order = array_map(static fn (array $c): array => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $combatants);
    return new JsonResponse(['order' => $order]);
};

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_controller' => $health], [], [], '', [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => $diceStats], [], [], '', [], ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_controller' => $abilityCheck], [], [], '', [], ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => $adjustedXp], [], [], '', [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_controller' => $initiativeOrder], [], [], '', [], ['POST']));

$request = Request::createFromGlobals();
$context = (new RequestContext())->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->matchRequest($request);
} catch (MethodNotAllowedException) {
    (new JsonResponse(['error' => 'method not allowed'], 405))->send();
    exit;
} catch (ResourceNotFoundException) {
    (new JsonResponse(['error' => 'not found'], 404))->send();
    exit;
}

$controller = $parameters['_controller'];
try {
    $response = $controller($request);
} catch (\InvalidArgumentException $e) {
    $response = new JsonResponse(['error' => $e->getMessage()], 400);
} catch (\Throwable $e) {
    $response = new JsonResponse(['error' => 'internal server error'], 500);
}
$response->send();
exit;

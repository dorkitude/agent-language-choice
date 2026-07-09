<?php

require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

function jsonResponse(Response $response, mixed $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data, JSON_THROW_ON_ERROR));
    return $response
        ->withHeader('Content-Type', 'application/json')
        ->withStatus($status);
}

function errorResponse(Response $response, string $message, int $status = 400): Response
{
    return jsonResponse($response, ['error' => $message], $status);
}

function parseJsonBody(Request $request): ?array
{
    $body = $request->getBody()->getContents();
    if ($body === '') {
        return [];
    }
    try {
        $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        return null;
    }
    return is_array($data) ? $data : null;
}

const CR_XP = [
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800,
    '6' => 2300,
    '7' => 2900,
    '8' => 3900,
    '9' => 5000,
    '10' => 5900,
    '11' => 7200,
    '12' => 8400,
    '13' => 10000,
    '14' => 11500,
    '15' => 13000,
    '16' => 15000,
    '17' => 18000,
    '18' => 20000,
    '19' => 22000,
    '20' => 25000,
    '21' => 33000,
    '22' => 41000,
    '23' => 50000,
    '24' => 62000,
    '25' => 75000,
    '26' => 90000,
    '27' => 105000,
    '28' => 120000,
    '29' => 135000,
    '30' => 155000,
];

const LEVEL_THRESHOLDS = [
    1 => ['easy' => 25, 'medium' => 50, 'hard' => 75, 'deadly' => 100],
    2 => ['easy' => 50, 'medium' => 100, 'hard' => 150, 'deadly' => 200],
    3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    4 => ['easy' => 125, 'medium' => 250, 'hard' => 375, 'deadly' => 500],
    5 => ['easy' => 250, 'medium' => 500, 'hard' => 750, 'deadly' => 1100],
    6 => ['easy' => 300, 'medium' => 600, 'hard' => 900, 'deadly' => 1400],
    7 => ['easy' => 350, 'medium' => 750, 'hard' => 1100, 'deadly' => 1700],
    8 => ['easy' => 450, 'medium' => 900, 'hard' => 1400, 'deadly' => 2100],
    9 => ['easy' => 550, 'medium' => 1100, 'hard' => 1600, 'deadly' => 2400],
    10 => ['easy' => 600, 'medium' => 1200, 'hard' => 1900, 'deadly' => 2800],
    11 => ['easy' => 800, 'medium' => 1600, 'hard' => 2400, 'deadly' => 3600],
    12 => ['easy' => 1000, 'medium' => 2000, 'hard' => 3000, 'deadly' => 4500],
    13 => ['easy' => 1100, 'medium' => 2200, 'hard' => 3400, 'deadly' => 5100],
    14 => ['easy' => 1250, 'medium' => 2500, 'hard' => 3800, 'deadly' => 5700],
    15 => ['easy' => 1400, 'medium' => 2800, 'hard' => 4300, 'deadly' => 6400],
    16 => ['easy' => 1600, 'medium' => 3200, 'hard' => 4800, 'deadly' => 7200],
    17 => ['easy' => 2000, 'medium' => 3900, 'hard' => 5900, 'deadly' => 8800],
    18 => ['easy' => 2100, 'medium' => 4200, 'hard' => 6300, 'deadly' => 9500],
    19 => ['easy' => 2400, 'medium' => 4900, 'hard' => 7300, 'deadly' => 10900],
    20 => ['easy' => 2800, 'medium' => 5700, 'hard' => 8500, 'deadly' => 12700],
];

function encounterMultiplier(int $monsterCount): float
{
    return match (true) {
        $monsterCount === 1 => 1.0,
        $monsterCount === 2 => 1.5,
        $monsterCount >= 3 && $monsterCount <= 6 => 2.0,
        $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
        $monsterCount >= 11 && $monsterCount <= 14 => 3.0,
        default => 4.0,
    };
}

$app = AppFactory::create();
$app->addBodyParsingMiddleware();

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = parseJsonBody($request);
    if ($data === null) {
        return errorResponse($response, 'Invalid JSON');
    }

    $expression = $data['expression'] ?? '';
    if (!is_string($expression) || !preg_match('/^(\d+)d(\d+)(?:(\+|-)(\d+))?$/', $expression, $matches)) {
        return errorResponse($response, 'Invalid expression');
    }

    $diceCount = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = 0;
    if (isset($matches[3])) {
        $modifierValue = (int) $matches[4];
        $modifier = $matches[3] === '+' ? $modifierValue : -$modifierValue;
    }

    if ($diceCount <= 0 || $sides <= 0) {
        return errorResponse($response, 'Invalid expression');
    }

    $min = $diceCount + $modifier;
    $max = $diceCount * $sides + $modifier;
    $average = (int) round(($min + $max) / 2);

    return jsonResponse($response, [
        'dice_count' => $diceCount,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $data = parseJsonBody($request);
    if ($data === null) {
        return errorResponse($response, 'Invalid JSON');
    }

    $roll = $data['roll'] ?? null;
    $modifier = $data['modifier'] ?? null;
    $dc = $data['dc'] ?? null;

    if (!is_int($roll) || !is_int($modifier) || !is_int($dc)) {
        return errorResponse($response, 'Invalid request');
    }

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return jsonResponse($response, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $data = parseJsonBody($request);
    if ($data === null) {
        return errorResponse($response, 'Invalid JSON');
    }

    $party = $data['party'] ?? null;
    $monsters = $data['monsters'] ?? null;

    if (!is_array($party) || !is_array($monsters)) {
        return errorResponse($response, 'Invalid request');
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])) {
            return errorResponse($response, 'Invalid request');
        }
        $level = $member['level'];
        if (!isset(LEVEL_THRESHOLDS[$level])) {
            return errorResponse($response, 'Invalid level');
        }
        foreach (LEVEL_THRESHOLDS[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster) || !isset($monster['cr']) || !isset($monster['count'])) {
            return errorResponse($response, 'Invalid request');
        }
        $cr = (string) $monster['cr'];
        $count = $monster['count'];
        if (!is_int($count) || $count < 0 || !isset(CR_XP[$cr])) {
            return errorResponse($response, 'Invalid request');
        }
        $baseXp += CR_XP[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = encounterMultiplier($monsterCount);
    $adjustedXp = (int) round($baseXp * $multiplier);

    $difficulty = 'trivial';
    $difficultyOrder = ['deadly', 'hard', 'medium', 'easy'];
    foreach ($difficultyOrder as $threshold) {
        if ($adjustedXp >= $thresholds[$threshold]) {
            $difficulty = $threshold;
            break;
        }
    }

    return jsonResponse($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $data = parseJsonBody($request);
    if ($data === null) {
        return errorResponse($response, 'Invalid JSON');
    }

    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants)) {
        return errorResponse($response, 'Invalid request');
    }

    $scored = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) || !isset($combatant['name']) || !isset($combatant['dex']) || !isset($combatant['roll'])) {
            return errorResponse($response, 'Invalid request');
        }
        $name = $combatant['name'];
        $dex = $combatant['dex'];
        $roll = $combatant['roll'];
        if (!is_string($name) || !is_int($dex) || !is_int($roll)) {
            return errorResponse($response, 'Invalid request');
        }
        $scored[] = [
            'name' => $name,
            'score' => $roll + $dex,
            'dex' => $dex,
        ];
    }

    usort($scored, function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $order = array_map(fn (array $c) => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $scored);

    return jsonResponse($response, ['order' => $order]);
});

$app->run();

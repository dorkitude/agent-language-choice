<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

function jsonResponse(Response $response, $data, int $status = 200): Response {
    $response->getBody()->write(json_encode($data));
    return $response->withHeader('Content-Type', 'application/json')->withStatus($status);
}

function getBody(Request $request): array {
    $body = (string) $request->getBody();
    $decoded = json_decode($body, true);
    return is_array($decoded) ? $decoded : [];
}

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = getBody($request);
    $expression = $data['expression'] ?? '';

    if (!is_string($expression) || !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $matches)) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;

    return jsonResponse($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $data = getBody($request);
    $roll = $data['roll'] ?? 0;
    $modifier = $data['modifier'] ?? 0;
    $dc = $data['dc'] ?? 0;

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
    $data = getBody($request);
    $party = $data['party'] ?? [];
    $monsters = $data['monsters'] ?? [];

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

    $thresholdsByLevel = [
        1 => ['easy' => 25, 'medium' => 50, 'hard' => 75, 'deadly' => 100],
        2 => ['easy' => 50, 'medium' => 100, 'hard' => 150, 'deadly' => 200],
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
        4 => ['easy' => 125, 'medium' => 250, 'hard' => 375, 'deadly' => 500],
        5 => ['easy' => 250, 'medium' => 500, 'hard' => 750, 'deadly' => 1100],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        $cr = (string) ($monster['cr'] ?? '0');
        $count = (int) ($monster['count'] ?? 0);
        $xp = $crXp[$cr] ?? 0;
        $baseXp += $xp * $count;
        $monsterCount += $count;
    }

    if ($monsterCount >= 15) {
        $multiplier = 4;
    } elseif ($monsterCount >= 11) {
        $multiplier = 3;
    } elseif ($monsterCount >= 7) {
        $multiplier = 2.5;
    } elseif ($monsterCount >= 3) {
        $multiplier = 2;
    } elseif ($monsterCount == 2) {
        $multiplier = 1.5;
    } else {
        $multiplier = 1;
    }

    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        $level = (int) ($member['level'] ?? 1);
        $t = $thresholdsByLevel[$level] ?? $thresholdsByLevel[1];
        $thresholds['easy'] += $t['easy'];
        $thresholds['medium'] += $t['medium'];
        $thresholds['hard'] += $t['hard'];
        $thresholds['deadly'] += $t['deadly'];
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
    $data = getBody($request);
    $combatants = $data['combatants'] ?? [];

    $order = [];
    foreach ($combatants as $c) {
        $order[] = [
            'name' => $c['name'] ?? '',
            'dex' => (int) ($c['dex'] ?? 0),
            'score' => (int) ($c['roll'] ?? 0) + (int) ($c['dex'] ?? 0),
        ];
    }

    usort($order, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] - $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] - $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $result = array_map(function ($c) {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $order);

    return jsonResponse($response, ['order' => $result]);
});

$app->run();

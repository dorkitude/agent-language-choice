<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();
$app->addBodyParsingMiddleware();
$app->addRoutingMiddleware();
$app->addErrorMiddleware(false, false, false);

$json = static function (Response $response, int $status, $data): Response {
    $response->getBody()->write(json_encode($data, JSON_PRESERVE_ZERO_FRACTION));
    return $response->withStatus($status)->withHeader('Content-Type', 'application/json');
};

$app->get('/health', function (Request $request, Response $response) use ($json) {
    return $json($response, 200, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) use ($json) {
    $body = $request->getParsedBody() ?? [];
    $expression = (string) ($body['expression'] ?? '');

    if (!preg_match('/^(?P<count>\d+)d(?P<sides>\d+)(?:(?P<sign>[+-])(?P<modifier>\d+))?$/', $expression, $m)) {
        return $json($response, 400, ['error' => 'invalid expression']);
    }

    $count = (int) $m['count'];
    $sides = (int) $m['sides'];
    $modifier = isset($m['modifier']) ? (int) ($m['sign'] . $m['modifier']) : 0;

    if ($count <= 0 || $sides <= 0) {
        return $json($response, 400, ['error' => 'count and sides must be positive']);
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

    return $json($response, 200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) use ($json) {
    $body = $request->getParsedBody() ?? [];

    if (!isset($body['roll'], $body['modifier'], $body['dc']) || !is_numeric($body['roll']) || !is_numeric($body['modifier']) || !is_numeric($body['dc'])) {
        return $json($response, 400, ['error' => 'invalid request']);
    }

    $roll = (int) $body['roll'];
    $modifier = (int) $body['modifier'];
    $dc = (int) $body['dc'];
    $total = $roll + $modifier;

    return $json($response, 200, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) use ($json) {
    $body = $request->getParsedBody() ?? [];

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

    $party = $body['party'] ?? [];
    $monsters = $body['monsters'] ?? [];

    if (!is_array($party) || !is_array($monsters) || empty($party) || empty($monsters)) {
        return $json($response, 400, ['error' => 'invalid request']);
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        $level = isset($member['level']) ? (int) $member['level'] : 0;
        if (isset($levelThresholds[$level])) {
            foreach ($levelThresholds[$level] as $key => $value) {
                $thresholds[$key] += $value;
            }
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        $cr = (string) ($monster['cr'] ?? '');
        $count = isset($monster['count']) ? (int) $monster['count'] : 0;
        if (!isset($crXp[$cr]) || $count <= 0) {
            return $json($response, 400, ['error' => 'invalid monster']);
        }
        $baseXp += $crXp[$cr] * $count;
        $monsterCount += $count;
    }

    if ($monsterCount <= 0) {
        return $json($response, 400, ['error' => 'invalid monster count']);
    }

    $multiplier = match (true) {
        $monsterCount === 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount >= 3 && $monsterCount <= 6 => 2,
        $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
        $monsterCount >= 11 && $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = $baseXp * $multiplier;

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

    return $json($response, 200, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) use ($json) {
    $body = $request->getParsedBody() ?? [];
    $combatants = $body['combatants'] ?? [];

    if (!is_array($combatants) || empty($combatants)) {
        return $json($response, 400, ['error' => 'invalid request']);
    }

    $order = [];
    foreach ($combatants as $c) {
        if (!isset($c['name'], $c['dex'], $c['roll']) || !is_numeric($c['dex']) || !is_numeric($c['roll'])) {
            return $json($response, 400, ['error' => 'invalid combatant']);
        }
        $order[] = [
            'name' => (string) $c['name'],
            'score' => (int) $c['roll'] + (int) $c['dex'],
            'dex' => (int) $c['dex'],
        ];
    }

    usort($order, static function ($a, $b) {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $result = [];
    foreach ($order as $c) {
        $result[] = ['name' => $c['name'], 'score' => $c['score']];
    }

    return $json($response, 200, ['order' => $result]);
});

$app->run();

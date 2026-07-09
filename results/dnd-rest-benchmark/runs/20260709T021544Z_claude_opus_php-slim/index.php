<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

/** Write a JSON response with the given status code. */
function json(Response $response, $data, int $status = 200): Response {
    $response->getBody()->write(json_encode($data));
    return $response->withStatus($status)->withHeader('Content-Type', 'application/json');
}

/** Decode the JSON request body, returning an array (empty on failure). */
function body(Request $request): array {
    $data = json_decode((string) $request->getBody(), true);
    return is_array($data) ? $data : [];
}

$app->get('/health', function (Request $request, Response $response) {
    return json($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = body($request);
    $expr = $data['expression'] ?? null;
    if (!is_string($expr) || !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($expr), $m)) {
        return json($response, ['error' => 'invalid expression'], 400);
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        return json($response, ['error' => 'invalid expression'], 400);
    }
    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    return json($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => ($min + $max) / 2,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $data = body($request);
    $roll = $data['roll'] ?? null;
    $modifier = $data['modifier'] ?? null;
    $dc = $data['dc'] ?? null;
    if (!is_int($roll) || !is_int($modifier) || !is_int($dc)) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    $total = $roll + $modifier;
    return json($response, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $CR_XP = [
        '0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100,
        '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800,
    ];
    $THRESHOLDS = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $data = body($request);
    $party = $data['party'] ?? null;
    $monsters = $data['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count'])) {
            return json($response, ['error' => 'invalid monster'], 400);
        }
        $cr = (string) $monster['cr'];
        $mcount = $monster['count'];
        if (!array_key_exists($cr, $CR_XP) || !is_int($mcount) || $mcount < 0) {
            return json($response, ['error' => 'invalid monster'], 400);
        }
        $baseXp += $CR_XP[$cr] * $mcount;
        $monsterCount += $mcount;
    }

    $multiplier = 1;
    if ($monsterCount == 1) $multiplier = 1;
    elseif ($monsterCount == 2) $multiplier = 1.5;
    elseif ($monsterCount <= 6) $multiplier = 2;
    elseif ($monsterCount <= 10) $multiplier = 2.5;
    elseif ($monsterCount <= 14) $multiplier = 3;
    else $multiplier = 4;

    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !isset($member['level'])) {
            return json($response, ['error' => 'invalid party member'], 400);
        }
        $level = $member['level'];
        if (!array_key_exists($level, $THRESHOLDS)) {
            return json($response, ['error' => 'unsupported level'], 400);
        }
        foreach ($THRESHOLDS[$level] as $k => $v) {
            $thresholds[$k] += $v;
        }
    }

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    return json($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $data = body($request);
    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $scored = [];
    foreach ($combatants as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_int($c['dex']) || !is_int($c['roll']) || !is_string($c['name'])) {
            return json($response, ['error' => 'invalid combatant'], 400);
        }
        $scored[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }

    usort($scored, function ($a, $b) {
        if ($a['score'] !== $b['score']) return $b['score'] <=> $a['score'];
        if ($a['dex'] !== $b['dex']) return $b['dex'] <=> $a['dex'];
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(fn($c) => ['name' => $c['name'], 'score' => $c['score']], $scored);
    return json($response, ['order' => $order]);
});

$app->run();

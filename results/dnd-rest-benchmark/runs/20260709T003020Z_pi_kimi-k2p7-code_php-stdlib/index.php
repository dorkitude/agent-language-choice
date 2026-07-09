<?php
header('Content-Type: application/json');

$method = $_SERVER['REQUEST_METHOD'];
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);
$path = $path ?? '/';

function json_body(): array {
    $raw = file_get_contents('php://input');
    return json_decode($raw, true) ?? [];
}

function send(int $code, array $data): void {
    http_response_code($code);
    echo json_encode($data);
    exit;
}

function bad_request(string $error): void {
    send(400, ['error' => $error]);
}

if ($method === 'GET' && $path === '/health') {
    send(200, ['ok' => true]);
}

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $body = json_body();
    $expr = $body['expression'] ?? '';
    if (!preg_match('/^([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?$/', $expr, $m)) {
        bad_request('invalid expression');
    }
    $count = (int)$m[1];
    $sides = (int)$m[2];
    $modifier = 0;
    if (isset($m[3])) {
        $modifier = (int)$m[4];
        if ($m[3] === '-') {
            $modifier = -$modifier;
        }
    }
    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = $count * ($sides + 1) / 2 + $modifier;
    send(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

if ($method === 'POST' && $path === '/v1/checks/ability') {
    $body = json_body();
    $roll = $body['roll'] ?? 0;
    $modifier = $body['modifier'] ?? 0;
    $dc = $body['dc'] ?? 0;
    $total = $roll + $modifier;
    send(200, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $body = json_body();
    $cr_xp = [
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
    $level_thresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $base_xp = 0;
    $monster_count = 0;
    foreach ($body['monsters'] ?? [] as $m) {
        $cr = (string)($m['cr'] ?? '');
        $count = (int)($m['count'] ?? 0);
        $xp = $cr_xp[$cr] ?? 0;
        $base_xp += $xp * $count;
        $monster_count += $count;
    }

    if ($monster_count === 1) {
        $multiplier = 1;
    } elseif ($monster_count === 2) {
        $multiplier = 1.5;
    } elseif ($monster_count <= 6) {
        $multiplier = 2;
    } elseif ($monster_count <= 10) {
        $multiplier = 2.5;
    } elseif ($monster_count <= 14) {
        $multiplier = 3;
    } else {
        $multiplier = 4;
    }

    $adjusted_xp = $base_xp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] ?? [] as $p) {
        $level = (int)($p['level'] ?? 0);
        $t = $level_thresholds[$level] ?? null;
        if ($t === null) {
            continue;
        }
        foreach (['easy', 'medium', 'hard', 'deadly'] as $k) {
            $thresholds[$k] += $t[$k];
        }
    }

    if ($adjusted_xp >= $thresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjusted_xp >= $thresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjusted_xp >= $thresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjusted_xp >= $thresholds['easy']) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    send(200, [
        'base_xp' => $base_xp,
        'monster_count' => $monster_count,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjusted_xp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

if ($method === 'POST' && $path === '/v1/initiative/order') {
    $body = json_body();
    $combatants = $body['combatants'] ?? [];
    $order = [];
    foreach ($combatants as $c) {
        $roll = $c['roll'] ?? 0;
        $dex = $c['dex'] ?? 0;
        $order[] = [
            'name' => $c['name'] ?? '',
            'score' => $roll + $dex,
            'dex' => $dex,
        ];
    }
    usort($order, static function ($a, $b) {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });
    foreach ($order as &$o) {
        unset($o['dex']);
    }
    unset($o);
    send(200, ['order' => $order]);
}

send(404, ['error' => 'not found']);

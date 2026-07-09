<?php

declare(strict_types=1);

function send_json(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($body, JSON_UNESCAPED_SLASHES);
}

function read_json_body(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        return null;
    }
    return $decoded;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';

if ($method === 'GET' && $path === '/health') {
    send_json(200, ['ok' => true]);
    return;
}

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $body = read_json_body();
    $expression = is_array($body) && isset($body['expression']) ? $body['expression'] : null;

    if (!is_string($expression) || !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $m)) {
        send_json(400, ['error' => 'invalid expression']);
        return;
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) ? (int) $m[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        send_json(400, ['error' => 'invalid expression']);
        return;
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;

    send_json(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/checks/ability') {
    $body = read_json_body();
    if (!is_array($body) || !isset($body['roll'], $body['modifier'], $body['dc'])) {
        send_json(400, ['error' => 'invalid request']);
        return;
    }

    $roll = $body['roll'];
    $modifier = $body['modifier'];
    $dc = $body['dc'];

    if (!is_numeric($roll) || !is_numeric($modifier) || !is_numeric($dc)) {
        send_json(400, ['error' => 'invalid request']);
        return;
    }

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    send_json(200, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $body = read_json_body();
    if (!is_array($body) || !isset($body['party'], $body['monsters']) || !is_array($body['party']) || !is_array($body['monsters'])) {
        send_json(400, ['error' => 'invalid request']);
        return;
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

    $thresholdTable = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count'])) {
            send_json(400, ['error' => 'invalid monster']);
            return;
        }
        $cr = (string) $monster['cr'];
        $count = (int) $monster['count'];
        if (!isset($crXp[$cr])) {
            send_json(400, ['error' => 'unsupported cr']);
            return;
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

    $sumThresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level'])) {
            send_json(400, ['error' => 'invalid party member']);
            return;
        }
        $level = (int) $member['level'];
        if (!isset($thresholdTable[$level])) {
            send_json(400, ['error' => 'unsupported level']);
            return;
        }
        foreach ($thresholdTable[$level] as $key => $value) {
            $sumThresholds[$key] += $value;
        }
    }

    $difficulty = 'trivial';
    if ($adjustedXp >= $sumThresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $sumThresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $sumThresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $sumThresholds['easy']) {
        $difficulty = 'easy';
    }

    send_json(200, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $sumThresholds,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/initiative/order') {
    $body = read_json_body();
    if (!is_array($body) || !isset($body['combatants']) || !is_array($body['combatants'])) {
        send_json(400, ['error' => 'invalid request']);
        return;
    }

    $combatants = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])) {
            send_json(400, ['error' => 'invalid combatant']);
            return;
        }
        $name = (string) $c['name'];
        $dex = $c['dex'];
        $roll = $c['roll'];
        $score = $roll + $dex;
        $combatants[] = ['name' => $name, 'dex' => $dex, 'score' => $score];
    }

    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(fn ($c) => ['name' => $c['name'], 'score' => $c['score']], $combatants);

    send_json(200, ['order' => $order]);
    return;
}

send_json(404, ['error' => 'not found']);

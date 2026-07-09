<?php

declare(strict_types=1);

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
];

const LEVEL_THRESHOLDS = [
    3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
];

function send_json(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($body);
}

function bad_request(): void
{
    send_json(400, ['error' => 'bad request']);
}

function read_json(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

function count_multiplier(int $n): float
{
    if ($n <= 1) return 1.0;
    if ($n == 2) return 1.5;
    if ($n <= 6) return 2.0;
    if ($n <= 10) return 2.5;
    if ($n <= 14) return 3.0;
    return 4.0;
}

function num_out(float $v)
{
    return $v == floor($v) ? (int) $v : $v;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';

if ($method === 'GET' && $path === '/health') {
    send_json(200, ['ok' => true]);
    return true;
}

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $body = read_json();
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        bad_request();
        return true;
    }
    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($body['expression']), $m)) {
        bad_request();
        return true;
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) ? (int) $m[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        bad_request();
        return true;
    }
    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    send_json(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => num_out(($min + $max) / 2),
    ]);
    return true;
}

if ($method === 'POST' && $path === '/v1/checks/ability') {
    $body = read_json();
    if ($body === null || !isset($body['roll'], $body['modifier'], $body['dc'])
        || !is_int($body['roll']) || !is_int($body['modifier']) || !is_int($body['dc'])) {
        bad_request();
        return true;
    }
    $total = $body['roll'] + $body['modifier'];
    send_json(200, [
        'total' => $total,
        'success' => $total >= $body['dc'],
        'margin' => $total - $body['dc'],
    ]);
    return true;
}

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $body = read_json();
    if ($body === null || !isset($body['party'], $body['monsters'])
        || !is_array($body['party']) || !is_array($body['monsters'])) {
        bad_request();
        return true;
    }

    $base_xp = 0;
    $monster_count = 0;
    foreach ($body['monsters'] as $mon) {
        if (!is_array($mon) || !isset($mon['cr'], $mon['count'])) {
            bad_request();
            return true;
        }
        $cr = (string) $mon['cr'];
        if (!array_key_exists($cr, CR_XP) || !is_int($mon['count']) || $mon['count'] < 0) {
            bad_request();
            return true;
        }
        $base_xp += CR_XP[$cr] * $mon['count'];
        $monster_count += $mon['count'];
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])
            || !array_key_exists($member['level'], LEVEL_THRESHOLDS)) {
            bad_request();
            return true;
        }
        foreach (LEVEL_THRESHOLDS[$member['level']] as $k => $v) {
            $thresholds[$k] += $v;
        }
    }

    $multiplier = count_multiplier($monster_count);
    $adjusted_xp = $base_xp * $multiplier;

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjusted_xp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    send_json(200, [
        'base_xp' => $base_xp,
        'monster_count' => $monster_count,
        'multiplier' => num_out($multiplier),
        'adjusted_xp' => num_out($adjusted_xp),
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
    return true;
}

if ($method === 'POST' && $path === '/v1/initiative/order') {
    $body = read_json();
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        bad_request();
        return true;
    }
    $order = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name']) || !is_int($c['dex']) || !is_int($c['roll'])) {
            bad_request();
            return true;
        }
        $order[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }
    usort($order, function ($a, $b) {
        return [$b['score'], $b['dex'], $a['name']] <=> [$a['score'], $a['dex'], $b['name']];
    });
    $out = array_map(fn($c) => ['name' => $c['name'], 'score' => $c['score']], $order);
    send_json(200, ['order' => $out]);
    return true;
}

send_json(404, ['error' => 'not found']);
return true;

<?php
declare(strict_types=1);

function respond(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($body, JSON_UNESCAPED_SLASHES) . "\n";
}

function bad_request(): void
{
    respond(400, ['error' => 'bad_request']);
}

function read_json_body(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }

    $data = json_decode($raw, true);
    if (!is_array($data) || json_last_error() !== JSON_ERROR_NONE) {
        return null;
    }

    return $data;
}

function is_int_value(mixed $value): bool
{
    return is_int($value);
}

function dice_stats(array $body): void
{
    if (!isset($body['expression']) || !is_string($body['expression'])) {
        bad_request();
        return;
    }

    if (!preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $body['expression'], $matches)) {
        bad_request();
        return;
    }

    $count = intval($matches[1], 10);
    $sides = intval($matches[2], 10);
    if ($count <= 0 || $sides <= 0) {
        bad_request();
        return;
    }

    $modifier = 0;
    if (isset($matches[3], $matches[4]) && $matches[3] !== '') {
        $modifier = intval($matches[4], 10);
        if ($matches[3] === '-') {
            $modifier = -$modifier;
        }
    }

    $min = $count + $modifier;
    $max = ($count * $sides) + $modifier;
    $average = ($min + $max) / 2;

    respond(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function ability_check(array $body): void
{
    if (!array_key_exists('roll', $body) || !array_key_exists('modifier', $body) || !array_key_exists('dc', $body)) {
        bad_request();
        return;
    }
    if (!is_int_value($body['roll']) || !is_int_value($body['modifier']) || !is_int_value($body['dc'])) {
        bad_request();
        return;
    }

    $total = $body['roll'] + $body['modifier'];
    respond(200, [
        'total' => $total,
        'success' => $total >= $body['dc'],
        'margin' => $total - $body['dc'],
    ]);
}

function monster_multiplier(int $count): float|int
{
    if ($count === 1) {
        return 1;
    }
    if ($count === 2) {
        return 1.5;
    }
    if ($count <= 6) {
        return 2;
    }
    if ($count <= 10) {
        return 2.5;
    }
    if ($count <= 14) {
        return 3;
    }
    return 4;
}

function encounter_xp(array $body): void
{
    $xp_by_cr = [
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

    if (!isset($body['party'], $body['monsters']) || !is_array($body['party']) || !is_array($body['monsters'])) {
        bad_request();
        return;
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int_value($member['level']) || !isset($level_thresholds[$member['level']])) {
            bad_request();
            return;
        }
        foreach ($thresholds as $name => $_) {
            $thresholds[$name] += $level_thresholds[$member['level']][$name];
        }
    }

    $base_xp = 0;
    $monster_count = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count']) || !is_string($monster['cr']) || !is_int_value($monster['count'])) {
            bad_request();
            return;
        }
        if ($monster['count'] <= 0 || !isset($xp_by_cr[$monster['cr']])) {
            bad_request();
            return;
        }
        $base_xp += $xp_by_cr[$monster['cr']] * $monster['count'];
        $monster_count += $monster['count'];
    }

    if ($monster_count <= 0) {
        bad_request();
        return;
    }

    $multiplier = monster_multiplier($monster_count);
    $adjusted_xp = $base_xp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $name) {
        if ($adjusted_xp >= $thresholds[$name]) {
            $difficulty = $name;
        }
    }

    respond(200, [
        'base_xp' => $base_xp,
        'monster_count' => $monster_count,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjusted_xp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

function initiative_order(array $body): void
{
    if (!isset($body['combatants']) || !is_array($body['combatants'])) {
        bad_request();
        return;
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (!is_array($combatant) || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])) {
            bad_request();
            return;
        }
        if (!is_string($combatant['name']) || !is_int_value($combatant['dex']) || !is_int_value($combatant['roll'])) {
            bad_request();
            return;
        }
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    usort($combatants, function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: strcmp($a['name'], $b['name']);
    });

    $order = array_map(
        fn(array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
        $combatants
    );

    respond(200, ['order' => $order]);
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

if ($method === 'GET' && $path === '/health') {
    respond(200, ['ok' => true]);
    return;
}

$routes = [
    '/v1/dice/stats' => 'dice_stats',
    '/v1/checks/ability' => 'ability_check',
    '/v1/encounters/adjusted-xp' => 'encounter_xp',
    '/v1/initiative/order' => 'initiative_order',
];

if ($method !== 'POST' || !isset($routes[$path])) {
    respond(404, ['error' => 'not_found']);
    return;
}

$body = read_json_body();
if ($body === null) {
    bad_request();
    return;
}

$routes[$path]($body);

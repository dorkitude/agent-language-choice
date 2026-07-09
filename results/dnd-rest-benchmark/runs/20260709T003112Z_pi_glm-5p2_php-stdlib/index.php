<?php
declare(strict_types=1);

/* D&D REST engine — PHP stdlib built-in server router */

function respond(int $status, mixed $data): never
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($data, JSON_THROW_ON_ERROR);
    exit;
}

function json_body(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

$CR_XP = [
    '0'   => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1'   => 200,
    '2'   => 450,
    '3'   => 700,
    '4'   => 1100,
    '5'   => 1800,
];

$LEVEL_THRESHOLDS = [
    3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
];

function multiplier_for(int $n): int|float
{
    if ($n <= 1)  return 1;
    if ($n === 2) return 1.5;
    if ($n <= 6)  return 2;
    if ($n <= 10) return 2.5;
    if ($n <= 14) return 3;
    return 4;
}

$method = $_SERVER['REQUEST_METHOD'] ?? '';
$path   = parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH);

/* GET /health */
if ($method === 'GET' && $path === '/health') {
    respond(200, ['ok' => true]);
}

/* POST /v1/dice/stats */
if ($method === 'POST' && $path === '/v1/dice/stats') {
    $b = json_body();
    if ($b === null) {
        respond(400, ['error' => 'invalid json']);
    }
    $expr = $b['expression'] ?? '';
    if (!is_string($expr)) {
        respond(400, ['error' => 'invalid expression']);
    }
    $expr = trim($expr);
    if (!preg_match('/\A([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?\z/', $expr, $m)) {
        respond(400, ['error' => 'invalid expression']);
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    if ($count <= 0 || $sides <= 0) {
        respond(400, ['error' => 'invalid expression']);
    }
    $modifier = 0;
    if (isset($m[3]) && $m[3] !== '') {
        $modifier = (int) ($m[3] . $m[4]);
    }
    respond(200, [
        'dice_count' => $count,
        'sides'      => $sides,
        'modifier'   => $modifier,
        'min'        => $count * 1 + $modifier,
        'max'        => $count * $sides + $modifier,
        'average'    => $count * ($sides + 1) / 2 + $modifier,
    ]);
}

/* POST /v1/checks/ability */
if ($method === 'POST' && $path === '/v1/checks/ability') {
    $b = json_body();
    if ($b === null) {
        respond(400, ['error' => 'invalid json']);
    }
    $roll     = $b['roll']     ?? 0;
    $modifier = $b['modifier'] ?? 0;
    $dc       = $b['dc']       ?? 0;
    $total    = $roll + $modifier;
    respond(200, [
        'total'   => $total,
        'success' => $total >= $dc,
        'margin'  => $total - $dc,
    ]);
}

/* POST /v1/encounters/adjusted-xp */
if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $b = json_body();
    if ($b === null) {
        respond(400, ['error' => 'invalid json']);
    }
    $party    = $b['party']    ?? [];
    $monsters = $b['monsters'] ?? [];

    $baseXp       = 0;
    $monsterCount = 0;
    foreach ($monsters as $mon) {
        $cr   = (string) ($mon['cr'] ?? '');
        $cnt  = (int) ($mon['count'] ?? 0);
        $baseXp       += ($CR_XP[$cr] ?? 0) * $cnt;
        $monsterCount += $cnt;
    }

    $multiplier = multiplier_for($monsterCount);
    $adjusted   = $baseXp * $multiplier;

    $easy = $medium = $hard = $deadly = 0;
    foreach ($party as $member) {
        $lvl = (int) ($member['level'] ?? 3);
        $t   = $LEVEL_THRESHOLDS[$lvl] ?? $LEVEL_THRESHOLDS[3];
        $easy   += $t['easy'];
        $medium += $t['medium'];
        $hard   += $t['hard'];
        $deadly += $t['deadly'];
    }

    if ($adjusted >= $deadly) {
        $difficulty = 'deadly';
    } elseif ($adjusted >= $hard) {
        $difficulty = 'hard';
    } elseif ($adjusted >= $medium) {
        $difficulty = 'medium';
    } elseif ($adjusted >= $easy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    respond(200, [
        'base_xp'       => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier'    => $multiplier,
        'adjusted_xp'   => $adjusted,
        'difficulty'    => $difficulty,
        'thresholds'    => [
            'easy'   => $easy,
            'medium' => $medium,
            'hard'   => $hard,
            'deadly' => $deadly,
        ],
    ]);
}

/* POST /v1/initiative/order */
if ($method === 'POST' && $path === '/v1/initiative/order') {
    $b = json_body();
    if ($b === null) {
        respond(400, ['error' => 'invalid json']);
    }
    $combatants = $b['combatants'] ?? [];

    $list = [];
    foreach ($combatants as $c) {
        $name = (string) ($c['name'] ?? '');
        $dex  = (int) ($c['dex']  ?? 0);
        $roll = (int) ($c['roll'] ?? 0);
        $list[] = [
            'name'  => $name,
            'dex'   => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($list, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score']; // score descending
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex']; // dex descending
        }
        return strcmp($a['name'], $b['name']); // name ascending
    });

    $order = [];
    foreach ($list as $c) {
        $order[] = ['name' => $c['name'], 'score' => $c['score']];
    }

    respond(200, ['order' => $order]);
}

respond(404, ['error' => 'not found']);

<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

/* --------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------ */

function jsonResponse(Response $response, mixed $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data));
    return $response->withStatus($status)->withHeader('Content-Type', 'application/json');
}

function badRequest(Response $response): Response
{
    return jsonResponse($response, ['error' => 'bad_request'], 400);
}

function notFound(Response $response): Response
{
    return jsonResponse($response, ['error' => 'not_found'], 404);
}

/** Ability modifier: floor((score - 10) / 2), flooring negative halves. */
function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

/** Proficiency bonus by level band: 1-4→2, 5-8→3, 9-12→4, 13-16→5, 17-20→6. */
function proficiencyBonus(int $level): int
{
    return 2 + intdiv($level - 1, 4);
}

/** Validate that a value is an integer within [min, max]. */
function isIntInRange(mixed $value, int $min, int $max): bool
{
    return is_int($value) && $value >= $min && $value <= $max;
}

function jsonBody(Request $request): ?array
{
    $raw = (string) $request->getBody();
    if ($raw === '') {
        return null;
    }
    try {
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
    } catch (\JsonException $e) {
        return null;
    }
    return is_array($data) ? $data : null;
}

/* --------------------------------------------------------------------------
 * Data tables
 * ------------------------------------------------------------------------ */

$crXp = [
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

// First benchmark suite: level-3 encounter thresholds only.
$levelThresholds = [
    3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
];

function multFor(int $count): int|float
{
    return match (true) {
        $count <= 1  => 1,
        $count === 2 => 1.5,
        $count <= 6  => 2,
        $count <= 10 => 2.5,
        $count <= 14 => 3,
        default      => 4,
    };
}

/**
 * Parse `<count>d<sides>[+<modifier>|-<modifier>]`.
 * count and sides must be positive base-10 integers (no leading zeros).
 */
function parseDice(string $expr): ?array
{
    if (!preg_match('/^([1-9][0-9]*)d([1-9][0-9]*)(?:([+-])(0|[1-9][0-9]*))?$/', $expr, $m)) {
        return null;
    }
    $count    = (int) $m[1];
    $sides    = (int) $m[2];
    $modifier = 0;
    if (isset($m[3]) && $m[3] !== '') {
        $modifier = (int) ($m[3] . $m[4]);
    }
    return ['count' => $count, 'sides' => $sides, 'modifier' => $modifier];
}

/* --------------------------------------------------------------------------
 * Error handling (keep every response JSON)
 * ------------------------------------------------------------------------ */

$responseFactory = $app->getResponseFactory();
$errorMiddleware = $app->addErrorMiddleware(false, false, false);

$errorMiddleware->setDefaultErrorHandler(
    function () use ($responseFactory): Response {
        $response = $responseFactory->createResponse(500);
        $response->getBody()->write(json_encode(['error' => 'internal_server_error']));
        return $response->withHeader('Content-Type', 'application/json');
    }
);

$errorMiddleware->setErrorHandler(
    \Slim\Exception\HttpNotFoundException::class,
    function () use ($responseFactory): Response {
        $response = $responseFactory->createResponse(404);
        $response->getBody()->write(json_encode(['error' => 'not_found']));
        return $response->withHeader('Content-Type', 'application/json');
    }
);

/* --------------------------------------------------------------------------
 * Routes
 * ------------------------------------------------------------------------ */

$app->get('/health', function (Request $request, Response $response): Response {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        return badRequest($response);
    }
    $parsed = parseDice(trim($body['expression']));
    if ($parsed === null) {
        return badRequest($response);
    }
    $count    = $parsed['count'];
    $sides    = $parsed['sides'];
    $modifier = $parsed['modifier'];

    $min     = $count + $modifier;
    $max     = $count * $sides + $modifier;
    $average = ($count * ($sides + 1)) / 2 + $modifier;

    return jsonResponse($response, [
        'dice_count' => $count,
        'sides'      => $sides,
        'modifier'   => $modifier,
        'min'        => $min,
        'max'        => $max,
        'average'    => $average,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    if ($body === null) {
        return badRequest($response);
    }
    $roll     = $body['roll'] ?? null;
    $modifier = $body['modifier'] ?? null;
    $dc       = $body['dc'] ?? null;
    if (!is_int($roll) || !is_int($modifier) || !is_int($dc)) {
        return badRequest($response);
    }
    $total = $roll + $modifier;
    return jsonResponse($response, [
        'total'   => $total,
        'success' => $total >= $dc,
        'margin'  => $total - $dc,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) use ($crXp, $levelThresholds): Response {
    $body = jsonBody($request);
    if ($body === null
        || !isset($body['party'], $body['monsters'])
        || !is_array($body['party'])
        || !is_array($body['monsters'])
    ) {
        return badRequest($response);
    }

    // Sum party thresholds across members.
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member)
            || !isset($member['level'])
            || !is_int($member['level'])
            || !isset($levelThresholds[$member['level']])
        ) {
            return badRequest($response);
        }
        foreach (['easy', 'medium', 'hard', 'deadly'] as $k) {
            $thresholds[$k] += $levelThresholds[$member['level']][$k];
        }
    }

    // Base XP and monster count.
    $baseXp       = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $mon) {
        if (!is_array($mon)
            || !isset($mon['cr'], $mon['count'])
            || !is_int($mon['count'])
            || $mon['count'] < 1
        ) {
            return badRequest($response);
        }
        $crKey = is_string($mon['cr']) ? $mon['cr'] : (string) $mon['cr'];
        if (!isset($crXp[$crKey])) {
            return badRequest($response);
        }
        $baseXp       += $crXp[$crKey] * $mon['count'];
        $monsterCount += $mon['count'];
    }

    $mult        = multFor($monsterCount);
    $adjustedXp  = $baseXp * $mult;

    if ($adjustedXp >= $thresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $thresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $thresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $thresholds['easy']) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    return jsonResponse($response, [
        'base_xp'       => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier'    => $mult,
        'adjusted_xp'   => $adjustedXp,
        'difficulty'    => $difficulty,
        'thresholds'    => $thresholds,
    ]);
});

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    if ($body === null || !isset($body['score']) || !isIntInRange($body['score'], 1, 30)) {
        return badRequest($response);
    }
    $score = $body['score'];
    return jsonResponse($response, [
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    if ($body === null || !isset($body['level']) || !isIntInRange($body['level'], 1, 20)) {
        return badRequest($response);
    }
    $level = $body['level'];
    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    if ($body === null) {
        return badRequest($response);
    }
    if (!isset($body['level']) || !isIntInRange($body['level'], 1, 20)) {
        return badRequest($response);
    }
    $level = $body['level'];

    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    if (!isset($body['abilities']) || !is_array($body['abilities'])) {
        return badRequest($response);
    }
    foreach ($abilityKeys as $k) {
        if (!isset($body['abilities'][$k]) || !isIntInRange($body['abilities'][$k], 1, 30)) {
            return badRequest($response);
        }
    }
    $abilities = $body['abilities'];

    if (!isset($body['armor']) || !is_array($body['armor'])) {
        return badRequest($response);
    }
    $armor = $body['armor'];
    if (!isset($armor['base'], $armor['shield'], $armor['dex_cap'])
        || !is_int($armor['base'])
        || !is_bool($armor['shield'])
        || !is_int($armor['dex_cap'])
    ) {
        return badRequest($response);
    }

    $modifiers = [];
    foreach ($abilityKeys as $k) {
        $modifiers[$k] = abilityModifier((int) $abilities[$k]);
    }

    $proficiency = proficiencyBonus($level);
    $conMod = $modifiers['con'];
    $hpMax = $level * (6 + $conMod);

    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => $proficiency,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return badRequest($response);
    }
    $list = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c)
            || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name'])
            || !is_int($c['dex'])
            || !is_int($c['roll'])
        ) {
            return badRequest($response);
        }
        $list[] = [
            'name'  => $c['name'],
            'dex'   => $c['dex'],
            'roll'  => $c['roll'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }
    usort($list, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score']; // score descending
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex']; // dex descending
        }
        return $a['name'] <=> $b['name']; // name ascending
    });
    $order = array_map(fn($c) => ['name' => $c['name'], 'score' => $c['score']], $list);
    return jsonResponse($response, ['order' => $order]);
});

/* --------------------------------------------------------------------------
 * Combat state — file-backed so it survives the dev server's per-request reset
 * ------------------------------------------------------------------------ */

$combatStateFile = __DIR__ . '/.combat_sessions.json';

function loadCombatSessions(string $file): array
{
    if (!is_file($file)) {
        return [];
    }
    $raw = (string) @file_get_contents($file);
    if ($raw === '') {
        return [];
    }
    $data = json_decode($raw, true, 512);
    return is_array($data) ? $data : [];
}

function saveCombatSessions(string $file, array $sessions): void
{
    file_put_contents($file, json_encode($sessions));
}

/** Public view of a session: id, round, turn_index, active, order. */
function sessionSummary(array $s): array
{
    $active = $s['order'][$s['turn_index']];
    return [
        'id'         => $s['id'],
        'round'      => $s['round'],
        'turn_index' => $s['turn_index'],
        'active'     => ['name' => $active['name'], 'score' => $active['score']],
        'order'      => array_map(fn($c) => ['name' => $c['name'], 'score' => $c['score']], $s['order']),
    ];
}

/** Map of combatant name -> condition list (may be empty after expiry), for advance responses. */
function combatConditionsView(array $s): array|object
{
    $view = [];
    // Include every combatant that has a conditions entry, even if their
    // list is now empty (all conditions expired). The spec removes expired
    // *conditions*, not the combatant's slot in the map.
    foreach ($s['conditions'] as $name => $conds) {
        $conds = is_array($conds) ? $conds : [];
        $view[$name] = array_map(fn($c) => [
            'condition'        => $c['condition'],
            'remaining_rounds' => $c['remaining_rounds'],
        ], array_values($conds));
    }
    // Empty map must serialize as {} (not []) so consumers decoding into a
    // map[string]T don't choke on a JSON array.
    return empty($view) ? (object) [] : $view;
}

$app->post('/v1/combat/sessions', function (Request $request, Response $response) use ($combatStateFile): Response {
    $body = jsonBody($request);
    if ($body === null
        || !isset($body['id'], $body['combatants'])
        || !is_string($body['id'])
        || $body['id'] === ''
        || !is_array($body['combatants'])
        || empty($body['combatants'])
    ) {
        return badRequest($response);
    }
    $list = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c)
            || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name'])
            || !is_int($c['dex'])
            || !is_int($c['roll'])
        ) {
            return badRequest($response);
        }
        $list[] = [
            'name'  => $c['name'],
            'dex'   => $c['dex'],
            'roll'  => $c['roll'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }
    usort($list, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score']; // score descending
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex']; // dex descending
        }
        return $a['name'] <=> $b['name']; // name ascending
    });
    $order = array_map(fn($c) => ['name' => $c['name'], 'score' => $c['score']], $list);

    $sessions = loadCombatSessions($combatStateFile);
    $sessions[$body['id']] = [
        'id'         => $body['id'],
        'round'      => 1,
        'turn_index' => 0,
        'order'      => $order,
        'conditions' => [],
    ];
    saveCombatSessions($combatStateFile, $sessions);

    return jsonResponse($response, sessionSummary($sessions[$body['id']]));
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) use ($combatStateFile): Response {
    $sessions = loadCombatSessions($combatStateFile);
    $sid = $args['id'];
    if (!isset($sessions[$sid])) {
        return notFound($response);
    }
    $body = jsonBody($request);
    if ($body === null
        || !isset($body['target'], $body['condition'], $body['duration_rounds'])
        || !is_string($body['target'])
        || !is_string($body['condition'])
        || !is_int($body['duration_rounds'])
        || $body['duration_rounds'] < 1
    ) {
        return badRequest($response);
    }
    $s = $sessions[$sid];
    $names = array_column($s['order'], 'name');
    if (!in_array($body['target'], $names, true)) {
        return badRequest($response);
    }
    $target = $body['target'];
    if (!isset($s['conditions'][$target]) || !is_array($s['conditions'][$target])) {
        $s['conditions'][$target] = [];
    }
    $s['conditions'][$target][] = [
        'condition'        => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];
    $sessions[$sid] = $s;
    saveCombatSessions($combatStateFile, $sessions);

    return jsonResponse($response, [
        'target'     => $target,
        'conditions' => array_map(fn($c) => [
            'condition'        => $c['condition'],
            'remaining_rounds' => $c['remaining_rounds'],
        ], array_values($s['conditions'][$target])),
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) use ($combatStateFile): Response {
    $sessions = loadCombatSessions($combatStateFile);
    $sid = $args['id'];
    if (!isset($sessions[$sid])) {
        return notFound($response);
    }
    $s = $sessions[$sid];
    $count = count($s['order']);

    // Advance to the next combatant, wrapping + incrementing round at the end.
    $s['turn_index']++;
    if ($s['turn_index'] >= $count) {
        $s['turn_index'] = 0;
        $s['round']++;
    }

    // At the start of the active combatant's turn, decrement their conditions.
    $activeName = $s['order'][$s['turn_index']]['name'];
    if (isset($s['conditions'][$activeName]) && is_array($s['conditions'][$activeName])) {
        foreach ($s['conditions'][$activeName] as $i => $cond) {
            $s['conditions'][$activeName][$i]['remaining_rounds']--;
        }
        $s['conditions'][$activeName] = array_values(array_filter(
            $s['conditions'][$activeName],
            fn($c) => $c['remaining_rounds'] > 0
        ));
        // Keep the combatant's key (with an empty list) after expiry so the
        // conditions map still reports them as a known target.
    }

    $sessions[$sid] = $s;
    saveCombatSessions($combatStateFile, $sessions);

    $active = $s['order'][$s['turn_index']];
    return jsonResponse($response, [
        'id'         => $s['id'],
        'round'      => $s['round'],
        'turn_index' => $s['turn_index'],
        'active'     => ['name' => $active['name'], 'score' => $active['score']],
        'conditions' => combatConditionsView($s),
    ]);
});

$app->run();

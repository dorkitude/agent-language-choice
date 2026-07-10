<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

/** Write a JSON body and set the content type. */
function json_response(Response $response, array $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data));
    return $response->withHeader('Content-Type', 'application/json')->withStatus($status);
}

/** Decode a JSON request body into an array (empty array on failure). */
function json_body(Request $request): array
{
    $data = json_decode((string) $request->getBody(), true);
    return is_array($data) ? $data : [];
}

$app->get('/health', function (Request $request, Response $response) {
    return json_response($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = json_body($request);
    $expression = $data['expression'] ?? null;

    if (!is_string($expression) ||
        !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($expression), $m)) {
        return json_response($response, ['error' => 'invalid expression'], 400);
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return json_response($response, ['error' => 'invalid expression'], 400);
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;

    return json_response($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => ($min + $max) / 2,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $data = json_body($request);
    $roll = (int) ($data['roll'] ?? 0);
    $modifier = (int) ($data['modifier'] ?? 0);
    $dc = (int) ($data['dc'] ?? 0);

    $total = $roll + $modifier;

    return json_response($response, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
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

    $data = json_body($request);
    $party = $data['party'] ?? [];
    $monsters = $data['monsters'] ?? [];

    if (!is_array($party) || !is_array($monsters)) {
        return json_response($response, ['error' => 'invalid request'], 400);
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        $cr = (string) ($monster['cr'] ?? '');
        $mCount = (int) ($monster['count'] ?? 0);
        if (!array_key_exists($cr, $crXp)) {
            return json_response($response, ['error' => 'unsupported cr'], 400);
        }
        $baseXp += $crXp[$cr] * $mCount;
        $monsterCount += $mCount;
    }

    if ($monsterCount <= 1) {
        $multiplier = 1;
    } elseif ($monsterCount == 2) {
        $multiplier = 1.5;
    } elseif ($monsterCount <= 6) {
        $multiplier = 2;
    } elseif ($monsterCount <= 10) {
        $multiplier = 2.5;
    } elseif ($monsterCount <= 14) {
        $multiplier = 3;
    } else {
        $multiplier = 4;
    }

    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        $level = (int) ($member['level'] ?? 0);
        if (!array_key_exists($level, $thresholdTable)) {
            return json_response($response, ['error' => 'unsupported level'], 400);
        }
        foreach ($thresholdTable[$level] as $tier => $value) {
            $thresholds[$tier] += $value;
        }
    }

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    return json_response($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $data = json_body($request);
    $combatants = $data['combatants'] ?? [];

    if (!is_array($combatants)) {
        return json_response($response, ['error' => 'invalid request'], 400);
    }

    $order = [];
    foreach ($combatants as $c) {
        $name = (string) ($c['name'] ?? '');
        $dex = (int) ($c['dex'] ?? 0);
        $roll = (int) ($c['roll'] ?? 0);
        $order[] = ['name' => $name, 'dex' => $dex, 'score' => $roll + $dex];
    }

    usort($order, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $result = array_map(fn ($c) => ['name' => $c['name'], 'score' => $c['score']], $order);

    return json_response($response, ['order' => $result]);
});

/** D&D ability modifier: floor((score - 10) / 2), flooring negative halves. */
function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

/** D&D proficiency bonus derived from character level (1-20). */
function proficiency_bonus(int $level): int
{
    return (int) (floor(($level - 1) / 4) + 2);
}

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $data = json_body($request);
    $score = $data['score'] ?? null;

    if (!is_int($score) || $score < 1 || $score > 30) {
        return json_response($response, ['error' => 'invalid score'], 400);
    }

    return json_response($response, [
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $data = json_body($request);
    $level = $data['level'] ?? null;

    if (!is_int($level) || $level < 1 || $level > 20) {
        return json_response($response, ['error' => 'invalid level'], 400);
    }

    return json_response($response, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $data = json_body($request);

    $level = $data['level'] ?? null;
    $abilities = $data['abilities'] ?? null;
    $armor = $data['armor'] ?? null;

    if (!is_int($level) || $level < 1 || $level > 20) {
        return json_response($response, ['error' => 'invalid level'], 400);
    }
    if (!is_array($abilities) || !is_array($armor)) {
        return json_response($response, ['error' => 'invalid request'], 400);
    }

    $keys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($keys as $key) {
        $score = $abilities[$key] ?? null;
        if (!is_int($score) || $score < 1 || $score > 30) {
            return json_response($response, ['error' => 'invalid ability score'], 400);
        }
        $modifiers[$key] = ability_modifier($score);
    }

    $base = $armor['base'] ?? null;
    $dexCap = $armor['dex_cap'] ?? null;
    $shield = $armor['shield'] ?? false;
    if (!is_int($base) || !is_int($dexCap) || !is_bool($shield)) {
        return json_response($response, ['error' => 'invalid armor'], 400);
    }

    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    return json_response($response, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
});

/**
 * Combat session store. PHP's built-in server re-executes this script per
 * request, so process globals reset each time. To keep state for the lifetime
 * of the server process we persist to a temp file keyed by the server PID
 * (stable across requests for the single-process built-in server, and distinct
 * per restart so state resets naturally).
 */
function combat_store_path(): string
{
    return sys_get_temp_dir() . '/dnd_combat_' . getmypid() . '.json';
}

function load_combat_sessions(): array
{
    $path = combat_store_path();
    if (!is_file($path)) {
        return [];
    }
    $data = json_decode((string) file_get_contents($path), true);
    return is_array($data) ? $data : [];
}

function save_combat_sessions(array $sessions): void
{
    file_put_contents(combat_store_path(), json_encode($sessions));
}

/** Public view of a combatant: name + initiative score. */
function combatant_view(array $c): array
{
    return ['name' => $c['name'], 'score' => $c['score']];
}

/** Map of combatant name -> list of active conditions, only for those with any. */
function conditions_view(array $session): array
{
    $out = [];
    foreach ($session['order'] as $c) {
        $name = $c['name'];
        if (!empty($session['conditions'][$name])) {
            $out[$name] = array_map(
                fn ($cond) => [
                    'condition' => $cond['condition'],
                    'remaining_rounds' => $cond['remaining_rounds'],
                ],
                $session['conditions'][$name]
            );
        }
    }
    return $out;
}

$app->post('/v1/combat/sessions', function (Request $request, Response $response) {
    $combatSessions = load_combat_sessions();
    $data = json_body($request);

    $id = $data['id'] ?? null;
    $combatants = $data['combatants'] ?? null;

    if (!is_string($id) || $id === '') {
        return json_response($response, ['error' => 'invalid id'], 400);
    }
    if (isset($combatSessions[$id])) {
        return json_response($response, ['error' => 'session already exists'], 400);
    }
    if (!is_array($combatants) || count($combatants) === 0) {
        return json_response($response, ['error' => 'invalid combatants'], 400);
    }

    $order = [];
    foreach ($combatants as $c) {
        if (!is_array($c)) {
            return json_response($response, ['error' => 'invalid combatant'], 400);
        }
        $name = $c['name'] ?? null;
        $dex = $c['dex'] ?? null;
        $roll = $c['roll'] ?? null;
        if (!is_string($name) || $name === '' || !is_int($dex) || !is_int($roll)) {
            return json_response($response, ['error' => 'invalid combatant'], 400);
        }
        $order[] = ['name' => $name, 'dex' => $dex, 'score' => $roll + $dex];
    }

    usort($order, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    $combatSessions[$id] = $session;
    save_combat_sessions($combatSessions);

    return json_response($response, [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => combatant_view($order[0]),
        'order' => array_map('combatant_view', $order),
    ]);
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) {
    $combatSessions = load_combat_sessions();
    $id = $args['id'];
    if (!isset($combatSessions[$id])) {
        return json_response($response, ['error' => 'unknown session'], 404);
    }

    $data = json_body($request);
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $duration = $data['duration_rounds'] ?? null;

    $names = array_column($combatSessions[$id]['order'], 'name');
    if (!is_string($target) || !in_array($target, $names, true)) {
        return json_response($response, ['error' => 'invalid target'], 400);
    }
    if (!is_string($condition) || $condition === '') {
        return json_response($response, ['error' => 'invalid condition'], 400);
    }
    if (!is_int($duration) || $duration <= 0) {
        return json_response($response, ['error' => 'invalid duration_rounds'], 400);
    }

    $combatSessions[$id]['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    save_combat_sessions($combatSessions);

    return json_response($response, [
        'target' => $target,
        'conditions' => array_map(
            fn ($cond) => [
                'condition' => $cond['condition'],
                'remaining_rounds' => $cond['remaining_rounds'],
            ],
            $combatSessions[$id]['conditions'][$target]
        ),
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) {
    $combatSessions = load_combat_sessions();
    $id = $args['id'];
    if (!isset($combatSessions[$id])) {
        return json_response($response, ['error' => 'unknown session'], 404);
    }

    $session = &$combatSessions[$id];
    $count = count($session['order']);

    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $active = $session['order'][$session['turn_index']];
    $activeName = $active['name'];

    // Decrement conditions on the newly-active combatant; drop expired ones.
    if (!empty($session['conditions'][$activeName])) {
        $remaining = [];
        foreach ($session['conditions'][$activeName] as $cond) {
            $cond['remaining_rounds']--;
            if ($cond['remaining_rounds'] > 0) {
                $remaining[] = $cond;
            }
        }
        if ($remaining) {
            $session['conditions'][$activeName] = $remaining;
        } else {
            unset($session['conditions'][$activeName]);
        }
    }

    $result = [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => combatant_view($active),
        'conditions' => (object) conditions_view($session),
    ];
    unset($session);
    save_combat_sessions($combatSessions);

    return json_response($response, $result);
});

$app->run();

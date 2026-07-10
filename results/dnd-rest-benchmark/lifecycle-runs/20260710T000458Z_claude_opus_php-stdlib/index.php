<?php

declare(strict_types=1);

/**
 * Core D&D REST Engine — PHP 8.5 built-in server implementation.
 *
 * Run via the built-in server with this file as the router:
 *   php -S 127.0.0.1:$PORT index.php
 */

function send_json(mixed $data, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($data, JSON_UNESCAPED_SLASHES);
}

function read_json_body(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : null;
}

/** Emit a JSON number that stays an int when whole. */
function num(int|float $value): int|float
{
    if (is_float($value) && floor($value) === $value && is_finite($value)) {
        return (int) $value;
    }
    return $value;
}

function handle_dice_stats(): void
{
    $body = read_json_body();
    $expression = $body['expression'] ?? null;

    if (!is_string($expression) ||
        !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($expression), $m)) {
        send_json(['error' => 'invalid expression'], 400);
        return;
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        send_json(['error' => 'invalid expression'], 400);
        return;
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = $count * ($sides + 1) / 2 + $modifier;

    send_json([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => num($average),
    ]);
}

function handle_ability_check(): void
{
    $body = read_json_body();
    if (!is_array($body) ||
        !is_numeric($body['roll'] ?? null) ||
        !is_numeric($body['modifier'] ?? null) ||
        !is_numeric($body['dc'] ?? null)) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $roll = (int) $body['roll'];
    $modifier = (int) $body['modifier'];
    $dc = (int) $body['dc'];

    $total = $roll + $modifier;

    send_json([
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

function cr_xp_table(): array
{
    return [
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
}

function level_thresholds(): array
{
    // level => [easy, medium, hard, deadly]
    return [
        3 => [75, 150, 225, 400],
    ];
}

function encounter_multiplier(int $monsterCount): int|float
{
    return match (true) {
        $monsterCount <= 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };
}

function handle_adjusted_xp(): void
{
    $body = read_json_body();
    $party = $body['party'] ?? null;
    $monsters = $body['monsters'] ?? null;

    if (!is_array($party) || !is_array($monsters)) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $xpTable = cr_xp_table();
    $thresholdsByLevel = level_thresholds();

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster)) {
            send_json(['error' => 'invalid monster'], 400);
            return;
        }
        $cr = (string) ($monster['cr'] ?? '');
        $count = $monster['count'] ?? null;
        if (!array_key_exists($cr, $xpTable) || !is_numeric($count)) {
            send_json(['error' => 'invalid monster'], 400);
            return;
        }
        $count = (int) $count;
        $baseXp += $xpTable[$cr] * $count;
        $monsterCount += $count;
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member)) {
            send_json(['error' => 'invalid party member'], 400);
            return;
        }
        $level = $member['level'] ?? null;
        if (!is_numeric($level) || !array_key_exists((int) $level, $thresholdsByLevel)) {
            send_json(['error' => 'unsupported level'], 400);
            return;
        }
        [$easy, $medium, $hard, $deadly] = $thresholdsByLevel[(int) $level];
        $thresholds['easy'] += $easy;
        $thresholds['medium'] += $medium;
        $thresholds['hard'] += $hard;
        $thresholds['deadly'] += $deadly;
    }

    $multiplier = encounter_multiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    send_json([
        'base_xp' => num($baseXp),
        'monster_count' => $monsterCount,
        'multiplier' => num($multiplier),
        'adjusted_xp' => num($adjustedXp),
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => $thresholds['easy'],
            'medium' => $thresholds['medium'],
            'hard' => $thresholds['hard'],
            'deadly' => $thresholds['deadly'],
        ],
    ]);
}

function handle_initiative_order(): void
{
    $body = read_json_body();
    $combatants = $body['combatants'] ?? null;

    if (!is_array($combatants)) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $entries = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) ||
            !is_string($combatant['name'] ?? null) ||
            !is_numeric($combatant['dex'] ?? null) ||
            !is_numeric($combatant['roll'] ?? null)) {
            send_json(['error' => 'invalid combatant'], 400);
            return;
        }
        $name = $combatant['name'];
        $dex = (int) $combatant['dex'];
        $roll = (int) $combatant['roll'];
        $entries[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($entries, static function (array $a, array $b): int {
        return $b['score'] <=> $a['score']
            ?: $b['dex'] <=> $a['dex']
            ?: strcmp($a['name'], $b['name']);
    });

    $order = array_map(
        static fn (array $e): array => ['name' => $e['name'], 'score' => $e['score']],
        $entries
    );

    send_json(['order' => $order]);
}

/** Whole-number check that also rejects floats like 9.5. */
function as_int(mixed $value): ?int
{
    if (is_int($value)) {
        return $value;
    }
    if (is_float($value) && floor($value) === $value && is_finite($value)) {
        return (int) $value;
    }
    return null;
}

function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int
{
    return intdiv($level + 3, 4) + 1;
}

function handle_ability_modifier(): void
{
    $body = read_json_body();
    $score = as_int($body['score'] ?? null);

    if ($score === null || $score < 1 || $score > 30) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    send_json([
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

function handle_proficiency(): void
{
    $body = read_json_body();
    $level = as_int($body['level'] ?? null);

    if ($level === null || $level < 1 || $level > 20) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

function handle_derived_stats(): void
{
    $body = read_json_body();
    if (!is_array($body)) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $level = as_int($body['level'] ?? null);
    $abilities = $body['abilities'] ?? null;
    $armor = $body['armor'] ?? null;

    if ($level === null || $level < 1 || $level > 20 ||
        !is_array($abilities) || !is_array($armor)) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $key) {
        $score = as_int($abilities[$key] ?? null);
        if ($score === null || $score < 1 || $score > 30) {
            send_json(['error' => 'invalid request'], 400);
            return;
        }
        $modifiers[$key] = ability_modifier($score);
    }

    $base = as_int($armor['base'] ?? null);
    $dexCap = as_int($armor['dex_cap'] ?? null);
    $shield = $armor['shield'] ?? null;

    if ($base === null || $dexCap === null || !is_bool($shield)) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $proficiency = proficiency_bonus($level);
    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

    send_json([
        'level' => $level,
        'proficiency_bonus' => $proficiency,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

// --- Combat sessions -------------------------------------------------------

/**
 * The built-in PHP server re-executes this script per request, so in-memory
 * globals do not persist. We back combat state with a JSON file scoped to the
 * listening port so state survives for the lifetime of the server process.
 */
function combat_state_path(): string
{
    $port = getenv('PORT') ?: ($_SERVER['SERVER_PORT'] ?? '0');
    return sys_get_temp_dir() . '/dnd-combat-' . preg_replace('/\D/', '', (string) $port) . '.json';
}

/** @return array{sessions: array<string, array>} */
function combat_load(): array
{
    $path = combat_state_path();
    if (!is_file($path)) {
        return ['sessions' => []];
    }
    $raw = file_get_contents($path);
    if ($raw === false || $raw === '') {
        return ['sessions' => []];
    }
    $data = json_decode($raw, true);
    return is_array($data) && isset($data['sessions']) && is_array($data['sessions'])
        ? $data
        : ['sessions' => []];
}

function combat_save(array $state): void
{
    file_put_contents(combat_state_path(), json_encode($state), LOCK_EX);
}

/** Build the initiative order (name, dex, score) sorted per the spec. */
function combat_sort_order(array $entries): array
{
    usort($entries, static function (array $a, array $b): int {
        return $b['score'] <=> $a['score']
            ?: $b['dex'] <=> $a['dex']
            ?: strcmp($a['name'], $b['name']);
    });
    return $entries;
}

/** Public order projection: [{name, score}, ...] */
function combat_public_order(array $order): array
{
    return array_map(
        static fn (array $e): array => ['name' => $e['name'], 'score' => $e['score']],
        $order
    );
}

function combat_active(array $session): array
{
    $entry = $session['order'][$session['turn_index']];
    return ['name' => $entry['name'], 'score' => $entry['score']];
}

/** Conditions map projection preserving insertion order, filtering empties. */
function combat_conditions_view(array $session): array
{
    $view = [];
    foreach ($session['order'] as $entry) {
        $name = $entry['name'];
        // Include any combatant that has (or has had) conditions tracked,
        // even when the current list is empty after expiry.
        if (!array_key_exists($name, $session['conditions'])) {
            continue;
        }
        $conds = $session['conditions'][$name];
        $view[$name] = array_map(
            static fn (array $c): array => [
                'condition' => $c['condition'],
                'remaining_rounds' => $c['remaining_rounds'],
            ],
            $conds
        );
    }
    return $view;
}

function handle_combat_create(): void
{
    $body = read_json_body();
    $id = $body['id'] ?? null;
    $combatants = $body['combatants'] ?? null;

    if (!is_string($id) || $id === '' || !is_array($combatants) || $combatants === []) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $entries = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) ||
            !is_string($combatant['name'] ?? null) ||
            !is_numeric($combatant['dex'] ?? null) ||
            !is_numeric($combatant['roll'] ?? null)) {
            send_json(['error' => 'invalid combatant'], 400);
            return;
        }
        $dex = (int) $combatant['dex'];
        $roll = (int) $combatant['roll'];
        $entries[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    $state = combat_load();
    if (isset($state['sessions'][$id])) {
        send_json(['error' => 'session already exists'], 400);
        return;
    }

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => combat_sort_order($entries),
        'conditions' => [],
    ];
    $state['sessions'][$id] = $session;
    combat_save($state);

    send_json([
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => combat_active($session),
        'order' => combat_public_order($session['order']),
    ]);
}

function handle_combat_add_condition(string $id): void
{
    $body = read_json_body();
    $state = combat_load();

    if (!isset($state['sessions'][$id])) {
        send_json(['error' => 'unknown session'], 404);
        return;
    }

    $target = $body['target'] ?? null;
    $condition = $body['condition'] ?? null;
    $duration = as_int($body['duration_rounds'] ?? null);

    if (!is_string($target) || !is_string($condition) || $condition === '' ||
        $duration === null || $duration < 1) {
        send_json(['error' => 'invalid request'], 400);
        return;
    }

    $session = $state['sessions'][$id];
    $names = array_column($session['order'], 'name');
    if (!in_array($target, $names, true)) {
        send_json(['error' => 'unknown target'], 400);
        return;
    }

    $session['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    $state['sessions'][$id] = $session;
    combat_save($state);

    $conds = array_map(
        static fn (array $c): array => [
            'condition' => $c['condition'],
            'remaining_rounds' => $c['remaining_rounds'],
        ],
        $session['conditions'][$target]
    );

    send_json([
        'target' => $target,
        'conditions' => $conds,
    ]);
}

function handle_combat_advance(string $id): void
{
    $state = combat_load();

    if (!isset($state['sessions'][$id])) {
        send_json(['error' => 'unknown session'], 404);
        return;
    }

    $session = $state['sessions'][$id];
    $count = count($session['order']);

    $next = $session['turn_index'] + 1;
    if ($next >= $count) {
        $next = 0;
        $session['round']++;
    }
    $session['turn_index'] = $next;

    // Decrement conditions on the newly-active combatant only.
    $activeName = $session['order'][$next]['name'];
    if (!empty($session['conditions'][$activeName])) {
        $remaining = [];
        foreach ($session['conditions'][$activeName] as $cond) {
            $cond['remaining_rounds']--;
            if ($cond['remaining_rounds'] > 0) {
                $remaining[] = $cond;
            }
        }
        // Keep the combatant's key present even once all conditions expire.
        $session['conditions'][$activeName] = $remaining;
    }

    $state['sessions'][$id] = $session;
    combat_save($state);

    send_json([
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => combat_active($session),
        'conditions' => (object) combat_conditions_view($session),
    ]);
}

// --- Routing ---------------------------------------------------------------

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';

$routes = [
    'GET /health' => static function (): void {
        send_json(['ok' => true]);
    },
    'POST /v1/dice/stats' => 'handle_dice_stats',
    'POST /v1/checks/ability' => 'handle_ability_check',
    'POST /v1/encounters/adjusted-xp' => 'handle_adjusted_xp',
    'POST /v1/initiative/order' => 'handle_initiative_order',
    'POST /v1/characters/ability-modifier' => 'handle_ability_modifier',
    'POST /v1/characters/proficiency' => 'handle_proficiency',
    'POST /v1/characters/derived-stats' => 'handle_derived_stats',
    'POST /v1/combat/sessions' => 'handle_combat_create',
];

$key = $method . ' ' . $path;

if (isset($routes[$key])) {
    ($routes[$key])();
} elseif ($method === 'POST' &&
    preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $m)) {
    handle_combat_add_condition(rawurldecode($m[1]));
} elseif ($method === 'POST' &&
    preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $m)) {
    handle_combat_advance(rawurldecode($m[1]));
} else {
    send_json(['error' => 'not found'], 404);
}

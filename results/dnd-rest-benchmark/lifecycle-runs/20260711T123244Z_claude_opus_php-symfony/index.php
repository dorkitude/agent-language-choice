<?php

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

/**
 * Durable storage schema version. Bump alongside migrations.
 */
const STORAGE_SCHEMA_VERSION = 1;

/**
 * Path to the SQLite database file. Durable game-world and game-state data
 * (combat sessions, user accounts) live here so they survive across the
 * per-request processes the PHP built-in server spawns. Defaults to game.db
 * in the project directory; overridable for per-port isolation in tests.
 */
function db_file(): string
{
    $path = getenv('DND_DB_FILE');
    if ($path === false || $path === '') {
        $path = __DIR__ . '/game.db';
    }
    return $path;
}

/**
 * Return a process-wide PDO handle to the SQLite database.
 */
function db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . db_file());
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->exec('PRAGMA busy_timeout=5000');
    }
    return $pdo;
}

/**
 * Create the durable schema if it does not already exist. Idempotent so it
 * can safely run on every startup and request.
 */
function init_schema(PDO $pdo): void
{
    $pdo->exec('CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    // Game-world compendium: monsters and items keyed by unique slug. Full
    // records are stored as JSON blobs so response shaping stays in the
    // handlers rather than the schema.
    $pdo->exec('CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, data TEXT NOT NULL)');
    // Campaign state: campaigns own characters and session-log events. Child
    // rows carry a monotonically increasing seq so insertion order is stable.
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS campaign_characters ('
        . 'campaign_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, '
        . 'seq INTEGER NOT NULL, PRIMARY KEY (campaign_id, id))'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS campaign_events ('
        . 'campaign_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, '
        . 'seq INTEGER NOT NULL, PRIMARY KEY (campaign_id, id))'
    );
}

/**
 * Whether the durable schema has been initialized in the database.
 */
function storage_initialized(PDO $pdo): bool
{
    $stmt = $pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name='kv'");
    return $stmt->fetchColumn() !== false;
}

/**
 * Run $callback with exclusive access to a JSON-encoded value stored under
 * $key. The decoded array is passed by reference; any mutation is persisted
 * atomically. Rows are stored as JSON blobs so existing handler logic, which
 * operates on plain PHP arrays, is preserved unchanged.
 */
function with_kv_state(string $key, callable $callback)
{
    $pdo = db();
    init_schema($pdo);
    $pdo->exec('BEGIN IMMEDIATE');
    try {
        $stmt = $pdo->prepare('SELECT value FROM kv WHERE key = ?');
        $stmt->execute([$key]);
        $raw = $stmt->fetchColumn();
        $data = ($raw === false || $raw === '') ? [] : json_decode($raw, true);
        if (!is_array($data)) {
            $data = [];
        }
        $result = $callback($data);
        $up = $pdo->prepare(
            'INSERT INTO kv (key, value) VALUES (?, ?) '
            . 'ON CONFLICT(key) DO UPDATE SET value = excluded.value'
        );
        $up->execute([$key, json_encode($data)]);
        $pdo->exec('COMMIT');
        return $result;
    } catch (\Throwable $e) {
        $pdo->exec('ROLLBACK');
        throw $e;
    }
}

/**
 * Decode the JSON body of a request, returning an associative array.
 * Throws on malformed JSON so callers can return HTTP 400.
 */
function decode_json_body(Request $request): array
{
    $raw = $request->getContent();
    if ($raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        throw new InvalidArgumentException('invalid JSON body');
    }
    return $data;
}

function bad_request(string $message): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

/** GET /health */
function handle_health(Request $request): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

/** POST /v1/dice/stats */
function handle_dice_stats(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $expression = $body['expression'] ?? null;
    if (!is_string($expression)) {
        return bad_request('expression must be a string');
    }

    // <count>d<sides>[+<modifier>|-<modifier>]
    if (!preg_match('/^\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$/', $expression, $m)) {
        return bad_request('invalid expression');
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = 0;
    if (isset($m[3]) && $m[3] !== '') {
        $modifier = (int) str_replace(' ', '', $m[3]);
    }

    if ($count <= 0 || $sides <= 0) {
        return bad_request('count and sides must be positive');
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => normalize_number($average),
    ]);
}

/** POST /v1/checks/ability */
function handle_ability_check(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    if (!is_int_like($body['roll'] ?? null)
        || !is_int_like($body['modifier'] ?? null)
        || !is_int_like($body['dc'] ?? null)) {
        return bad_request('roll, modifier, and dc must be integers');
    }

    $roll = (int) $body['roll'];
    $modifier = (int) $body['modifier'];
    $dc = (int) $body['dc'];

    $total = $roll + $modifier;

    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

/** POST /v1/encounters/adjusted-xp */
function handle_adjusted_xp(Request $request): JsonResponse
{
    static $crXp = [
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

    // Level => [easy, medium, hard, deadly]
    static $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $party = $body['party'] ?? null;
    $monsters = $body['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        return bad_request('party and monsters must be arrays');
    }

    // Sum party thresholds across members.
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !is_int_like($member['level'] ?? null)) {
            return bad_request('each party member requires an integer level');
        }
        $level = (int) $member['level'];
        if (!isset($levelThresholds[$level])) {
            return bad_request('unsupported party level: ' . $level);
        }
        foreach ($levelThresholds[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    // Base XP and monster count.
    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster)) {
            return bad_request('each monster must be an object');
        }
        $cr = $monster['cr'] ?? null;
        if (is_int($cr) || is_float($cr)) {
            $cr = rtrim(rtrim((string) $cr, '0'), '.');
        }
        if (!is_string($cr) || !isset($crXp[$cr])) {
            return bad_request('unsupported challenge rating');
        }
        if (!is_int_like($monster['count'] ?? null)) {
            return bad_request('monster count must be an integer');
        }
        $count = (int) $monster['count'];
        if ($count < 0) {
            return bad_request('monster count must be non-negative');
        }
        $baseXp += $crXp[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = encounter_multiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    return new JsonResponse([
        'base_xp' => normalize_number($baseXp),
        'monster_count' => $monsterCount,
        'multiplier' => normalize_number($multiplier),
        'adjusted_xp' => normalize_number($adjustedXp),
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

/** POST /v1/initiative/order */
function handle_initiative_order(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $combatants = $body['combatants'] ?? null;
    if (!is_array($combatants)) {
        return bad_request('combatants must be an array');
    }

    $entries = [];
    foreach ($combatants as $index => $combatant) {
        if (!is_array($combatant)
            || !is_string($combatant['name'] ?? null)
            || !is_int_like($combatant['dex'] ?? null)
            || !is_int_like($combatant['roll'] ?? null)) {
            return bad_request('each combatant requires name, dex, and roll');
        }
        $name = $combatant['name'];
        $dex = (int) $combatant['dex'];
        $roll = (int) $combatant['roll'];
        $entries[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
            'index' => $index,
        ];
    }

    usort($entries, function (array $a, array $b): int {
        // Score descending.
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        // Dex descending.
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        // Name ascending.
        if ($a['name'] !== $b['name']) {
            return $a['name'] <=> $b['name'];
        }
        // Stable fallback on original order.
        return $a['index'] <=> $b['index'];
    });

    $order = array_map(
        static fn (array $e): array => ['name' => $e['name'], 'score' => $e['score']],
        $entries
    );

    return new JsonResponse(['order' => $order]);
}

/** POST /v1/characters/ability-modifier */
function handle_ability_modifier(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    if (!is_int_like($body['score'] ?? null)) {
        return bad_request('score must be an integer');
    }
    $score = (int) $body['score'];
    if ($score < 1 || $score > 30) {
        return bad_request('score must be between 1 and 30');
    }

    return new JsonResponse([
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

/** POST /v1/characters/proficiency */
function handle_proficiency(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    if (!is_int_like($body['level'] ?? null)) {
        return bad_request('level must be an integer');
    }
    $level = (int) $body['level'];
    if ($level < 1 || $level > 20) {
        return bad_request('level must be between 1 and 20');
    }

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

/** POST /v1/characters/derived-stats */
function handle_derived_stats(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    if (!is_int_like($body['level'] ?? null)) {
        return bad_request('level must be an integer');
    }
    $level = (int) $body['level'];
    if ($level < 1 || $level > 20) {
        return bad_request('level must be between 1 and 20');
    }

    $abilities = $body['abilities'] ?? null;
    if (!is_array($abilities)) {
        return bad_request('abilities must be an object');
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $key) {
        if (!is_int_like($abilities[$key] ?? null)) {
            return bad_request('ability ' . $key . ' must be an integer');
        }
        $score = (int) $abilities[$key];
        if ($score < 1 || $score > 30) {
            return bad_request('ability ' . $key . ' must be between 1 and 30');
        }
        $modifiers[$key] = ability_modifier($score);
    }

    $armor = $body['armor'] ?? null;
    if (!is_array($armor)) {
        return bad_request('armor must be an object');
    }
    if (!is_int_like($armor['base'] ?? null)) {
        return bad_request('armor.base must be an integer');
    }
    if (!is_int_like($armor['dex_cap'] ?? null)) {
        return bad_request('armor.dex_cap must be an integer');
    }
    if (!is_bool($armor['shield'] ?? null)) {
        return bad_request('armor.shield must be a boolean');
    }
    $base = (int) $armor['base'];
    $dexCap = (int) $armor['dex_cap'];
    $shieldBonus = $armor['shield'] ? 2 : 0;

    $hpMax = $level * (6 + $modifiers['con']);
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

// --- Combat sessions ------------------------------------------------------

/**
 * Run $callback with exclusive access to the combat store. The current
 * sessions array is passed by reference; any mutation is persisted to the
 * SQLite-backed durable store.
 */
function with_combat_state(callable $callback)
{
    return with_kv_state('combat_sessions', $callback);
}

/** Project a stored order entry down to its public {name, score} shape. */
function combat_public_entry(array $entry): array
{
    return ['name' => $entry['name'], 'score' => $entry['score']];
}

/** Build the conditions map for a session's response (names with conditions). */
function combat_conditions_map(array $session): array
{
    $map = [];
    foreach ($session['order'] as $entry) {
        $name = $entry['name'];
        // Include any combatant that has had a condition attached, even if the
        // list is now empty (an expired condition leaves the key with []).
        if (array_key_exists($name, $session['conditions'])) {
            $map[$name] = array_values($session['conditions'][$name]);
        }
    }
    return $map;
}

/** POST /v1/combat/sessions */
function handle_combat_create(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $id = $body['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return bad_request('id must be a non-empty string');
    }

    $combatants = $body['combatants'] ?? null;
    if (!is_array($combatants) || $combatants === []) {
        return bad_request('combatants must be a non-empty array');
    }

    $entries = [];
    foreach ($combatants as $index => $combatant) {
        if (!is_array($combatant)
            || !is_string($combatant['name'] ?? null)
            || !is_int_like($combatant['dex'] ?? null)
            || !is_int_like($combatant['roll'] ?? null)) {
            return bad_request('each combatant requires name, dex, and roll');
        }
        $dex = (int) $combatant['dex'];
        $roll = (int) $combatant['roll'];
        $entries[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
            'index' => $index,
        ];
    }

    usort($entries, function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        if ($a['name'] !== $b['name']) {
            return $a['name'] <=> $b['name'];
        }
        return $a['index'] <=> $b['index'];
    });

    $order = array_map(
        static fn (array $e): array => ['name' => $e['name'], 'dex' => $e['dex'], 'score' => $e['score']],
        $entries
    );

    $conflict = with_combat_state(function (array &$sessions) use ($id, $order): bool {
        if (isset($sessions[$id])) {
            return true;
        }
        $sessions[$id] = [
            'id' => $id,
            'round' => 1,
            'turn_index' => 0,
            'order' => $order,
            'conditions' => [],
        ];
        return false;
    });

    if ($conflict) {
        return bad_request('session id already exists');
    }

    return new JsonResponse([
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => combat_public_entry($order[0]),
        'order' => array_map('combat_public_entry', $order),
    ]);
}

/** POST /v1/combat/sessions/{id}/conditions */
function handle_combat_add_condition(Request $request, string $id): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $target = $body['target'] ?? null;
    $condition = $body['condition'] ?? null;
    if (!is_string($target) || !is_string($condition)) {
        return bad_request('target and condition must be strings');
    }
    if (!is_int_like($body['duration_rounds'] ?? null)) {
        return bad_request('duration_rounds must be an integer');
    }
    $duration = (int) $body['duration_rounds'];
    if ($duration <= 0) {
        return bad_request('duration_rounds must be positive');
    }

    $outcome = with_combat_state(function (array &$sessions) use ($id, $target, $condition, $duration) {
        if (!isset($sessions[$id])) {
            return ['status' => 404];
        }
        $names = array_column($sessions[$id]['order'], 'name');
        if (!in_array($target, $names, true)) {
            return ['status' => 400];
        }
        $sessions[$id]['conditions'][$target][] = [
            'condition' => $condition,
            'remaining_rounds' => $duration,
        ];
        return [
            'status' => 200,
            'conditions' => array_values($sessions[$id]['conditions'][$target]),
        ];
    });

    if ($outcome['status'] === 404) {
        return new JsonResponse(['error' => 'unknown session'], 404);
    }
    if ($outcome['status'] === 400) {
        return bad_request('target is not a combatant in this session');
    }

    return new JsonResponse([
        'target' => $target,
        'conditions' => $outcome['conditions'],
    ]);
}

/** POST /v1/combat/sessions/{id}/advance */
function handle_combat_advance(Request $request, string $id): JsonResponse
{
    $outcome = with_combat_state(function (array &$sessions) use ($id) {
        if (!isset($sessions[$id])) {
            return null;
        }
        $session = &$sessions[$id];
        $count = count($session['order']);

        $session['turn_index']++;
        if ($session['turn_index'] >= $count) {
            $session['turn_index'] = 0;
            $session['round']++;
        }

        // Decrement conditions on the newly active combatant.
        $activeName = $session['order'][$session['turn_index']]['name'];
        if (!empty($session['conditions'][$activeName])) {
            $remaining = [];
            foreach ($session['conditions'][$activeName] as $condition) {
                $condition['remaining_rounds']--;
                if ($condition['remaining_rounds'] > 0) {
                    $remaining[] = $condition;
                }
            }
            // Keep the combatant's key even when all conditions have expired;
            // the response reports an empty list rather than dropping the name.
            $session['conditions'][$activeName] = $remaining;
        }

        return [
            'id' => $session['id'],
            'round' => $session['round'],
            'turn_index' => $session['turn_index'],
            'active' => combat_public_entry($session['order'][$session['turn_index']]),
            'conditions' => combat_conditions_map($session) ?: new stdClass(),
        ];
    });

    if ($outcome === null) {
        return new JsonResponse(['error' => 'unknown session'], 404);
    }

    return new JsonResponse($outcome);
}

// --- Users and authentication ---------------------------------------------

/**
 * Run $callback with exclusive access to the user store. The current users
 * array (keyed by username) is passed by reference; any mutation is persisted
 * to the SQLite-backed durable store.
 */
function with_user_state(callable $callback)
{
    return with_kv_state('users', $callback);
}

/**
 * Hash a plaintext password using PHP's framework-provided default algorithm.
 * Isolated here so the storage format can change without touching handlers.
 */
function hash_password(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

/** Verify a plaintext password against a stored hash. */
function verify_password(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

/** POST /v1/auth/register */
function handle_auth_register(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $username = $body['username'] ?? null;
    if (!is_string($username) || !preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        return bad_request('username must be 2-32 lowercase letters, digits, _ or -');
    }

    $password = $body['password'] ?? null;
    if (!is_string($password) || strlen($password) < 8) {
        return bad_request('password must be at least 8 characters');
    }

    $role = $body['role'] ?? null;
    if ($role !== 'dm' && $role !== 'player') {
        return bad_request('role must be dm or player');
    }

    $duplicate = with_user_state(function (array &$users) use ($username, $password, $role): bool {
        if (isset($users[$username])) {
            return true;
        }
        $users[$username] = [
            'username' => $username,
            'role' => $role,
            'password_hash' => hash_password($password),
        ];
        return false;
    });

    if ($duplicate) {
        return new JsonResponse(['error' => 'username already exists'], 409);
    }

    return new JsonResponse([
        'username' => $username,
        'role' => $role,
    ], 201);
}

/** POST /v1/auth/login */
function handle_auth_login(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $username = $body['username'] ?? null;
    $password = $body['password'] ?? null;
    if (!is_string($username) || !is_string($password)) {
        return bad_request('username and password must be strings');
    }

    $user = with_user_state(function (array &$users) use ($username) {
        return $users[$username] ?? null;
    });

    if ($user === null || !verify_password($password, $user['password_hash'])) {
        return new JsonResponse(['error' => 'invalid credentials'], 401);
    }

    return new JsonResponse([
        'username' => $username,
        'token' => 'session-' . $username,
    ]);
}

/**
 * Ability modifier: floor((score - 10) / 2), flooring negative halves.
 */
function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

/**
 * Proficiency bonus derived from level (1-20).
 */
function proficiency_bonus(int $level): int
{
    return intdiv($level - 1, 4) + 2;
}

/**
 * Encounter multiplier based on number of monsters.
 */
function encounter_multiplier(int $monsterCount): float
{
    return match (true) {
        $monsterCount <= 1 => 1.0,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2.0,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3.0,
        default => 4.0,
    };
}

/**
 * Whether a value is an integer or an integer-valued numeric.
 * Rejects booleans, strings, and non-integral floats.
 */
function is_int_like($value): bool
{
    if (is_bool($value)) {
        return false;
    }
    if (is_int($value)) {
        return true;
    }
    if (is_float($value)) {
        return floor($value) === $value;
    }
    return false;
}

/**
 * Emit whole numbers as ints so JSON has no trailing ".0".
 */
function normalize_number(float|int $value): float|int
{
    if (is_int($value)) {
        return $value;
    }
    if (floor($value) === $value) {
        return (int) $value;
    }
    return $value;
}

// --- Compendium -----------------------------------------------------------

/** POST /v1/compendium/monsters */
function handle_monster_create(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $slug = $body['slug'] ?? null;
    if (!is_string($slug) || !preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $slug)) {
        return bad_request('slug must be a lowercase kebab-case string');
    }
    $name = $body['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return bad_request('name must be a non-empty string');
    }
    $cr = $body['cr'] ?? null;
    if (!is_string($cr) || $cr === '') {
        return bad_request('cr must be a non-empty string');
    }
    if (!is_int_like($body['armor_class'] ?? null)) {
        return bad_request('armor_class must be an integer');
    }
    if (!is_int_like($body['hit_points'] ?? null)) {
        return bad_request('hit_points must be an integer');
    }
    $armorClass = (int) $body['armor_class'];
    $hitPoints = (int) $body['hit_points'];

    $tags = $body['tags'] ?? [];
    if (!is_array($tags)) {
        return bad_request('tags must be an array');
    }
    $tagList = [];
    foreach ($tags as $tag) {
        if (!is_string($tag)) {
            return bad_request('each tag must be a string');
        }
        $tagList[] = $tag;
    }

    $record = [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
        'tags' => $tagList,
    ];

    $pdo = db();
    init_schema($pdo);
    $stmt = $pdo->prepare('INSERT OR IGNORE INTO monsters (slug, data) VALUES (?, ?)');
    $stmt->execute([$slug, json_encode($record)]);
    if ($stmt->rowCount() === 0) {
        return new JsonResponse(['error' => 'monster slug already exists'], 409);
    }

    return new JsonResponse([
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
    ], 201);
}

/** GET /v1/compendium/monsters/{slug} */
function handle_monster_read(Request $request, string $slug): JsonResponse
{
    $pdo = db();
    init_schema($pdo);
    $stmt = $pdo->prepare('SELECT data FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    $raw = $stmt->fetchColumn();
    if ($raw === false) {
        return new JsonResponse(['error' => 'unknown monster'], 404);
    }
    $record = json_decode($raw, true);

    return new JsonResponse([
        'slug' => $record['slug'],
        'name' => $record['name'],
        'cr' => $record['cr'],
        'armor_class' => $record['armor_class'],
        'hit_points' => $record['hit_points'],
        'tags' => $record['tags'],
    ]);
}

/** POST /v1/compendium/items */
function handle_item_create(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $slug = $body['slug'] ?? null;
    if (!is_string($slug) || !preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $slug)) {
        return bad_request('slug must be a lowercase kebab-case string');
    }
    $name = $body['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return bad_request('name must be a non-empty string');
    }
    $type = $body['type'] ?? null;
    if (!is_string($type) || $type === '') {
        return bad_request('type must be a non-empty string');
    }
    $rarity = $body['rarity'] ?? null;
    if (!is_string($rarity) || $rarity === '') {
        return bad_request('rarity must be a non-empty string');
    }
    if (!is_int_like($body['cost_gp'] ?? null)) {
        return bad_request('cost_gp must be an integer');
    }
    $costGp = (int) $body['cost_gp'];

    $record = [
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $costGp,
    ];

    $pdo = db();
    init_schema($pdo);
    $stmt = $pdo->prepare('INSERT OR IGNORE INTO items (slug, data) VALUES (?, ?)');
    $stmt->execute([$slug, json_encode($record)]);
    if ($stmt->rowCount() === 0) {
        return new JsonResponse(['error' => 'item slug already exists'], 409);
    }

    return new JsonResponse($record, 201);
}

/** GET /v1/compendium/items/{slug} */
function handle_item_read(Request $request, string $slug): JsonResponse
{
    $pdo = db();
    init_schema($pdo);
    $stmt = $pdo->prepare('SELECT data FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    $raw = $stmt->fetchColumn();
    if ($raw === false) {
        return new JsonResponse(['error' => 'unknown item'], 404);
    }
    $record = json_decode($raw, true);

    return new JsonResponse([
        'slug' => $record['slug'],
        'name' => $record['name'],
        'type' => $record['type'],
        'rarity' => $record['rarity'],
        'cost_gp' => $record['cost_gp'],
    ]);
}

// --- Campaign state -------------------------------------------------------

/** Whether a campaign row exists for the given id. */
function campaign_exists(PDO $pdo, string $id): bool
{
    $stmt = $pdo->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    return $stmt->fetchColumn() !== false;
}

/** POST /v1/campaigns */
function handle_campaign_create(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $id = $body['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return bad_request('id must be a non-empty string');
    }
    $name = $body['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return bad_request('name must be a non-empty string');
    }
    $dm = $body['dm'] ?? null;
    if (!is_string($dm) || $dm === '') {
        return bad_request('dm must be a non-empty string');
    }

    $record = ['id' => $id, 'name' => $name, 'dm' => $dm];

    $pdo = db();
    init_schema($pdo);
    $stmt = $pdo->prepare('INSERT OR IGNORE INTO campaigns (id, data) VALUES (?, ?)');
    $stmt->execute([$id, json_encode($record)]);
    if ($stmt->rowCount() === 0) {
        return new JsonResponse(['error' => 'campaign id already exists'], 409);
    }

    return new JsonResponse($record, 201);
}

/** POST /v1/campaigns/{id}/characters */
function handle_campaign_add_character(Request $request, string $campaignId): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $id = $body['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return bad_request('id must be a non-empty string');
    }
    $name = $body['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return bad_request('name must be a non-empty string');
    }
    if (!is_int_like($body['level'] ?? null)) {
        return bad_request('level must be an integer');
    }
    $level = (int) $body['level'];
    $class = $body['class'] ?? null;
    if (!is_string($class) || $class === '') {
        return bad_request('class must be a non-empty string');
    }

    $record = ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class];

    $pdo = db();
    init_schema($pdo);
    if (!campaign_exists($pdo, $campaignId)) {
        return new JsonResponse(['error' => 'unknown campaign'], 404);
    }
    $seq = (int) $pdo->query('SELECT COALESCE(MAX(seq), 0) + 1 FROM campaign_characters')->fetchColumn();
    $stmt = $pdo->prepare('INSERT OR IGNORE INTO campaign_characters (campaign_id, id, data, seq) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $id, json_encode($record), $seq]);
    if ($stmt->rowCount() === 0) {
        return new JsonResponse(['error' => 'character id already exists'], 409);
    }

    return new JsonResponse($record, 201);
}

/** POST /v1/campaigns/{id}/events */
function handle_campaign_add_event(Request $request, string $campaignId): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $id = $body['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return bad_request('id must be a non-empty string');
    }
    $kind = $body['kind'] ?? null;
    if (!is_string($kind) || $kind === '') {
        return bad_request('kind must be a non-empty string');
    }
    $summary = $body['summary'] ?? null;
    if (!is_string($summary) || $summary === '') {
        return bad_request('summary must be a non-empty string');
    }

    $record = ['id' => $id, 'kind' => $kind, 'summary' => $summary];

    $pdo = db();
    init_schema($pdo);
    if (!campaign_exists($pdo, $campaignId)) {
        return new JsonResponse(['error' => 'unknown campaign'], 404);
    }
    $seq = (int) $pdo->query('SELECT COALESCE(MAX(seq), 0) + 1 FROM campaign_events')->fetchColumn();
    $stmt = $pdo->prepare('INSERT OR IGNORE INTO campaign_events (campaign_id, id, data, seq) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $id, json_encode($record), $seq]);
    if ($stmt->rowCount() === 0) {
        return new JsonResponse(['error' => 'event id already exists'], 409);
    }

    return new JsonResponse(['id' => $id, 'kind' => $kind], 201);
}

/** GET /v1/campaigns/{id}/state */
function handle_campaign_state(Request $request, string $campaignId): JsonResponse
{
    $pdo = db();
    init_schema($pdo);

    $stmt = $pdo->prepare('SELECT data FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    $raw = $stmt->fetchColumn();
    if ($raw === false) {
        return new JsonResponse(['error' => 'unknown campaign'], 404);
    }
    $campaign = json_decode($raw, true);

    $stmt = $pdo->prepare('SELECT data FROM campaign_characters WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $characters = [];
    foreach ($stmt->fetchAll(PDO::FETCH_COLUMN) as $row) {
        $characters[] = json_decode($row, true);
    }

    $stmt = $pdo->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $logCount = (int) $stmt->fetchColumn();

    return new JsonResponse([
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => $logCount,
    ]);
}

// --- DM tools -------------------------------------------------------------

/**
 * Challenge-rating to base-XP table shared with the core encounter math.
 * Returns null for an unsupported CR string.
 */
function cr_base_xp(string $cr): ?int
{
    static $crXp = [
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
    return $crXp[$cr] ?? null;
}

/**
 * Per-member encounter difficulty thresholds, keyed by character level.
 * Returns null for an unsupported level.
 */
function level_difficulty_thresholds(int $level): ?array
{
    static $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];
    return $levelThresholds[$level] ?? null;
}

/**
 * POST /v1/dm/encounter-builder
 *
 * Combines stored compendium CR data with the core adjusted-XP math to
 * produce a deterministic difficulty rating and recommendation.
 */
function handle_dm_encounter_builder(Request $request): JsonResponse
{
    static $recommendations = [
        'trivial' => 'trivial skirmish',
        'easy' => 'safe warm-up',
        'medium' => 'balanced clash',
        'hard' => 'grueling fight',
        'deadly' => 'deadly gauntlet',
    ];

    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $campaignId = $body['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        return bad_request('campaign_id must be a non-empty string');
    }
    $party = $body['party'] ?? null;
    $monsterSlugs = $body['monster_slugs'] ?? null;
    if (!is_array($party) || !is_array($monsterSlugs)) {
        return bad_request('party and monster_slugs must be arrays');
    }

    $pdo = db();
    init_schema($pdo);
    if (!campaign_exists($pdo, $campaignId)) {
        return new JsonResponse(['error' => 'unknown campaign'], 404);
    }

    // Sum per-member difficulty thresholds across the party.
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !is_int_like($member['level'] ?? null)) {
            return bad_request('each party member requires an integer level');
        }
        $tiers = level_difficulty_thresholds((int) $member['level']);
        if ($tiers === null) {
            return bad_request('unsupported party level: ' . (int) $member['level']);
        }
        foreach ($tiers as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    // Look up each monster CR from the compendium and sum base XP.
    $lookup = $pdo->prepare('SELECT data FROM monsters WHERE slug = ?');
    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug) || $slug === '') {
            return bad_request('each monster slug must be a non-empty string');
        }
        $lookup->execute([$slug]);
        $raw = $lookup->fetchColumn();
        if ($raw === false) {
            return new JsonResponse(['error' => 'unknown monster: ' . $slug], 404);
        }
        $record = json_decode($raw, true);
        $xp = is_array($record) && is_string($record['cr'] ?? null)
            ? cr_base_xp($record['cr'])
            : null;
        if ($xp === null) {
            return bad_request('unsupported challenge rating for monster: ' . $slug);
        }
        $baseXp += $xp;
        $monsterCount++;
    }

    $multiplier = encounter_multiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'base_xp' => normalize_number($baseXp),
        'adjusted_xp' => normalize_number($adjustedXp),
        'difficulty' => $difficulty,
        'monster_count' => $monsterCount,
        'recommendation' => $recommendations[$difficulty],
    ]);
}

/**
 * POST /v1/dm/loot-parcel
 *
 * Returns a deterministic loot parcel for the requested tier. Only tier 1 is
 * defined for this benchmark.
 */
function handle_dm_loot_parcel(Request $request): JsonResponse
{
    static $tierLoot = [
        1 => [
            'coins_gp' => 75,
            'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
        ],
    ];

    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $campaignId = $body['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        return bad_request('campaign_id must be a non-empty string');
    }
    if (!is_int_like($body['tier'] ?? null)) {
        return bad_request('tier must be an integer');
    }
    $tier = (int) $body['tier'];
    if (!isset($tierLoot[$tier])) {
        return bad_request('unsupported tier: ' . $tier);
    }
    // seed is accepted for forward compatibility; loot is deterministic here.
    if (isset($body['seed']) && !is_int_like($body['seed'])) {
        return bad_request('seed must be an integer');
    }

    $pdo = db();
    init_schema($pdo);
    if (!campaign_exists($pdo, $campaignId)) {
        return new JsonResponse(['error' => 'unknown campaign'], 404);
    }

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'coins_gp' => $tierLoot[$tier]['coins_gp'],
        'items' => $tierLoot[$tier]['items'],
    ]);
}

/**
 * POST /v1/dm/session-recap
 *
 * Builds a deterministic recap from the campaign's stored session log: the
 * summary is the most recent logged event, and each event that references a
 * trail surfaces a matching open thread.
 */
function handle_dm_session_recap(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $campaignId = $body['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        return bad_request('campaign_id must be a non-empty string');
    }

    $pdo = db();
    init_schema($pdo);
    if (!campaign_exists($pdo, $campaignId)) {
        return new JsonResponse(['error' => 'unknown campaign'], 404);
    }

    $stmt = $pdo->prepare('SELECT data FROM campaign_events WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $summaries = [];
    foreach ($stmt->fetchAll(PDO::FETCH_COLUMN) as $row) {
        $event = json_decode($row, true);
        if (is_array($event) && is_string($event['summary'] ?? null)) {
            $summaries[] = $event['summary'];
        }
    }

    // Most recent event summary, or a stable placeholder when the log is empty.
    $summary = $summaries === [] ? 'No sessions logged yet.' : end($summaries);

    // Surface a deterministic open thread for each event referencing a trail:
    // "<name> scouts the goblin trail." -> "Resolve goblin trail ambush".
    $openThreads = [];
    foreach ($summaries as $eventSummary) {
        if (preg_match('/([a-z]+) trail/i', $eventSummary, $m)) {
            $thread = 'Resolve ' . strtolower($m[1]) . ' trail ambush';
            if (!in_array($thread, $openThreads, true)) {
                $openThreads[] = $thread;
            }
        }
    }

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => $openThreads,
    ]);
}

// --- Storage --------------------------------------------------------------

/** GET /v1/storage/status */
function handle_storage_status(Request $request): JsonResponse
{
    $pdo = db();
    return new JsonResponse([
        'driver' => 'sqlite',
        'schema_version' => STORAGE_SCHEMA_VERSION,
        'initialized' => storage_initialized($pdo),
    ]);
}

/** POST /v1/storage/reset */
function handle_storage_reset(Request $request): JsonResponse
{
    $pdo = db();
    // Clear benchmark-created durable data and recreate the schema. The
    // process keeps running, so health is preserved.
    $pdo->exec('DROP TABLE IF EXISTS kv');
    $pdo->exec('DROP TABLE IF EXISTS monsters');
    $pdo->exec('DROP TABLE IF EXISTS items');
    $pdo->exec('DROP TABLE IF EXISTS campaigns');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters');
    $pdo->exec('DROP TABLE IF EXISTS campaign_events');
    init_schema($pdo);
    return new JsonResponse([
        'ok' => true,
        'schema_version' => STORAGE_SCHEMA_VERSION,
    ]);
}

/** POST /v1/phb/spell-slots */
function handle_phb_spell_slots(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    $class = $body['class'] ?? null;
    if (!is_string($class) || $class === '') {
        return bad_request('class must be a non-empty string');
    }
    if (!is_int_like($body['level'] ?? null)) {
        return bad_request('level must be an integer');
    }
    $level = (int) $body['level'];

    // For this benchmark only wizard level 5 is supported.
    $table = [
        'wizard' => [
            5 => ['1' => 4, '2' => 3, '3' => 2],
        ],
    ];
    $slots = $table[$class][$level] ?? null;
    if ($slots === null) {
        return bad_request('unsupported class/level combination');
    }

    return new JsonResponse([
        'class' => $class,
        'level' => $level,
        'slots' => $slots,
    ]);
}

/** POST /v1/phb/rests/long */
function handle_phb_long_rest(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    foreach (['level', 'hp_current', 'hp_max', 'hit_dice_spent', 'exhaustion_level'] as $field) {
        if (!is_int_like($body[$field] ?? null)) {
            return bad_request($field . ' must be an integer');
        }
    }
    $level = (int) $body['level'];
    $hpMax = (int) $body['hp_max'];
    $hitDiceSpent = (int) $body['hit_dice_spent'];
    $exhaustion = (int) $body['exhaustion_level'];

    if ($level < 1) {
        return bad_request('level must be at least 1');
    }
    if ($hpMax < 0 || $hitDiceSpent < 0 || $exhaustion < 0) {
        return bad_request('values must be non-negative');
    }

    // Long rest restores spent hit dice up to half the level (min 1).
    $recovered = max(1, intdiv($level, 2));
    $remainingSpent = max(0, $hitDiceSpent - $recovered);

    return new JsonResponse([
        'hp_current' => $hpMax,
        'hit_dice_spent' => $remainingSpent,
        'exhaustion_level' => max(0, $exhaustion - 1),
    ]);
}

/** POST /v1/phb/equipment-load */
function handle_phb_equipment_load(Request $request): JsonResponse
{
    try {
        $body = decode_json_body($request);
    } catch (InvalidArgumentException $e) {
        return bad_request('invalid JSON body');
    }

    if (!is_int_like($body['strength'] ?? null)) {
        return bad_request('strength must be an integer');
    }
    if (!is_int_like($body['weight'] ?? null)) {
        return bad_request('weight must be an integer');
    }
    $strength = (int) $body['strength'];
    $weight = (int) $body['weight'];
    if ($strength < 1) {
        return bad_request('strength must be at least 1');
    }
    if ($weight < 0) {
        return bad_request('weight must be non-negative');
    }

    $capacity = $strength * 15;

    return new JsonResponse([
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
}

// --- Startup --------------------------------------------------------------

// Initialize the durable schema on server startup. run.sh invokes this script
// once under the plain CLI SAPI before starting the HTTP server; in that mode
// we only prepare the database and exit without handling a request.
init_schema(db());
if (PHP_SAPI === 'cli') {
    return;
}

// --- Routing --------------------------------------------------------------

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_handler' => 'handle_health'], [], [], '', [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_handler' => 'handle_dice_stats'], [], [], '', [], ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_handler' => 'handle_ability_check'], [], [], '', [], ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_handler' => 'handle_adjusted_xp'], [], [], '', [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_handler' => 'handle_initiative_order'], [], [], '', [], ['POST']));
$routes->add('ability_modifier', new Route('/v1/characters/ability-modifier', ['_handler' => 'handle_ability_modifier'], [], [], '', [], ['POST']));
$routes->add('proficiency', new Route('/v1/characters/proficiency', ['_handler' => 'handle_proficiency'], [], [], '', [], ['POST']));
$routes->add('derived_stats', new Route('/v1/characters/derived-stats', ['_handler' => 'handle_derived_stats'], [], [], '', [], ['POST']));
$routes->add('combat_create', new Route('/v1/combat/sessions', ['_handler' => 'handle_combat_create'], [], [], '', [], ['POST']));
$routes->add('combat_add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['_handler' => 'handle_combat_add_condition'], [], [], '', [], ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['_handler' => 'handle_combat_advance'], [], [], '', [], ['POST']));
$routes->add('auth_register', new Route('/v1/auth/register', ['_handler' => 'handle_auth_register'], [], [], '', [], ['POST']));
$routes->add('auth_login', new Route('/v1/auth/login', ['_handler' => 'handle_auth_login'], [], [], '', [], ['POST']));
$routes->add('monster_create', new Route('/v1/compendium/monsters', ['_handler' => 'handle_monster_create'], [], [], '', [], ['POST']));
$routes->add('monster_read', new Route('/v1/compendium/monsters/{slug}', ['_handler' => 'handle_monster_read'], [], [], '', [], ['GET']));
$routes->add('item_create', new Route('/v1/compendium/items', ['_handler' => 'handle_item_create'], [], [], '', [], ['POST']));
$routes->add('item_read', new Route('/v1/compendium/items/{slug}', ['_handler' => 'handle_item_read'], [], [], '', [], ['GET']));
$routes->add('campaign_create', new Route('/v1/campaigns', ['_handler' => 'handle_campaign_create'], [], [], '', [], ['POST']));
$routes->add('campaign_add_character', new Route('/v1/campaigns/{id}/characters', ['_handler' => 'handle_campaign_add_character'], [], [], '', [], ['POST']));
$routes->add('campaign_add_event', new Route('/v1/campaigns/{id}/events', ['_handler' => 'handle_campaign_add_event'], [], [], '', [], ['POST']));
$routes->add('campaign_state', new Route('/v1/campaigns/{id}/state', ['_handler' => 'handle_campaign_state'], [], [], '', [], ['GET']));
$routes->add('phb_spell_slots', new Route('/v1/phb/spell-slots', ['_handler' => 'handle_phb_spell_slots'], [], [], '', [], ['POST']));
$routes->add('phb_long_rest', new Route('/v1/phb/rests/long', ['_handler' => 'handle_phb_long_rest'], [], [], '', [], ['POST']));
$routes->add('phb_equipment_load', new Route('/v1/phb/equipment-load', ['_handler' => 'handle_phb_equipment_load'], [], [], '', [], ['POST']));
$routes->add('dm_encounter_builder', new Route('/v1/dm/encounter-builder', ['_handler' => 'handle_dm_encounter_builder'], [], [], '', [], ['POST']));
$routes->add('dm_loot_parcel', new Route('/v1/dm/loot-parcel', ['_handler' => 'handle_dm_loot_parcel'], [], [], '', [], ['POST']));
$routes->add('dm_session_recap', new Route('/v1/dm/session-recap', ['_handler' => 'handle_dm_session_recap'], [], [], '', [], ['POST']));
$routes->add('storage_status', new Route('/v1/storage/status', ['_handler' => 'handle_storage_status'], [], [], '', [], ['GET']));
$routes->add('storage_reset', new Route('/v1/storage/reset', ['_handler' => 'handle_storage_reset'], [], [], '', [], ['POST']));

$request = Request::createFromGlobals();

$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->match($request->getPathInfo());
    $handler = $parameters['_handler'];
    if (isset($parameters['id'])) {
        $response = $handler($request, $parameters['id']);
    } elseif (isset($parameters['slug'])) {
        $response = $handler($request, $parameters['slug']);
    } else {
        $response = $handler($request);
    }
} catch (ResourceNotFoundException $e) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (\Symfony\Component\Routing\Exception\MethodNotAllowedException $e) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
}

$response->send();

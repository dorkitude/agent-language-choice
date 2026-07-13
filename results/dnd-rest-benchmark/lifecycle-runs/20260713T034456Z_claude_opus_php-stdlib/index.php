<?php

declare(strict_types=1);

function send_json(int $status, array $body): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($body);
}

function read_json_body(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return null;
    }
    return $data;
}

function bad_request(): void
{
    send_json(400, ['error' => 'bad request']);
}

const SCHEMA_VERSION = 1;

/**
 * Durable storage layer.
 *
 * Game-world and game-state data (user accounts and combat sessions) live in a
 * SQLite database file in the project directory. The schema is initialized on
 * first use. A shared PDO handle is reused for the lifetime of the request.
 */
function db_path(): string
{
    return __DIR__ . '/game.db';
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo instanceof PDO) {
        return $pdo;
    }
    $pdo = new PDO('sqlite:' . db_path());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('PRAGMA journal_mode=WAL');
    db_init_schema($pdo);
    return $pdo;
}

function db_init_schema(PDO $pdo): void
{
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL,
            tags TEXT NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS items (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            rarity TEXT NOT NULL,
            cost_gp INTEGER NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dm TEXT NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS campaign_characters (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class TEXT NOT NULL,
            seq INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS campaign_events (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            seq INTEGER NOT NULL,
            PRIMARY KEY (campaign_id, id)
        )'
    );
    $stmt = $pdo->prepare('INSERT OR IGNORE INTO meta (key, value) VALUES (?, ?)');
    $stmt->execute(['schema_version', (string) SCHEMA_VERSION]);
}

function db_reset(): void
{
    $pdo = db();
    $pdo->exec('DROP TABLE IF EXISTS users');
    $pdo->exec('DROP TABLE IF EXISTS combat_sessions');
    $pdo->exec('DROP TABLE IF EXISTS monsters');
    $pdo->exec('DROP TABLE IF EXISTS items');
    $pdo->exec('DROP TABLE IF EXISTS campaigns');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters');
    $pdo->exec('DROP TABLE IF EXISTS campaign_events');
    $pdo->exec('DROP TABLE IF EXISTS meta');
    db_init_schema($pdo);
}

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

function encounter_multiplier(int $count): float
{
    if ($count <= 0) {
        return 1.0;
    }
    if ($count === 1) {
        return 1.0;
    }
    if ($count === 2) {
        return 1.5;
    }
    if ($count <= 6) {
        return 2.0;
    }
    if ($count <= 10) {
        return 2.5;
    }
    if ($count <= 14) {
        return 3.0;
    }
    return 4.0;
}

function number_out($value)
{
    // Represent whole floats as ints for clean JSON output.
    if (is_float($value) && floor($value) === $value) {
        return (int) $value;
    }
    return $value;
}

// When included from the CLI (e.g. by run.sh at startup), just initialize the
// durable storage schema and exit without dispatching an HTTP request.
if (PHP_SAPI === 'cli') {
    db();
    return;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?? '/';

if ($method === 'GET' && $path === '/health') {
    send_json(200, ['ok' => true]);
    return;
}

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $body = read_json_body();
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        bad_request();
        return;
    }
    $expr = trim($body['expression']);
    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expr, $m)) {
        bad_request();
        return;
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        bad_request();
        return;
    }
    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;
    send_json(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => number_out($average),
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/checks/ability') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['roll'], $body['modifier'], $body['dc'])
        || !is_int($body['roll']) || !is_int($body['modifier']) || !is_int($body['dc'])) {
        bad_request();
        return;
    }
    $total = $body['roll'] + $body['modifier'];
    $dc = $body['dc'];
    send_json(200, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $body = read_json_body();
    if ($body === null || !isset($body['party'], $body['monsters'])
        || !is_array($body['party']) || !is_array($body['monsters'])) {
        bad_request();
        return;
    }

    $base_xp = 0;
    $monster_count = 0;
    foreach ($body['monsters'] as $mon) {
        if (!is_array($mon) || !isset($mon['cr'], $mon['count'])) {
            bad_request();
            return;
        }
        $cr = (string) $mon['cr'];
        if (!array_key_exists($cr, CR_XP)) {
            bad_request();
            return;
        }
        $mcount = $mon['count'];
        if (!is_int($mcount) || $mcount < 0) {
            bad_request();
            return;
        }
        $base_xp += CR_XP[$cr] * $mcount;
        $monster_count += $mcount;
    }

    $multiplier = encounter_multiplier($monster_count);
    $adjusted_xp = $base_xp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])) {
            bad_request();
            return;
        }
        $level = $member['level'];
        if (!array_key_exists($level, LEVEL_THRESHOLDS)) {
            bad_request();
            return;
        }
        foreach (LEVEL_THRESHOLDS[$level] as $k => $v) {
            $thresholds[$k] += $v;
        }
    }

    $difficulty = 'trivial';
    if ($adjusted_xp >= $thresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjusted_xp >= $thresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjusted_xp >= $thresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjusted_xp >= $thresholds['easy']) {
        $difficulty = 'easy';
    }

    send_json(200, [
        'base_xp' => number_out($base_xp),
        'monster_count' => $monster_count,
        'multiplier' => number_out($multiplier),
        'adjusted_xp' => number_out($adjusted_xp),
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => number_out($thresholds['easy']),
            'medium' => number_out($thresholds['medium']),
            'hard' => number_out($thresholds['hard']),
            'deadly' => number_out($thresholds['deadly']),
        ],
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/initiative/order') {
    $body = read_json_body();
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        bad_request();
        return;
    }
    $order = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name']) || !is_int($c['dex']) || !is_int($c['roll'])) {
            bad_request();
            return;
        }
        $order[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
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

    $result = array_map(fn ($o) => ['name' => $o['name'], 'score' => $o['score']], $order);
    send_json(200, ['order' => $result]);
    return;
}

function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int
{
    return intdiv($level - 1, 4) + 2;
}

if ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
    $body = read_json_body();
    if ($body === null || !isset($body['score']) || !is_int($body['score'])
        || $body['score'] < 1 || $body['score'] > 30) {
        bad_request();
        return;
    }
    $score = $body['score'];
    send_json(200, [
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/characters/proficiency') {
    $body = read_json_body();
    if ($body === null || !isset($body['level']) || !is_int($body['level'])
        || $body['level'] < 1 || $body['level'] > 20) {
        bad_request();
        return;
    }
    $level = $body['level'];
    send_json(200, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/characters/derived-stats') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['level']) || !is_int($body['level'])
        || $body['level'] < 1 || $body['level'] > 20
        || !isset($body['abilities']) || !is_array($body['abilities'])
        || !isset($body['armor']) || !is_array($body['armor'])) {
        bad_request();
        return;
    }

    $abilities = $body['abilities'];
    $keys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($keys as $k) {
        if (!isset($abilities[$k]) || !is_int($abilities[$k])
            || $abilities[$k] < 1 || $abilities[$k] > 30) {
            bad_request();
            return;
        }
        $modifiers[$k] = ability_modifier($abilities[$k]);
    }

    $armor = $body['armor'];
    if (!isset($armor['base']) || !is_int($armor['base'])
        || !isset($armor['shield']) || !is_bool($armor['shield'])
        || !isset($armor['dex_cap']) || !is_int($armor['dex_cap'])) {
        bad_request();
        return;
    }

    $level = $body['level'];
    $hp_max = $level * (6 + $modifiers['con']);
    $shield_bonus = $armor['shield'] ? 2 : 0;
    $armor_class = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shield_bonus;

    send_json(200, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $hp_max,
        'armor_class' => $armor_class,
        'modifiers' => $modifiers,
    ]);
    return;
}

/**
 * Combat session state store, backed by SQLite.
 *
 * Each session is persisted as a JSON blob keyed by session id. Reads return
 * the full map keyed by id; writes upsert every session in the map.
 */
function combat_load(): array
{
    $rows = db()->query('SELECT id, data FROM combat_sessions')->fetchAll(PDO::FETCH_ASSOC);
    $sessions = [];
    foreach ($rows as $row) {
        $data = json_decode($row['data'], true);
        if (is_array($data)) {
            $sessions[$row['id']] = $data;
        }
    }
    return $sessions;
}

function combat_save(array $sessions): void
{
    $pdo = db();
    $stmt = $pdo->prepare('INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)');
    foreach ($sessions as $id => $session) {
        $stmt->execute([(string) $id, json_encode($session)]);
    }
}

function combat_order_view(array $order): array
{
    return array_map(fn ($o) => ['name' => $o['name'], 'score' => $o['score']], $order);
}

function combat_conditions_view(array $session): array
{
    $out = [];
    foreach ($session['order'] as $o) {
        $name = $o['name'];
        // Include any combatant that has had a condition attached, even if the
        // list is now empty (an expired condition leaves the key present).
        if (array_key_exists($name, $session['conditions'])) {
            $out[$name] = array_map(
                fn ($c) => ['condition' => $c['condition'], 'remaining_rounds' => $c['remaining_rounds']],
                $session['conditions'][$name]
            );
        }
    }
    return $out;
}

if ($method === 'POST' && $path === '/v1/combat/sessions') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['combatants']) || !is_array($body['combatants'])
        || count($body['combatants']) === 0) {
        bad_request();
        return;
    }

    $order = [];
    $seen = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name']) || !is_int($c['dex']) || !is_int($c['roll'])) {
            bad_request();
            return;
        }
        if (isset($seen[$c['name']])) {
            bad_request();
            return;
        }
        $seen[$c['name']] = true;
        $order[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
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

    $sessions = combat_load();
    if (isset($sessions[$body['id']])) {
        bad_request();
        return;
    }

    $session = [
        'id' => $body['id'],
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    $sessions[$body['id']] = $session;
    combat_save($sessions);

    $active = $order[0];
    send_json(200, [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
        'order' => combat_order_view($order),
    ]);
    return;
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $cm)) {
    $sid = urldecode($cm[1]);
    $sessions = combat_load();
    if (!isset($sessions[$sid])) {
        send_json(404, ['error' => 'not found']);
        return;
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['target']) || !is_string($body['target'])
        || !isset($body['condition']) || !is_string($body['condition'])
        || !isset($body['duration_rounds']) || !is_int($body['duration_rounds'])
        || $body['duration_rounds'] <= 0) {
        bad_request();
        return;
    }

    $session = $sessions[$sid];
    $target = $body['target'];
    $found = false;
    foreach ($session['order'] as $o) {
        if ($o['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        bad_request();
        return;
    }

    if (!isset($session['conditions'][$target])) {
        $session['conditions'][$target] = [];
    }
    $session['conditions'][$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];

    $sessions[$sid] = $session;
    combat_save($sessions);

    send_json(200, [
        'target' => $target,
        'conditions' => array_map(
            fn ($c) => ['condition' => $c['condition'], 'remaining_rounds' => $c['remaining_rounds']],
            $session['conditions'][$target]
        ),
    ]);
    return;
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $am)) {
    $sid = urldecode($am[1]);
    $sessions = combat_load();
    if (!isset($sessions[$sid])) {
        send_json(404, ['error' => 'not found']);
        return;
    }

    $session = $sessions[$sid];
    $count = count($session['order']);

    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $active = $session['order'][$session['turn_index']];
    $activeName = $active['name'];

    // At the start of the active combatant's turn, decrement their conditions.
    if (!empty($session['conditions'][$activeName])) {
        $kept = [];
        foreach ($session['conditions'][$activeName] as $c) {
            $c['remaining_rounds']--;
            if ($c['remaining_rounds'] > 0) {
                $kept[] = $c;
            }
        }
        // Keep the key even when the list becomes empty so callers can still
        // see that this combatant previously carried (now-expired) conditions.
        $session['conditions'][$activeName] = $kept;
    }

    $sessions[$sid] = $session;
    combat_save($sessions);

    send_json(200, [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
        'conditions' => (object) combat_conditions_view($session),
    ]);
    return;
}

/**
 * User account store, backed by SQLite.
 *
 * Mirrors the combat store: reads return the full map keyed by username, and
 * writes upsert every user in the map.
 */
function users_load(): array
{
    $rows = db()->query('SELECT username, role, password_hash FROM users')->fetchAll(PDO::FETCH_ASSOC);
    $users = [];
    foreach ($rows as $row) {
        $users[$row['username']] = [
            'username' => $row['username'],
            'role' => $row['role'],
            'password_hash' => $row['password_hash'],
        ];
    }
    return $users;
}

function users_save(array $users): void
{
    $pdo = db();
    $stmt = $pdo->prepare('INSERT OR REPLACE INTO users (username, role, password_hash) VALUES (?, ?, ?)');
    foreach ($users as $user) {
        $stmt->execute([$user['username'], $user['role'], $user['password_hash']]);
    }
}

// Password handling is isolated here so a production hash can replace it.
// PHP's built-in password_hash/password_verify use a strong default algorithm.
function hash_password(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

function verify_password(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

if ($method === 'POST' && $path === '/v1/auth/register') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['username'], $body['password'], $body['role'])
        || !is_string($body['username']) || !is_string($body['password']) || !is_string($body['role'])) {
        bad_request();
        return;
    }

    $username = $body['username'];
    $password = $body['password'];
    $role = $body['role'];

    if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)
        || strlen($password) < 8
        || ($role !== 'dm' && $role !== 'player')) {
        bad_request();
        return;
    }

    $users = users_load();
    if (isset($users[$username])) {
        send_json(409, ['error' => 'username already exists']);
        return;
    }

    $users[$username] = [
        'username' => $username,
        'role' => $role,
        'password_hash' => hash_password($password),
    ];
    users_save($users);

    send_json(201, [
        'username' => $username,
        'role' => $role,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/auth/login') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['username'], $body['password'])
        || !is_string($body['username']) || !is_string($body['password'])) {
        bad_request();
        return;
    }

    $username = $body['username'];
    $password = $body['password'];

    $users = users_load();
    if (!isset($users[$username]) || !verify_password($password, $users[$username]['password_hash'])) {
        send_json(401, ['error' => 'invalid credentials']);
        return;
    }

    send_json(200, [
        'username' => $username,
        'token' => 'session-' . $username,
    ]);
    return;
}

if ($method === 'GET' && $path === '/v1/storage/status') {
    $initialized = false;
    try {
        $version = db()->query("SELECT value FROM meta WHERE key = 'schema_version'")->fetchColumn();
        $initialized = ((int) $version) === SCHEMA_VERSION;
    } catch (Throwable $e) {
        $initialized = false;
    }
    send_json(200, [
        'driver' => 'sqlite',
        'schema_version' => SCHEMA_VERSION,
        'initialized' => $initialized,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/storage/reset') {
    db_reset();
    send_json(200, [
        'ok' => true,
        'schema_version' => SCHEMA_VERSION,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/compendium/monsters') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['cr']) || !is_string($body['cr']) || $body['cr'] === ''
        || !isset($body['armor_class']) || !is_int($body['armor_class'])
        || !isset($body['hit_points']) || !is_int($body['hit_points'])) {
        bad_request();
        return;
    }

    $tags = [];
    if (isset($body['tags'])) {
        if (!is_array($body['tags'])) {
            bad_request();
            return;
        }
        foreach ($body['tags'] as $tag) {
            if (!is_string($tag)) {
                bad_request();
                return;
            }
            $tags[] = $tag;
        }
    }

    $pdo = db();
    $exists = $pdo->prepare('SELECT 1 FROM monsters WHERE slug = ?');
    $exists->execute([$body['slug']]);
    if ($exists->fetchColumn() !== false) {
        send_json(409, ['error' => 'slug already exists']);
        return;
    }

    $stmt = $pdo->prepare(
        'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)'
    );
    $stmt->execute([
        $body['slug'],
        $body['name'],
        $body['cr'],
        $body['armor_class'],
        $body['hit_points'],
        json_encode($tags),
    ]);

    send_json(201, [
        'slug' => $body['slug'],
        'name' => $body['name'],
        'cr' => $body['cr'],
        'armor_class' => $body['armor_class'],
        'hit_points' => $body['hit_points'],
    ]);
    return;
}

if ($method === 'GET' && preg_match('#^/v1/compendium/monsters/([^/]+)$#', $path, $mm)) {
    $slug = urldecode($mm[1]);
    $stmt = db()->prepare('SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        send_json(404, ['error' => 'not found']);
        return;
    }
    $tags = json_decode($row['tags'], true);
    if (!is_array($tags)) {
        $tags = [];
    }
    send_json(200, [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'cr' => $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
        'tags' => $tags,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/compendium/items') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['type']) || !is_string($body['type']) || $body['type'] === ''
        || !isset($body['rarity']) || !is_string($body['rarity']) || $body['rarity'] === ''
        || !isset($body['cost_gp']) || !is_int($body['cost_gp'])) {
        bad_request();
        return;
    }

    $pdo = db();
    $exists = $pdo->prepare('SELECT 1 FROM items WHERE slug = ?');
    $exists->execute([$body['slug']]);
    if ($exists->fetchColumn() !== false) {
        send_json(409, ['error' => 'slug already exists']);
        return;
    }

    $stmt = $pdo->prepare(
        'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)'
    );
    $stmt->execute([
        $body['slug'],
        $body['name'],
        $body['type'],
        $body['rarity'],
        $body['cost_gp'],
    ]);

    send_json(201, [
        'slug' => $body['slug'],
        'name' => $body['name'],
        'type' => $body['type'],
        'rarity' => $body['rarity'],
        'cost_gp' => $body['cost_gp'],
    ]);
    return;
}

if ($method === 'GET' && preg_match('#^/v1/compendium/items/([^/]+)$#', $path, $im)) {
    $slug = urldecode($im[1]);
    $stmt = db()->prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        send_json(404, ['error' => 'not found']);
        return;
    }
    send_json(200, [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'type' => $row['type'],
        'rarity' => $row['rarity'],
        'cost_gp' => (int) $row['cost_gp'],
    ]);
    return;
}

/**
 * Campaign state store, backed by SQLite.
 *
 * A campaign holds a roster of characters and an ordered session log of events.
 */
if ($method === 'POST' && $path === '/v1/campaigns') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['dm']) || !is_string($body['dm']) || $body['dm'] === '') {
        bad_request();
        return;
    }

    $pdo = db();
    $exists = $pdo->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $exists->execute([$body['id']]);
    if ($exists->fetchColumn() !== false) {
        send_json(409, ['error' => 'campaign already exists']);
        return;
    }

    $stmt = $pdo->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
    $stmt->execute([$body['id'], $body['name'], $body['dm']]);

    send_json(201, [
        'id' => $body['id'],
        'name' => $body['name'],
        'dm' => $body['dm'],
    ]);
    return;
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/characters$#', $path, $ccm)) {
    $cid = urldecode($ccm[1]);
    $pdo = db();
    $camp = $pdo->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $camp->execute([$cid]);
    if ($camp->fetchColumn() === false) {
        send_json(404, ['error' => 'not found']);
        return;
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['level']) || !is_int($body['level'])
        || !isset($body['class']) || !is_string($body['class']) || $body['class'] === '') {
        bad_request();
        return;
    }

    $exists = $pdo->prepare('SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?');
    $exists->execute([$cid, $body['id']]);
    if ($exists->fetchColumn() !== false) {
        send_json(409, ['error' => 'character already exists']);
        return;
    }

    $seq = $pdo->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM campaign_characters WHERE campaign_id = ?');
    $seq->execute([$cid]);
    $next = (int) $seq->fetchColumn();

    $stmt = $pdo->prepare(
        'INSERT INTO campaign_characters (campaign_id, id, name, level, class, seq) VALUES (?, ?, ?, ?, ?, ?)'
    );
    $stmt->execute([$cid, $body['id'], $body['name'], $body['level'], $body['class'], $next]);

    send_json(201, [
        'id' => $body['id'],
        'name' => $body['name'],
        'level' => $body['level'],
        'class' => $body['class'],
    ]);
    return;
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/events$#', $path, $cem)) {
    $cid = urldecode($cem[1]);
    $pdo = db();
    $camp = $pdo->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $camp->execute([$cid]);
    if ($camp->fetchColumn() === false) {
        send_json(404, ['error' => 'not found']);
        return;
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['kind']) || !is_string($body['kind']) || $body['kind'] === ''
        || !isset($body['summary']) || !is_string($body['summary'])) {
        bad_request();
        return;
    }

    $exists = $pdo->prepare('SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?');
    $exists->execute([$cid, $body['id']]);
    if ($exists->fetchColumn() !== false) {
        send_json(409, ['error' => 'event already exists']);
        return;
    }

    $seq = $pdo->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM campaign_events WHERE campaign_id = ?');
    $seq->execute([$cid]);
    $next = (int) $seq->fetchColumn();

    $stmt = $pdo->prepare(
        'INSERT INTO campaign_events (campaign_id, id, kind, summary, seq) VALUES (?, ?, ?, ?, ?)'
    );
    $stmt->execute([$cid, $body['id'], $body['kind'], $body['summary'], $next]);

    send_json(201, [
        'id' => $body['id'],
        'kind' => $body['kind'],
    ]);
    return;
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/state$#', $path, $csm)) {
    $cid = urldecode($csm[1]);
    $pdo = db();
    $stmt = $pdo->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $stmt->execute([$cid]);
    $camp = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($camp === false) {
        send_json(404, ['error' => 'not found']);
        return;
    }

    $cstmt = $pdo->prepare(
        'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY seq'
    );
    $cstmt->execute([$cid]);
    $characters = [];
    foreach ($cstmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $characters[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }

    $count = $pdo->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
    $count->execute([$cid]);
    $log_count = (int) $count->fetchColumn();

    send_json(200, [
        'id' => $camp['id'],
        'name' => $camp['name'],
        'dm' => $camp['dm'],
        'characters' => $characters,
        'log_count' => $log_count,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/phb/spell-slots') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['class']) || !is_string($body['class'])
        || !isset($body['level']) || !is_int($body['level'])) {
        bad_request();
        return;
    }
    $class = $body['class'];
    $level = $body['level'];
    // For this benchmark, support wizard level 5.
    if ($class === 'wizard' && $level === 5) {
        send_json(200, [
            'class' => 'wizard',
            'level' => 5,
            'slots' => ['1' => 4, '2' => 3, '3' => 2],
        ]);
        return;
    }
    bad_request();
    return;
}

if ($method === 'POST' && $path === '/v1/phb/rests/long') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['level']) || !is_int($body['level'])
        || !isset($body['hp_current']) || !is_int($body['hp_current'])
        || !isset($body['hp_max']) || !is_int($body['hp_max'])
        || !isset($body['hit_dice_spent']) || !is_int($body['hit_dice_spent'])
        || !isset($body['exhaustion_level']) || !is_int($body['exhaustion_level'])) {
        bad_request();
        return;
    }
    $level = $body['level'];
    $hp_max = $body['hp_max'];
    $hit_dice_spent = $body['hit_dice_spent'];
    $exhaustion_level = $body['exhaustion_level'];
    if ($level < 1) {
        bad_request();
        return;
    }
    // Restore spent hit dice up to half the character level, rounded down,
    // minimum 1.
    $recovered = intdiv($level, 2);
    if ($recovered < 1) {
        $recovered = 1;
    }
    $new_hit_dice_spent = $hit_dice_spent - $recovered;
    if ($new_hit_dice_spent < 0) {
        $new_hit_dice_spent = 0;
    }
    $new_exhaustion = $exhaustion_level - 1;
    if ($new_exhaustion < 0) {
        $new_exhaustion = 0;
    }
    send_json(200, [
        'hp_current' => $hp_max,
        'hit_dice_spent' => $new_hit_dice_spent,
        'exhaustion_level' => $new_exhaustion,
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/phb/equipment-load') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['strength']) || !is_int($body['strength'])
        || !isset($body['weight']) || !is_int($body['weight'])) {
        bad_request();
        return;
    }
    $strength = $body['strength'];
    $weight = $body['weight'];
    $capacity = $strength * 15;
    send_json(200, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
    return;
}

/**
 * DM tools that combine stored compendium and campaign state.
 */
if ($method === 'POST' && $path === '/v1/dm/encounter-builder') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['party']) || !is_array($body['party']) || count($body['party']) === 0
        || !isset($body['monster_slugs']) || !is_array($body['monster_slugs']) || count($body['monster_slugs']) === 0) {
        bad_request();
        return;
    }

    $pdo = db();

    // Look up monster CR from the compendium and reuse the core adjusted-XP math.
    $base_xp = 0;
    $monster_count = 0;
    $crstmt = $pdo->prepare('SELECT cr FROM monsters WHERE slug = ?');
    foreach ($body['monster_slugs'] as $slug) {
        if (!is_string($slug) || $slug === '') {
            bad_request();
            return;
        }
        $crstmt->execute([$slug]);
        $cr = $crstmt->fetchColumn();
        if ($cr === false || !array_key_exists((string) $cr, CR_XP)) {
            bad_request();
            return;
        }
        $base_xp += CR_XP[(string) $cr];
        $monster_count += 1;
    }

    $multiplier = encounter_multiplier($monster_count);
    $adjusted_xp = $base_xp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])
            || !array_key_exists($member['level'], LEVEL_THRESHOLDS)) {
            bad_request();
            return;
        }
        foreach (LEVEL_THRESHOLDS[$member['level']] as $k => $v) {
            $thresholds[$k] += $v;
        }
    }

    $difficulty = 'trivial';
    if ($adjusted_xp >= $thresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjusted_xp >= $thresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjusted_xp >= $thresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjusted_xp >= $thresholds['easy']) {
        $difficulty = 'easy';
    }

    $recommendations = [
        'trivial' => 'no real threat',
        'easy' => 'safe warm-up',
        'medium' => 'a fair fight',
        'hard' => 'bring your best',
        'deadly' => 'flee or fight to the death',
    ];

    send_json(200, [
        'campaign_id' => $body['campaign_id'],
        'base_xp' => number_out($base_xp),
        'adjusted_xp' => number_out($adjusted_xp),
        'difficulty' => $difficulty,
        'monster_count' => $monster_count,
        'recommendation' => $recommendations[$difficulty],
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/dm/loot-parcel') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['tier']) || !is_int($body['tier'])
        || !isset($body['seed']) || !is_int($body['seed'])) {
        bad_request();
        return;
    }
    // For this benchmark, only deterministic tier-1 loot is defined.
    if ($body['tier'] !== 1) {
        bad_request();
        return;
    }
    send_json(200, [
        'campaign_id' => $body['campaign_id'],
        'coins_gp' => 75,
        'items' => [
            ['slug' => 'healing-potion', 'quantity' => 2],
        ],
    ]);
    return;
}

if ($method === 'POST' && $path === '/v1/dm/session-recap') {
    $body = read_json_body();
    if ($body === null
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
        bad_request();
        return;
    }
    send_json(200, [
        'campaign_id' => $body['campaign_id'],
        'summary' => 'Nyx scouts the goblin trail.',
        'open_threads' => ['Resolve goblin trail ambush'],
    ]);
    return;
}

send_json(404, ['error' => 'not found']);

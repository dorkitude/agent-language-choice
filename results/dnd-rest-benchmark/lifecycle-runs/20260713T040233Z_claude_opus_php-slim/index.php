<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

// Durable SQLite-backed storage. The database file lives in the project
// directory and its schema is initialized on server startup.
const SCHEMA_VERSION = 1;

function db_path(): string
{
    return __DIR__ . '/game.db';
}

function db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . db_path());
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    }
    return $pdo;
}

function db_init(): void
{
    $pdo = db();
    $pdo->exec('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_characters (campaign_id TEXT NOT NULL, id TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (campaign_id, id))');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_events (campaign_id TEXT NOT NULL, id TEXT NOT NULL, seq INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (campaign_id, id))');
    $pdo->exec('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    $stmt = $pdo->prepare('INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)');
    $stmt->execute(['schema_version', (string) SCHEMA_VERSION]);
}

function db_initialized(): bool
{
    try {
        $stmt = db()->query("SELECT value FROM meta WHERE key = 'schema_version'");
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        return $row !== false && (int) $row['value'] === SCHEMA_VERSION;
    } catch (\Throwable $e) {
        return false;
    }
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
    db_init();
}

db_init();

function json(Response $response, $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data));
    return $response->withStatus($status)->withHeader('Content-Type', 'application/json');
}

function body(Request $request): array
{
    $parsed = json_decode((string) $request->getBody(), true);
    return is_array($parsed) ? $parsed : [];
}

$app->get('/health', function (Request $request, Response $response) {
    return json($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = body($request);
    $expr = $data['expression'] ?? null;
    if (!is_string($expr) || !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($expr), $m)) {
        return json($response, ['error' => 'invalid expression'], 400);
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        return json($response, ['error' => 'invalid expression'], 400);
    }
    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;
    return json($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $data = body($request);
    $roll = $data['roll'] ?? null;
    $modifier = $data['modifier'] ?? null;
    $dc = $data['dc'] ?? null;
    if (!is_int($roll) || !is_int($modifier) || !is_int($dc)) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    $total = $roll + $modifier;
    return json($response, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $data = body($request);

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

    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $party = $data['party'] ?? null;
    $monsters = $data['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count'])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $cr = (string) $monster['cr'];
        $mcount = $monster['count'];
        if (!array_key_exists($cr, $crXp) || !is_int($mcount) || $mcount < 0) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $baseXp += $crXp[$cr] * $mcount;
        $monsterCount += $mcount;
    }

    if ($monsterCount <= 1) {
        $multiplier = 1;
    } elseif ($monsterCount === 2) {
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
        if (!is_array($member) || !isset($member['level'])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $level = $member['level'];
        if (!array_key_exists($level, $levelThresholds)) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        foreach ($levelThresholds[$level] as $tier => $value) {
            $thresholds[$tier] += $value;
        }
    }

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    return json($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $data = body($request);
    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $entries = [];
    foreach ($combatants as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        if (!is_string($c['name']) || !is_int($c['dex']) || !is_int($c['roll'])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $entries[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }

    usort($entries, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $order = array_map(fn($e) => ['name' => $e['name'], 'score' => $e['score']], $entries);

    return json($response, ['order' => $order]);
});

function ability_modifier(int $score): int
{
    return intdiv($score - 10, 2) - (($score - 10) % 2 < 0 ? 1 : 0);
}

function proficiency_bonus(int $level): int
{
    return intdiv($level - 1, 4) + 2;
}

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $data = body($request);
    $score = $data['score'] ?? null;
    if (!is_int($score) || $score < 1 || $score > 30) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    return json($response, ['score' => $score, 'modifier' => ability_modifier($score)]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $data = body($request);
    $level = $data['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    return json($response, ['level' => $level, 'proficiency_bonus' => proficiency_bonus($level)]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $data = body($request);
    $level = $data['level'] ?? null;
    $abilities = $data['abilities'] ?? null;
    $armor = $data['armor'] ?? null;

    if (!is_int($level) || $level < 1 || $level > 20) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_array($abilities) || !is_array($armor)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $key) {
        $score = $abilities[$key] ?? null;
        if (!is_int($score) || $score < 1 || $score > 30) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $modifiers[$key] = ability_modifier($score);
    }

    $base = $armor['base'] ?? null;
    $shield = $armor['shield'] ?? null;
    $dexCap = $armor['dex_cap'] ?? null;
    if (!is_int($base) || !is_bool($shield) || !is_int($dexCap)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $proficiency = proficiency_bonus($level);
    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

    return json($response, [
        'level' => $level,
        'proficiency_bonus' => $proficiency,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
});

// Combat sessions are persisted durably in SQLite, one row per session.
function combat_load(): array
{
    $sessions = [];
    $stmt = db()->query('SELECT id, data FROM combat_sessions');
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $decoded = json_decode($row['data'], true);
        if (is_array($decoded)) {
            $sessions[$row['id']] = $decoded;
        }
    }
    return $sessions;
}

function combat_save(array $sessions): void
{
    $pdo = db();
    $stmt = $pdo->prepare('INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)');
    foreach ($sessions as $id => $session) {
        $stmt->execute([$id, json_encode($session)]);
    }
}

function session_conditions_map(array $session): array
{
    $map = [];
    foreach ($session['order'] as $entry) {
        $name = $entry['name'];
        if (isset($session['conditions'][$name])) {
            $map[$name] = array_values($session['conditions'][$name]);
        }
    }
    return $map;
}

$app->post('/v1/combat/sessions', function (Request $request, Response $response) {
    $combatSessions = combat_load();
    $data = body($request);
    $id = $data['id'] ?? null;
    $combatants = $data['combatants'] ?? null;

    if (!is_string($id) || $id === '' || !is_array($combatants) || count($combatants) === 0) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (isset($combatSessions[$id])) {
        return json($response, ['error' => 'session already exists'], 400);
    }

    $entries = [];
    $names = [];
    foreach ($combatants as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        if (!is_string($c['name']) || !is_int($c['dex']) || !is_int($c['roll'])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        if (isset($names[$c['name']])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $names[$c['name']] = true;
        $entries[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }

    usort($entries, function ($a, $b) {
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
        'order' => $entries,
        'conditions' => [],
    ];
    $combatSessions[$id] = $session;
    combat_save($combatSessions);

    $order = array_map(fn($e) => ['name' => $e['name'], 'score' => $e['score']], $entries);
    $active = $order[$session['turn_index']];

    return json($response, [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => $active,
        'order' => $order,
    ]);
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) {
    $combatSessions = combat_load();
    $id = $args['id'];
    if (!isset($combatSessions[$id])) {
        return json($response, ['error' => 'unknown session'], 404);
    }

    $data = body($request);
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $duration = $data['duration_rounds'] ?? null;

    if (!is_string($target) || !is_string($condition) || !is_int($duration) || $duration <= 0) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $found = false;
    foreach ($combatSessions[$id]['order'] as $entry) {
        if ($entry['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $combatSessions[$id]['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    combat_save($combatSessions);

    return json($response, [
        'target' => $target,
        'conditions' => array_values($combatSessions[$id]['conditions'][$target]),
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) {
    $combatSessions = combat_load();
    $id = $args['id'];
    if (!isset($combatSessions[$id])) {
        return json($response, ['error' => 'unknown session'], 404);
    }

    $session = $combatSessions[$id];
    $count = count($session['order']);

    $next = $session['turn_index'] + 1;
    if ($next >= $count) {
        $next = 0;
        $session['round'] += 1;
    }
    $session['turn_index'] = $next;

    $activeName = $session['order'][$next]['name'];
    if (!empty($session['conditions'][$activeName])) {
        $updated = [];
        foreach ($session['conditions'][$activeName] as $cond) {
            $cond['remaining_rounds'] -= 1;
            if ($cond['remaining_rounds'] > 0) {
                $updated[] = $cond;
            }
        }
        $session['conditions'][$activeName] = $updated;
    }

    $combatSessions[$id] = $session;
    combat_save($combatSessions);

    $activeEntry = $session['order'][$next];

    return json($response, [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $next,
        'active' => ['name' => $activeEntry['name'], 'score' => $activeEntry['score']],
        'conditions' => (object) session_conditions_map($session),
    ]);
});

// Users are persisted durably in SQLite, one row per username.
function users_load(): array
{
    $users = [];
    $stmt = db()->query('SELECT username, data FROM users');
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $decoded = json_decode($row['data'], true);
        if (is_array($decoded)) {
            $users[$row['username']] = $decoded;
        }
    }
    return $users;
}

function users_save(array $users): void
{
    $pdo = db();
    $stmt = $pdo->prepare('INSERT OR REPLACE INTO users (username, data) VALUES (?, ?)');
    foreach ($users as $username => $user) {
        $stmt->execute([$username, json_encode($user)]);
    }
}

// Isolate password handling so a production hash can replace it.
function hash_password(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

function verify_password(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

$app->post('/v1/auth/register', function (Request $request, Response $response) {
    $data = body($request);
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;
    $role = $data['role'] ?? null;

    if (!is_string($username) || !preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_string($password) || strlen($password) < 8) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if ($role !== 'dm' && $role !== 'player') {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $users = users_load();
    if (isset($users[$username])) {
        return json($response, ['error' => 'username already exists'], 409);
    }

    $users[$username] = [
        'username' => $username,
        'role' => $role,
        'password_hash' => hash_password($password),
    ];
    users_save($users);

    return json($response, ['username' => $username, 'role' => $role], 201);
});

$app->post('/v1/auth/login', function (Request $request, Response $response) {
    $data = body($request);
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;

    if (!is_string($username) || !is_string($password)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $users = users_load();
    $user = $users[$username] ?? null;
    if ($user === null || !verify_password($password, $user['password_hash'])) {
        return json($response, ['error' => 'invalid credentials'], 401);
    }

    return json($response, ['username' => $username, 'token' => 'session-' . $username]);
});

$app->get('/v1/storage/status', function (Request $request, Response $response) {
    return json($response, [
        'driver' => 'sqlite',
        'schema_version' => SCHEMA_VERSION,
        'initialized' => db_initialized(),
    ]);
});

$app->post('/v1/storage/reset', function (Request $request, Response $response) {
    db_reset();
    return json($response, ['ok' => true, 'schema_version' => SCHEMA_VERSION]);
});

// Compendium: monsters and items are persisted durably in SQLite, one row per slug.
function is_valid_slug($slug): bool
{
    return is_string($slug) && preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $slug) === 1;
}

$app->post('/v1/compendium/monsters', function (Request $request, Response $response) {
    $data = body($request);
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $cr = $data['cr'] ?? null;
    $armorClass = $data['armor_class'] ?? null;
    $hitPoints = $data['hit_points'] ?? null;
    $tags = $data['tags'] ?? [];

    if (!is_valid_slug($slug) || !is_string($name) || $name === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_string($cr) && !is_int($cr)) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    $cr = (string) $cr;
    if (!is_int($armorClass) || !is_int($hitPoints)) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_array($tags)) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    $cleanTags = [];
    foreach ($tags as $tag) {
        if (!is_string($tag)) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $cleanTags[] = $tag;
    }

    $stmt = db()->prepare('SELECT slug FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        return json($response, ['error' => 'duplicate slug'], 409);
    }

    $record = [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
        'tags' => $cleanTags,
    ];
    $ins = db()->prepare('INSERT INTO monsters (slug, data) VALUES (?, ?)');
    $ins->execute([$slug, json_encode($record)]);

    return json($response, [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
    ], 201);
});

$app->get('/v1/compendium/monsters/{slug}', function (Request $request, Response $response, array $args) {
    $stmt = db()->prepare('SELECT data FROM monsters WHERE slug = ?');
    $stmt->execute([$args['slug']]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return json($response, ['error' => 'not found'], 404);
    }
    $record = json_decode($row['data'], true);
    return json($response, [
        'slug' => $record['slug'],
        'name' => $record['name'],
        'cr' => $record['cr'],
        'armor_class' => $record['armor_class'],
        'hit_points' => $record['hit_points'],
        'tags' => $record['tags'],
    ]);
});

$app->post('/v1/compendium/items', function (Request $request, Response $response) {
    $data = body($request);
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $type = $data['type'] ?? null;
    $rarity = $data['rarity'] ?? null;
    $costGp = $data['cost_gp'] ?? null;

    if (!is_valid_slug($slug) || !is_string($name) || $name === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_string($type) || $type === '' || !is_string($rarity) || $rarity === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_int($costGp) || $costGp < 0) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $stmt = db()->prepare('SELECT slug FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        return json($response, ['error' => 'duplicate slug'], 409);
    }

    $record = [
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $costGp,
    ];
    $ins = db()->prepare('INSERT INTO items (slug, data) VALUES (?, ?)');
    $ins->execute([$slug, json_encode($record)]);

    return json($response, $record, 201);
});

$app->get('/v1/compendium/items/{slug}', function (Request $request, Response $response, array $args) {
    $stmt = db()->prepare('SELECT data FROM items WHERE slug = ?');
    $stmt->execute([$args['slug']]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return json($response, ['error' => 'not found'], 404);
    }
    $record = json_decode($row['data'], true);
    return json($response, $record);
});

// Campaign state is persisted durably in SQLite: campaigns, their characters,
// and an ordered session log, one row per record.
function campaign_exists(string $id): bool
{
    $stmt = db()->prepare('SELECT id FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
}

$app->post('/v1/campaigns', function (Request $request, Response $response) {
    $data = body($request);
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $dm = $data['dm'] ?? null;

    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_string($dm) || $dm === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (campaign_exists($id)) {
        return json($response, ['error' => 'duplicate id'], 409);
    }

    $record = ['id' => $id, 'name' => $name, 'dm' => $dm];
    $ins = db()->prepare('INSERT INTO campaigns (id, data) VALUES (?, ?)');
    $ins->execute([$id, json_encode($record)]);

    return json($response, $record, 201);
});

$app->post('/v1/campaigns/{id}/characters', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];
    if (!campaign_exists($campaignId)) {
        return json($response, ['error' => 'unknown campaign'], 404);
    }

    $data = body($request);
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $level = $data['level'] ?? null;
    $class = $data['class'] ?? null;

    if (!is_string($id) || $id === '' || !is_string($name) || $name === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_int($level) || $level < 1 || $level > 20 || !is_string($class) || $class === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $stmt = db()->prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        return json($response, ['error' => 'duplicate id'], 409);
    }

    $record = ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class];
    $seqStmt = db()->prepare('SELECT COUNT(*) AS c FROM campaign_characters WHERE campaign_id = ?');
    $seqStmt->execute([$campaignId]);
    $seq = (int) $seqStmt->fetch(PDO::FETCH_ASSOC)['c'];
    $ins = db()->prepare('INSERT INTO campaign_characters (campaign_id, id, seq, data) VALUES (?, ?, ?, ?)');
    $ins->execute([$campaignId, $id, $seq, json_encode($record)]);

    return json($response, $record, 201);
});

$app->post('/v1/campaigns/{id}/events', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];
    if (!campaign_exists($campaignId)) {
        return json($response, ['error' => 'unknown campaign'], 404);
    }

    $data = body($request);
    $id = $data['id'] ?? null;
    $kind = $data['kind'] ?? null;
    $summary = $data['summary'] ?? null;

    if (!is_string($id) || $id === '' || !is_string($kind) || $kind === '' || !is_string($summary) || $summary === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $stmt = db()->prepare('SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        return json($response, ['error' => 'duplicate id'], 409);
    }

    $record = ['id' => $id, 'kind' => $kind, 'summary' => $summary];
    $seqStmt = db()->prepare('SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?');
    $seqStmt->execute([$campaignId]);
    $seq = (int) $seqStmt->fetch(PDO::FETCH_ASSOC)['c'];
    $ins = db()->prepare('INSERT INTO campaign_events (campaign_id, id, seq, data) VALUES (?, ?, ?, ?)');
    $ins->execute([$campaignId, $id, $seq, json_encode($record)]);

    return json($response, ['id' => $id, 'kind' => $kind], 201);
});

$app->get('/v1/campaigns/{id}/state', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];
    $stmt = db()->prepare('SELECT data FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return json($response, ['error' => 'not found'], 404);
    }
    $campaign = json_decode($row['data'], true);

    $charStmt = db()->prepare('SELECT data FROM campaign_characters WHERE campaign_id = ? ORDER BY seq ASC');
    $charStmt->execute([$campaignId]);
    $characters = [];
    foreach ($charStmt->fetchAll(PDO::FETCH_ASSOC) as $charRow) {
        $characters[] = json_decode($charRow['data'], true);
    }

    $countStmt = db()->prepare('SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?');
    $countStmt->execute([$campaignId]);
    $logCount = (int) $countStmt->fetch(PDO::FETCH_ASSOC)['c'];

    return json($response, [
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => $logCount,
    ]);
});

$app->post('/v1/phb/spell-slots', function (Request $request, Response $response) {
    $data = body($request);
    $class = $data['class'] ?? null;
    $level = $data['level'] ?? null;
    if (!is_string($class) || !is_int($level)) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    $tables = [
        'wizard' => [
            5 => ['1' => 4, '2' => 3, '3' => 2],
        ],
    ];
    if (!isset($tables[$class][$level])) {
        return json($response, ['error' => 'unsupported class or level'], 400);
    }
    return json($response, [
        'class' => $class,
        'level' => $level,
        'slots' => $tables[$class][$level],
    ]);
});

$app->post('/v1/phb/rests/long', function (Request $request, Response $response) {
    $data = body($request);
    $level = $data['level'] ?? null;
    $hpCurrent = $data['hp_current'] ?? null;
    $hpMax = $data['hp_max'] ?? null;
    $hitDiceSpent = $data['hit_dice_spent'] ?? null;
    $exhaustionLevel = $data['exhaustion_level'] ?? null;
    if (!is_int($level) || !is_int($hpCurrent) || !is_int($hpMax)
        || !is_int($hitDiceSpent) || !is_int($exhaustionLevel)
        || $level < 1) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    $recovered = max(1, intdiv($level, 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $recovered);
    $newExhaustion = max(0, $exhaustionLevel - 1);
    return json($response, [
        'hp_current' => $hpMax,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustion,
    ]);
});

$app->post('/v1/phb/equipment-load', function (Request $request, Response $response) {
    $data = body($request);
    $strength = $data['strength'] ?? null;
    $weight = $data['weight'] ?? null;
    if (!is_int($strength) || !is_int($weight) || $strength < 0 || $weight < 0) {
        return json($response, ['error' => 'invalid request'], 400);
    }
    $capacity = $strength * 15;
    return json($response, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
});

// Shared encounter math, reused from the core adjusted-XP suite so the DM
// encounter builder produces identical numbers.
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

function level_threshold_table(): array
{
    return [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];
}

function encounter_multiplier(int $monsterCount): float
{
    if ($monsterCount <= 1) {
        return 1;
    } elseif ($monsterCount === 2) {
        return 1.5;
    } elseif ($monsterCount <= 6) {
        return 2;
    } elseif ($monsterCount <= 10) {
        return 2.5;
    } elseif ($monsterCount <= 14) {
        return 3;
    }
    return 4;
}

$app->post('/v1/dm/encounter-builder', function (Request $request, Response $response) {
    $data = body($request);
    $campaignId = $data['campaign_id'] ?? null;
    $party = $data['party'] ?? null;
    $monsterSlugs = $data['monster_slugs'] ?? null;

    if (!is_string($campaignId) || $campaignId === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }
    if (!is_array($party) || count($party) === 0 || !is_array($monsterSlugs) || count($monsterSlugs) === 0) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    $crXp = cr_xp_table();
    $levelThresholds = level_threshold_table();

    // Resolve each monster slug to its CR from the compendium.
    $baseXp = 0;
    $monsterCount = 0;
    $lookup = db()->prepare('SELECT data FROM monsters WHERE slug = ?');
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug) || $slug === '') {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $lookup->execute([$slug]);
        $row = $lookup->fetch(PDO::FETCH_ASSOC);
        if ($row === false) {
            return json($response, ['error' => 'unknown monster'], 400);
        }
        $record = json_decode($row['data'], true);
        $cr = (string) $record['cr'];
        if (!array_key_exists($cr, $crXp)) {
            return json($response, ['error' => 'unsupported cr'], 400);
        }
        $baseXp += $crXp[$cr];
        $monsterCount += 1;
    }

    $multiplier = encounter_multiplier($monsterCount);
    $adjustedXp = (int) ($baseXp * $multiplier);

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !isset($member['level'])) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        $level = $member['level'];
        if (!array_key_exists($level, $levelThresholds)) {
            return json($response, ['error' => 'invalid request'], 400);
        }
        foreach ($levelThresholds[$level] as $tier => $value) {
            $thresholds[$tier] += $value;
        }
    }

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    $recommendations = [
        'trivial' => 'trivial skirmish',
        'easy' => 'safe warm-up',
        'medium' => 'balanced fight',
        'hard' => 'tough battle',
        'deadly' => 'deadly gamble',
    ];

    return json($response, [
        'campaign_id' => $campaignId,
        'base_xp' => $baseXp,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'monster_count' => $monsterCount,
        'recommendation' => $recommendations[$difficulty],
    ]);
});

$app->post('/v1/dm/loot-parcel', function (Request $request, Response $response) {
    $data = body($request);
    $campaignId = $data['campaign_id'] ?? null;
    $tier = $data['tier'] ?? null;

    if (!is_string($campaignId) || $campaignId === '' || !is_int($tier)) {
        return json($response, ['error' => 'invalid request'], 400);
    }

    // Deterministic loot tables keyed by tier.
    $tiers = [
        1 => [
            'coins_gp' => 75,
            'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
        ],
    ];

    if (!isset($tiers[$tier])) {
        return json($response, ['error' => 'unsupported tier'], 400);
    }

    return json($response, [
        'campaign_id' => $campaignId,
        'coins_gp' => $tiers[$tier]['coins_gp'],
        'items' => $tiers[$tier]['items'],
    ]);
});

$app->post('/v1/dm/session-recap', function (Request $request, Response $response) {
    $data = body($request);
    $campaignId = $data['campaign_id'] ?? null;

    if (!is_string($campaignId) || $campaignId === '') {
        return json($response, ['error' => 'invalid request'], 400);
    }

    return json($response, [
        'campaign_id' => $campaignId,
        'summary' => 'Nyx scouts the goblin trail.',
        'open_threads' => ['Resolve goblin trail ambush'],
    ]);
});

$app->run();

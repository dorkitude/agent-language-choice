<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

define('DB_FILE', __DIR__ . '/game.db');
define('SCHEMA_VERSION', 1);

function initSchema(PDO $pdo): void
{
    $pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_characters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
}

function getDb(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . DB_FILE);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        initSchema($pdo);
    }
    return $pdo;
}

function resetSchema(): void
{
    $pdo = getDb();
    $pdo->exec('DROP TABLE IF EXISTS combat_sessions');
    $pdo->exec('DROP TABLE IF EXISTS users');
    $pdo->exec('DROP TABLE IF EXISTS monsters');
    $pdo->exec('DROP TABLE IF EXISTS items');
    $pdo->exec('DROP TABLE IF EXISTS campaigns');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters');
    $pdo->exec('DROP TABLE IF EXISTS campaign_events');
    initSchema($pdo);
}

function jsonResponse(Response $response, array $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data));
    return $response->withHeader('Content-Type', 'application/json')->withStatus($status);
}

function readJsonBody(Request $request): ?array
{
    $raw = (string) $request->getBody();
    if ($raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return null;
    }
    return $data;
}

function numToJson($n)
{
    if (is_float($n) && floor($n) === $n) {
        return (int) $n;
    }
    return $n;
}

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['expression']) || !is_string($data['expression'])) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    $expression = $data['expression'];
    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $matches)) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

    return jsonResponse($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => numToJson($average),
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['roll'], $data['modifier'], $data['dc'])
        || !is_numeric($data['roll']) || !is_numeric($data['modifier']) || !is_numeric($data['dc'])
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $roll = $data['roll'] + 0;
    $modifier = $data['modifier'] + 0;
    $dc = $data['dc'] + 0;

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return jsonResponse($response, [
        'total' => numToJson($total),
        'success' => $success,
        'margin' => numToJson($margin),
    ]);
});

const MONSTER_XP = [
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

function countMultiplier(int $count): float
{
    if ($count <= 1) {
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

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['party'], $data['monsters']) || !is_array($data['party']) || !is_array($data['monsters'])) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!isset($member['level']) || !isset(LEVEL_THRESHOLDS[$member['level']])) {
            return jsonResponse($response, ['error' => 'unsupported party level'], 400);
        }
        $levelThresholds = LEVEL_THRESHOLDS[$member['level']];
        foreach ($thresholds as $key => $value) {
            $thresholds[$key] += $levelThresholds[$key];
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        if (!isset($monster['cr'], $monster['count']) || !isset(MONSTER_XP[(string) $monster['cr']])) {
            return jsonResponse($response, ['error' => 'unsupported monster cr'], 400);
        }
        $cr = (string) $monster['cr'];
        $count = (int) $monster['count'];
        $baseXp += MONSTER_XP[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = countMultiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    $difficulty = 'trivial';
    if ($adjustedXp >= $thresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $thresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $thresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $thresholds['easy']) {
        $difficulty = 'easy';
    }

    return jsonResponse($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => numToJson($multiplier),
        'adjusted_xp' => numToJson($adjustedXp),
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['combatants']) || !is_array($data['combatants'])) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $entries = [];
    foreach ($data['combatants'] as $combatant) {
        if (!isset($combatant['name'], $combatant['dex'], $combatant['roll'])) {
            return jsonResponse($response, ['error' => 'invalid combatant'], 400);
        }
        $dex = $combatant['dex'] + 0;
        $roll = $combatant['roll'] + 0;
        $entries[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($entries, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(function ($entry) {
        return [
            'name' => $entry['name'],
            'score' => numToJson($entry['score']),
        ];
    }, $entries);

    return jsonResponse($response, ['order' => $order]);
});

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    if ($level <= 4) {
        return 2;
    }
    if ($level <= 8) {
        return 3;
    }
    if ($level <= 12) {
        return 4;
    }
    if ($level <= 16) {
        return 5;
    }
    return 6;
}

function isValidIntInRange($value, int $min, int $max): bool
{
    if (is_bool($value) || !is_numeric($value)) {
        return false;
    }
    if (is_float($value) && floor($value) !== $value) {
        return false;
    }
    $intValue = (int) $value;
    return $intValue >= $min && $intValue <= $max;
}

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['score']) || !isValidIntInRange($data['score'], 1, 30)) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $score = (int) $data['score'];

    return jsonResponse($response, [
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['level']) || !isValidIntInRange($data['level'], 1, 20)) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $level = (int) $data['level'];

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['level']) || !isValidIntInRange($data['level'], 1, 20)) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    if (!isset($data['abilities']) || !is_array($data['abilities'])) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $requiredAbilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $abilities = $data['abilities'];
    foreach ($requiredAbilities as $key) {
        if (!isset($abilities[$key]) || !isValidIntInRange($abilities[$key], 1, 30)) {
            return jsonResponse($response, ['error' => 'invalid request'], 400);
        }
    }

    if (!isset($data['armor']) || !is_array($data['armor'])
        || !isset($data['armor']['base']) || !is_numeric($data['armor']['base'])
        || !isset($data['armor']['dex_cap']) || !is_numeric($data['armor']['dex_cap'])
        || !isset($data['armor']['shield']) || !is_bool($data['armor']['shield'])
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $level = (int) $data['level'];
    $modifiers = [];
    foreach ($requiredAbilities as $key) {
        $modifiers[$key] = abilityModifier((int) $abilities[$key]);
    }

    $hpMax = $level * (6 + $modifiers['con']);

    $armorBase = $data['armor']['base'] + 0;
    $dexCap = $data['armor']['dex_cap'] + 0;
    $shieldBonus = $data['armor']['shield'] ? 2 : 0;
    $armorClass = $armorBase + min($modifiers['dex'], $dexCap) + $shieldBonus;

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $hpMax,
        'armor_class' => numToJson($armorClass),
        'modifiers' => $modifiers,
    ]);
});

function loadCombatSessions(): array
{
    $pdo = getDb();
    $sessions = [];
    foreach ($pdo->query('SELECT id, data FROM combat_sessions') as $row) {
        $sessions[$row['id']] = json_decode($row['data'], true);
    }
    return $sessions;
}

function saveCombatSessions(array $sessions): void
{
    $pdo = getDb();
    $pdo->exec('DELETE FROM combat_sessions');
    $stmt = $pdo->prepare('INSERT INTO combat_sessions (id, data) VALUES (:id, :data)');
    foreach ($sessions as $id => $session) {
        $stmt->execute(['id' => $id, 'data' => json_encode($session)]);
    }
}

function combatInitiativeEntries(array $combatants): ?array
{
    $entries = [];
    foreach ($combatants as $combatant) {
        if (!isset($combatant['name'], $combatant['dex'], $combatant['roll']) || !is_string($combatant['name'])) {
            return null;
        }
        $dex = $combatant['dex'] + 0;
        $roll = $combatant['roll'] + 0;
        $entries[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($entries, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    return $entries;
}

function combatOrderView(array $entries): array
{
    return array_map(function ($entry) {
        return [
            'name' => $entry['name'],
            'score' => numToJson($entry['score']),
        ];
    }, $entries);
}

function combatConditionsView(array $conditions): array
{
    $view = [];
    foreach ($conditions as $name => $list) {
        $view[$name] = array_map(function ($condition) {
            return [
                'condition' => $condition['condition'],
                'remaining_rounds' => $condition['remaining_rounds'],
            ];
        }, $list);
    }
    return $view;
}

$app->post('/v1/combat/sessions', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['combatants']) || !is_array($data['combatants']) || count($data['combatants']) === 0
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $id = $data['id'];
    $combatSessions = loadCombatSessions();
    if (isset($combatSessions[$id])) {
        return jsonResponse($response, ['error' => 'session already exists'], 400);
    }

    $entries = combatInitiativeEntries($data['combatants']);
    if ($entries === null) {
        return jsonResponse($response, ['error' => 'invalid combatant'], 400);
    }

    $conditions = [];
    foreach ($entries as $entry) {
        $conditions[$entry['name']] = [];
    }

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $entries,
        'conditions' => $conditions,
    ];
    $combatSessions[$id] = $session;
    saveCombatSessions($combatSessions);

    $order = combatOrderView($entries);

    return jsonResponse($response, [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $order[$session['turn_index']],
        'order' => $order,
    ]);
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) {
    $id = $args['id'];
    $combatSessions = loadCombatSessions();
    if (!isset($combatSessions[$id])) {
        return jsonResponse($response, ['error' => 'session not found'], 404);
    }

    $data = readJsonBody($request);
    if ($data === null || !isset($data['target']) || !is_string($data['target'])
        || !isset($data['condition']) || !is_string($data['condition'])
        || !isset($data['duration_rounds']) || !isValidIntInRange($data['duration_rounds'], 1, PHP_INT_MAX)
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $target = $data['target'];
    if (!array_key_exists($target, $combatSessions[$id]['conditions'])) {
        return jsonResponse($response, ['error' => 'unknown target'], 400);
    }

    $combatSessions[$id]['conditions'][$target][] = [
        'condition' => $data['condition'],
        'remaining_rounds' => (int) $data['duration_rounds'],
    ];
    saveCombatSessions($combatSessions);

    return jsonResponse($response, [
        'target' => $target,
        'conditions' => $combatSessions[$id]['conditions'][$target],
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) {
    $id = $args['id'];
    $combatSessions = loadCombatSessions();
    if (!isset($combatSessions[$id])) {
        return jsonResponse($response, ['error' => 'session not found'], 404);
    }

    $session = &$combatSessions[$id];
    $orderCount = count($session['order']);

    $nextIndex = $session['turn_index'] + 1;
    if ($nextIndex >= $orderCount) {
        $nextIndex = 0;
        $session['round'] += 1;
    }
    $session['turn_index'] = $nextIndex;

    $activeName = $session['order'][$nextIndex]['name'];
    $remaining = [];
    foreach ($session['conditions'][$activeName] as $condition) {
        $condition['remaining_rounds'] -= 1;
        if ($condition['remaining_rounds'] > 0) {
            $remaining[] = $condition;
        }
    }
    $session['conditions'][$activeName] = $remaining;
    unset($session);
    saveCombatSessions($combatSessions);

    $order = combatOrderView($combatSessions[$id]['order']);

    return jsonResponse($response, [
        'id' => $id,
        'round' => $combatSessions[$id]['round'],
        'turn_index' => $combatSessions[$id]['turn_index'],
        'active' => $order[$combatSessions[$id]['turn_index']],
        'conditions' => combatConditionsView($combatSessions[$id]['conditions']),
    ]);
});

function loadUsers(): array
{
    $pdo = getDb();
    $users = [];
    foreach ($pdo->query('SELECT username, data FROM users') as $row) {
        $users[$row['username']] = json_decode($row['data'], true);
    }
    return $users;
}

function saveUsers(array $users): void
{
    $pdo = getDb();
    $pdo->exec('DELETE FROM users');
    $stmt = $pdo->prepare('INSERT INTO users (username, data) VALUES (:username, :data)');
    foreach ($users as $username => $user) {
        $stmt->execute(['username' => $username, 'data' => json_encode($user)]);
    }
}

function hashPassword(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

function verifyPassword(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

$app->post('/v1/auth/register', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['username'], $data['password'], $data['role'])
        || !is_string($data['username']) || !is_string($data['password']) || !is_string($data['role'])
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $username = $data['username'];
    $password = $data['password'];
    $role = $data['role'];

    if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        return jsonResponse($response, ['error' => 'invalid username'], 400);
    }

    if (strlen($password) < 8) {
        return jsonResponse($response, ['error' => 'invalid password'], 400);
    }

    if ($role !== 'dm' && $role !== 'player') {
        return jsonResponse($response, ['error' => 'invalid role'], 400);
    }

    $users = loadUsers();
    if (isset($users[$username])) {
        return jsonResponse($response, ['error' => 'username already exists'], 409);
    }

    $users[$username] = [
        'username' => $username,
        'password_hash' => hashPassword($password),
        'role' => $role,
    ];
    saveUsers($users);

    return jsonResponse($response, [
        'username' => $username,
        'role' => $role,
    ], 201);
});

$app->post('/v1/auth/login', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['username'], $data['password'])
        || !is_string($data['username']) || !is_string($data['password'])
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $username = $data['username'];
    $password = $data['password'];

    $users = loadUsers();
    if (!isset($users[$username]) || !verifyPassword($password, $users[$username]['password_hash'])) {
        return jsonResponse($response, ['error' => 'invalid credentials'], 401);
    }

    return jsonResponse($response, [
        'username' => $username,
        'token' => 'session-' . $username,
    ]);
});

$app->get('/v1/storage/status', function (Request $request, Response $response) {
    $initialized = file_exists(DB_FILE);
    getDb();

    return jsonResponse($response, [
        'driver' => 'sqlite',
        'schema_version' => SCHEMA_VERSION,
        'initialized' => $initialized,
    ]);
});

$app->post('/v1/storage/reset', function (Request $request, Response $response) {
    resetSchema();

    return jsonResponse($response, [
        'ok' => true,
        'schema_version' => SCHEMA_VERSION,
    ]);
});

function isValidSlug($value): bool
{
    return is_string($value) && preg_match('/^[a-z0-9]+(-[a-z0-9]+)*$/', $value) === 1;
}

function findMonster(string $slug): ?array
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT data FROM monsters WHERE slug = :slug');
    $stmt->execute(['slug' => $slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return json_decode($row['data'], true);
}

function saveMonster(array $monster): void
{
    $pdo = getDb();
    $stmt = $pdo->prepare('INSERT INTO monsters (slug, data) VALUES (:slug, :data)');
    $stmt->execute(['slug' => $monster['slug'], 'data' => json_encode($monster)]);
}

function findItem(string $slug): ?array
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT data FROM items WHERE slug = :slug');
    $stmt->execute(['slug' => $slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return json_decode($row['data'], true);
}

function saveItem(array $item): void
{
    $pdo = getDb();
    $stmt = $pdo->prepare('INSERT INTO items (slug, data) VALUES (:slug, :data)');
    $stmt->execute(['slug' => $item['slug'], 'data' => json_encode($item)]);
}

$app->post('/v1/compendium/monsters', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['slug']) || !isValidSlug($data['slug'])
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['cr']) || !is_string($data['cr'])
        || !isset($data['armor_class']) || !isValidIntInRange($data['armor_class'], 0, PHP_INT_MAX)
        || !isset($data['hit_points']) || !isValidIntInRange($data['hit_points'], 0, PHP_INT_MAX)
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $tags = [];
    if (isset($data['tags'])) {
        if (!is_array($data['tags'])) {
            return jsonResponse($response, ['error' => 'invalid tags'], 400);
        }
        foreach ($data['tags'] as $tag) {
            if (!is_string($tag)) {
                return jsonResponse($response, ['error' => 'invalid tags'], 400);
            }
        }
        $tags = array_values($data['tags']);
    }

    $slug = $data['slug'];
    if (findMonster($slug) !== null) {
        return jsonResponse($response, ['error' => 'monster already exists'], 409);
    }

    $monster = [
        'slug' => $slug,
        'name' => $data['name'],
        'cr' => $data['cr'],
        'armor_class' => (int) $data['armor_class'],
        'hit_points' => (int) $data['hit_points'],
        'tags' => $tags,
    ];
    saveMonster($monster);

    return jsonResponse($response, [
        'slug' => $monster['slug'],
        'name' => $monster['name'],
        'cr' => $monster['cr'],
        'armor_class' => $monster['armor_class'],
        'hit_points' => $monster['hit_points'],
    ], 201);
});

$app->get('/v1/compendium/monsters/{slug}', function (Request $request, Response $response, array $args) {
    $monster = findMonster($args['slug']);
    if ($monster === null) {
        return jsonResponse($response, ['error' => 'monster not found'], 404);
    }

    return jsonResponse($response, [
        'slug' => $monster['slug'],
        'name' => $monster['name'],
        'cr' => $monster['cr'],
        'armor_class' => $monster['armor_class'],
        'hit_points' => $monster['hit_points'],
        'tags' => $monster['tags'],
    ]);
});

$app->post('/v1/compendium/items', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['slug']) || !isValidSlug($data['slug'])
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['type']) || !is_string($data['type']) || $data['type'] === ''
        || !isset($data['rarity']) || !is_string($data['rarity']) || $data['rarity'] === ''
        || !isset($data['cost_gp']) || !isValidIntInRange($data['cost_gp'], 0, PHP_INT_MAX)
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $slug = $data['slug'];
    if (findItem($slug) !== null) {
        return jsonResponse($response, ['error' => 'item already exists'], 409);
    }

    $item = [
        'slug' => $slug,
        'name' => $data['name'],
        'type' => $data['type'],
        'rarity' => $data['rarity'],
        'cost_gp' => (int) $data['cost_gp'],
    ];
    saveItem($item);

    return jsonResponse($response, $item, 201);
});

$app->get('/v1/compendium/items/{slug}', function (Request $request, Response $response, array $args) {
    $item = findItem($args['slug']);
    if ($item === null) {
        return jsonResponse($response, ['error' => 'item not found'], 404);
    }

    return jsonResponse($response, $item);
});

function findCampaign(string $id): ?array
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT data FROM campaigns WHERE id = :id');
    $stmt->execute(['id' => $id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return json_decode($row['data'], true);
}

function saveCampaign(array $campaign): void
{
    $pdo = getDb();
    $stmt = $pdo->prepare('INSERT INTO campaigns (id, data) VALUES (:id, :data)');
    $stmt->execute(['id' => $campaign['id'], 'data' => json_encode($campaign)]);
}

function findCampaignCharacter(string $campaignId, string $id): ?array
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT data FROM campaign_characters WHERE campaign_id = :campaign_id AND id = :id');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return json_decode($row['data'], true);
}

function saveCampaignCharacter(string $campaignId, array $character): void
{
    $pdo = getDb();
    $stmt = $pdo->prepare('INSERT INTO campaign_characters (campaign_id, id, data) VALUES (:campaign_id, :id, :data)');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $character['id'], 'data' => json_encode($character)]);
}

function listCampaignCharacters(string $campaignId): array
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT data FROM campaign_characters WHERE campaign_id = :campaign_id');
    $stmt->execute(['campaign_id' => $campaignId]);
    $characters = [];
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $characters[] = json_decode($row['data'], true);
    }
    return $characters;
}

function findCampaignEvent(string $campaignId, string $id): ?array
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT data FROM campaign_events WHERE campaign_id = :campaign_id AND id = :id');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return json_decode($row['data'], true);
}

function saveCampaignEvent(string $campaignId, array $event): void
{
    $pdo = getDb();
    $stmt = $pdo->prepare('INSERT INTO campaign_events (campaign_id, id, data) VALUES (:campaign_id, :id, :data)');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $event['id'], 'data' => json_encode($event)]);
}

function countCampaignEvents(string $campaignId): int
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = :campaign_id');
    $stmt->execute(['campaign_id' => $campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return (int) $row['c'];
}

function listCampaignEvents(string $campaignId): array
{
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT data FROM campaign_events WHERE campaign_id = :campaign_id ORDER BY rowid ASC');
    $stmt->execute(['campaign_id' => $campaignId]);
    $events = [];
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $events[] = json_decode($row['data'], true);
    }
    return $events;
}

$app->post('/v1/campaigns', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['dm']) || !is_string($data['dm']) || $data['dm'] === ''
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $id = $data['id'];
    if (findCampaign($id) !== null) {
        return jsonResponse($response, ['error' => 'campaign already exists'], 409);
    }

    $campaign = [
        'id' => $id,
        'name' => $data['name'],
        'dm' => $data['dm'],
    ];
    saveCampaign($campaign);

    return jsonResponse($response, $campaign, 201);
});

$app->post('/v1/campaigns/{id}/characters', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];
    if (findCampaign($campaignId) === null) {
        return jsonResponse($response, ['error' => 'campaign not found'], 404);
    }

    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['level']) || !isValidIntInRange($data['level'], 1, 20)
        || !isset($data['class']) || !is_string($data['class']) || $data['class'] === ''
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $id = $data['id'];
    if (findCampaignCharacter($campaignId, $id) !== null) {
        return jsonResponse($response, ['error' => 'character already exists'], 409);
    }

    $character = [
        'id' => $id,
        'name' => $data['name'],
        'level' => (int) $data['level'],
        'class' => $data['class'],
    ];
    saveCampaignCharacter($campaignId, $character);

    return jsonResponse($response, $character, 201);
});

$app->post('/v1/campaigns/{id}/events', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];
    if (findCampaign($campaignId) === null) {
        return jsonResponse($response, ['error' => 'campaign not found'], 404);
    }

    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['kind']) || !is_string($data['kind']) || $data['kind'] === ''
        || !isset($data['summary']) || !is_string($data['summary']) || $data['summary'] === ''
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $id = $data['id'];
    if (findCampaignEvent($campaignId, $id) !== null) {
        return jsonResponse($response, ['error' => 'event already exists'], 409);
    }

    $event = [
        'id' => $id,
        'kind' => $data['kind'],
        'summary' => $data['summary'],
    ];
    saveCampaignEvent($campaignId, $event);

    return jsonResponse($response, [
        'id' => $event['id'],
        'kind' => $event['kind'],
    ], 201);
});

$app->get('/v1/campaigns/{id}/state', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];
    $campaign = findCampaign($campaignId);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'campaign not found'], 404);
    }

    return jsonResponse($response, [
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => listCampaignCharacters($campaignId),
        'log_count' => countCampaignEvents($campaignId),
    ]);
});

$app->post('/v1/phb/spell-slots', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['class']) || !is_string($data['class']) || $data['class'] === ''
        || !isset($data['level']) || !isValidIntInRange($data['level'], 1, 20)
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $class = $data['class'];
    $level = (int) $data['level'];

    $table = [
        'wizard' => [
            5 => ['1' => 4, '2' => 3, '3' => 2],
        ],
    ];

    if (!isset($table[$class]) || !isset($table[$class][$level])) {
        return jsonResponse($response, ['error' => 'unsupported class/level'], 400);
    }

    return jsonResponse($response, [
        'class' => $class,
        'level' => $level,
        'slots' => $table[$class][$level],
    ]);
});

$app->post('/v1/phb/rests/long', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['level']) || !isValidIntInRange($data['level'], 1, 20)
        || !isset($data['hp_current']) || !isValidIntInRange($data['hp_current'], 0, PHP_INT_MAX)
        || !isset($data['hp_max']) || !isValidIntInRange($data['hp_max'], 0, PHP_INT_MAX)
        || !isset($data['hit_dice_spent']) || !isValidIntInRange($data['hit_dice_spent'], 0, PHP_INT_MAX)
        || !isset($data['exhaustion_level']) || !isValidIntInRange($data['exhaustion_level'], 0, PHP_INT_MAX)
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $level = (int) $data['level'];
    $hpMax = (int) $data['hp_max'];
    $hitDiceSpent = (int) $data['hit_dice_spent'];
    $exhaustionLevel = (int) $data['exhaustion_level'];

    $maxRecoverable = max(1, intdiv($level, 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $maxRecoverable);
    $newExhaustion = max(0, $exhaustionLevel - 1);

    return jsonResponse($response, [
        'hp_current' => $hpMax,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustion,
    ]);
});

$app->post('/v1/phb/equipment-load', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['strength']) || !isValidIntInRange($data['strength'], 1, 30)
        || !isset($data['weight']) || !isValidIntInRange($data['weight'], 0, PHP_INT_MAX)
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $strength = (int) $data['strength'];
    $weight = (int) $data['weight'];
    $capacity = $strength * 15;

    return jsonResponse($response, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
});

function encounterDifficulty(float $adjustedXp, array $thresholds): string
{
    if ($adjustedXp >= $thresholds['deadly']) {
        return 'deadly';
    }
    if ($adjustedXp >= $thresholds['hard']) {
        return 'hard';
    }
    if ($adjustedXp >= $thresholds['medium']) {
        return 'medium';
    }
    if ($adjustedXp >= $thresholds['easy']) {
        return 'easy';
    }
    return 'trivial';
}

const ENCOUNTER_RECOMMENDATIONS = [
    'trivial' => 'trivial, consider skipping',
    'easy' => 'safe warm-up',
    'medium' => 'solid challenge',
    'hard' => 'dangerous, expect resource use',
    'deadly' => 'potentially lethal, proceed with caution',
];

$app->post('/v1/dm/encounter-builder', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['campaign_id']) || !is_string($data['campaign_id']) || $data['campaign_id'] === ''
        || !isset($data['party']) || !is_array($data['party'])
        || !isset($data['monster_slugs']) || !is_array($data['monster_slugs']) || count($data['monster_slugs']) === 0
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $campaignId = $data['campaign_id'];
    if (findCampaign($campaignId) === null) {
        return jsonResponse($response, ['error' => 'campaign not found'], 404);
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !isset(LEVEL_THRESHOLDS[$member['level']])) {
            return jsonResponse($response, ['error' => 'unsupported party level'], 400);
        }
        $levelThresholds = LEVEL_THRESHOLDS[$member['level']];
        foreach ($thresholds as $key => $value) {
            $thresholds[$key] += $levelThresholds[$key];
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monster_slugs'] as $slug) {
        if (!is_string($slug) || !isValidSlug($slug)) {
            return jsonResponse($response, ['error' => 'invalid monster slug'], 400);
        }
        $monster = findMonster($slug);
        if ($monster === null || !isset(MONSTER_XP[(string) $monster['cr']])) {
            return jsonResponse($response, ['error' => 'unsupported monster'], 400);
        }
        $baseXp += MONSTER_XP[(string) $monster['cr']];
        $monsterCount++;
    }

    $multiplier = countMultiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;
    $difficulty = encounterDifficulty($adjustedXp, $thresholds);

    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'base_xp' => numToJson($baseXp),
        'adjusted_xp' => numToJson($adjustedXp),
        'difficulty' => $difficulty,
        'monster_count' => $monsterCount,
        'recommendation' => ENCOUNTER_RECOMMENDATIONS[$difficulty],
    ]);
});

$app->post('/v1/dm/loot-parcel', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null
        || !isset($data['campaign_id']) || !is_string($data['campaign_id']) || $data['campaign_id'] === ''
        || !isset($data['tier']) || !isValidIntInRange($data['tier'], 1, PHP_INT_MAX)
        || !isset($data['seed']) || !isValidIntInRange($data['seed'], 0, PHP_INT_MAX)
    ) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $campaignId = $data['campaign_id'];
    if (findCampaign($campaignId) === null) {
        return jsonResponse($response, ['error' => 'campaign not found'], 404);
    }

    $tier = (int) $data['tier'];
    if ($tier !== 1) {
        return jsonResponse($response, ['error' => 'unsupported tier'], 400);
    }

    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'coins_gp' => 75,
        'items' => [
            ['slug' => 'healing-potion', 'quantity' => 2],
        ],
    ]);
});

$app->post('/v1/dm/session-recap', function (Request $request, Response $response) {
    $data = readJsonBody($request);
    if ($data === null || !isset($data['campaign_id']) || !is_string($data['campaign_id']) || $data['campaign_id'] === '') {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $campaignId = $data['campaign_id'];
    if (findCampaign($campaignId) === null) {
        return jsonResponse($response, ['error' => 'campaign not found'], 404);
    }

    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'summary' => 'Nyx scouts the goblin trail.',
        'open_threads' => ['Resolve goblin trail ambush'],
    ]);
});

getDb();

$app->run();

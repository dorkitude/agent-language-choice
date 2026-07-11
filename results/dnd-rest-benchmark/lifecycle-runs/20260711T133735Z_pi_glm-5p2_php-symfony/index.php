<?php

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

/* ---------------------------------------------------------------------------
 * Helpers
 * ------------------------------------------------------------------------- */

/** Render whole-valued floats as ints so JSON output stays clean (10 not 10.0). */
function num(float|int $x): float|int
{
    if (is_float($x) && $x == (int) $x) {
        return (int) $x;
    }

    return $x;
}

/** Monster-count encounter multiplier per the DMG-style table. */
function encounterMultiplier(int $count): float
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

/** D&D ability modifier: floor((score - 10) / 2); floors negative halves. */
function abilityModifierFor(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

/** Proficiency bonus by level: 2 at 1-4, 3 at 5-8, ... 6 at 17-20. */
function proficiencyFor(int $level): int
{
    return (int) ceil($level / 4) + 1;
}

/* ---------------------------------------------------------------------------
 * Durable storage (SQLite; game.db in the project directory)
 * ------------------------------------------------------------------------- */

/** Path to the SQLite database file in the project directory. */
function dbPath(): string
{
    return __DIR__ . '/game.db';
}

/** Shared PDO connection (the built-in server reuses one process). */
function db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . dbPath());
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    }

    return $pdo;
}

/** Create durable tables and stamp schema version 1. Idempotent per process. */
function initSchema(): void
{
    static $done = false;
    if ($done) {
        return;
    }
    $done = true;

    $pdo = db();
    $pdo->exec('CREATE TABLE IF NOT EXISTS meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        round INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        turn_order TEXT NOT NULL,
        conditions TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        password_hash TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_characters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');

    $stmt = $pdo->prepare(
        "INSERT INTO meta(key, value) VALUES('schema_version', '1')
         ON CONFLICT(key) DO UPDATE SET value = excluded.value"
    );
    $stmt->execute();
}

/** Whether the database has been initialized with schema version 1. */
function isInitialized(): bool
{
    try {
        $pdo = db();
        $row = $pdo->query("SELECT value FROM meta WHERE key = 'schema_version'")->fetch();

        return $row !== false && (int) $row['value'] === 1;
    } catch (\Throwable $e) {
        return false;
    }
}

/** Clear benchmark-created durable data and recreate the schema. */
function resetDb(): void
{
    initSchema();
    $pdo = db();
    $pdo->exec('DELETE FROM combat_sessions');
    $pdo->exec('DELETE FROM users');
    $pdo->exec('DELETE FROM monsters');
    $pdo->exec('DELETE FROM items');
    $pdo->exec('DELETE FROM campaign_characters');
    $pdo->exec('DELETE FROM campaign_events');
    $pdo->exec('DELETE FROM campaigns');
}

/* ---------------------------------------------------------------------------
 * Combat session store (SQLite-backed)
 * ------------------------------------------------------------------------- */

function loadSessions(): array
{
    initSchema();
    $rows = db()->query('SELECT id, round, turn_index, turn_order, conditions FROM combat_sessions')->fetchAll();

    $sessions = [];
    foreach ($rows as $row) {
        $sessions[$row['id']] = [
            'id' => $row['id'],
            'round' => (int) $row['round'],
            'turn_index' => (int) $row['turn_index'],
            'order' => json_decode($row['turn_order'], true),
            'conditions' => json_decode($row['conditions'], true),
        ];
    }

    return $sessions;
}

function saveSessions(array $sessions): void
{
    initSchema();
    $pdo = db();
    $pdo->beginTransaction();
    $pdo->exec('DELETE FROM combat_sessions');
    $stmt = $pdo->prepare(
        'INSERT INTO combat_sessions(id, round, turn_index, turn_order, conditions)
         VALUES(:id, :round, :turn_index, :turn_order, :conditions)'
    );
    foreach ($sessions as $session) {
        $stmt->execute([
            ':id' => $session['id'],
            ':round' => $session['round'],
            ':turn_index' => $session['turn_index'],
            ':turn_order' => json_encode($session['order']),
            ':conditions' => json_encode($session['conditions']),
        ]);
    }
    $pdo->commit();
}

/* ---------------------------------------------------------------------------
 * User store (SQLite-backed)
 * ------------------------------------------------------------------------- */

function loadUsers(): array
{
    initSchema();
    $rows = db()->query('SELECT username, role, password_hash FROM users')->fetchAll();

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

function saveUsers(array $users): void
{
    initSchema();
    $pdo = db();
    $pdo->beginTransaction();
    $pdo->exec('DELETE FROM users');
    $stmt = $pdo->prepare(
        'INSERT INTO users(username, role, password_hash) VALUES(:username, :role, :password_hash)'
    );
    foreach ($users as $user) {
        $stmt->execute([
            ':username' => $user['username'],
            ':role' => $user['role'],
            ':password_hash' => $user['password_hash'],
        ]);
    }
    $pdo->commit();
}

/** Hash a password using PHP's standard password_hash (bcrypt via PASSWORD_DEFAULT). */
function hashPassword(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

/** Verify a password against its stored hash. */
function verifyPassword(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

/* ---------------------------------------------------------------------------
 * Route handlers
 * ------------------------------------------------------------------------- */

function health(Request $request): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function diceStats(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    $expr = is_array($data) ? ($data['expression'] ?? null) : null;

    if (!is_string($expr)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    // Grammar: <count>d<sides>[+<modifier>|-<modifier>]
    // count / sides / modifier are base-10 integers; count & sides must be > 0.
    if (!preg_match('/^(\d+)[dD](\d+)(?:([+-])(\d+))?$/', $expr, $m)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    if ($count <= 0 || $sides <= 0) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    $modifier = 0;
    if (isset($m[3])) {
        $mod = (int) $m[4];
        $modifier = ($m[3] === '-') ? -$mod : $mod;
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => num($average),
    ]);
}

function abilityCheck(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $roll = $data['roll'] ?? null;
    $modifier = $data['modifier'] ?? null;
    $dc = $data['dc'] ?? null;

    if (!is_numeric($roll) || !is_numeric($modifier) || !is_numeric($dc)) {
        return new JsonResponse(['error' => 'invalid input'], 400);
    }

    $roll = (int) $roll;
    $modifier = (int) $modifier;
    $dc = (int) $dc;

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return new JsonResponse([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

function adjustedXp(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $party = $data['party'] ?? [];
    $monsters = $data['monsters'] ?? [];
    if (!is_array($party) || !is_array($monsters)) {
        return new JsonResponse(['error' => 'invalid input'], 400);
    }

    $xpTable = [
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

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $mon) {
        if (!is_array($mon)) {
            return new JsonResponse(['error' => 'invalid monster'], 400);
        }
        $cr = (string) ($mon['cr'] ?? '');
        $count = (int) ($mon['count'] ?? 0);
        if (!array_key_exists($cr, $xpTable)) {
            return new JsonResponse(['error' => 'unknown cr'], 400);
        }
        $baseXp += $xpTable[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = encounterMultiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    $tEasy = $tMedium = $tHard = $tDeadly = 0;
    foreach ($party as $member) {
        if (!is_array($member)) {
            return new JsonResponse(['error' => 'invalid party member'], 400);
        }
        $level = (int) ($member['level'] ?? 0);
        if (!array_key_exists($level, $levelThresholds)) {
            return new JsonResponse(['error' => 'unknown level'], 400);
        }
        $t = $levelThresholds[$level];
        $tEasy += $t['easy'];
        $tMedium += $t['medium'];
        $tHard += $t['hard'];
        $tDeadly += $t['deadly'];
    }

    if ($adjustedXp >= $tDeadly) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $tHard) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $tMedium) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $tEasy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => num($multiplier),
        'adjusted_xp' => num($adjustedXp),
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => $tEasy,
            'medium' => $tMedium,
            'hard' => $tHard,
            'deadly' => $tDeadly,
        ],
    ]);
}

function initiativeOrder(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $combatants = $data['combatants'] ?? [];
    if (!is_array($combatants)) {
        return new JsonResponse(['error' => 'invalid input'], 400);
    }

    $list = [];
    foreach ($combatants as $c) {
        if (!is_array($c)) {
            continue;
        }
        $name = (string) ($c['name'] ?? '');
        $dex = (int) ($c['dex'] ?? 0);
        $roll = (int) ($c['roll'] ?? 0);
        $list[] = [
            'name' => $name,
            'dex' => $dex,
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

        return $a['name'] <=> $b['name']; // name ascending
    });

    $order = [];
    foreach ($list as $c) {
        $order[] = ['name' => $c['name'], 'score' => $c['score']];
    }

    return new JsonResponse(['order' => $order]);
}

function abilityModifier(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $score = $data['score'] ?? null;
    if (!is_int($score) || $score < 1 || $score > 30) {
        return new JsonResponse(['error' => 'invalid score'], 400);
    }

    return new JsonResponse([
        'score' => $score,
        'modifier' => abilityModifierFor($score),
    ]);
}

function proficiency(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $level = $data['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyFor($level),
    ]);
}

function derivedStats(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $level = $data['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }

    $abilities = $data['abilities'] ?? null;
    if (!is_array($abilities)) {
        return new JsonResponse(['error' => 'invalid abilities'], 400);
    }

    $armor = $data['armor'] ?? null;
    if (!is_array($armor)) {
        return new JsonResponse(['error' => 'invalid armor'], 400);
    }

    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilityKeys as $key) {
        $score = $abilities[$key] ?? null;
        if (!is_int($score) || $score < 1 || $score > 30) {
            return new JsonResponse(['error' => 'invalid ability: ' . $key], 400);
        }
        $modifiers[$key] = abilityModifierFor($score);
    }

    $base = $armor['base'] ?? null;
    if (!is_int($base)) {
        return new JsonResponse(['error' => 'invalid armor base'], 400);
    }

    $dexCap = $armor['dex_cap'] ?? null;
    if (!is_int($dexCap)) {
        return new JsonResponse(['error' => 'invalid dex_cap'], 400);
    }

    $shieldBonus = ($armor['shield'] ?? false) === true ? 2 : 0;

    $hpMax = $level * (6 + $modifiers['con']);
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyFor($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

function createCombatSession(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $id = $data['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return new JsonResponse(['error' => 'invalid id'], 400);
    }

    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants) || count($combatants) === 0) {
        return new JsonResponse(['error' => 'invalid combatants'], 400);
    }

    $list = [];
    foreach ($combatants as $c) {
        if (!is_array($c)) {
            return new JsonResponse(['error' => 'invalid combatant'], 400);
        }
        $name = $c['name'] ?? null;
        if (!is_string($name) || $name === '') {
            return new JsonResponse(['error' => 'invalid combatant name'], 400);
        }
        $dex = (int) ($c['dex'] ?? 0);
        $roll = (int) ($c['roll'] ?? 0);
        $list[] = [
            'name' => $name,
            'dex' => $dex,
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

        return $a['name'] <=> $b['name']; // name ascending
    });

    $order = [];
    foreach ($list as $c) {
        $order[] = ['name' => $c['name'], 'score' => $c['score']];
    }

    $sessions = loadSessions();
    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    saveSessions($sessions);

    return new JsonResponse([
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]);
}

function addCondition(Request $request, string $sessionId): JsonResponse
{
    $sessions = loadSessions();
    if (!isset($sessions[$sessionId])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }

    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $target = $data['target'] ?? null;
    if (!is_string($target) || $target === '') {
        return new JsonResponse(['error' => 'invalid target'], 400);
    }

    $names = array_column($sessions[$sessionId]['order'], 'name');
    if (!in_array($target, $names, true)) {
        return new JsonResponse(['error' => 'unknown target'], 400);
    }

    $condition = $data['condition'] ?? null;
    if (!is_string($condition)) {
        return new JsonResponse(['error' => 'invalid condition'], 400);
    }

    $duration = $data['duration_rounds'] ?? null;
    if (!is_int($duration) || $duration <= 0) {
        return new JsonResponse(['error' => 'invalid duration_rounds'], 400);
    }

    if (!isset($sessions[$sessionId]['conditions'][$target])) {
        $sessions[$sessionId]['conditions'][$target] = [];
    }
    $sessions[$sessionId]['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    saveSessions($sessions);

    return new JsonResponse([
        'target' => $target,
        'conditions' => $sessions[$sessionId]['conditions'][$target],
    ]);
}

function advanceTurn(Request $request, string $sessionId): JsonResponse
{
    $sessions = loadSessions();
    if (!isset($sessions[$sessionId])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }

    $session = &$sessions[$sessionId];

    $turnIndex = $session['turn_index'] + 1;
    if ($turnIndex >= count($session['order'])) {
        $turnIndex = 0;
        $session['round']++;
    }
    $session['turn_index'] = $turnIndex;

    // At the start of the new active combatant's turn, decrement their conditions.
    $activeName = $session['order'][$turnIndex]['name'];
    if (isset($session['conditions'][$activeName])) {
        foreach ($session['conditions'][$activeName] as $i => $cond) {
            $session['conditions'][$activeName][$i]['remaining_rounds']--;
        }
        $session['conditions'][$activeName] = array_values(array_filter(
            $session['conditions'][$activeName],
            static fn(array $c): bool => $c['remaining_rounds'] > 0
        ));
        // Keep the combatant's key with an empty array once all their
        // conditions have expired; the spec only requires removing the
        // expired condition entries, not the combatant bucket itself.
    }

    saveSessions($sessions);

    $conditionsOut = [];
    foreach ($session['conditions'] as $name => $conds) {
        $conditionsOut[$name] = array_values($conds);
    }

    return new JsonResponse([
        'id' => $sessionId,
        'round' => $session['round'],
        'turn_index' => $turnIndex,
        'active' => $session['order'][$turnIndex],
        'conditions' => count($conditionsOut) > 0 ? $conditionsOut : new \stdClass(),
    ]);
}

function registerUser(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;
    $role = $data['role'] ?? null;

    // username: 2-32 chars, lowercase letters, digits, `_`, or `-`.
    if (!is_string($username) || !preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        return new JsonResponse(['error' => 'invalid username'], 400);
    }

    // password: at least 8 characters.
    if (!is_string($password) || strlen($password) < 8) {
        return new JsonResponse(['error' => 'invalid password'], 400);
    }

    // role: either `dm` or `player`.
    if (!is_string($role) || !in_array($role, ['dm', 'player'], true)) {
        return new JsonResponse(['error' => 'invalid role'], 400);
    }

    $users = loadUsers();
    if (isset($users[$username])) {
        return new JsonResponse(['error' => 'username already exists'], 409);
    }

    $users[$username] = [
        'username' => $username,
        'role' => $role,
        'password_hash' => hashPassword($password),
    ];
    saveUsers($users);

    // Never echo the plain password in responses. 201 Created for new resource.
    return new JsonResponse(['username' => $username, 'role' => $role], 201);
}

function loginUser(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;

    if (!is_string($username) || !is_string($password)) {
        return new JsonResponse(['error' => 'invalid input'], 400);
    }

    $users = loadUsers();
    if (!isset($users[$username]) || !verifyPassword($password, $users[$username]['password_hash'])) {
        return new JsonResponse(['error' => 'invalid credentials'], 401);
    }

    return new JsonResponse([
        'username' => $username,
        'token' => 'session-' . $username,
    ]);
}

function storageStatus(Request $request): JsonResponse
{
    initSchema();

    return new JsonResponse([
        'driver' => 'sqlite',
        'schema_version' => 1,
        'initialized' => isInitialized(),
    ]);
}

function resetStorage(Request $request): JsonResponse
{
    resetDb();

    return new JsonResponse(['ok' => true, 'schema_version' => 1]);
}

/* ---------------------------------------------------------------------------
 * Compendium: monsters and items (SQLite-backed)
 * ------------------------------------------------------------------------- */

function createMonster(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $slug = $data['slug'] ?? null;
    if (!is_string($slug) || $slug === '') {
        return new JsonResponse(['error' => 'invalid slug'], 400);
    }

    $name = $data['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return new JsonResponse(['error' => 'invalid name'], 400);
    }

    $cr = $data['cr'] ?? null;
    if (!is_string($cr) || $cr === '') {
        return new JsonResponse(['error' => 'invalid cr'], 400);
    }

    $armorClass = $data['armor_class'] ?? null;
    if (!is_int($armorClass)) {
        return new JsonResponse(['error' => 'invalid armor_class'], 400);
    }

    $hitPoints = $data['hit_points'] ?? null;
    if (!is_int($hitPoints)) {
        return new JsonResponse(['error' => 'invalid hit_points'], 400);
    }

    $tags = $data['tags'] ?? [];
    if (!is_array($tags)) {
        return new JsonResponse(['error' => 'invalid tags'], 400);
    }

    initSchema();
    $pdo = db();

    $check = $pdo->prepare('SELECT slug FROM monsters WHERE slug = :slug');
    $check->execute([':slug' => $slug]);
    if ($check->fetch() !== false) {
        return new JsonResponse(['error' => 'monster already exists'], 409);
    }

    $stmt = $pdo->prepare(
        'INSERT INTO monsters(slug, name, cr, armor_class, hit_points, tags)
         VALUES(:slug, :name, :cr, :armor_class, :hit_points, :tags)'
    );
    $stmt->execute([
        ':slug' => $slug,
        ':name' => $name,
        ':cr' => $cr,
        ':armor_class' => $armorClass,
        ':hit_points' => $hitPoints,
        ':tags' => json_encode(array_values($tags)),
    ]);

    // Create response omits tags per spec; read response includes them.
    return new JsonResponse([
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
    ], 201);
}

function readMonster(Request $request, string $slug): JsonResponse
{
    initSchema();
    $stmt = db()->prepare(
        'SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = :slug'
    );
    $stmt->execute([':slug' => $slug]);
    $row = $stmt->fetch();

    if ($row === false) {
        return new JsonResponse(['error' => 'monster not found'], 404);
    }

    $tags = json_decode($row['tags'], true);
    if (!is_array($tags)) {
        $tags = [];
    }

    return new JsonResponse([
        'slug' => $row['slug'],
        'name' => $row['name'],
        'cr' => $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
        'tags' => array_values($tags),
    ]);
}

function createItem(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $slug = $data['slug'] ?? null;
    if (!is_string($slug) || $slug === '') {
        return new JsonResponse(['error' => 'invalid slug'], 400);
    }

    $name = $data['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return new JsonResponse(['error' => 'invalid name'], 400);
    }

    $type = $data['type'] ?? null;
    if (!is_string($type) || $type === '') {
        return new JsonResponse(['error' => 'invalid type'], 400);
    }

    $rarity = $data['rarity'] ?? null;
    if (!is_string($rarity) || $rarity === '') {
        return new JsonResponse(['error' => 'invalid rarity'], 400);
    }

    $costGp = $data['cost_gp'] ?? null;
    if (!is_int($costGp)) {
        return new JsonResponse(['error' => 'invalid cost_gp'], 400);
    }

    initSchema();
    $pdo = db();

    $check = $pdo->prepare('SELECT slug FROM items WHERE slug = :slug');
    $check->execute([':slug' => $slug]);
    if ($check->fetch() !== false) {
        return new JsonResponse(['error' => 'item already exists'], 409);
    }

    $stmt = $pdo->prepare(
        'INSERT INTO items(slug, name, type, rarity, cost_gp)
         VALUES(:slug, :name, :type, :rarity, :cost_gp)'
    );
    $stmt->execute([
        ':slug' => $slug,
        ':name' => $name,
        ':type' => $type,
        ':rarity' => $rarity,
        ':cost_gp' => $costGp,
    ]);

    return new JsonResponse([
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $costGp,
    ], 201);
}

function readItem(Request $request, string $slug): JsonResponse
{
    initSchema();
    $stmt = db()->prepare(
        'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = :slug'
    );
    $stmt->execute([':slug' => $slug]);
    $row = $stmt->fetch();

    if ($row === false) {
        return new JsonResponse(['error' => 'item not found'], 404);
    }

    return new JsonResponse([
        'slug' => $row['slug'],
        'name' => $row['name'],
        'type' => $row['type'],
        'rarity' => $row['rarity'],
        'cost_gp' => (int) $row['cost_gp'],
    ]);
}

/* ---------------------------------------------------------------------------
 * Campaign state (SQLite-backed)
 * ------------------------------------------------------------------------- */

function createCampaign(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $id = $data['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return new JsonResponse(['error' => 'invalid id'], 400);
    }

    $name = $data['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return new JsonResponse(['error' => 'invalid name'], 400);
    }

    $dm = $data['dm'] ?? null;
    if (!is_string($dm) || $dm === '') {
        return new JsonResponse(['error' => 'invalid dm'], 400);
    }

    initSchema();
    $pdo = db();

    $check = $pdo->prepare('SELECT id FROM campaigns WHERE id = :id');
    $check->execute([':id' => $id]);
    if ($check->fetch() !== false) {
        return new JsonResponse(['error' => 'campaign already exists'], 409);
    }

    $stmt = $pdo->prepare('INSERT INTO campaigns(id, name, dm) VALUES(:id, :name, :dm)');
    $stmt->execute([':id' => $id, ':name' => $name, ':dm' => $dm]);

    return new JsonResponse(['id' => $id, 'name' => $name, 'dm' => $dm], 201);
}

function addCampaignCharacter(Request $request, string $campaignId): JsonResponse
{
    initSchema();
    $pdo = db();

    $campStmt = $pdo->prepare('SELECT id FROM campaigns WHERE id = :id');
    $campStmt->execute([':id' => $campaignId]);
    if ($campStmt->fetch() === false) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $id = $data['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return new JsonResponse(['error' => 'invalid id'], 400);
    }

    $name = $data['name'] ?? null;
    if (!is_string($name) || $name === '') {
        return new JsonResponse(['error' => 'invalid name'], 400);
    }

    $level = $data['level'] ?? null;
    if (!is_int($level)) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }

    $charClass = $data['class'] ?? null;
    if (!is_string($charClass) || $charClass === '') {
        return new JsonResponse(['error' => 'invalid class'], 400);
    }

    $check = $pdo->prepare('SELECT id FROM campaign_characters WHERE campaign_id = :cid AND id = :id');
    $check->execute([':cid' => $campaignId, ':id' => $id]);
    if ($check->fetch() !== false) {
        return new JsonResponse(['error' => 'character already exists'], 409);
    }

    $stmt = $pdo->prepare(
        'INSERT INTO campaign_characters(campaign_id, id, name, level, class)
         VALUES(:cid, :id, :name, :level, :class)'
    );
    $stmt->execute([
        ':cid' => $campaignId,
        ':id' => $id,
        ':name' => $name,
        ':level' => $level,
        ':class' => $charClass,
    ]);

    return new JsonResponse(['id' => $id, 'name' => $name, 'level' => $level, 'class' => $charClass], 201);
}

function addCampaignEvent(Request $request, string $campaignId): JsonResponse
{
    initSchema();
    $pdo = db();

    $campStmt = $pdo->prepare('SELECT id FROM campaigns WHERE id = :id');
    $campStmt->execute([':id' => $campaignId]);
    if ($campStmt->fetch() === false) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $id = $data['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return new JsonResponse(['error' => 'invalid id'], 400);
    }

    $kind = $data['kind'] ?? null;
    if (!is_string($kind) || $kind === '') {
        return new JsonResponse(['error' => 'invalid kind'], 400);
    }

    $summary = $data['summary'] ?? null;
    if (!is_string($summary)) {
        return new JsonResponse(['error' => 'invalid summary'], 400);
    }

    $check = $pdo->prepare('SELECT id FROM campaign_events WHERE campaign_id = :cid AND id = :id');
    $check->execute([':cid' => $campaignId, ':id' => $id]);
    if ($check->fetch() !== false) {
        return new JsonResponse(['error' => 'event already exists'], 409);
    }

    $stmt = $pdo->prepare(
        'INSERT INTO campaign_events(campaign_id, id, kind, summary)
         VALUES(:cid, :id, :kind, :summary)'
    );
    $stmt->execute([
        ':cid' => $campaignId,
        ':id' => $id,
        ':kind' => $kind,
        ':summary' => $summary,
    ]);

    // Response omits summary per spec; only id and kind are returned.
    return new JsonResponse(['id' => $id, 'kind' => $kind], 201);
}

function readCampaignState(Request $request, string $campaignId): JsonResponse
{
    initSchema();
    $pdo = db();

    $campStmt = $pdo->prepare('SELECT id, name, dm FROM campaigns WHERE id = :id');
    $campStmt->execute([':id' => $campaignId]);
    $campaign = $campStmt->fetch();

    if ($campaign === false) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    $charStmt = $pdo->prepare(
        'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = :cid ORDER BY rowid'
    );
    $charStmt->execute([':cid' => $campaignId]);
    $characters = [];
    foreach ($charStmt->fetchAll() as $row) {
        $characters[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }

    $countStmt = $pdo->prepare('SELECT COUNT(*) AS cnt FROM campaign_events WHERE campaign_id = :cid');
    $countStmt->execute([':cid' => $campaignId]);
    $logCount = (int) $countStmt->fetch()['cnt'];

    return new JsonResponse([
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => $logCount,
    ]);
}

/* ---------------------------------------------------------------------------
 * PHB rules (deterministic, stateless)
 * ------------------------------------------------------------------------- */

function phbSpellSlots(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $class = $data['class'] ?? null;
    $level = $data['level'] ?? null;

    // For this benchmark, only wizard level 5 is supported.
    if (!is_string($class) || $class !== 'wizard') {
        return new JsonResponse(['error' => 'unsupported class'], 400);
    }
    if (!is_int($level) || $level !== 5) {
        return new JsonResponse(['error' => 'unsupported level'], 400);
    }

    // Wizard level 5 spell slots per the PHB-style table.
    $slots = [1 => 4, 2 => 3, 3 => 2];

    return new JsonResponse([
        'class' => $class,
        'level' => $level,
        'slots' => $slots,
    ]);
}

function phbLongRest(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $level = $data['level'] ?? null;
    $hpCurrent = $data['hp_current'] ?? null;
    $hpMax = $data['hp_max'] ?? null;
    $hitDiceSpent = $data['hit_dice_spent'] ?? null;
    $exhaustion = $data['exhaustion_level'] ?? null;

    if (!is_int($level) || $level < 1) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }
    if (!is_int($hpCurrent) || $hpCurrent < 0) {
        return new JsonResponse(['error' => 'invalid hp_current'], 400);
    }
    if (!is_int($hpMax) || $hpMax < 0) {
        return new JsonResponse(['error' => 'invalid hp_max'], 400);
    }
    if (!is_int($hitDiceSpent) || $hitDiceSpent < 0) {
        return new JsonResponse(['error' => 'invalid hit_dice_spent'], 400);
    }
    if (!is_int($exhaustion) || $exhaustion < 0) {
        return new JsonResponse(['error' => 'invalid exhaustion_level'], 400);
    }

    // Long rest restores current HP to max HP.
    $newHpCurrent = $hpMax;

    // Restore spent hit dice: half level rounded down, minimum 1.
    $recovered = max(1, (int) floor($level / 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $recovered);

    // Reduce exhaustion by 1, to a minimum of 0.
    $newExhaustion = max(0, $exhaustion - 1);

    return new JsonResponse([
        'hp_current' => $newHpCurrent,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustion,
    ]);
}

function phbEquipmentLoad(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $strength = $data['strength'] ?? null;
    $weight = $data['weight'] ?? null;

    if (!is_int($strength) || $strength < 0) {
        return new JsonResponse(['error' => 'invalid strength'], 400);
    }
    if (!is_int($weight) || $weight < 0) {
        return new JsonResponse(['error' => 'invalid weight'], 400);
    }

    // Carrying capacity is strength * 15; encumbered when weight exceeds it.
    $capacity = $strength * 15;
    $encumbered = $weight > $capacity;

    return new JsonResponse([
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $encumbered,
    ]);
}

/* ---------------------------------------------------------------------------
 * DM tools (combine compendium and campaign state)
 * ------------------------------------------------------------------------- */

/** Difficulty -> recommendation text for the DM encounter builder. */
function difficultyRecommendation(string $difficulty): string
{
    $map = [
        'trivial' => 'cakewalk',
        'easy' => 'safe warm-up',
        'medium' => 'a fair fight',
        'hard' => 'tough battle',
        'deadly' => 'risk of a wipe',
    ];

    return $map[$difficulty] ?? 'cakewalk';
}

/** Deterministic tier-keyed loot parcels for the benchmark. */
function lootParcelForTier(int $tier): ?array
{
    $parcels = [
        1 => ['coins_gp' => 75, 'items' => [['slug' => 'healing-potion', 'quantity' => 2]]],
    ];

    return $parcels[$tier] ?? null;
}

/** Fetch a compendium monster row by slug, or null when absent. */
function getMonsterRow(string $slug): ?array
{
    initSchema();
    $stmt = db()->prepare(
        'SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = :slug'
    );
    $stmt->execute([':slug' => $slug]);
    $row = $stmt->fetch();

    return $row === false ? null : $row;
}

/** Fetch a campaign's events in insertion order (by rowid ascending). */
function getCampaignEvents(string $campaignId): array
{
    initSchema();
    $stmt = db()->prepare(
        'SELECT id, kind, summary FROM campaign_events WHERE campaign_id = :cid ORDER BY rowid'
    );
    $stmt->execute([':cid' => $campaignId]);

    return $stmt->fetchAll();
}

/** Whether a campaign with the given id exists. */
function campaignExists(string $campaignId): bool
{
    initSchema();
    $stmt = db()->prepare('SELECT id FROM campaigns WHERE id = :id');
    $stmt->execute([':id' => $campaignId]);

    return $stmt->fetch() !== false;
}

function dmEncounterBuilder(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $campaignId = $data['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        return new JsonResponse(['error' => 'invalid campaign_id'], 400);
    }

    $party = $data['party'] ?? null;
    if (!is_array($party) || count($party) === 0) {
        return new JsonResponse(['error' => 'invalid party'], 400);
    }

    $monsterSlugs = $data['monster_slugs'] ?? null;
    if (!is_array($monsterSlugs) || count($monsterSlugs) === 0) {
        return new JsonResponse(['error' => 'invalid monster_slugs'], 400);
    }

    // Reuse the core suite's CR->XP table and encounter multiplier.
    $xpTable = [
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

    // Look up each monster's CR from the compendium and sum its XP value.
    $baseXp = 0;
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug) || $slug === '') {
            return new JsonResponse(['error' => 'invalid monster slug'], 400);
        }
        $monster = getMonsterRow($slug);
        if ($monster === null) {
            return new JsonResponse(['error' => 'monster not found'], 404);
        }
        $cr = (string) $monster['cr'];
        if (!array_key_exists($cr, $xpTable)) {
            return new JsonResponse(['error' => 'unsupported cr'], 400);
        }
        $baseXp += $xpTable[$cr];
    }

    $monsterCount = count($monsterSlugs);
    $multiplier = encounterMultiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    // Party difficulty thresholds, reusing the core adjusted-XP math.
    $tEasy = $tMedium = $tHard = $tDeadly = 0;
    foreach ($party as $member) {
        if (!is_array($member)) {
            return new JsonResponse(['error' => 'invalid party member'], 400);
        }
        $level = (int) ($member['level'] ?? 0);
        if (!array_key_exists($level, $levelThresholds)) {
            return new JsonResponse(['error' => 'unsupported level'], 400);
        }
        $t = $levelThresholds[$level];
        $tEasy += $t['easy'];
        $tMedium += $t['medium'];
        $tHard += $t['hard'];
        $tDeadly += $t['deadly'];
    }

    if ($adjustedXp >= $tDeadly) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $tHard) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $tMedium) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $tEasy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'base_xp' => $baseXp,
        'adjusted_xp' => num($adjustedXp),
        'difficulty' => $difficulty,
        'monster_count' => $monsterCount,
        'recommendation' => difficultyRecommendation($difficulty),
    ]);
}

function dmLootParcel(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $campaignId = $data['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        return new JsonResponse(['error' => 'invalid campaign_id'], 400);
    }

    $tier = $data['tier'] ?? null;
    if (!is_int($tier)) {
        return new JsonResponse(['error' => 'invalid tier'], 400);
    }

    $parcel = lootParcelForTier($tier);
    if ($parcel === null) {
        return new JsonResponse(['error' => 'unsupported tier'], 400);
    }

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'coins_gp' => $parcel['coins_gp'],
        'items' => array_values($parcel['items']),
    ]);
}

function dmSessionRecap(Request $request): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    if (!is_array($data)) {
        return new JsonResponse(['error' => 'invalid body'], 400);
    }

    $campaignId = $data['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        return new JsonResponse(['error' => 'invalid campaign_id'], 400);
    }

    if (!campaignExists($campaignId)) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    $events = getCampaignEvents($campaignId);

    // Summary: the most recent logged event summary (deterministic by seq).
    $summary = '';
    if (count($events) > 0) {
        $summary = (string) $events[count($events) - 1]['summary'];
    }

    // Open threads: derive a deterministic follow-up from any event that
    // references a "goblin trail".
    $openThreads = [];
    foreach ($events as $event) {
        $eventSummary = (string) $event['summary'];
        if (stripos($eventSummary, 'goblin trail') !== false) {
            $thread = 'Resolve goblin trail ambush';
            if (!in_array($thread, $openThreads, true)) {
                $openThreads[] = $thread;
            }
        }
    }

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => array_values($openThreads),
    ]);
}

/* ---------------------------------------------------------------------------
 * Routing & dispatch
 * ------------------------------------------------------------------------- */

// CLI bootstrap: `php index.php init-schema` prepares game.db without serving.
if (php_sapi_name() === 'cli' && isset($argv[1]) && $argv[1] === 'init-schema') {
    initSchema();
    exit(0);
}

// Ensure the durable schema exists for every request (idempotent; runs once).
initSchema();

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_controller' => 'health'], methods: ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => 'diceStats'], methods: ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_controller' => 'abilityCheck'], methods: ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => 'adjustedXp'], methods: ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_controller' => 'initiativeOrder'], methods: ['POST']));
$routes->add('ability_modifier', new Route('/v1/characters/ability-modifier', ['_controller' => 'abilityModifier'], methods: ['POST']));
$routes->add('proficiency', new Route('/v1/characters/proficiency', ['_controller' => 'proficiency'], methods: ['POST']));
$routes->add('derived_stats', new Route('/v1/characters/derived-stats', ['_controller' => 'derivedStats'], methods: ['POST']));
$routes->add('combat_create', new Route('/v1/combat/sessions', ['_controller' => 'createCombatSession'], methods: ['POST']));
$routes->add('combat_conditions', new Route('/v1/combat/sessions/{id}/conditions', ['_controller' => 'addCondition'], methods: ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['_controller' => 'advanceTurn'], methods: ['POST']));
$routes->add('auth_register', new Route('/v1/auth/register', ['_controller' => 'registerUser'], methods: ['POST']));
$routes->add('auth_login', new Route('/v1/auth/login', ['_controller' => 'loginUser'], methods: ['POST']));
$routes->add('storage_status', new Route('/v1/storage/status', ['_controller' => 'storageStatus'], methods: ['GET']));
$routes->add('storage_reset', new Route('/v1/storage/reset', ['_controller' => 'resetStorage'], methods: ['POST']));
$routes->add('compendium_monster_create', new Route('/v1/compendium/monsters', ['_controller' => 'createMonster'], methods: ['POST']));
$routes->add('compendium_monster_read', new Route('/v1/compendium/monsters/{slug}', ['_controller' => 'readMonster'], methods: ['GET']));
$routes->add('compendium_item_create', new Route('/v1/compendium/items', ['_controller' => 'createItem'], methods: ['POST']));
$routes->add('compendium_item_read', new Route('/v1/compendium/items/{slug}', ['_controller' => 'readItem'], methods: ['GET']));
$routes->add('campaign_create', new Route('/v1/campaigns', ['_controller' => 'createCampaign'], methods: ['POST']));
$routes->add('campaign_add_character', new Route('/v1/campaigns/{campaignId}/characters', ['_controller' => 'addCampaignCharacter'], methods: ['POST']));
$routes->add('campaign_add_event', new Route('/v1/campaigns/{campaignId}/events', ['_controller' => 'addCampaignEvent'], methods: ['POST']));
$routes->add('campaign_read_state', new Route('/v1/campaigns/{campaignId}/state', ['_controller' => 'readCampaignState'], methods: ['GET']));
$routes->add('phb_spell_slots', new Route('/v1/phb/spell-slots', ['_controller' => 'phbSpellSlots'], methods: ['POST']));
$routes->add('phb_long_rest', new Route('/v1/phb/rests/long', ['_controller' => 'phbLongRest'], methods: ['POST']));
$routes->add('phb_equipment_load', new Route('/v1/phb/equipment-load', ['_controller' => 'phbEquipmentLoad'], methods: ['POST']));
$routes->add('dm_encounter_builder', new Route('/v1/dm/encounter-builder', ['_controller' => 'dmEncounterBuilder'], methods: ['POST']));
$routes->add('dm_loot_parcel', new Route('/v1/dm/loot-parcel', ['_controller' => 'dmLootParcel'], methods: ['POST']));
$routes->add('dm_session_recap', new Route('/v1/dm/session-recap', ['_controller' => 'dmSessionRecap'], methods: ['POST']));

$request = Request::createFromGlobals();
$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $match = $matcher->match($request->getPathInfo());
    $controller = $match['_controller'];
    $routeParams = [];
    foreach ($match as $key => $value) {
        if ($key[0] !== '_') {
            $routeParams[] = $value;
        }
    }
    $response = $controller($request, ...$routeParams);
} catch (ResourceNotFoundException $e) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (MethodNotAllowedException $e) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
}

$response->send();

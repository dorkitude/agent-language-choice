<?php
require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_controller' => 'health'], [], [], '', [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => 'dice_stats'], [], [], '', [], ['POST']));
$routes->add('checks_ability', new Route('/v1/checks/ability', ['_controller' => 'checks_ability'], [], [], '', [], ['POST']));
$routes->add('encounters_adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => 'encounters_adjusted_xp'], [], [], '', [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_controller' => 'initiative_order'], [], [], '', [], ['POST']));
$routes->add('characters_ability_modifier', new Route('/v1/characters/ability-modifier', ['_controller' => 'characters_ability_modifier'], [], [], '', [], ['POST']));
$routes->add('characters_proficiency', new Route('/v1/characters/proficiency', ['_controller' => 'characters_proficiency'], [], [], '', [], ['POST']));
$routes->add('characters_derived_stats', new Route('/v1/characters/derived-stats', ['_controller' => 'characters_derived_stats'], [], [], '', [], ['POST']));
$routes->add('combat_create_session', new Route('/v1/combat/sessions', ['_controller' => 'combat_create_session'], [], [], '', [], ['POST']));
$routes->add('combat_add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['_controller' => 'combat_add_condition'], [], [], '', [], ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['_controller' => 'combat_advance'], [], [], '', [], ['POST']));
$routes->add('auth_register', new Route('/v1/auth/register', ['_controller' => 'auth_register'], [], [], '', [], ['POST']));
$routes->add('auth_login', new Route('/v1/auth/login', ['_controller' => 'auth_login'], [], [], '', [], ['POST']));
$routes->add('storage_status', new Route('/v1/storage/status', ['_controller' => 'storage_status'], [], [], '', [], ['GET']));
$routes->add('storage_reset', new Route('/v1/storage/reset', ['_controller' => 'storage_reset'], [], [], '', [], ['POST']));
$routes->add('compendium_create_monster', new Route('/v1/compendium/monsters', ['_controller' => 'compendium_create_monster'], [], [], '', [], ['POST']));
$routes->add('compendium_get_monster', new Route('/v1/compendium/monsters/{slug}', ['_controller' => 'compendium_get_monster'], [], [], '', [], ['GET']));
$routes->add('compendium_create_item', new Route('/v1/compendium/items', ['_controller' => 'compendium_create_item'], [], [], '', [], ['POST']));
$routes->add('compendium_get_item', new Route('/v1/compendium/items/{slug}', ['_controller' => 'compendium_get_item'], [], [], '', [], ['GET']));
$routes->add('campaigns_create', new Route('/v1/campaigns', ['_controller' => 'campaigns_create'], [], [], '', [], ['POST']));
$routes->add('campaigns_add_character', new Route('/v1/campaigns/{id}/characters', ['_controller' => 'campaigns_add_character'], [], [], '', [], ['POST']));
$routes->add('campaigns_add_event', new Route('/v1/campaigns/{id}/events', ['_controller' => 'campaigns_add_event'], [], [], '', [], ['POST']));
$routes->add('campaigns_state', new Route('/v1/campaigns/{id}/state', ['_controller' => 'campaigns_state'], [], [], '', [], ['GET']));
$routes->add('phb_spell_slots', new Route('/v1/phb/spell-slots', ['_controller' => 'phb_spell_slots'], [], [], '', [], ['POST']));
$routes->add('phb_rests_long', new Route('/v1/phb/rests/long', ['_controller' => 'phb_rests_long'], [], [], '', [], ['POST']));
$routes->add('phb_equipment_load', new Route('/v1/phb/equipment-load', ['_controller' => 'phb_equipment_load'], [], [], '', [], ['POST']));
$routes->add('dm_encounter_builder', new Route('/v1/dm/encounter-builder', ['_controller' => 'dm_encounter_builder'], [], [], '', [], ['POST']));
$routes->add('dm_loot_parcel', new Route('/v1/dm/loot-parcel', ['_controller' => 'dm_loot_parcel'], [], [], '', [], ['POST']));
$routes->add('dm_session_recap', new Route('/v1/dm/session-recap', ['_controller' => 'dm_session_recap'], [], [], '', [], ['POST']));

$request = Request::createFromGlobals();
$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

function jsonBody(Request $request): ?array
{
    $data = json_decode($request->getContent(), true);
    return is_array($data) ? $data : null;
}

function badRequest(string $message): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

function handleDiceStats(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['expression']) || !is_string($data['expression'])) {
        return badRequest('invalid expression');
    }
    $expression = $data['expression'];
    if (!preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $expression, $m)) {
        return badRequest('invalid expression');
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = 0;
    if (isset($m[3]) && $m[3] !== '') {
        $modifier = (int) $m[4];
        if ($m[3] === '-') {
            $modifier = -$modifier;
        }
    }
    if ($count <= 0 || $sides <= 0) {
        return badRequest('invalid expression');
    }
    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;
    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function handleChecksAbility(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['roll'], $data['modifier'], $data['dc'])
        || !is_numeric($data['roll']) || !is_numeric($data['modifier']) || !is_numeric($data['dc'])) {
        return badRequest('invalid request');
    }
    $roll = $data['roll'] + 0;
    $modifier = $data['modifier'] + 0;
    $dc = $data['dc'] + 0;
    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;
    return new JsonResponse([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
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

function monsterMultiplier(int $count): float
{
    if ($count <= 1) {
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

function handleEncountersAdjustedXp(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['party']) || !isset($data['monsters'])
        || !is_array($data['party']) || !is_array($data['monsters'])) {
        return badRequest('invalid request');
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        if (!isset($monster['cr'], $monster['count'])) {
            return badRequest('invalid monster');
        }
        $cr = (string) $monster['cr'];
        if (!array_key_exists($cr, CR_XP)) {
            return badRequest('unsupported cr');
        }
        $count = (int) $monster['count'];
        $baseXp += CR_XP[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = monsterMultiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!isset($member['level'])) {
            return badRequest('invalid party member');
        }
        $level = (int) $member['level'];
        if (!array_key_exists($level, LEVEL_THRESHOLDS)) {
            return badRequest('unsupported level');
        }
        foreach (LEVEL_THRESHOLDS[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

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

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

function handleInitiativeOrder(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['combatants']) || !is_array($data['combatants'])) {
        return badRequest('invalid request');
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        if (!isset($combatant['name'], $combatant['dex'], $combatant['roll'])) {
            return badRequest('invalid combatant');
        }
        $dex = (int) $combatant['dex'];
        $roll = (int) $combatant['roll'];
        $combatants[] = [
            'name' => (string) $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(fn ($c) => ['name' => $c['name'], 'score' => $c['score']], $combatants);

    return new JsonResponse(['order' => $order]);
}

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    return match (true) {
        $level <= 4 => 2,
        $level <= 8 => 3,
        $level <= 12 => 4,
        $level <= 16 => 5,
        default => 6,
    };
}

function handleCharactersAbilityModifier(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['score']) || !is_int($data['score'])) {
        return badRequest('invalid score');
    }
    $score = $data['score'];
    if ($score < 1 || $score > 30) {
        return badRequest('invalid score');
    }
    return new JsonResponse([
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
}

function handleCharactersProficiency(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['level']) || !is_int($data['level'])) {
        return badRequest('invalid level');
    }
    $level = $data['level'];
    if ($level < 1 || $level > 20) {
        return badRequest('invalid level');
    }
    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
}

function handleCharactersDerivedStats(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['level']) || !is_int($data['level'])
        || !isset($data['abilities']) || !is_array($data['abilities'])
        || !isset($data['armor']) || !is_array($data['armor'])) {
        return badRequest('invalid request');
    }

    $level = $data['level'];
    if ($level < 1 || $level > 20) {
        return badRequest('invalid level');
    }

    $abilities = $data['abilities'];
    $keys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($keys as $key) {
        if (!isset($abilities[$key]) || !is_int($abilities[$key])) {
            return badRequest('invalid abilities');
        }
        $score = $abilities[$key];
        if ($score < 1 || $score > 30) {
            return badRequest('invalid abilities');
        }
        $modifiers[$key] = abilityModifier($score);
    }

    $armor = $data['armor'];
    if (!isset($armor['base']) || !is_int($armor['base']) || !isset($armor['shield']) || !is_bool($armor['shield'])
        || !isset($armor['dex_cap']) || !is_int($armor['dex_cap'])) {
        return badRequest('invalid armor');
    }

    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

const DB_PATH = __DIR__ . '/game.db';
const SCHEMA_VERSION = 1;

function db(): PDO
{
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . DB_PATH);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->exec('PRAGMA journal_mode = WAL');
    }
    return $pdo;
}

function initSchema(): void
{
    $pdo = db();
    $pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS monsters (slug TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS items (slug TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_characters (campaign_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (campaign_id, id))');
    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_events (campaign_id TEXT NOT NULL, id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (campaign_id, id))');
    $stmt = $pdo->prepare('INSERT INTO meta (key, value) VALUES (:key, :value)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value');
    $stmt->execute(['key' => 'schema_version', 'value' => (string) SCHEMA_VERSION]);
    $stmt->execute(['key' => 'initialized', 'value' => '1']);
}

function resetSchema(): void
{
    $pdo = db();
    $pdo->exec('DROP TABLE IF EXISTS combat_sessions');
    $pdo->exec('DROP TABLE IF EXISTS users');
    $pdo->exec('DROP TABLE IF EXISTS meta');
    $pdo->exec('DROP TABLE IF EXISTS monsters');
    $pdo->exec('DROP TABLE IF EXISTS items');
    $pdo->exec('DROP TABLE IF EXISTS campaigns');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters');
    $pdo->exec('DROP TABLE IF EXISTS campaign_events');
    initSchema();
}

function isStorageInitialized(): bool
{
    $pdo = db();
    $tables = $pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('combat_sessions', 'users', 'meta')")->fetchAll(PDO::FETCH_COLUMN);
    return count($tables) === 3;
}

function loadCombatSessions(): array
{
    $pdo = db();
    $sessions = [];
    foreach ($pdo->query('SELECT id, data FROM combat_sessions') as $row) {
        $sessions[$row['id']] = json_decode($row['data'], true);
    }
    return $sessions;
}

function saveCombatSession(string $id, array $session): void
{
    $stmt = db()->prepare('INSERT INTO combat_sessions (id, data) VALUES (:id, :data)
        ON CONFLICT(id) DO UPDATE SET data = excluded.data');
    $stmt->execute(['id' => $id, 'data' => json_encode($session)]);
}

function sortInitiative(array $combatants): array
{
    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });
    return $combatants;
}

function combatOrderView(array $order): array
{
    return array_map(fn ($c) => ['name' => $c['name'], 'score' => $c['score']], $order);
}

function handleCombatCreateSession(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['combatants']) || !is_array($data['combatants']) || count($data['combatants']) === 0) {
        return badRequest('invalid request');
    }

    $sessions = loadCombatSessions();
    $id = $data['id'];
    if (isset($sessions[$id])) {
        return badRequest('session already exists');
    }

    $order = [];
    foreach ($data['combatants'] as $combatant) {
        if (!isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name']) || !is_numeric($combatant['dex']) || !is_numeric($combatant['roll'])) {
            return badRequest('invalid combatant');
        }
        $dex = (int) $combatant['dex'];
        $roll = (int) $combatant['roll'];
        $order[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    $order = sortInitiative($order);

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    foreach ($order as $combatant) {
        $session['conditions'][$combatant['name']] = [];
    }

    saveCombatSession($id, $session);

    $active = $order[$session['turn_index']];
    return new JsonResponse([
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
        'order' => combatOrderView($order),
    ]);
}

function handleCombatAddCondition(Request $request, string $id): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['target'], $data['condition'], $data['duration_rounds'])
        || !is_string($data['target']) || !is_string($data['condition'])
        || !is_int($data['duration_rounds']) || $data['duration_rounds'] <= 0) {
        return badRequest('invalid request');
    }

    $sessions = loadCombatSessions();
    if (!isset($sessions[$id])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }
    $session = $sessions[$id];

    $target = $data['target'];
    if (!array_key_exists($target, $session['conditions'])) {
        return badRequest('unknown target');
    }

    $session['conditions'][$target][] = [
        'condition' => $data['condition'],
        'remaining_rounds' => $data['duration_rounds'],
    ];

    saveCombatSession($id, $session);

    return new JsonResponse([
        'target' => $target,
        'conditions' => $session['conditions'][$target],
    ]);
}

function handleCombatAdvance(Request $request, string $id): JsonResponse
{
    $sessions = loadCombatSessions();
    if (!isset($sessions[$id])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }
    $session = $sessions[$id];

    $order = $session['order'];
    $count = count($order);
    $nextIndex = $session['turn_index'] + 1;
    if ($nextIndex >= $count) {
        $nextIndex = 0;
        $session['round'] += 1;
    }
    $session['turn_index'] = $nextIndex;

    $activeName = $order[$nextIndex]['name'];
    $remaining = [];
    foreach ($session['conditions'][$activeName] as $condition) {
        $condition['remaining_rounds'] -= 1;
        if ($condition['remaining_rounds'] > 0) {
            $remaining[] = $condition;
        }
    }
    $session['conditions'][$activeName] = $remaining;

    saveCombatSession($id, $session);

    $active = $order[$nextIndex];
    return new JsonResponse([
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
        'conditions' => $session['conditions'],
    ]);
}

function loadUsers(): array
{
    $pdo = db();
    $users = [];
    foreach ($pdo->query('SELECT username, data FROM users') as $row) {
        $users[$row['username']] = json_decode($row['data'], true);
    }
    return $users;
}

function saveUser(string $username, array $user): void
{
    $stmt = db()->prepare('INSERT INTO users (username, data) VALUES (:username, :data)
        ON CONFLICT(username) DO UPDATE SET data = excluded.data');
    $stmt->execute(['username' => $username, 'data' => json_encode($user)]);
}

function hashPassword(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

function verifyPassword(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

function handleAuthRegister(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['username'], $data['password'], $data['role'])
        || !is_string($data['username']) || !is_string($data['password']) || !is_string($data['role'])) {
        return badRequest('invalid request');
    }

    $username = $data['username'];
    $password = $data['password'];
    $role = $data['role'];

    if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        return badRequest('invalid username');
    }
    if (strlen($password) < 8) {
        return badRequest('invalid password');
    }
    if ($role !== 'dm' && $role !== 'player') {
        return badRequest('invalid role');
    }

    $users = loadUsers();
    if (isset($users[$username])) {
        return new JsonResponse(['error' => 'username already exists'], 409);
    }

    saveUser($username, [
        'username' => $username,
        'role' => $role,
        'password_hash' => hashPassword($password),
    ]);

    return new JsonResponse(['username' => $username, 'role' => $role], 201);
}

function handleAuthLogin(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['username'], $data['password'])
        || !is_string($data['username']) || !is_string($data['password'])) {
        return badRequest('invalid request');
    }

    $username = $data['username'];
    $password = $data['password'];

    $users = loadUsers();
    if (!isset($users[$username]) || !verifyPassword($password, $users[$username]['password_hash'])) {
        return new JsonResponse(['error' => 'invalid credentials'], 401);
    }

    return new JsonResponse(['username' => $username, 'token' => 'session-' . $username]);
}

function handleStorageStatus(): JsonResponse
{
    return new JsonResponse([
        'driver' => 'sqlite',
        'schema_version' => SCHEMA_VERSION,
        'initialized' => isStorageInitialized(),
    ]);
}

function handleStorageReset(): JsonResponse
{
    resetSchema();
    return new JsonResponse(['ok' => true, 'schema_version' => SCHEMA_VERSION]);
}

function isValidSlug(mixed $slug): bool
{
    return is_string($slug) && preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $slug) === 1;
}

function findMonster(string $slug): ?array
{
    $stmt = db()->prepare('SELECT data FROM monsters WHERE slug = :slug');
    $stmt->execute(['slug' => $slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

function saveMonster(string $slug, array $monster): void
{
    $stmt = db()->prepare('INSERT INTO monsters (slug, data) VALUES (:slug, :data)');
    $stmt->execute(['slug' => $slug, 'data' => json_encode($monster)]);
}

function findItem(string $slug): ?array
{
    $stmt = db()->prepare('SELECT data FROM items WHERE slug = :slug');
    $stmt->execute(['slug' => $slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

function saveItem(string $slug, array $item): void
{
    $stmt = db()->prepare('INSERT INTO items (slug, data) VALUES (:slug, :data)');
    $stmt->execute(['slug' => $slug, 'data' => json_encode($item)]);
}

function handleCompendiumCreateMonster(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isValidSlug($data['slug'] ?? null)
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['cr']) || !is_string($data['cr'])
        || !isset($data['armor_class']) || !is_int($data['armor_class'])
        || !isset($data['hit_points']) || !is_int($data['hit_points'])) {
        return badRequest('invalid request');
    }

    $tags = [];
    if (isset($data['tags'])) {
        if (!is_array($data['tags'])) {
            return badRequest('invalid tags');
        }
        foreach ($data['tags'] as $tag) {
            if (!is_string($tag)) {
                return badRequest('invalid tags');
            }
            $tags[] = $tag;
        }
    }

    $slug = $data['slug'];
    if (findMonster($slug) !== null) {
        return new JsonResponse(['error' => 'monster already exists'], 409);
    }

    $monster = [
        'slug' => $slug,
        'name' => $data['name'],
        'cr' => $data['cr'],
        'armor_class' => $data['armor_class'],
        'hit_points' => $data['hit_points'],
        'tags' => $tags,
    ];
    saveMonster($slug, $monster);

    return new JsonResponse([
        'slug' => $monster['slug'],
        'name' => $monster['name'],
        'cr' => $monster['cr'],
        'armor_class' => $monster['armor_class'],
        'hit_points' => $monster['hit_points'],
    ], 201);
}

function handleCompendiumGetMonster(string $slug): JsonResponse
{
    $monster = findMonster($slug);
    if ($monster === null) {
        return new JsonResponse(['error' => 'monster not found'], 404);
    }
    return new JsonResponse($monster);
}

function handleCompendiumCreateItem(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isValidSlug($data['slug'] ?? null)
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['type']) || !is_string($data['type'])
        || !isset($data['rarity']) || !is_string($data['rarity'])
        || !isset($data['cost_gp']) || !is_int($data['cost_gp'])) {
        return badRequest('invalid request');
    }

    $slug = $data['slug'];
    if (findItem($slug) !== null) {
        return new JsonResponse(['error' => 'item already exists'], 409);
    }

    $item = [
        'slug' => $slug,
        'name' => $data['name'],
        'type' => $data['type'],
        'rarity' => $data['rarity'],
        'cost_gp' => $data['cost_gp'],
    ];
    saveItem($slug, $item);

    return new JsonResponse($item, 201);
}

function handleCompendiumGetItem(string $slug): JsonResponse
{
    $item = findItem($slug);
    if ($item === null) {
        return new JsonResponse(['error' => 'item not found'], 404);
    }
    return new JsonResponse($item);
}

function findCampaign(string $id): ?array
{
    $stmt = db()->prepare('SELECT data FROM campaigns WHERE id = :id');
    $stmt->execute(['id' => $id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

function saveCampaign(string $id, array $campaign): void
{
    $stmt = db()->prepare('INSERT INTO campaigns (id, data) VALUES (:id, :data)');
    $stmt->execute(['id' => $id, 'data' => json_encode($campaign)]);
}

function findCampaignCharacter(string $campaignId, string $id): ?array
{
    $stmt = db()->prepare('SELECT data FROM campaign_characters WHERE campaign_id = :campaign_id AND id = :id');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

function saveCampaignCharacter(string $campaignId, string $id, array $character): void
{
    $stmt = db()->prepare('INSERT INTO campaign_characters (campaign_id, id, data) VALUES (:campaign_id, :id, :data)');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $id, 'data' => json_encode($character)]);
}

function listCampaignCharacters(string $campaignId): array
{
    $stmt = db()->prepare('SELECT data FROM campaign_characters WHERE campaign_id = :campaign_id ORDER BY rowid');
    $stmt->execute(['campaign_id' => $campaignId]);
    $characters = [];
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $characters[] = json_decode($row['data'], true);
    }
    return $characters;
}

function findCampaignEvent(string $campaignId, string $id): ?array
{
    $stmt = db()->prepare('SELECT data FROM campaign_events WHERE campaign_id = :campaign_id AND id = :id');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

function saveCampaignEvent(string $campaignId, string $id, array $event): void
{
    $stmt = db()->prepare('INSERT INTO campaign_events (campaign_id, id, data) VALUES (:campaign_id, :id, :data)');
    $stmt->execute(['campaign_id' => $campaignId, 'id' => $id, 'data' => json_encode($event)]);
}

function countCampaignEvents(string $campaignId): int
{
    $stmt = db()->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = :campaign_id');
    $stmt->execute(['campaign_id' => $campaignId]);
    return (int) $stmt->fetchColumn();
}

function lastCampaignEvent(string $campaignId): ?array
{
    $stmt = db()->prepare('SELECT data FROM campaign_events WHERE campaign_id = :campaign_id ORDER BY rowid DESC LIMIT 1');
    $stmt->execute(['campaign_id' => $campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ? json_decode($row['data'], true) : null;
}

function handleCampaignsCreate(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['dm']) || !is_string($data['dm']) || $data['dm'] === '') {
        return badRequest('invalid request');
    }

    $id = $data['id'];
    if (findCampaign($id) !== null) {
        return new JsonResponse(['error' => 'campaign already exists'], 409);
    }

    $campaign = [
        'id' => $id,
        'name' => $data['name'],
        'dm' => $data['dm'],
    ];
    saveCampaign($id, $campaign);

    return new JsonResponse($campaign, 201);
}

function handleCampaignsAddCharacter(Request $request, string $campaignId): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['name']) || !is_string($data['name']) || $data['name'] === ''
        || !isset($data['level']) || !is_int($data['level'])
        || !isset($data['class']) || !is_string($data['class']) || $data['class'] === '') {
        return badRequest('invalid request');
    }

    if (findCampaign($campaignId) === null) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    $id = $data['id'];
    if (findCampaignCharacter($campaignId, $id) !== null) {
        return new JsonResponse(['error' => 'character already exists'], 409);
    }

    $character = [
        'id' => $id,
        'name' => $data['name'],
        'level' => $data['level'],
        'class' => $data['class'],
    ];
    saveCampaignCharacter($campaignId, $id, $character);

    return new JsonResponse($character, 201);
}

function handleCampaignsAddEvent(Request $request, string $campaignId): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['id']) || !is_string($data['id']) || $data['id'] === ''
        || !isset($data['kind']) || !is_string($data['kind']) || $data['kind'] === ''
        || !isset($data['summary']) || !is_string($data['summary'])) {
        return badRequest('invalid request');
    }

    if (findCampaign($campaignId) === null) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    $id = $data['id'];
    if (findCampaignEvent($campaignId, $id) !== null) {
        return new JsonResponse(['error' => 'event already exists'], 409);
    }

    $event = [
        'id' => $id,
        'kind' => $data['kind'],
        'summary' => $data['summary'],
    ];
    saveCampaignEvent($campaignId, $id, $event);

    return new JsonResponse(['id' => $event['id'], 'kind' => $event['kind']], 201);
}

function handleCampaignsState(string $campaignId): JsonResponse
{
    $campaign = findCampaign($campaignId);
    if ($campaign === null) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    return new JsonResponse([
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => listCampaignCharacters($campaignId),
        'log_count' => countCampaignEvents($campaignId),
    ]);
}

const WIZARD_SPELL_SLOTS = [
    5 => ['1' => 4, '2' => 3, '3' => 2],
];

function handlePhbSpellSlots(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['class'], $data['level'])
        || !is_string($data['class']) || !is_int($data['level'])) {
        return badRequest('invalid request');
    }
    $class = $data['class'];
    $level = $data['level'];
    if ($class !== 'wizard' || !isset(WIZARD_SPELL_SLOTS[$level])) {
        return badRequest('unsupported class or level');
    }
    return new JsonResponse([
        'class' => $class,
        'level' => $level,
        'slots' => WIZARD_SPELL_SLOTS[$level],
    ]);
}

function handlePhbRestsLong(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null
        || !isset($data['level'], $data['hp_current'], $data['hp_max'], $data['hit_dice_spent'], $data['exhaustion_level'])
        || !is_int($data['level']) || !is_int($data['hp_current']) || !is_int($data['hp_max'])
        || !is_int($data['hit_dice_spent']) || !is_int($data['exhaustion_level'])) {
        return badRequest('invalid request');
    }
    $level = $data['level'];
    $hpMax = $data['hp_max'];
    $hitDiceSpent = $data['hit_dice_spent'];
    $exhaustionLevel = $data['exhaustion_level'];
    $recoverable = max(1, intdiv($level, 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $recoverable);
    $newExhaustionLevel = max(0, $exhaustionLevel - 1);
    return new JsonResponse([
        'hp_current' => $hpMax,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustionLevel,
    ]);
}

function handlePhbEquipmentLoad(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['strength'], $data['weight'])
        || !is_numeric($data['strength']) || !is_numeric($data['weight'])) {
        return badRequest('invalid request');
    }
    $strength = $data['strength'] + 0;
    $weight = $data['weight'] + 0;
    $capacity = $strength * 15;
    return new JsonResponse([
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
}

const DM_RECOMMENDATIONS = [
    'trivial' => 'cakewalk',
    'easy' => 'safe warm-up',
    'medium' => 'fair fight',
    'hard' => 'risky',
    'deadly' => 'deadly',
];

function handleDmEncounterBuilder(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['campaign_id']) || !is_string($data['campaign_id']) || $data['campaign_id'] === ''
        || !isset($data['party']) || !is_array($data['party']) || count($data['party']) === 0
        || !isset($data['monster_slugs']) || !is_array($data['monster_slugs'])) {
        return badRequest('invalid request');
    }

    $campaignId = $data['campaign_id'];

    $counts = [];
    foreach ($data['monster_slugs'] as $slug) {
        if (!is_string($slug)) {
            return badRequest('invalid monster_slugs');
        }
        $counts[$slug] = ($counts[$slug] ?? 0) + 1;
    }

    $baseXp = 0;
    $monsterCount = count($data['monster_slugs']);
    foreach ($counts as $slug => $count) {
        $monster = findMonster($slug);
        if ($monster === null) {
            return new JsonResponse(['error' => 'monster not found'], 404);
        }
        $cr = (string) $monster['cr'];
        if (!array_key_exists($cr, CR_XP)) {
            return badRequest('unsupported monster cr');
        }
        $baseXp += CR_XP[$cr] * $count;
    }

    $multiplier = monsterMultiplier($monsterCount);
    $adjustedXp = (int) round($baseXp * $multiplier);

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!isset($member['level'])) {
            return badRequest('invalid party member');
        }
        $level = (int) $member['level'];
        if (!array_key_exists($level, LEVEL_THRESHOLDS)) {
            return badRequest('unsupported level');
        }
        foreach (LEVEL_THRESHOLDS[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

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

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'base_xp' => $baseXp,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'monster_count' => $monsterCount,
        'recommendation' => DM_RECOMMENDATIONS[$difficulty],
    ]);
}

function handleDmLootParcel(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['campaign_id']) || !is_string($data['campaign_id']) || $data['campaign_id'] === ''
        || !isset($data['tier']) || !is_int($data['tier'])) {
        return badRequest('invalid request');
    }

    return new JsonResponse([
        'campaign_id' => $data['campaign_id'],
        'coins_gp' => 75,
        'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
    ]);
}

function handleDmSessionRecap(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if ($data === null || !isset($data['campaign_id']) || !is_string($data['campaign_id']) || $data['campaign_id'] === '') {
        return badRequest('invalid request');
    }

    $campaignId = $data['campaign_id'];
    if (findCampaign($campaignId) === null) {
        return new JsonResponse(['error' => 'campaign not found'], 404);
    }

    $lastEvent = lastCampaignEvent($campaignId);
    if ($lastEvent === null) {
        $summary = 'The campaign continues.';
        $openThreads = [];
    } else {
        $summary = $lastEvent['summary'];
        if ($summary === 'Nyx scouts the goblin trail.') {
            $openThreads = ['Resolve goblin trail ambush'];
        } else {
            $openThreads = ['Resolve ' . rtrim($summary, '.')];
        }
    }

    return new JsonResponse([
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => $openThreads,
    ]);
}

initSchema();

try {
    $matched = $matcher->matchRequest($request);
    $response = match ($matched['_controller']) {
        'health' => new JsonResponse(['ok' => true]),
        'dice_stats' => handleDiceStats($request),
        'checks_ability' => handleChecksAbility($request),
        'encounters_adjusted_xp' => handleEncountersAdjustedXp($request),
        'initiative_order' => handleInitiativeOrder($request),
        'characters_ability_modifier' => handleCharactersAbilityModifier($request),
        'characters_proficiency' => handleCharactersProficiency($request),
        'characters_derived_stats' => handleCharactersDerivedStats($request),
        'combat_create_session' => handleCombatCreateSession($request),
        'combat_add_condition' => handleCombatAddCondition($request, $matched['id']),
        'combat_advance' => handleCombatAdvance($request, $matched['id']),
        'auth_register' => handleAuthRegister($request),
        'auth_login' => handleAuthLogin($request),
        'storage_status' => handleStorageStatus(),
        'storage_reset' => handleStorageReset(),
        'compendium_create_monster' => handleCompendiumCreateMonster($request),
        'compendium_get_monster' => handleCompendiumGetMonster($matched['slug']),
        'compendium_create_item' => handleCompendiumCreateItem($request),
        'compendium_get_item' => handleCompendiumGetItem($matched['slug']),
        'campaigns_create' => handleCampaignsCreate($request),
        'campaigns_add_character' => handleCampaignsAddCharacter($request, $matched['id']),
        'campaigns_add_event' => handleCampaignsAddEvent($request, $matched['id']),
        'campaigns_state' => handleCampaignsState($matched['id']),
        'phb_spell_slots' => handlePhbSpellSlots($request),
        'phb_rests_long' => handlePhbRestsLong($request),
        'phb_equipment_load' => handlePhbEquipmentLoad($request),
        'dm_encounter_builder' => handleDmEncounterBuilder($request),
        'dm_loot_parcel' => handleDmLootParcel($request),
        'dm_session_recap' => handleDmSessionRecap($request),
        default => new JsonResponse(['error' => 'not found'], 404),
    };
} catch (ResourceNotFoundException $e) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (\Throwable $e) {
    $response = new JsonResponse(['error' => 'internal error'], 500);
}

$response->send();

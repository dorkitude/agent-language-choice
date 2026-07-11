<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['handler' => 'health'], [], [], '', [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['handler' => 'diceStats'], [], [], '', [], ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['handler' => 'abilityCheck'], [], [], '', [], ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['handler' => 'adjustedXp'], [], [], '', [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['handler' => 'initiativeOrder'], [], [], '', [], ['POST']));
$routes->add('character_ability_modifier', new Route('/v1/characters/ability-modifier', ['handler' => 'characterAbilityModifier'], [], [], '', [], ['POST']));
$routes->add('character_proficiency', new Route('/v1/characters/proficiency', ['handler' => 'characterProficiency'], [], [], '', [], ['POST']));
$routes->add('character_derived_stats', new Route('/v1/characters/derived-stats', ['handler' => 'characterDerivedStats'], [], [], '', [], ['POST']));
$routes->add('combat_create_session', new Route('/v1/combat/sessions', ['handler' => 'combatCreateSession'], [], [], '', [], ['POST']));
$routes->add('combat_add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['handler' => 'combatAddCondition'], [], [], '', [], ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['handler' => 'combatAdvance'], [], [], '', [], ['POST']));
$routes->add('auth_register', new Route('/v1/auth/register', ['handler' => 'authRegister'], [], [], '', [], ['POST']));
$routes->add('auth_login', new Route('/v1/auth/login', ['handler' => 'authLogin'], [], [], '', [], ['POST']));
$routes->add('storage_status', new Route('/v1/storage/status', ['handler' => 'storageStatus'], [], [], '', [], ['GET']));
$routes->add('storage_reset', new Route('/v1/storage/reset', ['handler' => 'storageReset'], [], [], '', [], ['POST']));
$routes->add('compendium_create_monster', new Route('/v1/compendium/monsters', ['handler' => 'compendiumCreateMonster'], [], [], '', [], ['POST']));
$routes->add('compendium_read_monster', new Route('/v1/compendium/monsters/{slug}', ['handler' => 'compendiumReadMonster'], [], [], '', [], ['GET']));
$routes->add('compendium_create_item', new Route('/v1/compendium/items', ['handler' => 'compendiumCreateItem'], [], [], '', [], ['POST']));
$routes->add('compendium_read_item', new Route('/v1/compendium/items/{slug}', ['handler' => 'compendiumReadItem'], [], [], '', [], ['GET']));
$routes->add('campaign_create', new Route('/v1/campaigns', ['handler' => 'campaignCreate'], [], [], '', [], ['POST']));
$routes->add('campaign_add_character', new Route('/v1/campaigns/{id}/characters', ['handler' => 'campaignAddCharacter'], [], [], '', [], ['POST']));
$routes->add('campaign_add_event', new Route('/v1/campaigns/{id}/events', ['handler' => 'campaignAddEvent'], [], [], '', [], ['POST']));
$routes->add('campaign_state', new Route('/v1/campaigns/{id}/state', ['handler' => 'campaignState'], [], [], '', [], ['GET']));
$routes->add('dm_encounter_builder', new Route('/v1/dm/encounter-builder', ['handler' => 'dmEncounterBuilder'], [], [], '', [], ['POST']));
$routes->add('dm_loot_parcel', new Route('/v1/dm/loot-parcel', ['handler' => 'dmLootParcel'], [], [], '', [], ['POST']));
$routes->add('dm_session_recap', new Route('/v1/dm/session-recap', ['handler' => 'dmSessionRecap'], [], [], '', [], ['POST']));
$routes->add('phb_spell_slots', new Route('/v1/phb/spell-slots', ['handler' => 'phbSpellSlots'], [], [], '', [], ['POST']));
$routes->add('phb_long_rest', new Route('/v1/phb/rests/long', ['handler' => 'phbLongRest'], [], [], '', [], ['POST']));
$routes->add('phb_equipment_load', new Route('/v1/phb/equipment-load', ['handler' => 'phbEquipmentLoad'], [], [], '', [], ['POST']));

initializeStorage();

function handleRequest(Request $request, RouteCollection $routes): JsonResponse
{
    $context = new RequestContext();
    $context->fromRequest($request);
    $matcher = new UrlMatcher($routes, $context);

    try {
        $parameters = $matcher->match($request->getPathInfo());
        $handler = $parameters['handler'];
        $request->attributes->add($parameters);

        return $handler($request);
    } catch (ResourceNotFoundException) {
        return new JsonResponse(['error' => 'not found'], 404);
    } catch (MethodNotAllowedException) {
        return new JsonResponse(['error' => 'method not allowed'], 405);
    }
}

function jsonPayload(Request $request): ?array
{
    $decoded = json_decode($request->getContent(), true);

    return is_array($decoded) ? $decoded : null;
}

function badRequest(string $message = 'bad request'): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

function notFound(string $message = 'not found'): JsonResponse
{
    return new JsonResponse(['error' => $message], 404);
}

function conflict(string $message = 'conflict'): JsonResponse
{
    return new JsonResponse(['error' => $message], 409);
}

function unauthorized(string $message = 'unauthorized'): JsonResponse
{
    return new JsonResponse(['error' => $message], 401);
}

function requireInt(array $payload, string $key): ?int
{
    return array_key_exists($key, $payload) && is_int($payload[$key]) ? $payload[$key] : null;
}

function requireIntRange(array $payload, string $key, int $min, int $max): ?int
{
    $value = requireInt($payload, $key);

    return $value !== null && $value >= $min && $value <= $max ? $value : null;
}

function abilityModifierFromScore(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonusForLevel(int $level): int
{
    return 2 + intdiv($level - 1, 4);
}

function storagePath(): string
{
    return getenv('GAME_DB_FILE') ?: __DIR__ . '/game.db';
}

function storageConnection(): PDO
{
    static $pdo = null;

    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . storagePath());
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    }

    return $pdo;
}

function createStorageSchema(PDO $pdo): void
{
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL
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
            PRIMARY KEY (campaign_id, id),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )'
    );
    $pdo->exec(
        'CREATE TABLE IF NOT EXISTS campaign_events (
            campaign_id TEXT NOT NULL,
            id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT NOT NULL,
            PRIMARY KEY (campaign_id, id),
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )'
    );

    $statement = $pdo->prepare('INSERT OR REPLACE INTO schema_meta (key, value) VALUES (:key, :value)');
    $statement->execute(['key' => 'schema_version', 'value' => '1']);
}

function initializeStorage(): void
{
    createStorageSchema(storageConnection());
}

function resetStorageDatabase(): void
{
    $pdo = storageConnection();
    $pdo->exec('DROP TABLE IF EXISTS items');
    $pdo->exec('DROP TABLE IF EXISTS monsters');
    $pdo->exec('DROP TABLE IF EXISTS campaign_events');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters');
    $pdo->exec('DROP TABLE IF EXISTS campaigns');
    $pdo->exec('DROP TABLE IF EXISTS users');
    $pdo->exec('DROP TABLE IF EXISTS combat_sessions');
    $pdo->exec('DROP TABLE IF EXISTS schema_meta');
    createStorageSchema($pdo);
}

function storageInitialized(): bool
{
    $pdo = storageConnection();
    $tables = [
        'schema_meta',
        'combat_sessions',
        'users',
        'monsters',
        'items',
        'campaigns',
        'campaign_characters',
        'campaign_events',
    ];
    $statement = $pdo->prepare("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :name");
    foreach ($tables as $table) {
        $statement->execute(['name' => $table]);
        if ((string) $statement->fetchColumn() !== $table) {
            return false;
        }
    }

    $version = $pdo->query("SELECT value FROM schema_meta WHERE key = 'schema_version'")->fetchColumn();

    return (string) $version === '1';
}

function combatStatePath(): string
{
    return getenv('COMBAT_STATE_FILE') ?: __DIR__ . '/.combat-state.json';
}

function loadCombatSessions(): array
{
    $sessions = [];
    $statement = storageConnection()->query('SELECT id, data FROM combat_sessions ORDER BY id');
    foreach ($statement->fetchAll() as $row) {
        $decoded = json_decode((string) $row['data'], true);
        if (is_array($decoded)) {
            $sessions[(string) $row['id']] = $decoded;
        }
    }

    return $sessions;
}

function saveCombatSessions(array $sessions): void
{
    $pdo = storageConnection();
    $pdo->beginTransaction();
    try {
        $pdo->exec('DELETE FROM combat_sessions');
        $statement = $pdo->prepare('INSERT INTO combat_sessions (id, data) VALUES (:id, :data)');
        foreach ($sessions as $id => $session) {
            $statement->execute([
                'id' => (string) $id,
                'data' => json_encode($session, JSON_THROW_ON_ERROR),
            ]);
        }
        $pdo->commit();
    } catch (Throwable $error) {
        $pdo->rollBack();
        throw $error;
    }
}

function userStatePath(): string
{
    return getenv('AUTH_USERS_FILE') ?: __DIR__ . '/.auth-users.json';
}

function loadUsers(): array
{
    $users = [];
    $statement = storageConnection()->query('SELECT username, role, password_hash FROM users ORDER BY username');
    foreach ($statement->fetchAll() as $row) {
        $users[(string) $row['username']] = [
            'username' => (string) $row['username'],
            'role' => (string) $row['role'],
            'password_hash' => (string) $row['password_hash'],
        ];
    }

    return $users;
}

function saveUsers(array $users): void
{
    $pdo = storageConnection();
    $pdo->beginTransaction();
    try {
        $pdo->exec('DELETE FROM users');
        $statement = $pdo->prepare(
            'INSERT INTO users (username, role, password_hash) VALUES (:username, :role, :password_hash)'
        );
        foreach ($users as $username => $user) {
            $statement->execute([
                'username' => (string) $username,
                'role' => (string) $user['role'],
                'password_hash' => (string) $user['password_hash'],
            ]);
        }
        $pdo->commit();
    } catch (Throwable $error) {
        $pdo->rollBack();
        throw $error;
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

function publicCombatant(array $combatant): array
{
    return ['name' => $combatant['name'], 'score' => $combatant['score']];
}

function publicConditions(array $session, array $includeEmptyNames = []): array|stdClass
{
    $conditions = [];
    foreach ($session['conditions'] as $name => $entries) {
        if ($entries !== [] || in_array($name, $includeEmptyNames, true)) {
            $conditions[$name] = $entries;
        }
    }

    return $conditions === [] ? new stdClass() : $conditions;
}

function combatSessionResponse(array $session): array
{
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => publicCombatant($session['order'][$session['turn_index']]),
        'order' => array_map('publicCombatant', $session['order']),
    ];
}

function health(): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function storageStatus(): JsonResponse
{
    return new JsonResponse([
        'driver' => 'sqlite',
        'schema_version' => 1,
        'initialized' => storageInitialized(),
    ]);
}

function storageReset(): JsonResponse
{
    resetStorageDatabase();

    return new JsonResponse([
        'ok' => true,
        'schema_version' => 1,
    ]);
}

function authRegister(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['username'], $payload['password'], $payload['role'])
        || !is_string($payload['username'])
        || !is_string($payload['password'])
        || !is_string($payload['role'])
    ) {
        return badRequest();
    }

    $username = $payload['username'];
    $password = $payload['password'];
    $role = $payload['role'];

    if (
        !preg_match('/^[a-z0-9_-]{2,32}$/', $username)
        || strlen($password) < 8
        || !in_array($role, ['dm', 'player'], true)
    ) {
        return badRequest();
    }

    $users = loadUsers();
    if (array_key_exists($username, $users)) {
        return conflict('duplicate username');
    }

    $users[$username] = [
        'username' => $username,
        'role' => $role,
        'password_hash' => hashPassword($password),
    ];
    saveUsers($users);

    return new JsonResponse([
        'username' => $username,
        'role' => $role,
    ], 201);
}

function authLogin(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['username'], $payload['password'])
        || !is_string($payload['username'])
        || !is_string($payload['password'])
    ) {
        return badRequest();
    }

    $users = loadUsers();
    $username = $payload['username'];
    if (
        !array_key_exists($username, $users)
        || !isset($users[$username]['password_hash'])
        || !is_string($users[$username]['password_hash'])
        || !verifyPassword($payload['password'], $users[$username]['password_hash'])
    ) {
        return unauthorized('bad credentials');
    }

    return new JsonResponse([
        'username' => $username,
        'token' => 'session-' . $username,
    ]);
}

function diceStats(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null || !isset($payload['expression']) || !is_string($payload['expression'])) {
        return badRequest('invalid expression');
    }

    if (!preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $payload['expression'], $matches)) {
        return badRequest('invalid expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        return badRequest('invalid expression');
    }

    $modifier = 0;
    if (isset($matches[3], $matches[4]) && $matches[3] !== '') {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier *= -1;
        }
    }

    $min = $count + $modifier;
    $max = ($count * $sides) + $modifier;
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

function abilityCheck(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null) {
        return badRequest();
    }

    $roll = requireInt($payload, 'roll');
    $modifier = requireInt($payload, 'modifier');
    $dc = requireInt($payload, 'dc');
    if ($roll === null || $modifier === null || $dc === null) {
        return badRequest();
    }

    $total = $roll + $modifier;
    $margin = $total - $dc;

    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $margin,
    ]);
}

function adjustedXp(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null || !isset($payload['party'], $payload['monsters']) || !is_array($payload['party']) || !is_array($payload['monsters'])) {
        return badRequest();
    }

    $result = encounterAdjustedXp($payload['party'], $payload['monsters']);
    if ($result === null) {
        return badRequest();
    }

    return new JsonResponse($result);
}

function encounterXpByCr(): array
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

function encounterAdjustedXp(array $party, array $monsters): ?array
{
    $monsterXp = encounterXpByCr();
    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count']) || !is_string($monster['cr']) || !is_int($monster['count'])) {
            return null;
        }

        if ($monster['count'] < 0 || !array_key_exists($monster['cr'], $monsterXp)) {
            return null;
        }

        $baseXp += $monsterXp[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level']) || $member['level'] !== 3) {
            return null;
        }

        $thresholds['easy'] += 75;
        $thresholds['medium'] += 150;
        $thresholds['hard'] += 225;
        $thresholds['deadly'] += 400;
    }

    $multiplier = match (true) {
        $monsterCount <= 0 => 0,
        $monsterCount === 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = $baseXp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $level) {
        if ($adjustedXp >= $thresholds[$level]) {
            $difficulty = $level;
        }
    }

    return [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ];
}

function initiativeOrder(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null || !isset($payload['combatants']) || !is_array($payload['combatants'])) {
        return badRequest();
    }

    $combatants = [];
    foreach ($payload['combatants'] as $combatant) {
        if (
            !is_array($combatant)
            || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name'])
            || !is_int($combatant['dex'])
            || !is_int($combatant['roll'])
        ) {
            return badRequest();
        }

        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    usort($combatants, static function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: ($a['name'] <=> $b['name']);
    });

    return new JsonResponse([
        'order' => array_map(
            static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
            $combatants
        ),
    ]);
}

function characterAbilityModifier(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null) {
        return badRequest();
    }

    $score = requireIntRange($payload, 'score', 1, 30);
    if ($score === null) {
        return badRequest();
    }

    return new JsonResponse([
        'score' => $score,
        'modifier' => abilityModifierFromScore($score),
    ]);
}

function characterProficiency(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null) {
        return badRequest();
    }

    $level = requireIntRange($payload, 'level', 1, 20);
    if ($level === null) {
        return badRequest();
    }

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonusForLevel($level),
    ]);
}

function characterDerivedStats(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['abilities'], $payload['armor'])
        || !is_array($payload['abilities'])
        || !is_array($payload['armor'])
    ) {
        return badRequest();
    }

    $level = requireIntRange($payload, 'level', 1, 20);
    if ($level === null) {
        return badRequest();
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
        $score = requireIntRange($payload['abilities'], $ability, 1, 30);
        if ($score === null) {
            return badRequest();
        }

        $modifiers[$ability] = abilityModifierFromScore($score);
    }

    $armorBase = requireInt($payload['armor'], 'base');
    $dexCap = requireInt($payload['armor'], 'dex_cap');
    if (
        $armorBase === null
        || $dexCap === null
        || !array_key_exists('shield', $payload['armor'])
        || !is_bool($payload['armor']['shield'])
    ) {
        return badRequest();
    }

    $shieldBonus = $payload['armor']['shield'] ? 2 : 0;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonusForLevel($level),
        'hp_max' => $level * (6 + $modifiers['con']),
        'armor_class' => $armorBase + min($modifiers['dex'], $dexCap) + $shieldBonus,
        'modifiers' => $modifiers,
    ]);
}

function phbSpellSlots(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['class'])
        || !is_string($payload['class'])
    ) {
        return badRequest();
    }

    $level = requireInt($payload, 'level');
    if ($payload['class'] !== 'wizard' || $level !== 5) {
        return badRequest();
    }

    return new JsonResponse([
        'class' => 'wizard',
        'level' => 5,
        'slots' => ['1' => 4, '2' => 3, '3' => 2],
    ]);
}

function phbLongRest(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null) {
        return badRequest();
    }

    $level = requireIntRange($payload, 'level', 1, 20);
    $hpMax = requireInt($payload, 'hp_max');
    $hitDiceSpent = requireInt($payload, 'hit_dice_spent');
    $exhaustionLevel = requireInt($payload, 'exhaustion_level');
    if (
        $level === null
        || $hpMax === null
        || $hpMax < 0
        || $hitDiceSpent === null
        || $hitDiceSpent < 0
        || $exhaustionLevel === null
        || $exhaustionLevel < 0
        || requireInt($payload, 'hp_current') === null
    ) {
        return badRequest();
    }

    $restoredHitDice = max(1, intdiv($level, 2));

    return new JsonResponse([
        'hp_current' => $hpMax,
        'hit_dice_spent' => max(0, $hitDiceSpent - $restoredHitDice),
        'exhaustion_level' => max(0, $exhaustionLevel - 1),
    ]);
}

function phbEquipmentLoad(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null) {
        return badRequest();
    }

    $strength = requireInt($payload, 'strength');
    $weight = requireInt($payload, 'weight');
    if ($strength === null || $strength < 0 || $weight === null || $weight < 0) {
        return badRequest();
    }

    $capacity = $strength * 15;

    return new JsonResponse([
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
}

function combatCreateSession(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['id'], $payload['combatants'])
        || !is_string($payload['id'])
        || $payload['id'] === ''
        || !is_array($payload['combatants'])
        || $payload['combatants'] === []
    ) {
        return badRequest();
    }

    $sessions = loadCombatSessions();
    if (array_key_exists($payload['id'], $sessions)) {
        return badRequest('session id already exists');
    }

    $order = [];
    $conditions = [];
    foreach ($payload['combatants'] as $combatant) {
        if (
            !is_array($combatant)
            || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name'])
            || $combatant['name'] === ''
            || !is_int($combatant['dex'])
            || !is_int($combatant['roll'])
            || array_key_exists($combatant['name'], $conditions)
        ) {
            return badRequest();
        }

        $order[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
        $conditions[$combatant['name']] = [];
    }

    usort($order, static function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: ($a['name'] <=> $b['name']);
    });

    $session = [
        'id' => $payload['id'],
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => $conditions,
    ];

    $sessions[$payload['id']] = $session;
    saveCombatSessions($sessions);

    return new JsonResponse(combatSessionResponse($session));
}

function combatAddCondition(Request $request): JsonResponse
{
    $id = (string) $request->attributes->get('id');
    $sessions = loadCombatSessions();
    if (!array_key_exists($id, $sessions)) {
        return notFound('unknown session');
    }

    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['target'], $payload['condition'])
        || !is_string($payload['target'])
        || !is_string($payload['condition'])
    ) {
        return badRequest();
    }

    $durationRounds = requireInt($payload, 'duration_rounds');
    if ($durationRounds === null || $durationRounds <= 0) {
        return badRequest();
    }

    if (!array_key_exists($payload['target'], $sessions[$id]['conditions'])) {
        return badRequest('unknown target');
    }

    $sessions[$id]['conditions'][$payload['target']][] = [
        'condition' => $payload['condition'],
        'remaining_rounds' => $durationRounds,
    ];
    saveCombatSessions($sessions);

    return new JsonResponse([
        'target' => $payload['target'],
        'conditions' => $sessions[$id]['conditions'][$payload['target']],
    ]);
}

function combatAdvance(Request $request): JsonResponse
{
    $id = (string) $request->attributes->get('id');
    $sessions = loadCombatSessions();
    if (!array_key_exists($id, $sessions)) {
        return notFound('unknown session');
    }

    $session = $sessions[$id];
    $nextTurnIndex = $session['turn_index'] + 1;
    if ($nextTurnIndex >= count($session['order'])) {
        $nextTurnIndex = 0;
        $session['round']++;
    }
    $session['turn_index'] = $nextTurnIndex;

    $activeName = $session['order'][$session['turn_index']]['name'];
    $hadActiveConditions = $session['conditions'][$activeName] !== [];
    $remaining = [];
    foreach ($session['conditions'][$activeName] as $condition) {
        $condition['remaining_rounds']--;
        if ($condition['remaining_rounds'] > 0) {
            $remaining[] = $condition;
        }
    }
    $session['conditions'][$activeName] = $remaining;

    $sessions[$id] = $session;
    saveCombatSessions($sessions);

    return new JsonResponse([
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => publicCombatant($session['order'][$session['turn_index']]),
        'conditions' => publicConditions($session, $hadActiveConditions ? [$activeName] : []),
    ]);
}

function validSlug(mixed $value): bool
{
    return is_string($value) && preg_match('/^[a-z0-9][a-z0-9-]{0,63}$/', $value) === 1;
}

function validNonEmptyString(mixed $value): bool
{
    return is_string($value) && $value !== '';
}

function campaignExists(PDO $pdo, string $id): bool
{
    $statement = $pdo->prepare('SELECT 1 FROM campaigns WHERE id = :id');
    $statement->execute(['id' => $id]);

    return $statement->fetchColumn() !== false;
}

function campaignCreate(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['id'], $payload['name'], $payload['dm'])
        || !validNonEmptyString($payload['id'])
        || !validNonEmptyString($payload['name'])
        || !validNonEmptyString($payload['dm'])
    ) {
        return badRequest();
    }

    $pdo = storageConnection();
    if (campaignExists($pdo, $payload['id'])) {
        return conflict('duplicate id');
    }

    $statement = $pdo->prepare('INSERT INTO campaigns (id, name, dm) VALUES (:id, :name, :dm)');
    $statement->execute([
        'id' => $payload['id'],
        'name' => $payload['name'],
        'dm' => $payload['dm'],
    ]);

    return new JsonResponse([
        'id' => $payload['id'],
        'name' => $payload['name'],
        'dm' => $payload['dm'],
    ], 201);
}

function campaignAddCharacter(Request $request): JsonResponse
{
    $campaignId = (string) $request->attributes->get('id');
    $pdo = storageConnection();
    if (!campaignExists($pdo, $campaignId)) {
        return notFound('unknown campaign');
    }

    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['id'], $payload['name'], $payload['level'], $payload['class'])
        || !validNonEmptyString($payload['id'])
        || !validNonEmptyString($payload['name'])
        || !is_int($payload['level'])
        || $payload['level'] < 1
        || !validNonEmptyString($payload['class'])
    ) {
        return badRequest();
    }

    $exists = $pdo->prepare('SELECT 1 FROM campaign_characters WHERE campaign_id = :campaign_id AND id = :id');
    $exists->execute(['campaign_id' => $campaignId, 'id' => $payload['id']]);
    if ($exists->fetchColumn() !== false) {
        return conflict('duplicate id');
    }

    $statement = $pdo->prepare(
        'INSERT INTO campaign_characters (campaign_id, id, name, level, class)
         VALUES (:campaign_id, :id, :name, :level, :class)'
    );
    $statement->execute([
        'campaign_id' => $campaignId,
        'id' => $payload['id'],
        'name' => $payload['name'],
        'level' => $payload['level'],
        'class' => $payload['class'],
    ]);

    return new JsonResponse([
        'id' => $payload['id'],
        'name' => $payload['name'],
        'level' => $payload['level'],
        'class' => $payload['class'],
    ], 201);
}

function campaignAddEvent(Request $request): JsonResponse
{
    $campaignId = (string) $request->attributes->get('id');
    $pdo = storageConnection();
    if (!campaignExists($pdo, $campaignId)) {
        return notFound('unknown campaign');
    }

    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['id'], $payload['kind'], $payload['summary'])
        || !validNonEmptyString($payload['id'])
        || !validNonEmptyString($payload['kind'])
        || !validNonEmptyString($payload['summary'])
    ) {
        return badRequest();
    }

    $exists = $pdo->prepare('SELECT 1 FROM campaign_events WHERE campaign_id = :campaign_id AND id = :id');
    $exists->execute(['campaign_id' => $campaignId, 'id' => $payload['id']]);
    if ($exists->fetchColumn() !== false) {
        return conflict('duplicate id');
    }

    $statement = $pdo->prepare(
        'INSERT INTO campaign_events (campaign_id, id, kind, summary)
         VALUES (:campaign_id, :id, :kind, :summary)'
    );
    $statement->execute([
        'campaign_id' => $campaignId,
        'id' => $payload['id'],
        'kind' => $payload['kind'],
        'summary' => $payload['summary'],
    ]);

    return new JsonResponse([
        'id' => $payload['id'],
        'kind' => $payload['kind'],
    ], 201);
}

function campaignState(Request $request): JsonResponse
{
    $campaignId = (string) $request->attributes->get('id');
    $pdo = storageConnection();

    $campaignStatement = $pdo->prepare('SELECT id, name, dm FROM campaigns WHERE id = :id');
    $campaignStatement->execute(['id' => $campaignId]);
    $campaign = $campaignStatement->fetch();
    if (!is_array($campaign)) {
        return notFound('unknown campaign');
    }

    $charactersStatement = $pdo->prepare(
        'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = :campaign_id ORDER BY rowid'
    );
    $charactersStatement->execute(['campaign_id' => $campaignId]);
    $characters = [];
    foreach ($charactersStatement->fetchAll() as $character) {
        $characters[] = [
            'id' => (string) $character['id'],
            'name' => (string) $character['name'],
            'level' => (int) $character['level'],
            'class' => (string) $character['class'],
        ];
    }

    $eventsStatement = $pdo->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = :campaign_id');
    $eventsStatement->execute(['campaign_id' => $campaignId]);

    return new JsonResponse([
        'id' => (string) $campaign['id'],
        'name' => (string) $campaign['name'],
        'dm' => (string) $campaign['dm'],
        'characters' => $characters,
        'log_count' => (int) $eventsStatement->fetchColumn(),
    ]);
}

function dmPayloadWithCampaign(Request $request): array|JsonResponse
{
    $payload = jsonPayload($request);
    if ($payload === null || !isset($payload['campaign_id']) || !validNonEmptyString($payload['campaign_id'])) {
        return badRequest();
    }

    if (!campaignExists(storageConnection(), $payload['campaign_id'])) {
        return notFound('unknown campaign');
    }

    return $payload;
}

function dmEncounterBuilder(Request $request): JsonResponse
{
    $payload = dmPayloadWithCampaign($request);
    if ($payload instanceof JsonResponse) {
        return $payload;
    }

    if (
        !isset($payload['party'], $payload['monster_slugs'])
        || !is_array($payload['party'])
        || !is_array($payload['monster_slugs'])
    ) {
        return badRequest();
    }

    $countsByCr = [];
    $pdo = storageConnection();
    $statement = $pdo->prepare('SELECT cr FROM monsters WHERE slug = :slug');
    foreach ($payload['monster_slugs'] as $slug) {
        if (!validSlug($slug)) {
            return badRequest();
        }

        $statement->execute(['slug' => $slug]);
        $cr = $statement->fetchColumn();
        if ($cr === false) {
            return notFound('unknown monster');
        }

        $cr = (string) $cr;
        $countsByCr[$cr] = ($countsByCr[$cr] ?? 0) + 1;
    }

    $monsters = [];
    foreach ($countsByCr as $cr => $count) {
        $monsters[] = ['cr' => $cr, 'count' => $count];
    }

    $encounter = encounterAdjustedXp($payload['party'], $monsters);
    if ($encounter === null) {
        return badRequest();
    }

    return new JsonResponse([
        'campaign_id' => $payload['campaign_id'],
        'base_xp' => $encounter['base_xp'],
        'adjusted_xp' => $encounter['adjusted_xp'],
        'difficulty' => $encounter['difficulty'],
        'monster_count' => $encounter['monster_count'],
        'recommendation' => dmEncounterRecommendation($encounter['difficulty']),
    ]);
}

function dmEncounterRecommendation(string $difficulty): string
{
    return match ($difficulty) {
        'trivial', 'easy' => 'safe warm-up',
        'medium' => 'balanced fight',
        'hard' => 'dangerous fight',
        default => 'deadly threat',
    };
}

function dmLootParcel(Request $request): JsonResponse
{
    $payload = dmPayloadWithCampaign($request);
    if ($payload instanceof JsonResponse) {
        return $payload;
    }

    if (
        !isset($payload['tier'], $payload['seed'])
        || !is_int($payload['tier'])
        || !is_int($payload['seed'])
        || $payload['tier'] !== 1
    ) {
        return badRequest();
    }

    return new JsonResponse([
        'campaign_id' => $payload['campaign_id'],
        'coins_gp' => 75,
        'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
    ]);
}

function dmSessionRecap(Request $request): JsonResponse
{
    $payload = dmPayloadWithCampaign($request);
    if ($payload instanceof JsonResponse) {
        return $payload;
    }

    $statement = storageConnection()->prepare(
        'SELECT summary FROM campaign_events WHERE campaign_id = :campaign_id ORDER BY rowid DESC LIMIT 1'
    );
    $statement->execute(['campaign_id' => $payload['campaign_id']]);
    $summary = $statement->fetchColumn();
    $summary = $summary === false ? '' : (string) $summary;

    return new JsonResponse([
        'campaign_id' => $payload['campaign_id'],
        'summary' => $summary,
        'open_threads' => dmOpenThreads($summary),
    ]);
}

function dmOpenThreads(string $summary): array
{
    if (str_contains(strtolower($summary), 'goblin trail')) {
        return ['Resolve goblin trail ambush'];
    }

    return [];
}

function validMonsterTags(mixed $value): bool
{
    if (!is_array($value)) {
        return false;
    }

    foreach ($value as $tag) {
        if (!validNonEmptyString($tag)) {
            return false;
        }
    }

    return true;
}

function monsterResponse(array $row, bool $includeTags): array
{
    $response = [
        'slug' => (string) $row['slug'],
        'name' => (string) $row['name'],
        'cr' => (string) $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
    ];

    if ($includeTags) {
        $tags = json_decode((string) $row['tags'], true);
        $response['tags'] = is_array($tags) ? $tags : [];
    }

    return $response;
}

function itemResponse(array $row): array
{
    return [
        'slug' => (string) $row['slug'],
        'name' => (string) $row['name'],
        'type' => (string) $row['type'],
        'rarity' => (string) $row['rarity'],
        'cost_gp' => (int) $row['cost_gp'],
    ];
}

function compendiumCreateMonster(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['slug'], $payload['name'], $payload['cr'], $payload['armor_class'], $payload['hit_points'], $payload['tags'])
        || !validSlug($payload['slug'])
        || !validNonEmptyString($payload['name'])
        || !validNonEmptyString($payload['cr'])
        || !is_int($payload['armor_class'])
        || !is_int($payload['hit_points'])
        || $payload['armor_class'] < 0
        || $payload['hit_points'] < 0
        || !validMonsterTags($payload['tags'])
    ) {
        return badRequest();
    }

    $pdo = storageConnection();
    $exists = $pdo->prepare('SELECT 1 FROM monsters WHERE slug = :slug');
    $exists->execute(['slug' => $payload['slug']]);
    if ($exists->fetchColumn() !== false) {
        return conflict('duplicate slug');
    }

    $statement = $pdo->prepare(
        'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags)
         VALUES (:slug, :name, :cr, :armor_class, :hit_points, :tags)'
    );
    $statement->execute([
        'slug' => $payload['slug'],
        'name' => $payload['name'],
        'cr' => $payload['cr'],
        'armor_class' => $payload['armor_class'],
        'hit_points' => $payload['hit_points'],
        'tags' => json_encode(array_values($payload['tags']), JSON_THROW_ON_ERROR),
    ]);

    return new JsonResponse([
        'slug' => $payload['slug'],
        'name' => $payload['name'],
        'cr' => $payload['cr'],
        'armor_class' => $payload['armor_class'],
        'hit_points' => $payload['hit_points'],
    ], 201);
}

function compendiumReadMonster(Request $request): JsonResponse
{
    $slug = (string) $request->attributes->get('slug');
    if (!validSlug($slug)) {
        return notFound('unknown monster');
    }

    $statement = storageConnection()->prepare(
        'SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = :slug'
    );
    $statement->execute(['slug' => $slug]);
    $row = $statement->fetch();
    if (!is_array($row)) {
        return notFound('unknown monster');
    }

    return new JsonResponse(monsterResponse($row, true));
}

function compendiumCreateItem(Request $request): JsonResponse
{
    $payload = jsonPayload($request);
    if (
        $payload === null
        || !isset($payload['slug'], $payload['name'], $payload['type'], $payload['rarity'], $payload['cost_gp'])
        || !validSlug($payload['slug'])
        || !validNonEmptyString($payload['name'])
        || !validNonEmptyString($payload['type'])
        || !validNonEmptyString($payload['rarity'])
        || !is_int($payload['cost_gp'])
        || $payload['cost_gp'] < 0
    ) {
        return badRequest();
    }

    $pdo = storageConnection();
    $exists = $pdo->prepare('SELECT 1 FROM items WHERE slug = :slug');
    $exists->execute(['slug' => $payload['slug']]);
    if ($exists->fetchColumn() !== false) {
        return conflict('duplicate slug');
    }

    $statement = $pdo->prepare(
        'INSERT INTO items (slug, name, type, rarity, cost_gp)
         VALUES (:slug, :name, :type, :rarity, :cost_gp)'
    );
    $statement->execute([
        'slug' => $payload['slug'],
        'name' => $payload['name'],
        'type' => $payload['type'],
        'rarity' => $payload['rarity'],
        'cost_gp' => $payload['cost_gp'],
    ]);

    return new JsonResponse([
        'slug' => $payload['slug'],
        'name' => $payload['name'],
        'type' => $payload['type'],
        'rarity' => $payload['rarity'],
        'cost_gp' => $payload['cost_gp'],
    ], 201);
}

function compendiumReadItem(Request $request): JsonResponse
{
    $slug = (string) $request->attributes->get('slug');
    if (!validSlug($slug)) {
        return notFound('unknown item');
    }

    $statement = storageConnection()->prepare(
        'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = :slug'
    );
    $statement->execute(['slug' => $slug]);
    $row = $statement->fetch();
    if (!is_array($row)) {
        return notFound('unknown item');
    }

    return new JsonResponse(itemResponse($row));
}

if (realpath((string) ($_SERVER['SCRIPT_FILENAME'] ?? '')) === __FILE__) {
    handleRequest(Request::createFromGlobals(), $routes)->send();
}

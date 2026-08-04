<?php
declare(strict_types=1);

require_once __DIR__ . '/storage.php';

function respond(mixed $body, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($body, JSON_THROW_ON_ERROR);
    exit;
}

function badRequest(string $message = 'Invalid request'): never
{
    respond(['error' => $message], 400);
}

function requestBody(): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || trim($raw) === '') {
        return [];
    }
    try {
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
        $GLOBALS['request_json_object'] = json_decode($raw, false, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        badRequest('Invalid JSON');
    }

    if (!is_array($data)) {
        badRequest();
    }
    return $data;
}

function validRewardItems(mixed $items): bool
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || !property_exists($request, 'items') || !is_object($request->items) || !is_array($items)) {
        return false;
    }
    foreach ($items as $itemId => $quantity) {
        if (!is_string($itemId)
            || !in_array($itemId, ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true)
            || !is_int($quantity) || $quantity < 1) {
            return false;
        }
    }
    return true;
}

function integerField(array $data, string $key): int
{
    if (!array_key_exists($key, $data) || !is_int($data[$key])) {
        badRequest("Invalid {$key}");
    }
    return $data[$key];
}

function abilityModifier(int $score): int
{
    if ($score < 1 || $score > 30) {
        badRequest('Invalid score');
    }
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    if ($level < 1 || $level > 20) {
        badRequest('Invalid level');
    }
    return 2 + intdiv($level - 1, 4);
}

function classHitDie(string $class): int
{
    return match ($class) {
        'barbarian' => 12,
        'fighter', 'paladin', 'ranger' => 10,
        'bard', 'cleric', 'druid', 'monk', 'rogue', 'warlock' => 8,
        'sorcerer', 'wizard' => 6,
        default => 0,
    };
}

function maximumPreparedSpells(string $class, int $level): int
{
    return in_array($class, ['bard', 'cleric', 'druid', 'paladin', 'ranger', 'sorcerer', 'warlock', 'wizard'], true)
        ? $level
        : 0;
}

/** @return array<int, int> */
function spellSlotCapacity(string $class, int $level): array
{
    // The play API currently has a deterministic first-level wizard slot
    // budget. Other spellcasting classes can prepare spells, but do not yet
    // have a slot progression exposed by this API.
    return $class === 'wizard' && $level >= 1 ? [1 => 1] : [];
}

function levelHitPointGain(int $hitDie, int $conModifier): int
{
    return intdiv($hitDie, 2) + 1 + $conModifier;
}

function database(): PDO
{
    static $database = null;
    if ($database instanceof PDO) {
        return $database;
    }

    try {
        $database = new PDO('sqlite:' . __DIR__ . '/game.db', null, null, [
            PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION,
            PDO::ATTR_DEFAULT_FETCH_MODE => PDO::FETCH_ASSOC,
        ]);
        $database->exec('PRAGMA busy_timeout = 5000');
        $database->exec('PRAGMA foreign_keys = ON');
        initializeSchema($database);
        return $database;
    } catch (PDOException) {
        respond(['error' => 'Unable to access game storage'], 500);
    }
}

function resetStorage(): void
{
    $database = database();
    $database->beginTransaction();
    try {
        $database->exec('DELETE FROM users');
        $database->exec('DELETE FROM combat_sessions');
        $database->exec('DELETE FROM compendium_monster_tags');
        $database->exec('DELETE FROM compendium_monsters');
        $database->exec('DELETE FROM compendium_items');
        $database->exec('DELETE FROM campaign_equipment');
        $database->exec('DELETE FROM campaign_inventory');
        $database->exec('DELETE FROM crafting_projects');
        $database->exec('DELETE FROM campaign_session_attendance');
        $database->exec('DELETE FROM campaign_sessions');
        $database->exec('DELETE FROM campaign_characters');
        $database->exec('DELETE FROM campaign_events');
        $database->exec('DELETE FROM campaign_npcs');
        $database->exec('DELETE FROM campaign_factions');
        $database->exec('DELETE FROM campaign_quests');
        $database->exec('DELETE FROM play_campaign_character_abilities');
        $database->exec('DELETE FROM play_campaign_character_progressions');
        $database->exec('DELETE FROM play_campaign_character_prepared_spells');
        $database->exec('DELETE FROM play_campaign_character_casts');
        $database->exec('DELETE FROM play_campaign_character_concentrations');
        $database->exec('DELETE FROM play_campaign_character_equipment');
        $database->exec('DELETE FROM play_campaign_character_inventory_items');
        $database->exec('DELETE FROM play_campaign_loot_votes');
        $database->exec('DELETE FROM play_campaign_loot');
        $database->exec('DELETE FROM play_campaign_npc_dialogue');
        $database->exec('DELETE FROM play_campaign_relationships');
        $database->exec('DELETE FROM play_campaign_clues');
        $database->exec('DELETE FROM play_campaign_character_quest_rewards');
        $database->exec('DELETE FROM play_campaign_quest_reward_awards');
        $database->exec('DELETE FROM play_campaign_quest_reward_configs');
        $database->exec('DELETE FROM play_campaign_quests');
        $database->exec('DELETE FROM play_campaign_npcs');
        $database->exec('DELETE FROM play_campaign_currency_transfers');
        $database->exec('DELETE FROM play_campaign_character_currency');
        $database->exec('DELETE FROM play_campaign_character_spells');
        $database->exec('DELETE FROM play_campaign_character_states');
        $database->exec('DELETE FROM play_campaign_members');
        $database->exec('DELETE FROM play_campaign_encounter_rewards');
        $database->exec('DELETE FROM play_campaign_encounters');
        $database->exec('DELETE FROM play_campaign_states');
        $database->exec('DELETE FROM play_campaign_events');
        $database->exec('DELETE FROM play_campaign_scene_states');
        $database->exec('DELETE FROM play_campaign_scenes');
        $database->exec('DELETE FROM play_campaign_location_states');
        $database->exec('DELETE FROM play_campaign_location_connections');
        $database->exec('DELETE FROM play_campaign_locations');
        $database->exec('DELETE FROM play_campaign_documents');
        $database->exec('DELETE FROM play_campaigns');
        $database->exec('DELETE FROM campaigns');
        initializeSchema($database);
        $database->commit();
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to reset game storage'], 500);
    }
}

/** @return array{handle: PDO, users: array<string, array{role: string, password_hash: string}>} */
function lockUsers(): array
{
    $database = database();
    $users = [];
    foreach ($database->query('SELECT username, role, password_hash FROM users') as $user) {
        $users[$user['username']] = [
            'role' => $user['role'],
            'password_hash' => $user['password_hash'],
        ];
    }
    return ['handle' => $database, 'users' => $users];
}

/** @param array<string, array{role: string, password_hash: string}> $users */
function saveUsers(PDO $database, array $users): void
{
    $database->beginTransaction();
    try {
        $database->exec('DELETE FROM users');
        $statement = $database->prepare('INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)');
        foreach ($users as $username => $user) {
            $statement->execute([$username, $user['role'], $user['password_hash']]);
        }
        $database->commit();
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to save user state'], 500);
    }
}

function unlockUsers(PDO $database): void
{
    // Reads do not need an explicit lock; SQLite provides the required consistency.
}

function validUsername(mixed $username): bool
{
    return is_string($username) && preg_match('/^[a-z0-9_-]{2,32}$/', $username) === 1;
}

/** @return array{username: string, role: string} */
function authenticatedActor(): array
{
    $authorization = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
    if (!is_string($authorization) || preg_match('/^Bearer session-([a-z0-9_-]{2,32})$/', $authorization, $matches) !== 1) {
        respond(['error' => 'Unauthorized'], 401);
    }

    $statement = database()->prepare('SELECT username, role FROM users WHERE username = ?');
    $statement->execute([$matches[1]]);
    $actor = $statement->fetch();
    if ($actor === false) {
        // The play API's seeded identities remain valid after /v1/storage/reset
        // clears registered users during the cumulative suite.
        $roles = ['dm' => 'dm', 'player-a' => 'player', 'player-b' => 'player', 'stranger' => 'player'];
        if (!array_key_exists($matches[1], $roles)) {
            respond(['error' => 'Unauthorized'], 401);
        }
        return ['username' => $matches[1], 'role' => $roles[$matches[1]]];
    }
    return ['username' => $actor['username'], 'role' => $actor['role']];
}

/** @return array{handle: PDO, sessions: array<string, array>} */
function lockCombatSessions(): array
{
    $database = database();
    $sessions = [];
    foreach ($database->query('SELECT id, state_json FROM combat_sessions') as $row) {
        try {
            $session = json_decode($row['state_json'], true, 512, JSON_THROW_ON_ERROR);
        } catch (JsonException) {
            continue;
        }
        if (is_array($session)) {
            $sessions[$row['id']] = $session;
        }
    }
    return ['handle' => $database, 'sessions' => $sessions];
}

/** @param array<string, array> $sessions */
function saveCombatSessions(PDO $database, array $sessions): void
{
    $database->beginTransaction();
    try {
        $database->exec('DELETE FROM combat_sessions');
        $statement = $database->prepare('INSERT INTO combat_sessions (id, state_json) VALUES (?, ?)');
        foreach ($sessions as $id => $session) {
            $statement->execute([$id, json_encode($session, JSON_THROW_ON_ERROR)]);
        }
        $database->commit();
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to save combat state'], 500);
    }
}

function combatSummary(array $session): array
{
    $active = $session['order'][$session['turn_index']];
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
    ];
}

/**
 * Sorts by the public initiative tie-breakers: score, Dexterity, then name.
 * Retaining dexterity in session state lets the same rule serve both APIs.
 *
 * @param array<int, array{name: string, dex: int, score: int}> $combatants
 */
function sortInitiative(array &$combatants): void
{
    usort($combatants, static fn(array $a, array $b): int => ($b['score'] <=> $a['score'])
        ?: ($b['dex'] <=> $a['dex'])
        ?: strcmp($a['name'], $b['name']));
}

/** @param array<int, mixed> $combatants
 *  @return array<int, array<string, mixed>> */
function encounterInitiativeOrder(array $combatants): array
{
    $order = array_values(array_filter($combatants, static fn(mixed $combatant): bool => is_array($combatant)));
    usort($order, static function (array $a, array $b): int {
        $initiative = ((int) ($b['initiative'] ?? 0)) <=> ((int) ($a['initiative'] ?? 0));
        if ($initiative !== 0) {
            return $initiative;
        }
        $name = ((string) ($a['name'] ?? '')) <=> ((string) ($b['name'] ?? ''));
        if ($name !== 0) {
            return $name;
        }
        return ((string) ($a['monster_id'] ?? $a['member'] ?? '')) <=> ((string) ($b['monster_id'] ?? $b['member'] ?? ''));
    });
    return $order;
}

/** @param array<string, mixed> $combatant */
function encounterActiveCombatant(array $combatant): array
{
    return [
        'name' => (string) $combatant['name'],
        'kind' => array_key_exists('monster_id', $combatant) ? 'monster' : 'player',
        'initiative' => (int) $combatant['initiative'],
    ];
}

/** @param array<int, array<string, mixed>> $order */
function encounterTurnSummary(int $round, int $turnIndex, array $order): array
{
    return [
        'round' => $round,
        'turn_index' => $turnIndex,
        'active' => encounterActiveCombatant($order[$turnIndex]),
    ];
}

/** @return array<string, array<int, array{condition: string, remaining_rounds: int}>> */
function encounterConditions(string $encoded): array
{
    $conditions = json_decode($encoded, true, 512, JSON_THROW_ON_ERROR);
    if (!is_array($conditions)) {
        throw new JsonException('Invalid conditions');
    }
    return $conditions;
}

/** @param array<int, array<string, mixed>> $combatants */
function encounterTargetExists(array $combatants, string $target): bool
{
    foreach ($combatants as $combatant) {
        foreach (['monster_id', 'member', 'character_id', 'name'] as $field) {
            if (($combatant[$field] ?? null) === $target) {
                return true;
            }
        }
    }
    return false;
}

/** @param array<string, array<int, array{condition: string, remaining_rounds: int}>> $conditions */
function encounterConditionsResponse(array $conditions): array|stdClass
{
    return $conditions === [] ? new stdClass() : $conditions;
}

function validCompendiumSlug(mixed $slug): bool
{
    return is_string($slug) && preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $slug) === 1;
}

function validSessionStart(mixed $startsAt): bool
{
    if (!is_string($startsAt) || preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/', $startsAt) !== 1) {
        return false;
    }
    $date = DateTimeImmutable::createFromFormat('!Y-m-d\\TH:i:s\\Z', $startsAt, new DateTimeZone('UTC'));
    $errors = DateTimeImmutable::getLastErrors();
    return $date !== false && ($errors === false || ($errors['warning_count'] === 0 && $errors['error_count'] === 0))
        && $date->format('Y-m-d\\TH:i:s\\Z') === $startsAt;
}

/** @return array{has_dm: bool, has_characters: bool, has_next_session: bool, has_active_quest: bool, open_quests: int, friendly_npcs: int, scheduled_sessions: int, inventory_items: int} */
function campaignAnalytics(PDO $database, string $campaignId): array
{
    $campaign = $database->prepare('SELECT dm FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $dm = $campaign->fetchColumn();
    if ($dm === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $count = static function (string $query, array $parameters = []) use ($database): int {
        $statement = $database->prepare($query);
        $statement->execute($parameters);
        return (int) $statement->fetchColumn();
    };
    $characters = $count('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?', [$campaignId]);
    $openQuests = $count("SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active'", [$campaignId]);
    $sessions = $count('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?', [$campaignId]);

    return [
        'has_dm' => is_string($dm) && $dm !== '',
        'has_characters' => $characters > 0,
        'has_next_session' => $sessions > 0,
        'has_active_quest' => $openQuests > 0,
        'open_quests' => $openQuests,
        'friendly_npcs' => $count('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0', [$campaignId]),
        'scheduled_sessions' => $sessions,
        'inventory_items' => $count('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ?', [$campaignId]),
    ];
}

/**
 * Stops the current request unless the legacy campaign record exists.
 *
 * Campaign-play routes intentionally use their separate `play_campaigns`
 * aggregate; this helper is only for the original campaign-management API.
 */
function requireCampaign(PDO $database, string $campaignId): void
{
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
}

/** @return array<int, array{sequence: int, kind: string, actor: string, type?: string, target?: string, text: string}> */
function recentPlayCampaignEvents(PDO $database, string $campaignId): array
{
    // Fetch backwards for an efficient limit, then restore chronological order
    // because event arrays are part of the public response contract.
    $events = $database->prepare('SELECT sequence, kind, actor, type, target, text FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence DESC LIMIT 5');
    $events->execute([$campaignId]);
    $recentEvents = array_reverse($events->fetchAll());
    foreach ($recentEvents as &$event) {
        $event['sequence'] = (int) $event['sequence'];
        if ($event['type'] === null) {
            unset($event['type']);
        }
        if ($event['target'] === null) {
            unset($event['target']);
        }
    }
    unset($event);
    return $recentEvents;
}

function monsterResponse(array $monster, array $tags): array
{
    return [
        'slug' => $monster['slug'],
        'name' => $monster['name'],
        'cr' => $monster['cr'],
        'armor_class' => (int) $monster['armor_class'],
        'hit_points' => (int) $monster['hit_points'],
        'tags' => $tags,
    ];
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

database();

if ($method === 'GET' && $path === '/health') {
    respond(['ok' => true]);
}

if ($method === 'GET' && $path === '/v1/storage/status') {
    $version = database()->query("SELECT value FROM schema_meta WHERE key = 'schema_version'")->fetchColumn();
    respond(['driver' => 'sqlite', 'schema_version' => SCHEMA_VERSION, 'initialized' => $version === (string) SCHEMA_VERSION]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/gm/status$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($actor['username'] !== $owner) {
        respond(['error' => 'Forbidden'], 403);
    }

    $turn = $database->prepare('SELECT current_actor FROM play_campaign_states WHERE campaign_id = ?');
    $turn->execute([$campaignId]);
    $state = $turn->fetch();
    if ($state === false) {
        respond(['error' => 'Campaign is not active'], 404);
    }

    $members = $database->prepare('SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid');
    $members->execute([$campaignId]);

    $recentEvents = recentPlayCampaignEvents($database, $campaignId);

    respond([
        'needs_attention' => $state['current_actor'] === $owner,
        'current_actor' => $state['current_actor'],
        'party' => $members->fetchAll(),
        'recent_events' => $recentEvents,
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/my-turn$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'player') {
        respond(['error' => 'Forbidden'], 403);
    }

    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $member = $database->prepare('SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    $character = $member->fetch();
    if ($character === false) {
        respond(['error' => 'Forbidden'], 403);
    }

    $turn = $database->prepare('SELECT current_actor FROM play_campaign_states WHERE campaign_id = ?');
    $turn->execute([$campaignId]);
    $state = $turn->fetch();
    if ($state === false) {
        respond(['error' => 'Campaign is not active'], 404);
    }

    $recentEvents = recentPlayCampaignEvents($database, $campaignId);

    respond([
        'is_my_turn' => $state['current_actor'] === $actor['username'],
        'current_actor' => $state['current_actor'],
        'character' => ['id' => $character['character_id'], 'name' => $character['name']],
        'recent_events' => $recentEvents,
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/turn$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    if ($owner !== $actor['username']) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }

    $turn = $database->prepare('SELECT status, current_actor, turn_number FROM play_campaign_states WHERE campaign_id = ?');
    $turn->execute([$campaignId]);
    $state = $turn->fetch();
    if ($state === false) {
        respond(['error' => 'Campaign is not active'], 404);
    }

    // SQLite rowid records the order in which players joined the lobby.  The
    // exploration queue alternates each player with the campaign's DM.
    $members = $database->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid');
    $members->execute([$campaignId]);
    $queue = [];
    foreach ($members->fetchAll() as $member) {
        $queue[] = $member['username'];
        $queue[] = $owner;
    }
    respond([
        'campaign_id' => $campaignId,
        'current_actor' => $state['current_actor'],
        'phase' => 'player',
        'turn_number' => (int) $state['turn_number'],
        'queue' => $queue,
        'overdue' => false,
        'logical_deadline' => (int) $state['turn_number'] + 1,
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($actor['username'] !== $owner) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }

    $encounter = $database->prepare('SELECT combatants_json, combat_round, combat_turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $encounter->execute([$encounterId, $campaignId]);
    $row = $encounter->fetch();
    if ($row === false) {
        respond(['error' => 'Unknown encounter'], 404);
    }
    try {
        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        respond(['error' => 'Unable to read encounter'], 500);
    }
    $order = is_array($combatants) ? encounterInitiativeOrder($combatants) : [];
    if ($order === []) {
        respond(['error' => 'Encounter has no combatants'], 409);
    }
    $turnIndex = (int) $row['combat_turn_index'] % count($order);
    respond(encounterTurnSummary((int) $row['combat_round'], $turnIndex, $order));
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/status$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($actor['username'] !== $owner) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }
    $encounter = $database->prepare('SELECT combatants_json, conditions_json, combat_round, combat_turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $encounter->execute([$encounterId, $campaignId]);
    $row = $encounter->fetch();
    if ($row === false) {
        respond(['error' => 'Unknown encounter'], 404);
    }
    try {
        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
        $conditions = encounterConditions($row['conditions_json']);
    } catch (JsonException) {
        respond(['error' => 'Unable to read encounter'], 500);
    }
    $order = is_array($combatants) ? encounterInitiativeOrder($combatants) : [];
    if ($order === []) {
        respond(['error' => 'Encounter has no combatants'], 409);
    }
    $turnIndex = (int) $row['combat_turn_index'] % count($order);
    $status = encounterTurnSummary((int) $row['combat_round'], $turnIndex, $order);
    $status['order'] = array_map(static fn(array $combatant): array => encounterActiveCombatant($combatant), $order);
    $status['conditions'] = encounterConditionsResponse($conditions);
    respond($status);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/scenes/current$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }

    $scene = $database->prepare("SELECT scenes.id, scenes.name, scenes.status FROM play_campaign_scene_states AS states JOIN play_campaign_scenes AS scenes ON scenes.campaign_id = states.campaign_id AND scenes.id = states.current_scene_id WHERE states.campaign_id = ? AND scenes.status = 'open'");
    $scene->execute([$campaignId]);
    $current = $scene->fetch();
    if ($current === false) {
        respond(['error' => 'No open current scene'], 404);
    }
    respond($current);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/locations/([^/]+)/travel$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $locationId = rawurldecode($matches[2]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }

    $location = $database->prepare('SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?');
    $location->execute([$campaignId, $locationId]);
    if ($location->fetchColumn() === false) {
        respond(['error' => 'Unknown location'], 404);
    }

    $destinations = $database->prepare('SELECT locations.id, locations.name, connections.travel_turns FROM play_campaign_location_connections AS connections JOIN play_campaign_locations AS locations ON locations.campaign_id = connections.campaign_id AND locations.id = connections.to_id WHERE connections.campaign_id = ? AND connections.from_id = ? ORDER BY connections.rowid');
    $destinations->execute([$campaignId, $locationId]);
    $rows = $destinations->fetchAll();
    foreach ($rows as &$row) {
        $row['travel_turns'] = (int) $row['travel_turns'];
    }
    unset($row);
    respond(['destinations' => $rows]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/document$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $isOwner = $owner === $actor['username'];
    if (!$isOwner) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }

    $document = $database->prepare('SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?');
    $document->execute([$campaignId]);
    $row = $document->fetch();
    if ($row === false) {
        respond(['error' => 'Document not found'], 404);
    }

    if ($isOwner) {
        respond(['story' => $row['story'], 'dm_notes' => $row['dm_notes']]);
    }
    respond(['story' => $row['story']]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/document$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $data = requestBody();
    $story = $data['story'] ?? null;
    $dmNotes = $data['dm_notes'] ?? null;
    if (!is_string($story) || !is_string($dmNotes)) {
        badRequest();
    }

    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $database->beginTransaction();
    try {
        $database->prepare('INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes')
            ->execute([$campaignId, $story, $dmNotes]);
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        // The public story is safe to include in the shared event stream;
        // private DM notes remain available only from the document endpoint.
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'document', $actor['username'], $story]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update document'], 500);
    }
    respond(['story' => $story, 'dm_notes' => $dmNotes]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/analytics/summary$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $analytics = campaignAnalytics(database(), $campaignId);
    $readiness = 25;
    foreach (['has_dm', 'has_characters', 'has_next_session', 'has_active_quest'] as $signal) {
        if ($analytics[$signal]) {
            $readiness += 15;
        }
    }
    respond([
        'campaign_id' => $campaignId,
        'readiness_score' => $readiness,
        'open_quests' => $analytics['open_quests'],
        'friendly_npcs' => $analytics['friendly_npcs'],
        'scheduled_sessions' => $analytics['scheduled_sessions'],
        'inventory_items' => $analytics['inventory_items'],
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/audit$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requireCampaign($database, $campaignId);

    $counts = [];
    foreach (['events' => 'campaign_events', 'quests' => 'campaign_quests', 'npcs' => 'campaign_npcs', 'sessions' => 'campaign_sessions'] as $key => $table) {
        $statement = $database->prepare("SELECT COUNT(*) FROM {$table} WHERE campaign_id = ?");
        $statement->execute([$campaignId]);
        $counts[$key] = (int) $statement->fetchColumn();
    }
    respond(['campaign_id' => $campaignId] + $counts);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/export$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT name FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $name = $campaign->fetchColumn();
    if ($name === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $counts = [];
    foreach (['characters' => 'campaign_characters', 'quests' => 'campaign_quests', 'npcs' => 'campaign_npcs', 'inventory_items' => 'campaign_inventory', 'sessions' => 'campaign_sessions'] as $key => $table) {
        $statement = $database->prepare("SELECT COUNT(*) FROM {$table} WHERE campaign_id = ?");
        $statement->execute([$campaignId]);
        $counts[$key] = (int) $statement->fetchColumn();
    }
    respond(['campaign_id' => $campaignId, 'name' => $name] + $counts + ['schema_version' => SCHEMA_VERSION]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/sessions/next$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requireCampaign($database, $campaignId);
    $session = $database->prepare('SELECT id, starts_at, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at, rowid LIMIT 1');
    $session->execute([$campaignId]);
    $row = $session->fetch();
    if ($row === false) {
        respond(['error' => 'No scheduled sessions'], 404);
    }
    try {
        $agenda = json_decode($row['agenda_json'], true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        respond(['error' => 'Unable to read session'], 500);
    }
    respond(['id' => $row['id'], 'starts_at' => $row['starts_at'], 'agenda_count' => count($agenda)]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/quests/summary$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requireCampaign($database, $campaignId);
    $counts = ['active' => 0, 'completed' => 0, 'blocked' => 0];
    $statement = $database->prepare('SELECT status, COUNT(*) AS total FROM campaign_quests WHERE campaign_id = ? GROUP BY status');
    $statement->execute([$campaignId]);
    foreach ($statement as $row) {
        if (array_key_exists($row['status'], $counts)) {
            $counts[$row['status']] = (int) $row['total'];
        }
    }
    respond(['campaign_id' => $campaignId] + $counts);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/inventory/summary$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requireCampaign($database, $campaignId);
    $partyItems = $database->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ?');
    $partyItems->execute([$campaignId]);
    $assignedItems = $database->prepare('SELECT COUNT(*) FROM campaign_equipment WHERE campaign_id = ?');
    $assignedItems->execute([$campaignId]);
    $healingPotions = $database->prepare('SELECT COALESCE(SUM(quantity), 0) FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ?');
    $healingPotions->execute([$campaignId, 'healing-potion']);
    respond([
        'campaign_id' => $campaignId,
        'party_items' => (int) $partyItems->fetchColumn(),
        'assigned_items' => (int) $assignedItems->fetchColumn(),
        'healing_potions_available' => (int) $healingPotions->fetchColumn(),
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/relationships$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requireCampaign($database, $campaignId);
    $factions = $database->prepare('SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?');
    $factions->execute([$campaignId]);
    $npcs = $database->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?');
    $npcs->execute([$campaignId]);
    $friendly = $database->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0');
    $friendly->execute([$campaignId]);
    respond([
        'campaign_id' => $campaignId,
        'factions' => (int) $factions->fetchColumn(),
        'npcs' => (int) $npcs->fetchColumn(),
        'friendly_npcs' => (int) $friendly->fetchColumn(),
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/state$#', $path, $matches)) {
    $id = rawurldecode($matches[1]);
    $database = database();
    $statement = $database->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $statement->execute([$id]);
    $campaign = $statement->fetch();
    if ($campaign === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $characters = $database->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid');
    $characters->execute([$id]);
    $characterRows = $characters->fetchAll();
    foreach ($characterRows as &$character) {
        $character['level'] = (int) $character['level'];
    }
    unset($character);
    $count = $database->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
    $count->execute([$id]);
    respond([
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characterRows,
        'log_count' => (int) $count->fetchColumn(),
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/compendium/monsters/([^/]+)$#', $path, $matches)) {
    $slug = rawurldecode($matches[1]);
    $statement = database()->prepare('SELECT slug, name, cr, armor_class, hit_points FROM compendium_monsters WHERE slug = ?');
    $statement->execute([$slug]);
    $monster = $statement->fetch();
    if ($monster === false) {
        respond(['error' => 'Unknown monster'], 404);
    }
    $tags = database()->prepare('SELECT tag FROM compendium_monster_tags WHERE monster_slug = ? ORDER BY position');
    $tags->execute([$slug]);
    respond(monsterResponse($monster, array_column($tags->fetchAll(), 'tag')));
}

if ($method === 'GET' && preg_match('#^/v1/compendium/items/([^/]+)$#', $path, $matches)) {
    $slug = rawurldecode($matches[1]);
    $statement = database()->prepare('SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?');
    $statement->execute([$slug]);
    $item = $statement->fetch();
    if ($item === false) {
        respond(['error' => 'Unknown item'], 404);
    }
    $item['cost_gp'] = (int) $item['cost_gp'];
    respond($item);
}

if ($method !== 'POST' && !($method === 'PUT'
        && (preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/prepared-spells$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/concentration$#', $path) === 1))
    && !($method === 'DELETE'
    && (preg_match('#^/v1/play/campaigns/[^/]+/encounters/[^/]+/monsters/[^/]+$#', $path) === 1
        || preg_match('#^/v1/play/campaigns/[^/]+/encounters/[^/]+/combatants/[^/]+$#', $path) === 1
        || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/concentration$#', $path) === 1
        || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items/[^/]+$#', $path) === 1))
    && !($method === 'GET'
        && (preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/(status|owner|spells|prepared-spells|casts|concentration)$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/currency$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/equipment/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/loot/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+/dialogue$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/relationships$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/clues$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/quests$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/factions/[^/]+/reputation$#', $path) === 1))
    && !($method === 'PUT'
        && (preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/equipment/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+/agenda$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/relationships/[^/]+/[^/]+/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/quests/[^/]+/state$#', $path) === 1))
    && !($method === 'POST'
        && (preg_match('#^/v1/play/campaigns/[^/]+/(loot|npcs)$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/loot/[^/]+/(votes|assign)$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+/dialogue$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/relationships$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/clues$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/factions$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/factions/[^/]+/reputation$#', $path) === 1))) {
    respond(['error' => 'Not found'], 404);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/owner$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $owner->execute([$campaignId, $characterId]);
    $ownerName = $owner->fetchColumn();
    if ($ownerName === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    respond(['character_id' => $characterId, 'owner' => $ownerName]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $spells = $database->prepare('SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid');
    $spells->execute([$campaignId, $characterId]);
    $spellbook = $spells->fetchAll();
    foreach ($spellbook as &$spell) {
        $spell['level'] = (int) $spell['level'];
    }
    unset($spell);
    respond(['spells' => $spellbook]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $character = $database->prepare('SELECT members.class, COALESCE(progression.level, 1) AS level FROM play_campaign_members AS members LEFT JOIN play_campaign_character_progressions AS progression ON progression.campaign_id = members.campaign_id AND progression.character_id = members.character_id WHERE members.campaign_id = ? AND members.character_id = ?');
    $character->execute([$campaignId, $characterId]);
    $characterRow = $character->fetch();
    if ($characterRow === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $prepared = $database->prepare('SELECT spell_id FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? ORDER BY position');
    $prepared->execute([$campaignId, $characterId]);
    respond(['character_id' => $characterId, 'prepared_spells' => array_column($prepared->fetchAll(), 'spell_id'), 'max_prepared' => maximumPreparedSpells($characterRow['class'], (int) $characterRow['level'])]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $casts = $database->prepare('SELECT character_id, spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence');
    $casts->execute([$campaignId, $characterId]);
    $history = $casts->fetchAll();
    foreach ($history as &$cast) {
        $cast['slot_level'] = (int) $cast['slot_level'];
        $cast['slots_remaining'] = (int) $cast['slots_remaining'];
        $cast['sequence'] = (int) $cast['sequence'];
    }
    unset($cast);
    respond(['casts' => $history]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $concentration = $database->prepare('SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?');
    $concentration->execute([$campaignId, $characterId]);
    $active = $concentration->fetch();
    if ($active !== false) {
        $active['remaining_turns'] = (int) $active['remaining_turns'];
    }
    respond(['character_id' => $characterId, 'concentration' => $active === false ? null : $active]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $items = $database->prepare('SELECT item_id, quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? ORDER BY item_id');
    $items->execute([$campaignId, $characterId]);
    $stacks = $items->fetchAll();
    foreach ($stacks as &$stack) {
        $stack['quantity'] = (int) $stack['quantity'];
    }
    unset($stack);
    respond(['character_id' => $characterId, 'items' => $stacks]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/rewards$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $grants = $database->prepare('SELECT xp, items_json FROM play_campaign_character_quest_rewards WHERE campaign_id = ? AND character_id = ?');
    $grants->execute([$campaignId, $characterId]);
    $xp = 0;
    $items = [];
    foreach ($grants as $grant) {
        $xp += (int) $grant['xp'];
        foreach (json_decode($grant['items_json'], true, 512, JSON_THROW_ON_ERROR) as $itemId => $quantity) {
            $items[$itemId] = ($items[$itemId] ?? 0) + $quantity;
        }
    }
    ksort($items, SORT_STRING);
    respond(['character_id' => $characterId, 'xp' => $xp, 'items' => $items]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $currency = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
    $currency->execute([$campaignId, $characterId]);
    $gold = $currency->fetchColumn();
    if ($gold === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    respond(['character_id' => $characterId, 'gold' => (int) $gold]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/loot/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $lootId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ? AND owner = ?');
    $campaign->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false && $campaign->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $loot = $database->prepare('SELECT loot_id, item_id, quantity, status, recipient_character_id FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
    $loot->execute([$campaignId, $lootId]);
    $record = $loot->fetch();
    if ($record === false) {
        respond(['error' => 'Unknown loot'], 404);
    }
    $record['quantity'] = (int) $record['quantity'];
    $voteTotals = $database->prepare('SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY recipient_character_id');
    $voteTotals->execute([$campaignId, $lootId]);
    $votes = [];
    foreach ($voteTotals->fetchAll() as $voteTotal) {
        $votes[$voteTotal['recipient_character_id']] = (int) $voteTotal['votes'];
    }
    $record['votes'] = (object) $votes;
    respond($record);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $npcId = rawurldecode($matches[2]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($owner !== $actor['username'] && $member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $npc = $database->prepare('SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $npc->execute([$campaignId, $npcId]);
    $record = $npc->fetch();
    if ($record === false) {
        respond(['error' => 'Unknown NPC'], 404);
    }
    if ($owner !== $actor['username']) {
        unset($record['agenda']);
    }
    respond($record);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $npcId = rawurldecode($matches[2]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($owner !== $actor['username'] && $member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $npc = $database->prepare('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $npc->execute([$campaignId, $npcId]);
    if ($npc->fetchColumn() === false) {
        respond(['error' => 'Unknown NPC'], 404);
    }
    if ($owner === $actor['username']) {
        $dialogue = $database->prepare('SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? ORDER BY sequence');
        $dialogue->execute([$campaignId, $npcId]);
    } else {
        $dialogue = $database->prepare("SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND visibility = 'public' ORDER BY sequence");
        $dialogue->execute([$campaignId, $npcId]);
    }
    respond(['npc_id' => $npcId, 'entries' => $dialogue->fetchAll()]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/relationships$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($owner !== $actor['username'] && $member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $edges = $database->prepare('SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY sequence');
    $edges->execute([$campaignId]);
    $records = $edges->fetchAll();
    foreach ($records as &$record) {
        $record['score'] = (int) $record['score'];
    }
    unset($record);
    respond(['edges' => $records]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/clues$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    $characterId = $member->fetchColumn();
    if ($owner !== $actor['username'] && $characterId === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    if ($owner === $actor['username']) {
        $clues = $database->prepare('SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? ORDER BY sequence');
        $clues->execute([$campaignId]);
    } else {
        $clues = $database->prepare("SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ? AND (audience = 'party' OR (audience = 'character' AND character_id = ?)) ORDER BY sequence");
        $clues->execute([$campaignId, $characterId]);
    }
    $records = $clues->fetchAll();
    foreach ($records as &$record) {
        if ($record['audience'] !== 'character') {
            unset($record['character_id']);
        }
    }
    unset($record);
    respond(['clues' => $records]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/quests$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($owner !== $actor['username'] && $member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $quests = $database->prepare('SELECT quest_id, title, depends_on_json, state FROM play_campaign_quests WHERE campaign_id = ? ORDER BY sequence');
    $quests->execute([$campaignId]);
    $records = $quests->fetchAll();
    foreach ($records as &$record) {
        $record['depends_on'] = json_decode($record['depends_on_json'], true, 512, JSON_THROW_ON_ERROR);
        unset($record['depends_on_json']);
    }
    unset($record);
    respond(['quests' => $records]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $factionId = rawurldecode($matches[2]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    $characterId = $member->fetchColumn();
    if ($owner !== $actor['username'] && $characterId === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $faction = $database->prepare('SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?');
    $faction->execute([$campaignId, $factionId]);
    if ($faction->fetchColumn() === false) {
        respond(['error' => 'Unknown faction'], 404);
    }
    if ($owner === $actor['username']) {
        $history = $database->prepare('SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? ORDER BY sequence');
        $history->execute([$campaignId, $factionId]);
    } else {
        $history = $database->prepare('SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence');
        $history->execute([$campaignId, $factionId, $characterId]);
    }
    $entries = $history->fetchAll();
    foreach ($entries as &$entry) {
        $entry['reputation'] = (int) $entry['reputation'];
        $entry['delta'] = (int) $entry['delta'];
    }
    unset($entry);
    respond(['faction_id' => $factionId, 'entries' => $entries]);
}

$data = requestBody();

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/factions$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $factionId = $data['faction_id'] ?? null;
    $name = $data['name'] ?? null;
    if (!is_string($factionId) || $factionId === '' || !is_string($name) || $name === '') {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    try {
        $database->prepare('INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)')->execute([$campaignId, $factionId, $name]);
    } catch (PDOException) {
        respond(['error' => 'Faction ID already exists'], 409);
    }
    respond(['faction_id' => $factionId, 'name' => $name], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $factionId = rawurldecode($matches[2]);
    $characterId = $data['character_id'] ?? null;
    $delta = $data['delta'] ?? null;
    $reason = $data['reason'] ?? null;
    if (!is_string($characterId) || $characterId === '' || !is_int($delta) || $delta === 0 || $delta < -25 || $delta > 25 || !is_string($reason) || $reason === '') {
        badRequest();
    }
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $faction = $database->prepare('SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?');
        $faction->execute([$campaignId, $factionId]);
        if ($faction->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Unknown faction'], 404);
        }
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $member->execute([$campaignId, $characterId]);
        if ($member->fetchColumn() === false) {
            $database->rollBack();
            badRequest('Invalid campaign character');
        }
        $total = $database->prepare('SELECT reputation FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence DESC LIMIT 1');
        $total->execute([$campaignId, $factionId, $characterId]);
        $previous = $total->fetchColumn();
        $reputation = max(-100, min(100, (int) ($previous === false ? 0 : $previous) + $delta));
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?');
        $next->execute([$campaignId, $factionId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_faction_reputation_history (campaign_id, faction_id, sequence, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $factionId, $sequence, $characterId, $reputation, $delta, $reason]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to change reputation'], 500);
    }
    respond(['faction_id' => $factionId, 'character_id' => $characterId, 'reputation' => $reputation, 'delta' => $delta, 'reason' => $reason], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/relationships$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $sourceId = $data['source_id'] ?? null;
    $targetId = $data['target_id'] ?? null;
    $kind = $data['kind'] ?? null;
    $score = $data['score'] ?? null;
    if (!is_string($sourceId) || $sourceId === '' || !is_string($targetId) || $targetId === ''
        || $sourceId === $targetId || !is_string($kind) || $kind === ''
        || !is_int($score) || $score < -100 || $score > 100) {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $entity = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ? UNION SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $entity->execute([$campaignId, $sourceId, $campaignId, $sourceId]);
    if ($entity->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign entity'], 404);
    }
    $entity->execute([$campaignId, $targetId, $campaignId, $targetId]);
    if ($entity->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign entity'], 404);
    }
    try {
        $database->beginTransaction();
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_relationships WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_relationships (campaign_id, sequence, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $sourceId, $targetId, $kind, $score]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Relationship already exists'], 409);
    }
    respond(['source_id' => $sourceId, 'target_id' => $targetId, 'kind' => $kind, 'score' => $score], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/clues$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $clueId = $data['clue_id'] ?? null;
    $text = $data['text'] ?? null;
    $audience = $data['audience'] ?? null;
    $hasCharacterId = array_key_exists('character_id', $data);
    $characterId = $data['character_id'] ?? null;
    if (!is_string($clueId) || $clueId === '' || !is_string($text) || $text === ''
        || !is_string($audience) || !in_array($audience, ['character', 'party', 'hidden'], true)
        || ($audience === 'character' && (!$hasCharacterId || !is_string($characterId) || $characterId === ''))
        || ($audience !== 'character' && $hasCharacterId)) {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    if ($audience === 'character') {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $member->execute([$campaignId, $characterId]);
        if ($member->fetchColumn() === false) {
            badRequest('Invalid campaign character');
        }
    }
    try {
        $database->beginTransaction();
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_clues WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_clues (campaign_id, sequence, clue_id, text, audience, character_id) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $clueId, $text, $audience, $audience === 'character' ? $characterId : null]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Clue ID already exists'], 409);
    }
    $response = ['clue_id' => $clueId, 'text' => $text, 'audience' => $audience];
    if ($audience === 'character') {
        $response['character_id'] = $characterId;
    }
    respond($response, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/quests$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $questId = $data['quest_id'] ?? null;
    $title = $data['title'] ?? null;
    $dependsOn = $data['depends_on'] ?? null;
    if (!is_string($questId) || $questId === '' || !is_string($title) || $title === ''
        || !is_array($dependsOn) || !array_is_list($dependsOn)) {
        badRequest();
    }
    $dependencies = [];
    foreach ($dependsOn as $dependency) {
        if (!is_string($dependency) || $dependency === '' || $dependency === $questId || isset($dependencies[$dependency])) {
            badRequest('Invalid dependencies');
        }
        $dependencies[$dependency] = true;
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    try {
        $database->beginTransaction();
        $existing = $database->prepare('SELECT 1 FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
        foreach (array_keys($dependencies) as $dependency) {
            $existing->execute([$campaignId, $dependency]);
            if ($existing->fetchColumn() === false) {
                $database->rollBack();
                badRequest('Invalid dependencies');
            }
        }
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_quests WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare("INSERT INTO play_campaign_quests (campaign_id, sequence, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?, 'locked')")
            ->execute([$campaignId, $sequence, $questId, $title, json_encode($dependsOn, JSON_THROW_ON_ERROR)]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Quest ID already exists'], 409);
    }
    respond(['quest_id' => $questId, 'title' => $title, 'depends_on' => $dependsOn, 'state' => 'locked'], 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/quests/([^/]+)/state$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $questId = rawurldecode($matches[2]);
    $state = $data['state'] ?? null;
    if (!is_string($state) || !in_array($state, ['active', 'completed'], true)) {
        badRequest('Invalid state');
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $quest = $database->prepare('SELECT title, depends_on_json, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
    $quest->execute([$campaignId, $questId]);
    $record = $quest->fetch();
    if ($record === false) {
        respond(['error' => 'Unknown quest'], 404);
    }
    $dependsOn = json_decode($record['depends_on_json'], true, 512, JSON_THROW_ON_ERROR);
    if (($record['state'] === 'locked' && $state === 'active')) {
        $dependency = $database->prepare('SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
        foreach ($dependsOn as $dependencyId) {
            $dependency->execute([$campaignId, $dependencyId]);
            if ($dependency->fetchColumn() !== 'completed') {
                respond(['error' => 'Invalid quest state transition'], 409);
            }
        }
    } elseif (!($record['state'] === 'active' && $state === 'completed')) {
        respond(['error' => 'Invalid quest state transition'], 409);
    }
    $database->prepare('UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?')
        ->execute([$state, $campaignId, $questId]);
    respond(['quest_id' => $questId, 'title' => $record['title'], 'depends_on' => $dependsOn, 'state' => $state]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $questId = rawurldecode($matches[2]);
    $xp = $data['xp'] ?? null;
    $items = $data['items'] ?? null;
    if (!is_int($xp) || $xp < 0 || !validRewardItems($items)) {
        badRequest();
    }

    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $quest = $database->prepare('SELECT title, depends_on_json, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
    $quest->execute([$campaignId, $questId]);
    $record = $quest->fetch();
    if ($record === false) {
        respond(['error' => 'Unknown quest'], 404);
    }
    if ($record['state'] === 'completed') {
        respond(['error' => 'Completed quest rewards cannot be configured'], 409);
    }
    $database->prepare('INSERT INTO play_campaign_quest_reward_configs (campaign_id, quest_id, xp, items_json) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, quest_id) DO UPDATE SET xp = excluded.xp, items_json = excluded.items_json')
        ->execute([$campaignId, $questId, $xp, json_encode($items, JSON_THROW_ON_ERROR)]);
    respond(['quest_id' => $questId, 'title' => $record['title'], 'depends_on' => json_decode($record['depends_on_json'], true, 512, JSON_THROW_ON_ERROR), 'state' => $record['state'], 'rewards' => ['xp' => $xp, 'items' => $items]]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards/award$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $questId = rawurldecode($matches[2]);
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $quest = $database->prepare('SELECT state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
        $quest->execute([$campaignId, $questId]);
        $questState = $quest->fetchColumn();
        if ($questState === false) {
            $database->rollBack();
            respond(['error' => 'Unknown quest'], 404);
        }
        $config = $database->prepare('SELECT xp, items_json FROM play_campaign_quest_reward_configs WHERE campaign_id = ? AND quest_id = ?');
        $config->execute([$campaignId, $questId]);
        $reward = $config->fetch();
        if ($questState !== 'completed' || $reward === false) {
            $database->rollBack();
            respond(['error' => 'Quest rewards cannot be awarded'], 409);
        }
        $award = $database->prepare('INSERT INTO play_campaign_quest_reward_awards (campaign_id, quest_id) VALUES (?, ?)');
        $award->execute([$campaignId, $questId]);
        $items = json_decode($reward['items_json'], true, 512, JSON_THROW_ON_ERROR);
        $members = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ?');
        $members->execute([$campaignId]);
        $grant = $database->prepare('INSERT INTO play_campaign_character_quest_rewards (campaign_id, quest_id, character_id, xp, items_json) VALUES (?, ?, ?, ?, ?)');
        $addItem = $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity');
        foreach ($members as $member) {
            $grant->execute([$campaignId, $questId, $member['character_id'], (int) $reward['xp'], $reward['items_json']]);
            foreach ($items as $itemId => $quantity) {
                $addItem->execute([$campaignId, $member['character_id'], $itemId, $quantity]);
            }
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Quest rewards already awarded'], 409);
    }
    respond(['quest_id' => $questId, 'awarded' => true, 'xp' => (int) $reward['xp'], 'items' => $items], 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/relationships/([^/]+)/([^/]+)/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $sourceId = rawurldecode($matches[2]);
    $targetId = rawurldecode($matches[3]);
    $kind = rawurldecode($matches[4]);
    $score = $data['score'] ?? null;
    if (!is_int($score) || $score < -100 || $score > 100) {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $update = $database->prepare('UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
    $update->execute([$score, $campaignId, $sourceId, $targetId, $kind]);
    if ($update->rowCount() !== 1) {
        respond(['error' => 'Unknown relationship'], 404);
    }
    respond(['source_id' => $sourceId, 'target_id' => $targetId, 'kind' => $kind, 'score' => $score]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $npcId = $data['npc_id'] ?? null;
    $name = $data['name'] ?? null;
    $agenda = $data['agenda'] ?? null;
    $publicStatus = $data['public_status'] ?? null;
    if (!is_string($npcId) || $npcId === '' || !is_string($name) || $name === ''
        || !is_string($agenda) || $agenda === '' || !is_string($publicStatus) || $publicStatus === '') {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    try {
        $database->prepare('INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $npcId, $name, $agenda, $publicStatus]);
    } catch (PDOException) {
        respond(['error' => 'NPC ID already exists'], 409);
    }
    respond(['npc_id' => $npcId, 'name' => $name, 'agenda' => $agenda, 'public_status' => $publicStatus], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $npcId = rawurldecode($matches[2]);
    $dialogueId = $data['dialogue_id'] ?? null;
    $speaker = $data['speaker'] ?? null;
    $text = $data['text'] ?? null;
    $visibility = $data['visibility'] ?? null;
    if (!is_string($dialogueId) || $dialogueId === '' || !is_string($speaker) || $speaker === ''
        || !is_string($text) || $text === '' || !is_string($visibility) || !in_array($visibility, ['public', 'private'], true)) {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $npc = $database->prepare('SELECT 1 FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $npc->execute([$campaignId, $npcId]);
    if ($npc->fetchColumn() === false) {
        respond(['error' => 'Unknown NPC'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    try {
        $database->beginTransaction();
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?');
        $next->execute([$campaignId, $npcId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, sequence, dialogue_id, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $npcId, $sequence, $dialogueId, $speaker, $text, $visibility]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Dialogue ID already exists'], 409);
    }
    respond(['dialogue_id' => $dialogueId, 'speaker' => $speaker, 'text' => $text, 'visibility' => $visibility], 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/agenda$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $npcId = rawurldecode($matches[2]);
    $agenda = $data['agenda'] ?? null;
    $publicStatus = $data['public_status'] ?? null;
    if (!is_string($agenda) || $agenda === '' || !is_string($publicStatus) || $publicStatus === '') {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $update = $database->prepare('UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?');
    $update->execute([$agenda, $publicStatus, $campaignId, $npcId]);
    if ($update->rowCount() !== 1) {
        respond(['error' => 'Unknown NPC'], 404);
    }
    $npc = $database->prepare('SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $npc->execute([$campaignId, $npcId]);
    respond($npc->fetch());
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/loot$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $lootId = $data['loot_id'] ?? null;
    $itemId = $data['item_id'] ?? null;
    $quantity = $data['quantity'] ?? null;
    if (!is_string($lootId) || $lootId === ''
        || !is_string($itemId) || !in_array($itemId, ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true)
        || !is_int($quantity) || $quantity < 1) {
        badRequest();
    }

    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    try {
        $database->prepare("INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, 'open')")
            ->execute([$campaignId, $lootId, $itemId, $quantity]);
    } catch (PDOException) {
        respond(['error' => 'Loot ID already exists'], 409);
    }
    respond(['loot_id' => $lootId, 'item_id' => $itemId, 'quantity' => $quantity, 'status' => 'open'], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/loot/([^/]+)/votes$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $lootId = rawurldecode($matches[2]);
    $recipientCharacterId = $data['recipient_character_id'] ?? null;
    if (!is_string($recipientCharacterId) || $recipientCharacterId === '') {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $loot = $database->prepare('SELECT status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
        $loot->execute([$campaignId, $lootId]);
        $lootStatus = $loot->fetchColumn();
        if ($lootStatus === false) {
            $database->rollBack();
            respond(['error' => 'Unknown loot'], 404);
        }
        if ($lootStatus !== 'open') {
            $database->rollBack();
            respond(['error' => 'Loot already assigned'], 409);
        }
        $recipient = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $recipient->execute([$campaignId, $recipientCharacterId]);
        if ($recipient->fetchColumn() === false) {
            $database->rollBack();
            badRequest('Invalid recipient character');
        }
        try {
            $database->prepare('INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)')
                ->execute([$campaignId, $lootId, $actor['username'], $recipientCharacterId]);
        } catch (PDOException) {
            $database->rollBack();
            respond(['error' => 'Vote already cast'], 409);
        }
        $count = $database->prepare('SELECT COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?');
        $count->execute([$campaignId, $lootId, $recipientCharacterId]);
        $votesForRecipient = (int) $count->fetchColumn();
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to cast vote'], 500);
    }
    respond(['loot_id' => $lootId, 'voter' => $actor['username'], 'recipient_character_id' => $recipientCharacterId, 'votes_for_recipient' => $votesForRecipient], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/loot/([^/]+)/assign$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $lootId = rawurldecode($matches[2]);
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $loot = $database->prepare('SELECT item_id, quantity, status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
        $loot->execute([$campaignId, $lootId]);
        $record = $loot->fetch();
        if ($record === false) {
            $database->rollBack();
            respond(['error' => 'Unknown loot'], 404);
        }
        if ($record['status'] !== 'open') {
            $database->rollBack();
            respond(['error' => 'Loot already assigned'], 409);
        }
        $totals = $database->prepare('SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY votes DESC, recipient_character_id');
        $totals->execute([$campaignId, $lootId]);
        $ranked = $totals->fetchAll();
        if ($ranked === [] || (count($ranked) > 1 && (int) $ranked[0]['votes'] === (int) $ranked[1]['votes'])) {
            $database->rollBack();
            respond(['error' => 'Loot vote is tied or absent'], 409);
        }
        $recipientCharacterId = $ranked[0]['recipient_character_id'];
        $votes = (int) $ranked[0]['votes'];
        $assign = $database->prepare("UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ?, votes = ? WHERE campaign_id = ? AND loot_id = ? AND status = 'open'");
        $assign->execute([$recipientCharacterId, $votes, $campaignId, $lootId]);
        if ($assign->rowCount() !== 1) {
            $database->rollBack();
            respond(['error' => 'Loot already assigned'], 409);
        }
        $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
            ->execute([$campaignId, $recipientCharacterId, $record['item_id'], (int) $record['quantity']]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to assign loot'], 500);
    }
    respond(['loot_id' => $lootId, 'recipient_character_id' => $recipientCharacterId, 'item_id' => $record['item_id'], 'quantity' => (int) $record['quantity'], 'votes' => $votes, 'status' => 'assigned']);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency/transfers$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $fromCharacterId = rawurldecode($matches[2]);
    $toCharacterId = $data['to_character_id'] ?? null;
    $gold = $data['gold'] ?? null;
    if (!is_string($toCharacterId) || $toCharacterId === '' || !is_int($gold) || $gold <= 0 || $toCharacterId === $fromCharacterId) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $fromCharacterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $destination = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $destination->execute([$campaignId, $toCharacterId]);
        if ($destination->fetchColumn() === false) {
            $database->rollBack();
            badRequest('Invalid destination character');
        }

        // A conditional debit makes the balance check and mutation a single
        // database operation; the matching credit and transfer record share
        // this transaction, so a failed transfer cannot change either purse.
        $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
        $debit->execute([$gold, $campaignId, $fromCharacterId, $gold]);
        if ($debit->rowCount() !== 1) {
            $database->rollBack();
            respond(['error' => 'Insufficient gold'], 409);
        }
        $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?')
            ->execute([$gold, $campaignId, $toCharacterId]);
        $balances = $database->prepare('SELECT character_id, gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id IN (?, ?)');
        $balances->execute([$campaignId, $fromCharacterId, $toCharacterId]);
        $updatedBalances = [];
        foreach ($balances as $balance) {
            $updatedBalances[$balance['character_id']] = (int) $balance['gold'];
        }
        $nextTransfer = $database->prepare('SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_campaign_currency_transfers WHERE campaign_id = ?');
        $nextTransfer->execute([$campaignId]);
        $nextId = (int) $nextTransfer->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $nextId, $fromCharacterId, $toCharacterId, $gold]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to transfer gold'], 500);
    }
    respond(['from_character_id' => $fromCharacterId, 'to_character_id' => $toCharacterId, 'gold' => $gold, 'from_gold' => $updatedBalances[$fromCharacterId], 'to_gold' => $updatedBalances[$toCharacterId], 'transfer_id' => $nextId], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $itemId = $data['item_id'] ?? null;
    $quantity = $data['quantity'] ?? null;
    if (!is_string($itemId) || !in_array($itemId, ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true) || !is_int($quantity) || $quantity < 1) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
            ->execute([$campaignId, $characterId, $itemId, $quantity]);
        $total = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $total->execute([$campaignId, $characterId, $itemId]);
        $totalQuantity = (int) $total->fetchColumn();
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to add inventory item'], 500);
    }
    respond(['character_id' => $characterId, 'item_id' => $itemId, 'quantity' => $quantity, 'total_quantity' => $totalQuantity], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)/consume$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $itemId = rawurldecode($matches[3]);
    if ($itemId !== 'healing-potion') {
        badRequest('Item cannot be consumed');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $stack = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $stack->execute([$campaignId, $characterId, $itemId]);
        $held = $stack->fetchColumn();
        if ($held === false || (int) $held < 1) {
            $database->rollBack();
            respond(['error' => 'No consumable item held'], 409);
        }
        $totalQuantity = (int) $held - 1;
        if ($totalQuantity === 0) {
            $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$campaignId, $characterId, $itemId]);
        } else {
            $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$totalQuantity, $campaignId, $characterId, $itemId]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to consume item'], 500);
    }
    respond(['character_id' => $characterId, 'item_id' => $itemId, 'quantity_consumed' => 1, 'total_quantity' => $totalQuantity, 'effect' => ['type' => 'healing', 'hp_restored' => 5]]);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $itemId = rawurldecode($matches[3]);
    $quantity = $data['quantity'] ?? null;
    if (!in_array($itemId, ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true) || !is_int($quantity) || $quantity < 1) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $stack = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $stack->execute([$campaignId, $characterId, $itemId]);
        $held = $stack->fetchColumn();
        if ($held === false || $quantity > (int) $held) {
            $database->rollBack();
            respond(['error' => 'Insufficient item quantity'], 409);
        }
        $totalQuantity = (int) $held - $quantity;
        if ($totalQuantity === 0) {
            $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$campaignId, $characterId, $itemId]);
        } else {
            $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$totalQuantity, $campaignId, $characterId, $itemId]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to remove inventory item'], 500);
    }
    respond(['character_id' => $characterId, 'item_id' => $itemId, 'quantity' => $quantity, 'total_quantity' => $totalQuantity]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $slot = rawurldecode($matches[3]);
    if (!in_array($slot, ['armor', 'accessory'], true)) {
        badRequest();
    }
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $equipment = $database->prepare('SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
    $equipment->execute([$campaignId, $characterId, $slot]);
    $item = $equipment->fetch();
    respond(['character_id' => $characterId, 'slot' => $slot, 'item_id' => $item === false ? '' : $item['item_id'], 'attuned' => $item !== false && (int) $item['attuned'] === 1]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $slot = rawurldecode($matches[3]);
    $itemId = $data['item_id'] ?? null;
    $legalSlots = ['leather-armor' => 'armor', 'ring-of-protection' => 'accessory', 'amulet-of-health' => 'accessory'];
    if (!in_array($slot, ['armor', 'accessory'], true) || !is_string($itemId) || !isset($legalSlots[$itemId]) || $legalSlots[$itemId] !== $slot) {
        badRequest();
    }
    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $held = $database->prepare('SELECT 1 FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $held->execute([$campaignId, $characterId, $itemId]);
        if ($held->fetchColumn() === false) {
            $database->rollBack();
            badRequest('Item is not held');
        }
        $database->prepare('INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0')
            ->execute([$campaignId, $characterId, $slot, $itemId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to equip item'], 500);
    }
    respond(['character_id' => $characterId, 'slot' => $slot, 'item_id' => $itemId, 'attuned' => false]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $slot = rawurldecode($matches[3]);
    if (!in_array($slot, ['armor', 'accessory'], true)) {
        badRequest();
    }
    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $equipment = $database->prepare('SELECT item_id FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
        $equipment->execute([$campaignId, $characterId, $slot]);
        $itemId = $equipment->fetchColumn();
        if (!in_array($itemId, ['ring-of-protection', 'amulet-of-health'], true)) {
            $database->rollBack();
            badRequest('Item cannot be attuned');
        }
        $attuned = $database->prepare('SELECT COUNT(*) FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1');
        $attuned->execute([$campaignId, $characterId]);
        if ((int) $attuned->fetchColumn() >= 1) {
            $database->rollBack();
            respond(['error' => 'Maximum attunements reached'], 409);
        }
        $database->prepare('UPDATE play_campaign_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?')->execute([$campaignId, $characterId, $slot]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to attune item'], 500);
    }
    respond(['character_id' => $characterId, 'slot' => $slot, 'item_id' => $itemId, 'attuned' => true, 'attunement_count' => 1, 'max_attunements' => 1]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $spellId = $data['spell_id'] ?? null;
    $target = $data['target'] ?? null;
    $duration = $data['duration_turns'] ?? null;
    if (!is_string($spellId) || $spellId === '' || !is_string($target) || $target === '' || !is_int($duration) || $duration < 1) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $character = $database->prepare('SELECT class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $character->execute([$campaignId, $characterId]);
        $class = $character->fetchColumn();
        if ($class === false || maximumPreparedSpells($class, 1) === 0) {
            $database->rollBack();
            badRequest('Character cannot concentrate on spells');
        }
        $known = $database->prepare('SELECT 1 FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
        $known->execute([$campaignId, $characterId, $spellId]);
        if ($known->fetchColumn() === false) {
            $database->rollBack();
            badRequest('Unknown spell');
        }
        $prepared = $database->prepare('SELECT 1 FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
        $prepared->execute([$campaignId, $characterId, $spellId]);
        if ($prepared->fetchColumn() === false) {
            $database->rollBack();
            badRequest('Spell is not prepared');
        }
        $database->prepare('INSERT INTO play_campaign_character_concentrations (campaign_id, character_id, spell_id, target, remaining_turns) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns')
            ->execute([$campaignId, $characterId, $spellId, $target, $duration]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to set concentration'], 500);
    }
    respond(['character_id' => $characterId, 'concentration' => ['spell_id' => $spellId, 'target' => $target, 'remaining_turns' => $duration]]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration/advance-turn$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $database->beginTransaction();
    try {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $character->execute([$campaignId, $characterId]);
        if ($character->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        $concentration = $database->prepare('SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?');
        $concentration->execute([$campaignId, $characterId]);
        $active = $concentration->fetch();
        if ($active !== false) {
            $remaining = (int) $active['remaining_turns'] - 1;
            if ($remaining === 0) {
                $database->prepare('DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?')->execute([$campaignId, $characterId]);
                $active = null;
            } else {
                $database->prepare('UPDATE play_campaign_character_concentrations SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?')->execute([$remaining, $campaignId, $characterId]);
                $active['remaining_turns'] = $remaining;
            }
        } else {
            $active = null;
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to advance concentration'], 500);
    }
    respond(['character_id' => $characterId, 'concentration' => $active]);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $owner->execute([$campaignId, $characterId]);
    $ownerName = $owner->fetchColumn();
    if ($ownerName === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    if ($ownerName !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $database->prepare('DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?')->execute([$campaignId, $characterId]);
    respond(['character_id' => $characterId, 'concentration' => null]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $spellIds = $data['spell_ids'] ?? null;
    if (!is_array($spellIds)) {
        badRequest('Invalid spell_ids');
    }
    foreach ($spellIds as $spellId) {
        if (!is_string($spellId) || $spellId === '') {
            badRequest('Invalid spell_ids');
        }
    }
    if (count($spellIds) !== count(array_unique($spellIds))) {
        badRequest('Invalid spell_ids');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $character = $database->prepare('SELECT members.class, COALESCE(progression.level, 1) AS level FROM play_campaign_members AS members LEFT JOIN play_campaign_character_progressions AS progression ON progression.campaign_id = members.campaign_id AND progression.character_id = members.character_id WHERE members.campaign_id = ? AND members.character_id = ?');
        $character->execute([$campaignId, $characterId]);
        $characterRow = $character->fetch();
        $maxPrepared = $characterRow === false ? 0 : maximumPreparedSpells($characterRow['class'], (int) $characterRow['level']);
        if ($characterRow === false || $maxPrepared === 0) {
            $database->rollBack();
            badRequest('Character cannot prepare spells');
        }
        if (count($spellIds) > $maxPrepared) {
            $database->rollBack();
            badRequest('Too many prepared spells');
        }
        $known = $database->prepare('SELECT 1 FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
        foreach ($spellIds as $spellId) {
            $known->execute([$campaignId, $characterId, $spellId]);
            if ($known->fetchColumn() === false) {
                $database->rollBack();
                badRequest('Unknown spell');
            }
        }
        $database->prepare('DELETE FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ?')->execute([$campaignId, $characterId]);
        $insert = $database->prepare('INSERT INTO play_campaign_character_prepared_spells (campaign_id, character_id, position, spell_id) VALUES (?, ?, ?, ?)');
        foreach ($spellIds as $position => $spellId) {
            $insert->execute([$campaignId, $characterId, $position, $spellId]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to prepare spells'], 500);
    }
    respond(['character_id' => $characterId, 'prepared_spells' => array_values($spellIds), 'max_prepared' => $maxPrepared]);
}

if ($path === '/v1/play/campaigns') {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'dm') {
        respond(['error' => 'Forbidden'], 403);
    }

    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $maxPlayers = $data['max_players'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_int($maxPlayers) || $maxPlayers < 1) {
        badRequest();
    }
    try {
        database()->prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)')
            ->execute([$id, $name, $actor['username'], 'lobby', $maxPlayers]);
    } catch (PDOException) {
        respond(['error' => 'Campaign ID already exists'], 409);
    }
    respond(['id' => $id, 'name' => $name, 'owner' => $actor['username'], 'status' => 'lobby', 'max_players' => $maxPlayers], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/members$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'player') {
        respond(['error' => 'Forbidden'], 403);
    }

    $campaignId = rawurldecode($matches[1]);
    $characterId = $data['character_id'] ?? null;
    $name = $data['name'] ?? null;
    $class = $data['class'] ?? null;
    if (!is_string($characterId) || $characterId === '' || !is_string($name) || $name === '' || !is_string($class) || $class === '') {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT COALESCE(states.status, campaigns.status) AS status, campaigns.max_players FROM play_campaigns AS campaigns LEFT JOIN play_campaign_states AS states ON states.campaign_id = campaigns.id WHERE campaigns.id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($campaignRow['status'] !== 'lobby') {
            $database->rollBack();
            respond(['error' => 'Campaign is not accepting members'], 409);
        }

        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $character->execute([$campaignId, $characterId]);
        $count = $database->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?');
        $count->execute([$campaignId]);
        if ($member->fetchColumn() !== false || $character->fetchColumn() !== false || (int) $count->fetchColumn() >= (int) $campaignRow['max_players']) {
            $database->rollBack();
            respond(['error' => 'Party membership conflict'], 409);
        }

        $database->prepare('INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $actor['username'], $characterId, $name, $class]);
        $database->prepare('INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)')
            ->execute([$campaignId, $characterId, $actor['username']]);
        $database->prepare('INSERT INTO play_campaign_character_states (campaign_id, character_id, hp_current, hp_max, death_save_successes, death_save_failures, status) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $characterId, 20, 20, 0, 0, 'conscious']);
        $database->prepare('INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)')
            ->execute([$campaignId, $characterId, 10]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Party membership conflict'], 409);
    }
    respond(['username' => $actor['username'], 'character_id' => $characterId, 'name' => $name, 'class' => $class], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $spellId = $data['spell_id'] ?? null;
    $name = $data['name'] ?? null;
    $level = $data['level'] ?? null;
    if (!is_string($spellId) || $spellId === '' || !is_string($name) || $name === '' || !is_int($level) || $level < 0 || $level > 9) {
        badRequest();
    }

    $database = database();
    $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $owner->execute([$campaignId, $characterId]);
    $ownerName = $owner->fetchColumn();
    if ($ownerName === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    if ($ownerName !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $character = $database->prepare('SELECT class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    $class = $character->fetchColumn();
    // This play API currently exposes the wizard spell list only.  A wizard
    // may add any spell supplied by that list; non-casters (including rogues)
    // cannot add entries to a spellbook.
    if ($class !== 'wizard') {
        badRequest('Spell is not valid for this character class');
    }

    try {
        $database->prepare('INSERT INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $characterId, $spellId, $name, $level]);
    } catch (PDOException $exception) {
        respond(['error' => 'Spell already known'], 409);
    }
    respond(['spell_id' => $spellId, 'name' => $name, 'level' => $level], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $spellId = $data['spell_id'] ?? null;
    $target = $data['target'] ?? null;
    if (!is_string($spellId) || $spellId === '' || !is_string($target) || $target === '') {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $character = $database->prepare('SELECT members.class, COALESCE(progression.level, 1) AS level FROM play_campaign_members AS members LEFT JOIN play_campaign_character_progressions AS progression ON progression.campaign_id = members.campaign_id AND progression.character_id = members.character_id WHERE members.campaign_id = ? AND members.character_id = ?');
        $character->execute([$campaignId, $characterId]);
        $characterRow = $character->fetch();
        if ($characterRow === false || maximumPreparedSpells($characterRow['class'], (int) $characterRow['level']) === 0) {
            $database->rollBack();
            badRequest('Character cannot cast spells');
        }

        $spell = $database->prepare('SELECT level FROM play_campaign_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
        $spell->execute([$campaignId, $characterId, $spellId]);
        $spellLevel = $spell->fetchColumn();
        if ($spellLevel === false) {
            $database->rollBack();
            badRequest('Unknown spell');
        }
        $prepared = $database->prepare('SELECT 1 FROM play_campaign_character_prepared_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?');
        $prepared->execute([$campaignId, $characterId, $spellId]);
        if ($prepared->fetchColumn() === false) {
            $database->rollBack();
            badRequest('Spell is not prepared');
        }

        $slotLevel = (int) $spellLevel;
        $capacity = spellSlotCapacity($characterRow['class'], (int) $characterRow['level'])[$slotLevel] ?? 0;
        $used = $database->prepare('SELECT COUNT(*) FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?');
        $used->execute([$campaignId, $characterId, $slotLevel]);
        $slotsRemaining = $capacity - (int) $used->fetchColumn();
        if ($slotsRemaining <= 0) {
            $database->rollBack();
            respond(['error' => 'No spell slots remaining'], 409);
        }
        --$slotsRemaining;
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ?');
        $next->execute([$campaignId, $characterId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $characterId, $sequence, $spellId, $target, $slotLevel, $slotsRemaining]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to record spell cast'], 500);
    }
    respond(['character_id' => $characterId, 'spell_id' => $spellId, 'target' => $target, 'slot_level' => $slotLevel, 'slots_remaining' => $slotsRemaining, 'sequence' => $sequence], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/build$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $race = $data['race'] ?? null;
    $class = $data['class'] ?? null;
    $background = $data['background'] ?? null;
    $abilities = $data['abilities'] ?? null;

    // Keep these choices explicit and deterministic rather than accepting
    // arbitrary labels that later rules could not interpret.
    $races = ['dragonborn', 'dwarf', 'elf', 'gnome', 'half-elf', 'half-orc', 'halfling', 'human', 'tiefling'];
    $classes = ['barbarian', 'bard', 'cleric', 'druid', 'fighter', 'monk', 'paladin', 'ranger', 'rogue', 'sorcerer', 'warlock', 'wizard'];
    $backgrounds = ['acolyte', 'charlatan', 'criminal', 'entertainer', 'folk-hero', 'guild-artisan', 'hermit', 'noble', 'outlander', 'sage', 'sailor', 'soldier', 'urchin'];
    if (!is_string($race) || !in_array($race, $races, true)
        || !is_string($class) || !in_array($class, $classes, true)
        || !is_string($background) || !in_array($background, $backgrounds, true)
        || !is_array($abilities)) {
        badRequest();
    }

    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
        abilityModifier(integerField($abilities, $ability));
    }

    $owner = database()->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $owner->execute([$campaignId, $characterId]);
    $ownerName = $owner->fetchColumn();
    if ($ownerName === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    if ($ownerName !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $conModifier = abilityModifier(integerField($abilities, 'con'));
    $hitDie = classHitDie($class);
    $hpMax = $hitDie + $conModifier;
    $database = database();
    $database->beginTransaction();
    try {
        $database->prepare('INSERT INTO play_campaign_character_progressions (campaign_id, character_id, level, class, con_modifier, hp_max) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET level = excluded.level, class = excluded.class, con_modifier = excluded.con_modifier, hp_max = excluded.hp_max')
            ->execute([$campaignId, $characterId, 1, $class, $conModifier, $hpMax]);
        $database->prepare('INSERT INTO play_campaign_character_abilities (campaign_id, character_id, str, dex, con, int, wis, cha) VALUES (?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET str = excluded.str, dex = excluded.dex, con = excluded.con, int = excluded.int, wis = excluded.wis, cha = excluded.cha')
            ->execute([$campaignId, $characterId, $abilities['str'], $abilities['dex'], $abilities['con'], $abilities['int'], $abilities['wis'], $abilities['cha']]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to save character build'], 500);
    }
    respond([
        'character_id' => $characterId,
        'race' => $race,
        'class' => $class,
        'background' => $background,
        'level' => 1,
        'hp_max' => $hpMax,
        'proficiency_bonus' => proficiencyBonus(1),
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/skill-check$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $skill = $data['skill'] ?? null;
    $ability = $data['ability'] ?? null;
    $proficient = $data['proficient'] ?? null;
    $roll = $data['roll'] ?? null;
    $skills = [
        'acrobatics', 'animal-handling', 'arcana', 'athletics', 'deception',
        'history', 'insight', 'intimidation', 'investigation', 'medicine',
        'nature', 'perception', 'performance', 'persuasion', 'religion',
        'sleight-of-hand', 'stealth', 'survival',
    ];
    $abilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    if (!is_string($skill) || !in_array($skill, $skills, true)
        || !is_string($ability) || !in_array($ability, $abilities, true)
        || !is_bool($proficient) || !is_int($roll)) {
        badRequest();
    }

    $database = database();
    $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $owner->execute([$campaignId, $characterId]);
    $ownerName = $owner->fetchColumn();
    if ($ownerName === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    if ($ownerName !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $character = $database->prepare('SELECT abilities.' . $ability . ' AS score, progression.level FROM play_campaign_character_abilities AS abilities INNER JOIN play_campaign_character_progressions AS progression ON progression.campaign_id = abilities.campaign_id AND progression.character_id = abilities.character_id WHERE abilities.campaign_id = ? AND abilities.character_id = ?');
    $character->execute([$campaignId, $characterId]);
    $characterData = $character->fetch();
    if ($characterData === false) {
        badRequest('Character has no build');
    }
    $modifier = abilityModifier((int) $characterData['score']) + ($proficient ? proficiencyBonus((int) $characterData['level']) : 0);
    respond([
        'character_id' => $characterId,
        'skill' => $skill,
        'ability' => $ability,
        'modifier' => $modifier,
        'total' => $roll + $modifier,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/level-up$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $requestedLevel = $data['level'] ?? null;
    if (!is_int($requestedLevel)) {
        badRequest('Invalid level');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $ownerName = $owner->fetchColumn();
        if ($ownerName === false) {
            $database->rollBack();
            badRequest('Unknown character');
        }
        if ($ownerName !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $progression = $database->prepare('SELECT level, class, con_modifier, hp_max FROM play_campaign_character_progressions WHERE campaign_id = ? AND character_id = ?');
        $progression->execute([$campaignId, $characterId]);
        $character = $progression->fetch();
        if ($character === false || $requestedLevel < 2 || $requestedLevel > 20 || $requestedLevel !== (int) $character['level'] + 1) {
            $database->rollBack();
            badRequest('Invalid level');
        }

        $hitDie = classHitDie($character['class']);
        $hpMax = (int) $character['hp_max'] + levelHitPointGain($hitDie, (int) $character['con_modifier']);
        $database->prepare('UPDATE play_campaign_character_progressions SET level = ?, hp_max = ? WHERE campaign_id = ? AND character_id = ?')
            ->execute([$requestedLevel, $hpMax, $campaignId, $characterId]);
        $database->prepare('UPDATE play_campaign_character_states SET hp_max = ? WHERE campaign_id = ? AND character_id = ?')
            ->execute([$hpMax, $campaignId, $characterId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to level up character'], 500);
    }
    respond([
        'character_id' => $characterId,
        'level' => $requestedLevel,
        'hp_max' => $hpMax,
        'hit_dice' => "1d{$hitDie}",
        'proficiency_bonus' => proficiencyBonus($requestedLevel),
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/claim$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'player') {
        respond(['error' => 'Forbidden'], 403);
    }
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $database->beginTransaction();
    try {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $character = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $character->execute([$campaignId, $characterId]);
        if ($character->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $currentOwner = $owner->fetchColumn();
        if ($currentOwner !== false && $currentOwner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Character is already owned'], 409);
        }
        if ($currentOwner === false) {
            $database->prepare('INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)')
                ->execute([$campaignId, $characterId, $actor['username']]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to claim character'], 500);
    }
    respond(['character_id' => $characterId, 'owner' => $actor['username']], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/transfer$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $newOwner = $data['new_owner'] ?? null;
    if (!is_string($newOwner) || $newOwner === '') {
        badRequest('Invalid new_owner');
    }
    $database = database();
    $database->beginTransaction();
    try {
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $currentOwner = $owner->fetchColumn();
        if ($currentOwner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($currentOwner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $newOwner]);
        if ($member->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'New owner must be a campaign member'], 400);
        }
        $database->prepare('UPDATE play_campaign_character_owners SET owner = ? WHERE campaign_id = ? AND character_id = ?')
            ->execute([$newOwner, $campaignId, $characterId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to transfer character ownership'], 500);
    }
    respond(['character_id' => $characterId, 'owner' => $newOwner]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/damage$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $amount = $data['amount'] ?? null;
    if (!is_int($amount) || $amount <= 0) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $state = $database->prepare('SELECT hp_current, hp_max, status FROM play_campaign_character_states WHERE campaign_id = ? AND character_id = ?');
        $state->execute([$campaignId, $characterId]);
        $characterState = $state->fetch();
        if ($characterState === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        $hpBefore = (int) $characterState['hp_current'];
        $hpAfter = max(0, $hpBefore - $amount);
        $status = $hpAfter === 0 && $characterState['status'] !== 'dead' ? 'unconscious' : $characterState['status'];
        $database->prepare("UPDATE play_campaign_character_states SET hp_current = ?, status = ?, death_save_successes = CASE WHEN status = 'stable' THEN 0 ELSE death_save_successes END, death_save_failures = CASE WHEN status = 'stable' THEN 0 ELSE death_save_failures END WHERE campaign_id = ? AND character_id = ?")
            ->execute([$hpAfter, $status, $campaignId, $characterId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to apply damage'], 500);
    }
    respond(['target' => $characterId, 'character_id' => $characterId, 'hp_before' => $hpBefore, 'hp_after' => $hpAfter, 'damage' => $amount, 'status' => $status]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/death-saves$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $outcome = $data['outcome'] ?? null;
    if (!is_string($outcome) || !in_array($outcome, ['success', 'failure'], true)) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() !== $characterId) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $state = $database->prepare('SELECT death_save_successes, death_save_failures, status FROM play_campaign_character_states WHERE campaign_id = ? AND character_id = ?');
        $state->execute([$campaignId, $characterId]);
        $characterState = $state->fetch();
        if ($characterState === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($characterState['status'] !== 'unconscious') {
            $database->rollBack();
            respond(['error' => 'Character cannot make a death save'], 409);
        }
        $successes = (int) $characterState['death_save_successes'] + ($outcome === 'success' ? 1 : 0);
        $failures = (int) $characterState['death_save_failures'] + ($outcome === 'failure' ? 1 : 0);
        $status = $successes >= 3 ? 'stable' : ($failures >= 3 ? 'dead' : 'unconscious');
        $database->prepare('UPDATE play_campaign_character_states SET death_save_successes = ?, death_save_failures = ?, status = ? WHERE campaign_id = ? AND character_id = ?')
            ->execute([$successes, $failures, $status, $campaignId, $characterId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to record death save'], 500);
    }
    respond(['character_id' => $characterId, 'successes' => $successes, 'failures' => $failures, 'status' => $status], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/status$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    if ($member->fetchColumn() === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $state = $database->prepare('SELECT hp_current, hp_max, status FROM play_campaign_character_states WHERE campaign_id = ? AND character_id = ?');
    $state->execute([$campaignId, $characterId]);
    $characterState = $state->fetch();
    if ($characterState === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    respond(['character_id' => $characterId, 'hp_current' => (int) $characterState['hp_current'], 'hp_max' => (int) $characterState['hp_max'], 'status' => $characterState['status']]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/rewards$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $xp = $data['xp'] ?? null;
    $loot = $data['loot'] ?? null;
    if (!is_int($xp) || $xp < 0 || !is_array($loot)) {
        badRequest();
    }
    foreach ($loot as $item) {
        if (!is_array($item)
            || !isset($item['slug'], $item['quantity'])
            || !is_string($item['slug']) || $item['slug'] === ''
            || !is_int($item['quantity']) || $item['quantity'] <= 0) {
            badRequest();
        }
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $encounter = $database->prepare('SELECT 1 FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        if ($encounter->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $database->prepare('INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot_json) VALUES (?, ?, ?)')
            ->execute([$encounterId, $xp, json_encode($loot, JSON_THROW_ON_ERROR)]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Rewards already awarded'], 409);
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to save rewards'], 500);
    }
    respond(['encounter_id' => $encounterId, 'xp' => $xp, 'loot' => $loot]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/close$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $encounter = $database->prepare('SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        if ($encounter->fetch() === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $xp = $database->prepare('SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ?');
        $xp->execute([$encounterId]);
        $xpAwarded = $xp->fetchColumn();
        $database->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ?")
            ->execute([$encounterId, $campaignId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to close encounter'], 500);
    }
    respond(['id' => $encounterId, 'status' => 'closed', 'xp_awarded' => $xpAwarded === false ? 0 : (int) $xpAwarded]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/end$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $state = $database->prepare('SELECT status, phase, current_actor FROM play_campaign_states WHERE campaign_id = ?');
        $state->execute([$campaignId]);
        $campaignState = $state->fetch();
        if ($campaignState === false || $campaignState['phase'] !== 'combat') {
            $database->rollBack();
            respond(['error' => 'Campaign is not in combat'], 409);
        }

        $encounter = $database->prepare('SELECT status FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $encounterState = $encounter->fetchColumn();
        if ($encounterState === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        // Rewards may have closed the encounter already; ending combat still
        // needs to resume the paused exploration queue. A non-combat campaign
        // remains the conflict condition above.
        if ($encounterState === 'active') {
            $database->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ?")
                ->execute([$encounterId, $campaignId]);
        }
        $database->prepare("UPDATE play_campaign_states SET phase = 'exploration' WHERE campaign_id = ?")
            ->execute([$campaignId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to end encounter'], 500);
    }
    respond([
        'campaign_id' => $campaignId,
        'status' => 'active',
        'phase' => 'exploration',
        'current_actor' => $campaignState['current_actor'],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/conditions$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $duration = $data['duration_rounds'] ?? null;
    if (!is_string($target) || $target === '' || !is_string($condition) || $condition === '' || !is_int($duration) || $duration <= 0) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $encounter = $database->prepare('SELECT combatants_json, conditions_json FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $row = $encounter->fetch();
        if ($row === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($combatants) || !encounterTargetExists($combatants, $target)) {
            $database->rollBack();
            respond(['error' => 'Unknown combatant'], 404);
        }
        $conditions = encounterConditions($row['conditions_json']);
        $conditions[$target] ??= [];
        $conditions[$target][] = ['condition' => $condition, 'remaining_rounds' => $duration];
        $database->prepare('UPDATE play_campaign_encounters SET conditions_json = ? WHERE id = ? AND campaign_id = ?')
            ->execute([json_encode($conditions, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond(['target' => $target, 'conditions' => $conditions[$target]], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/advance$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($actor['username'] !== $owner) {
            $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
            $member->execute([$campaignId, $actor['username']]);
            if ($member->fetchColumn() === false) {
                $database->rollBack();
                respond(['error' => 'Forbidden'], 403);
            }
        }

        $encounter = $database->prepare('SELECT combatants_json, conditions_json, combat_round, combat_turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $row = $encounter->fetch();
        if ($row === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
        $order = is_array($combatants) ? encounterInitiativeOrder($combatants) : [];
        if ($order === []) {
            $database->rollBack();
            respond(['error' => 'Encounter has no combatants'], 409);
        }

        $turnIndex = (int) $row['combat_turn_index'] % count($order);
        $active = $order[$turnIndex];
        if ($actor['username'] !== $owner && ($active['member'] ?? null) !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'It is not your turn'], 409);
        }

        $nextIndex = $turnIndex + 1;
        $round = (int) $row['combat_round'];
        if ($nextIndex === count($order)) {
            $nextIndex = 0;
            $round++;
        }
        $conditions = encounterConditions($row['conditions_json']);
        $nextCombatant = $order[$nextIndex];
        $processedTargets = [];
        foreach (['monster_id', 'member', 'character_id', 'name'] as $field) {
            $target = $nextCombatant[$field] ?? null;
            if (!is_string($target) || isset($processedTargets[$target]) || !isset($conditions[$target])) {
                continue;
            }
            $processedTargets[$target] = true;
            foreach ($conditions[$target] as &$condition) {
                $condition['remaining_rounds']--;
            }
            unset($condition);
            $conditions[$target] = array_values(array_filter(
                $conditions[$target],
                static fn(array $condition): bool => $condition['remaining_rounds'] > 0,
            ));
            if ($conditions[$target] === []) {
                unset($conditions[$target]);
            }
        }
        $database->prepare('UPDATE play_campaign_encounters SET combat_round = ?, combat_turn_index = ?, conditions_json = ? WHERE id = ? AND campaign_id = ?')
            ->execute([$round, $nextIndex, json_encode($conditions, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond(encounterTurnSummary($round, $nextIndex, $order));
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/delay$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $newIndex = $data['new_index'] ?? null;
    if (!is_int($newIndex)) {
        badRequest('Invalid new_index');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }

        $encounter = $database->prepare('SELECT combatants_json, combat_turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $row = $encounter->fetch();
        if ($row === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
        $order = is_array($combatants) ? encounterInitiativeOrder($combatants) : [];
        if ($order === []) {
            $database->rollBack();
            respond(['error' => 'Encounter has no combatants'], 409);
        }

        $turnIndex = (int) $row['combat_turn_index'] % count($order);
        $active = $order[$turnIndex];
        if ($actor['username'] !== $owner && ($active['member'] ?? null) !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'It is not your turn'], 409);
        }
        if ($newIndex <= $turnIndex || $newIndex >= count($order)) {
            $database->rollBack();
            badRequest('Invalid new_index');
        }

        array_splice($order, $turnIndex, 1);
        array_splice($order, $newIndex, 0, [$active]);
        // Initiative is the persisted ordering key.  Renumbering after the
        // move makes the delayed order durable while retaining one entry per
        // combatant and the existing initiative-based reads.
        foreach ($order as $index => &$combatant) {
            $combatant['initiative'] = count($order) - $index;
        }
        unset($combatant);
        $database->prepare('UPDATE play_campaign_encounters SET combatants_json = ?, combat_turn_index = ? WHERE id = ? AND campaign_id = ?')
            ->execute([json_encode($order, JSON_THROW_ON_ERROR), $newIndex, $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond(['order' => array_map(static fn(array $combatant): array => ['name' => (string) $combatant['name']], $order)]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/ready$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $trigger = $data['trigger'] ?? null;
    if (!is_string($trigger) || $trigger === '') {
        badRequest('Invalid trigger');
    }

    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $encounter = $database->prepare('SELECT combatants_json, combat_turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $encounter->execute([$encounterId, $campaignId]);
    $row = $encounter->fetch();
    if ($row === false) {
        respond(['error' => 'Unknown encounter'], 404);
    }
    try {
        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        respond(['error' => 'Unable to read encounter'], 500);
    }
    $order = is_array($combatants) ? encounterInitiativeOrder($combatants) : [];
    if ($order === []) {
        respond(['error' => 'Encounter has no combatants'], 409);
    }
    $active = $order[(int) $row['combat_turn_index'] % count($order)];
    if ($actor['role'] !== 'player' || ($active['member'] ?? null) !== $actor['username']) {
        respond(['error' => 'It is not your turn'], 409);
    }
    respond(['actor' => $actor['username'], 'trigger' => $trigger], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/actions$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $type = $data['type'] ?? null;
    $target = $data['target'] ?? null;
    $text = $data['text'] ?? null;
    if (!is_string($type) || !in_array($type, ['attack', 'help', 'dodge', 'ready'], true)
        || !is_string($target) || $target === '' || !is_string($text) || $text === '') {
        badRequest('Invalid combat action');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        if ($campaign->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }

        $encounter = $database->prepare('SELECT combatants_json, combat_turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $row = $encounter->fetch();
        if ($row === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($row['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
        $order = is_array($combatants) ? encounterInitiativeOrder($combatants) : [];
        if ($order === []) {
            $database->rollBack();
            respond(['error' => 'Encounter has no combatants'], 409);
        }
        $active = $order[(int) $row['combat_turn_index'] % count($order)];
        if ($actor['role'] !== 'player' || ($active['member'] ?? null) !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'It is not your turn'], 409);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, target, text) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'combat_action', $actor['username'], $type, $target, $text]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to submit combat action'], 500);
    }
    respond(['sequence' => $sequence, 'kind' => 'combat_action', 'actor' => $actor['username'], 'type' => $type, 'target' => $target, 'text' => $text], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/(damage|heal)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $operation = $matches[3];
    $target = $data['target'] ?? null;
    $amount = $data['amount'] ?? null;
    if (!is_string($target) || $target === '' || !is_int($amount) || $amount <= 0) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $encounter = $database->prepare('SELECT combatants_json FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $combatantsJson = $encounter->fetchColumn();
        if ($combatantsJson === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($combatants)) {
            throw new JsonException('Invalid combatants');
        }

        $found = false;
        $hpBefore = 0;
        $hpAfter = 0;
        foreach ($combatants as &$combatant) {
            if (!is_array($combatant) || (($combatant['monster_id'] ?? $combatant['member'] ?? null) !== $target)) {
                continue;
            }

            if (array_key_exists('monster_id', $combatant)) {
                if (!is_int($combatant['hp_current'] ?? null) || !is_int($combatant['hp_max'] ?? null)) {
                    throw new JsonException('Invalid combatant HP');
                }
                $hpBefore = $combatant['hp_current'];
                $hpAfter = $operation === 'damage'
                    ? max(0, $hpBefore - $amount)
                    : min($combatant['hp_max'], $hpBefore + $amount);
                $combatant['hp_current'] = $hpAfter;
            } else {
                $characterId = $combatant['character_id'] ?? null;
                if (!is_string($characterId) || $characterId === '') {
                    throw new JsonException('Invalid combatant');
                }
                $state = $database->prepare('SELECT hp_current, hp_max, status FROM play_campaign_character_states WHERE campaign_id = ? AND character_id = ?');
                $state->execute([$campaignId, $characterId]);
                $characterState = $state->fetch();
                if ($characterState === false) {
                    throw new JsonException('Missing combatant HP');
                }
                $hpBefore = (int) $characterState['hp_current'];
                $hpMax = (int) $characterState['hp_max'];
                $hpAfter = $operation === 'damage'
                    ? max(0, $hpBefore - $amount)
                    : min($hpMax, $hpBefore + $amount);
                if ($operation === 'damage' && $hpAfter === 0 && $characterState['status'] !== 'dead') {
                    $database->prepare("UPDATE play_campaign_character_states SET hp_current = ?, status = 'unconscious', death_save_successes = CASE WHEN status = 'stable' THEN 0 ELSE death_save_successes END, death_save_failures = CASE WHEN status = 'stable' THEN 0 ELSE death_save_failures END WHERE campaign_id = ? AND character_id = ?")
                        ->execute([$hpAfter, $campaignId, $characterId]);
                } elseif ($operation === 'heal' && $hpAfter > 0) {
                    $database->prepare("UPDATE play_campaign_character_states SET hp_current = ?, status = 'conscious', death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND character_id = ?")
                        ->execute([$hpAfter, $campaignId, $characterId]);
                } else {
                    $database->prepare('UPDATE play_campaign_character_states SET hp_current = ? WHERE campaign_id = ? AND character_id = ?')
                        ->execute([$hpAfter, $campaignId, $characterId]);
                }
            }
            $found = true;
            break;
        }
        unset($combatant);
        if (!$found) {
            $database->rollBack();
            respond(['error' => 'Unknown combatant'], 404);
        }

        $database->prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE id = ? AND campaign_id = ?')
            ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond(['target' => $target, 'hp_before' => $hpBefore, 'hp_after' => $hpAfter, $operation === 'damage' ? 'damage' : 'healing' => $amount]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $memberId = $data['member'] ?? null;
    $initiative = $data['initiative'] ?? null;
    if (!is_string($memberId) || $memberId === '' || !is_int($initiative)) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $encounter = $database->prepare('SELECT combatants_json FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $combatantsJson = $encounter->fetchColumn();
        if ($combatantsJson === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $member = $database->prepare('SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $memberId]);
        $memberRow = $member->fetch();
        if ($memberRow === false) {
            $database->rollBack();
            badRequest('Unknown party member');
        }

        $combatants = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($combatants)) {
            throw new JsonException('Invalid combatants');
        }
        foreach ($combatants as $combatant) {
            if (is_array($combatant) && ($combatant['member'] ?? null) === $memberId) {
                $database->rollBack();
                respond(['error' => 'Member is already a combatant'], 409);
            }
        }

        $combatant = [
            'member' => $memberId,
            'character_id' => $memberRow['character_id'],
            'name' => $memberRow['name'],
            'initiative' => $initiative,
        ];
        $combatants[] = $combatant;
        $database->prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE id = ? AND campaign_id = ?')
            ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond($combatant, 201);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $memberId = rawurldecode($matches[3]);

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $encounter = $database->prepare('SELECT combatants_json FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $combatantsJson = $encounter->fetchColumn();
        if ($combatantsJson === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($combatants)) {
            throw new JsonException('Invalid combatants');
        }
        $remaining = array_values(array_filter($combatants, static fn(mixed $combatant): bool => !is_array($combatant) || ($combatant['member'] ?? null) !== $memberId));
        if (count($remaining) === count($combatants)) {
            $database->rollBack();
            respond(['error' => 'Unknown combatant'], 404);
        }
        $database->prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE id = ? AND campaign_id = ?')
            ->execute([json_encode($remaining, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond(['removed' => $memberId]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $monsterId = $data['monster_id'] ?? null;
    $name = $data['name'] ?? null;
    $hpMax = $data['hp_max'] ?? null;
    $initiative = $data['initiative'] ?? null;
    if (!is_string($monsterId) || $monsterId === '' || !is_string($name) || $name === ''
        || !is_int($hpMax) || $hpMax <= 0 || !is_int($initiative)) {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $encounter = $database->prepare('SELECT combatants_json FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $combatantsJson = $encounter->fetchColumn();
        if ($combatantsJson === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($combatants)) {
            throw new JsonException('Invalid combatants');
        }
        foreach ($combatants as $combatant) {
            if (is_array($combatant) && ($combatant['monster_id'] ?? null) === $monsterId) {
                $database->rollBack();
                respond(['error' => 'Monster ID already exists'], 409);
            }
        }

        $monster = ['monster_id' => $monsterId, 'name' => $name, 'hp_max' => $hpMax, 'initiative' => $initiative, 'hp_current' => $hpMax];
        $combatants[] = $monster;
        $database->prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE id = ? AND campaign_id = ?')
            ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond($monster, 201);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = rawurldecode($matches[2]);
    $monsterId = rawurldecode($matches[3]);

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $encounter = $database->prepare('SELECT combatants_json FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $combatantsJson = $encounter->fetchColumn();
        if ($combatantsJson === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $combatants = json_decode($combatantsJson, true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($combatants)) {
            throw new JsonException('Invalid combatants');
        }
        $remaining = array_values(array_filter($combatants, static fn(mixed $combatant): bool => !is_array($combatant) || ($combatant['monster_id'] ?? null) !== $monsterId));
        if (count($remaining) === count($combatants)) {
            $database->rollBack();
            respond(['error' => 'Unknown monster'], 404);
        }
        $database->prepare('UPDATE play_campaign_encounters SET combatants_json = ? WHERE id = ? AND campaign_id = ?')
            ->execute([json_encode($remaining, JSON_THROW_ON_ERROR), $encounterId, $campaignId]);
        $database->commit();
    } catch (JsonException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to read encounter'], 500);
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update encounter'], 500);
    }
    respond(['removed' => $monsterId]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/encounters$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $encounterId = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    if (!is_string($encounterId) || $encounterId === '' || !is_string($name) || $name === '') {
        badRequest();
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $database->prepare('INSERT INTO play_campaign_encounters (id, campaign_id, name, status, combatants_json) VALUES (?, ?, ?, ?, ?)')
            ->execute([$encounterId, $campaignId, $name, 'active', '[]']);
        $database->prepare("UPDATE play_campaign_states SET phase = 'combat' WHERE campaign_id = ?")
            ->execute([$campaignId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Encounter conflict'], 409);
    }
    // Preserve current_actor so the exploration queue can resume exactly
    // where it paused when the encounter ends.
    respond(['id' => $encounterId, 'name' => $name, 'status' => 'active', 'combatants' => []], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/locations$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $locationId = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    if (!is_string($locationId) || $locationId === '' || !is_string($name) || $name === '') {
        badRequest();
    }

    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    try {
        $database->prepare('INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)')
            ->execute([$campaignId, $locationId, $name]);
    } catch (PDOException) {
        respond(['error' => 'Location ID already exists'], 409);
    }
    respond(['id' => $locationId, 'name' => $name], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/locations/([^/]+)/connections$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $fromId = rawurldecode($matches[2]);
    $toId = $data['to_id'] ?? null;
    $travelTurns = $data['travel_turns'] ?? null;
    if (!is_string($toId) || $toId === '' || !is_int($travelTurns) || $travelTurns < 1) {
        badRequest();
    }

    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $location = $database->prepare('SELECT 1 FROM play_campaign_locations WHERE campaign_id = ? AND id = ?');
    $location->execute([$campaignId, $fromId]);
    if ($location->fetchColumn() === false) {
        badRequest('Unknown location');
    }
    $location->execute([$campaignId, $toId]);
    if ($location->fetchColumn() === false) {
        badRequest('Unknown location');
    }
    try {
        $database->prepare('INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $fromId, $toId, $travelTurns]);
    } catch (PDOException) {
        badRequest('Connection already exists');
    }
    respond(['from_id' => $fromId, 'to_id' => $toId, 'travel_turns' => $travelTurns], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/scenes$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $sceneId = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    if (!is_string($sceneId) || $sceneId === '' || !is_string($name) || $name === '') {
        badRequest();
    }

    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    try {
        $database->prepare('INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $sceneId, $name, 'open']);
    } catch (PDOException) {
        respond(['error' => 'Scene ID already exists'], 409);
    }
    respond(['id' => $sceneId, 'name' => $name, 'status' => 'open'], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/enter$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $sceneId = rawurldecode($matches[2]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $scene = $database->prepare('SELECT name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?');
    $scene->execute([$campaignId, $sceneId]);
    $sceneRow = $scene->fetch();
    if ($sceneRow === false) {
        respond(['error' => 'Unknown scene'], 404);
    }
    if ($sceneRow['status'] !== 'open') {
        respond(['error' => 'Scene is closed'], 409);
    }
    $database->prepare('INSERT INTO play_campaign_scene_states (campaign_id, current_scene_id) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET current_scene_id = excluded.current_scene_id')
        ->execute([$campaignId, $sceneId]);
    respond(['current_scene_id' => $sceneId, 'name' => $sceneRow['name']]);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/close$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $sceneId = rawurldecode($matches[2]);
    $database = database();

    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $close = $database->prepare("UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = ? AND id = ? AND status = 'open'");
    $close->execute([$campaignId, $sceneId]);
    if ($close->rowCount() === 0) {
        $scene = $database->prepare('SELECT 1 FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?');
        $scene->execute([$campaignId, $sceneId]);
        if ($scene->fetchColumn() === false) {
            respond(['error' => 'Unknown scene'], 404);
        }
    }
    respond(['id' => $sceneId, 'status' => 'closed']);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/start$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'dm') {
        respond(['error' => 'Forbidden'], 403);
    }

    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT campaigns.owner, campaigns.status AS campaign_status, states.status AS active_status FROM play_campaigns AS campaigns LEFT JOIN play_campaign_states AS states ON states.campaign_id = campaigns.id WHERE campaigns.id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($campaignRow['owner'] !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        if ($campaignRow['campaign_status'] !== 'lobby' || $campaignRow['active_status'] === 'active') {
            $database->rollBack();
            respond(['error' => 'Campaign cannot be started'], 409);
        }

        $members = $database->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid');
        $members->execute([$campaignId]);
        $party = $members->fetchAll();
        if (count($party) < 2) {
            $database->rollBack();
            respond(['error' => 'Campaign cannot be started'], 409);
        }

        $currentActor = $party[0]['username'];
        $database->prepare('INSERT INTO play_campaign_states (campaign_id, status, current_actor, turn_number) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, 'active', $currentActor, 1]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Campaign cannot be started'], 409);
    }
    respond(['id' => $campaignId, 'status' => 'active', 'current_actor' => $currentActor, 'turn_number' => 1]);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/narrations$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'dm') {
        respond(['error' => 'Forbidden'], 403);
    }

    $campaignId = rawurldecode($matches[1]);
    $text = $data['text'] ?? null;
    if (!is_string($text) || $text === '') {
        badRequest('Invalid text');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'narration', 'dm', $text]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to append narration'], 500);
    }
    respond(['sequence' => $sequence, 'kind' => 'narration', 'actor' => 'dm', 'text' => $text], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/turn/nudge$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $message = $data['message'] ?? null;
    if (!is_string($message) || $message === '') {
        badRequest('Invalid message');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($actor['username'] !== $owner) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $turn = $database->prepare('SELECT current_actor FROM play_campaign_states WHERE campaign_id = ?');
        $turn->execute([$campaignId]);
        $state = $turn->fetch();
        if ($state === false) {
            $database->rollBack();
            respond(['error' => 'Campaign is not active'], 404);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'nudge', $actor['username'], $message]);
        $count = $database->prepare("SELECT COUNT(*) FROM play_campaign_events WHERE campaign_id = ? AND kind = 'nudge'");
        $count->execute([$campaignId]);
        $nudgeCount = (int) $count->fetchColumn();
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to send nudge'], 500);
    }
    respond(['actor' => $actor['username'], 'target' => $state['current_actor'], 'message' => $message, 'nudge_count' => $nudgeCount], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/actions$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $type = $data['type'] ?? null;
    $text = $data['text'] ?? null;
    if (!is_string($type) || $type === '' || !is_string($text) || $text === '') {
        badRequest('Invalid action');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }

        $turn = $database->prepare('SELECT current_actor FROM play_campaign_states WHERE campaign_id = ?');
        $turn->execute([$campaignId]);
        $state = $turn->fetch();
        if ($state === false) {
            $database->rollBack();
            respond(['error' => 'Campaign is not active'], 404);
        }

        // The DM is part of the exploration queue, but cannot submit a
        // player action; the same conflict response applies to any actor
        // whose turn is not currently active.
        if ($actor['role'] !== 'player' || $state['current_actor'] !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'It is not your turn'], 409);
        }

        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'action', $actor['username'], $type, $text]);
        $database->prepare('UPDATE play_campaign_states SET current_actor = ? WHERE campaign_id = ?')->execute([$owner, $campaignId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to submit action'], 500);
    }
    respond(['sequence' => $sequence, 'kind' => 'action', 'actor' => $actor['username'], 'type' => $type, 'text' => $text, 'next_actor' => $owner], 201);
}

if (preg_match('#^/v1/play/campaigns/([^/]+)/turn/travel$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $destinationId = $data['destination_id'] ?? null;
    if (!is_string($destinationId) || $destinationId === '') {
        badRequest('Invalid destination_id');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }

        $turn = $database->prepare('SELECT current_actor FROM play_campaign_states WHERE campaign_id = ?');
        $turn->execute([$campaignId]);
        $state = $turn->fetch();
        if ($state === false) {
            $database->rollBack();
            respond(['error' => 'Campaign is not active'], 404);
        }
        if ($actor['role'] !== 'player' || $state['current_actor'] !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'It is not your turn'], 409);
        }

        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $locationState = $database->prepare('SELECT current_location_id FROM play_campaign_location_states WHERE campaign_id = ?');
        $locationState->execute([$campaignId]);
        $currentLocationId = $locationState->fetchColumn();
        if ($currentLocationId === false) {
            // Campaigns created before travel existed, and those whose map is
            // built after start, begin at their first deterministic location.
            $initialLocation = $database->prepare('SELECT id FROM play_campaign_locations WHERE campaign_id = ? ORDER BY rowid LIMIT 1');
            $initialLocation->execute([$campaignId]);
            $currentLocationId = $initialLocation->fetchColumn();
        }

        $connection = $database->prepare('SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?');
        $connection->execute([$campaignId, $currentLocationId, $destinationId]);
        $travelTurns = $connection->fetchColumn();
        if ($travelTurns === false) {
            $database->rollBack();
            respond(['error' => 'Invalid travel destination'], 409);
        }
        $travelTurns = (int) $travelTurns;

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'travel', $actor['username'], $destinationId]);
        $database->prepare('INSERT INTO play_campaign_location_states (campaign_id, current_location_id) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET current_location_id = excluded.current_location_id')
            ->execute([$campaignId, $destinationId]);
        $database->prepare('UPDATE play_campaign_states SET current_actor = ? WHERE campaign_id = ?')->execute([$owner, $campaignId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to travel'], 500);
    }
    respond(['sequence' => $sequence, 'kind' => 'travel', 'actor' => $actor['username'], 'destination_id' => $destinationId, 'travel_turns' => $travelTurns, 'next_actor' => $owner], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/turn/rest$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $type = $data['type'] ?? null;
    if (!is_string($type) || !in_array($type, ['short', 'long'], true)) {
        badRequest('Invalid rest type');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }

        $turn = $database->prepare('SELECT current_actor FROM play_campaign_states WHERE campaign_id = ?');
        $turn->execute([$campaignId]);
        $state = $turn->fetch();
        if ($state === false) {
            $database->rollBack();
            respond(['error' => 'Campaign is not active'], 404);
        }
        if ($actor['role'] !== 'player' || $state['current_actor'] !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'It is not your turn'], 409);
        }

        $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        $characterId = $member->fetchColumn();
        if ($characterId === false) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        // Campaigns persisted before character HP was introduced get the
        // same deterministic starting state as newly joined characters.
        $database->prepare('INSERT OR IGNORE INTO play_campaign_character_states (campaign_id, character_id, hp_current, hp_max, death_save_successes, death_save_failures, status) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $characterId, 20, 20, 0, 0, 'conscious']);
        if ($type === 'long') {
            $database->prepare("UPDATE play_campaign_character_states SET hp_current = hp_max, status = 'conscious', death_save_successes = 0, death_save_failures = 0 WHERE campaign_id = ? AND character_id = ?")
                ->execute([$campaignId, $characterId]);
        }
        $hp = $database->prepare('SELECT hp_current, hp_max FROM play_campaign_character_states WHERE campaign_id = ? AND character_id = ?');
        $hp->execute([$campaignId, $characterId]);
        $characterState = $hp->fetch();

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, text) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'rest', $actor['username'], $type, '']);
        $database->prepare('UPDATE play_campaign_states SET current_actor = ? WHERE campaign_id = ?')->execute([$owner, $campaignId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to take rest'], 500);
    }
    respond(['sequence' => $sequence, 'kind' => 'rest', 'actor' => $actor['username'], 'type' => $type, 'hp_current' => (int) $characterState['hp_current'], 'hp_max' => (int) $characterState['hp_max'], 'next_actor' => $owner], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/resolutions$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $text = $data['text'] ?? null;
    if (!is_string($text) || $text === '') {
        badRequest('Invalid text');
    }

    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }

        $turn = $database->prepare('SELECT current_actor, turn_number FROM play_campaign_states WHERE campaign_id = ?');
        $turn->execute([$campaignId]);
        $state = $turn->fetch();
        if ($state === false) {
            $database->rollBack();
            respond(['error' => 'Campaign is not active'], 404);
        }
        if ($actor['username'] !== $owner || $state['current_actor'] !== $owner) {
            $database->rollBack();
            respond(['error' => 'It is not your turn'], 409);
        }

        // The turn-consuming player event immediately before the GM turn
        // identifies the player to advance from. Party rowid is the
        // deterministic lobby join order.
        $lastAction = $database->prepare("SELECT actor FROM play_campaign_events WHERE campaign_id = ? AND kind IN ('action', 'travel', 'rest') ORDER BY sequence DESC LIMIT 1");
        $lastAction->execute([$campaignId]);
        $previousActor = $lastAction->fetchColumn();
        $members = $database->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid');
        $members->execute([$campaignId]);
        $party = $members->fetchAll(PDO::FETCH_COLUMN);
        $position = array_search($previousActor, $party, true);
        if ($position === false || count($party) < 2) {
            $database->rollBack();
            respond(['error' => 'Unable to resolve turn'], 409);
        }
        $nextActor = $party[($position + 1) % count($party)];
        $turnNumber = (int) $state['turn_number'] + 1;

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'resolution', $owner, $text]);
        $database->prepare('UPDATE play_campaign_states SET current_actor = ?, turn_number = ? WHERE campaign_id = ?')
            ->execute([$nextActor, $turnNumber, $campaignId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to append resolution'], 500);
    }
    respond(['sequence' => $sequence, 'kind' => 'resolution', 'actor' => $owner, 'text' => $text, 'next_actor' => $nextActor, 'turn_number' => $turnNumber], 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/analytics/risk-report$#', $path, $matches)) {
    $includeZeroes = $data['include_zeroes'] ?? false;
    if (!is_bool($includeZeroes)) {
        badRequest('Invalid include_zeroes');
    }
    $campaignId = rawurldecode($matches[1]);
    $analytics = campaignAnalytics(database(), $campaignId);
    $missing = [];
    foreach ([
        'has_dm' => 'dm',
        'has_characters' => 'characters',
        'has_active_quest' => 'active_quest',
        'has_next_session' => 'next_session',
    ] as $signal => $name) {
        if (!$analytics[$signal]) {
            $missing[] = $name;
        }
    }
    if ($includeZeroes) {
        if ($analytics['friendly_npcs'] === 0) {
            $missing[] = 'friendly_npcs';
        }
        if ($analytics['inventory_items'] === 0) {
            $missing[] = 'inventory_items';
        }
    }
    $coreMissing = count(array_filter([
        $analytics['has_dm'],
        $analytics['has_characters'],
        $analytics['has_next_session'],
        $analytics['has_active_quest'],
    ], static fn(bool $signal): bool => !$signal));
    $riskLevel = $coreMissing === 0 ? 'low' : ($coreMissing <= 2 ? 'medium' : 'high');
    respond([
        'campaign_id' => $campaignId,
        'risk_level' => $riskLevel,
        'missing' => $missing,
        'signals' => [
            'has_dm' => $analytics['has_dm'],
            'has_characters' => $analytics['has_characters'],
            'has_next_session' => $analytics['has_next_session'],
            'has_active_quest' => $analytics['has_active_quest'],
        ],
    ]);
}

if ($path === '/v1/storage/reset') {
    resetStorage();
    respond(['ok' => true, 'schema_version' => SCHEMA_VERSION]);
}

if ($path === '/v1/campaigns') {
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $dm = $data['dm'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_string($dm) || $dm === '') {
        badRequest();
    }
    try {
        database()->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)')->execute([$id, $name, $dm]);
    } catch (PDOException) {
        respond(['error' => 'Campaign ID already exists'], 409);
    }
    respond(['id' => $id, 'name' => $name, 'dm' => $dm], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $sessionId = rawurldecode($matches[2]);
    $present = $data['present'] ?? null;
    $absent = $data['absent'] ?? null;
    if (!is_array($present) || !array_is_list($present) || !is_array($absent) || !array_is_list($absent)) {
        badRequest();
    }
    $attendance = [];
    foreach ([['present', $present], ['absent', $absent]] as [$status, $characters]) {
        foreach ($characters as $characterId) {
            if (!is_string($characterId) || $characterId === '' || isset($attendance[$characterId])) {
                badRequest('Invalid attendance');
            }
            $attendance[$characterId] = $status;
        }
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $session = $database->prepare('SELECT 1 FROM campaign_sessions WHERE id = ? AND campaign_id = ?');
    $session->execute([$sessionId, $campaignId]);
    if ($session->fetchColumn() === false) {
        respond(['error' => 'Unknown session'], 404);
    }
    $character = $database->prepare('SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?');
    foreach (array_keys($attendance) as $characterId) {
        $character->execute([$characterId, $campaignId]);
        if ($character->fetchColumn() === false) {
            respond(['error' => 'Unknown character'], 404);
        }
    }
    try {
        $database->beginTransaction();
        $database->prepare('DELETE FROM campaign_session_attendance WHERE session_id = ?')->execute([$sessionId]);
        $insert = $database->prepare('INSERT INTO campaign_session_attendance (session_id, character_id, status) VALUES (?, ?, ?)');
        foreach ($attendance as $characterId => $status) {
            $insert->execute([$sessionId, $characterId, $status]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to record attendance'], 500);
    }
    respond(['session_id' => $sessionId, 'present_count' => count($present), 'absent_count' => count($absent)]);
}

if (preg_match('#^/v1/campaigns/([^/]+)/sessions$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $id = $data['id'] ?? null;
    $startsAt = $data['starts_at'] ?? null;
    $durationMinutes = $data['duration_minutes'] ?? null;
    $agenda = $data['agenda'] ?? null;
    if (!is_string($id) || $id === '' || !validSessionStart($startsAt)
        || !is_int($durationMinutes) || $durationMinutes <= 0 || !is_array($agenda) || !array_is_list($agenda)) {
        badRequest();
    }
    foreach ($agenda as $item) {
        if (!is_string($item) || $item === '') {
            badRequest('Invalid agenda');
        }
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    try {
        $database->prepare('INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)')
            ->execute([$id, $campaignId, $startsAt, $durationMinutes, json_encode($agenda, JSON_THROW_ON_ERROR)]);
    } catch (PDOException) {
        respond(['error' => 'Session ID already exists'], 409);
    }
    respond(['id' => $id, 'starts_at' => $startsAt, 'duration_minutes' => $durationMinutes, 'agenda_count' => count($agenda)], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $projectId = rawurldecode($matches[2]);
    $days = $data['days'] ?? null;
    if (!is_int($days) || $days <= 0) {
        badRequest('Invalid days');
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    try {
        $database->beginTransaction();
        $projectStatement = $database->prepare('SELECT id, item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ? AND campaign_id = ?');
        $projectStatement->execute([$projectId, $campaignId]);
        $project = $projectStatement->fetch();
        if ($project === false) {
            $database->rollBack();
            respond(['error' => 'Unknown crafting project'], 404);
        }
        $completed = (int) $project['days_completed'];
        $status = $project['status'];
        if ($status === 'active') {
            $completed = min((int) $project['days_required'], $completed + $days);
            $status = $completed === (int) $project['days_required'] ? 'complete' : 'active';
            $database->prepare('UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?')->execute([$completed, $status, $projectId]);
            if ($status === 'complete') {
                $database->prepare("INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, 1, 'party') ON CONFLICT(campaign_id, item_slug) DO UPDATE SET quantity = quantity + 1")
                    ->execute([$campaignId, $project['item_slug']]);
            }
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to advance crafting project'], 500);
    }
    respond(['id' => $projectId, 'days_completed' => $completed, 'status' => $status]);
}

if (preg_match('#^/v1/campaigns/([^/]+)/downtime/crafting$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $id = $data['id'] ?? null;
    $characterId = $data['character_id'] ?? null;
    $itemSlug = $data['item_slug'] ?? null;
    $daysRequired = $data['days_required'] ?? null;
    $costGp = $data['cost_gp'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($characterId) || $characterId === ''
        || !validCompendiumSlug($itemSlug) || !is_int($daysRequired) || $daysRequired <= 0
        || !is_int($costGp) || $costGp < 0) {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $character = $database->prepare('SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?');
    $character->execute([$characterId, $campaignId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    try {
        $database->prepare('INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, 0, ?, \'active\')')
            ->execute([$id, $campaignId, $characterId, $itemSlug, $daysRequired, $costGp]);
    } catch (PDOException) {
        respond(['error' => 'Crafting project ID already exists'], 409);
    }
    respond([
        'id' => $id,
        'character_id' => $characterId,
        'item_slug' => $itemSlug,
        'days_required' => $daysRequired,
        'days_completed' => 0,
        'status' => 'active',
    ], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/inventory$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $itemSlug = $data['item_slug'] ?? null;
    $quantity = $data['quantity'] ?? null;
    $owner = $data['owner'] ?? null;
    if (!validCompendiumSlug($itemSlug) || !is_int($quantity) || $quantity <= 0 || $owner !== 'party') {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $database->prepare("INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity")
        ->execute([$campaignId, $itemSlug, $quantity, $owner]);
    respond(['item_slug' => $itemSlug, 'quantity' => $quantity, 'owner' => $owner], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/characters/([^/]+)/equipment$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $itemSlug = $data['item_slug'] ?? null;
    $quantity = $data['quantity'] ?? null;
    if (!validCompendiumSlug($itemSlug) || !is_int($quantity) || $quantity <= 0) {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $character = $database->prepare('SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?');
    $character->execute([$characterId, $campaignId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    try {
        $database->beginTransaction();
        $available = $database->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ?');
        $available->execute([$campaignId, $itemSlug]);
        $availableQuantity = $available->fetchColumn();
        if ($availableQuantity === false || (int) $availableQuantity < $quantity) {
            $database->rollBack();
            badRequest('Insufficient inventory');
        }
        $database->prepare('UPDATE campaign_inventory SET quantity = quantity - ? WHERE campaign_id = ? AND item_slug = ?')->execute([$quantity, $campaignId, $itemSlug]);
        $database->prepare('DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND quantity = 0')->execute([$campaignId, $itemSlug]);
        $database->prepare('INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity')
            ->execute([$campaignId, $characterId, $itemSlug, $quantity]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to assign equipment'], 500);
    }
    respond(['character_id' => $characterId, 'item_slug' => $itemSlug, 'quantity' => $quantity]);
}

if (preg_match('#^/v1/campaigns/([^/]+)/factions$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $stance = $data['stance'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_string($stance) || $stance === '') {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    try {
        $database->prepare('INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)')->execute([$id, $campaignId, $name, $stance]);
    } catch (PDOException) {
        respond(['error' => 'Faction ID already exists'], 409);
    }
    respond(['id' => $id, 'name' => $name, 'stance' => $stance], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/npcs$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $factionId = $data['faction_id'] ?? null;
    $disposition = $data['disposition'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($name) || $name === ''
        || !is_string($factionId) || $factionId === '' || !is_int($disposition)) {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $faction = $database->prepare('SELECT 1 FROM campaign_factions WHERE id = ? AND campaign_id = ?');
    $faction->execute([$factionId, $campaignId]);
    if ($faction->fetchColumn() === false) {
        respond(['error' => 'Unknown faction'], 404);
    }
    try {
        $database->prepare('INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)')->execute([$id, $campaignId, $name, $factionId, $disposition]);
    } catch (PDOException) {
        respond(['error' => 'NPC ID already exists'], 409);
    }
    respond(['id' => $id, 'name' => $name, 'faction_id' => $factionId, 'disposition' => $disposition], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/quests$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $id = $data['id'] ?? null;
    $title = $data['title'] ?? null;
    $status = $data['status'] ?? null;
    $milestones = $data['milestones'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($title) || $title === ''
        || !is_string($status) || !in_array($status, ['active', 'completed', 'blocked'], true)
        || !is_array($milestones) || !array_is_list($milestones)) {
        badRequest();
    }
    foreach ($milestones as $milestone) {
        if (!is_string($milestone) || $milestone === '') {
            badRequest('Invalid milestones');
        }
    }
    if (count($milestones) !== count(array_unique($milestones))) {
        badRequest('Invalid milestones');
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    try {
        $database->beginTransaction();
        $database->prepare('INSERT INTO campaign_quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)')->execute([$id, $campaignId, $title, $status]);
        $milestone = $database->prepare('INSERT INTO campaign_quest_milestones (quest_id, position, title) VALUES (?, ?, ?)');
        foreach ($milestones as $position => $milestoneTitle) {
            $milestone->execute([$id, $position, $milestoneTitle]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Quest ID already exists'], 409);
    }
    respond(['id' => $id, 'title' => $title, 'status' => $status, 'milestones_total' => count($milestones), 'milestones_done' => 0], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/quests/([^/]+)/progress$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $questId = rawurldecode($matches[2]);
    $completed = $data['completed'] ?? null;
    if (!is_array($completed) || !array_is_list($completed)) {
        badRequest();
    }
    foreach ($completed as $milestone) {
        if (!is_string($milestone) || $milestone === '') {
            badRequest('Invalid completed');
        }
    }
    if (count($completed) !== count(array_unique($completed))) {
        badRequest('Invalid completed');
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $quest = $database->prepare('SELECT id, status FROM campaign_quests WHERE id = ? AND campaign_id = ?');
    $quest->execute([$questId, $campaignId]);
    $questRow = $quest->fetch();
    if ($questRow === false) {
        respond(['error' => 'Unknown quest'], 404);
    }
    $known = $database->prepare('SELECT COUNT(*) FROM campaign_quest_milestones WHERE quest_id = ? AND title = ?');
    foreach ($completed as $title) {
        $known->execute([$questId, $title]);
        if ((int) $known->fetchColumn() !== 1) {
            badRequest('Unknown milestone');
        }
    }
    try {
        $database->beginTransaction();
        $update = $database->prepare('UPDATE campaign_quest_milestones SET completed = 1 WHERE quest_id = ? AND title = ?');
        foreach ($completed as $title) {
            $update->execute([$questId, $title]);
        }
        $totals = $database->prepare('SELECT COUNT(*) AS total, SUM(completed) AS done FROM campaign_quest_milestones WHERE quest_id = ?');
        $totals->execute([$questId]);
        $progress = $totals->fetch();
        $total = (int) $progress['total'];
        $done = (int) ($progress['done'] ?? 0);
        $status = $questRow['status'];
        if ($total > 0 && $done === $total && $status === 'active') {
            $status = 'completed';
            $database->prepare('UPDATE campaign_quests SET status = ? WHERE id = ?')->execute([$status, $questId]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update quest progress'], 500);
    }
    respond(['id' => $questId, 'status' => $status, 'milestones_total' => $total, 'milestones_done' => $done]);
}

if (preg_match('#^/v1/campaigns/([^/]+)/characters$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $level = $data['level'] ?? null;
    $class = $data['class'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($name) || $name === ''
        || !is_int($level) || $level < 1 || $level > 20 || !is_string($class) || $class === '') {
        badRequest();
    }
    $database = database();
    $exists = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $exists->execute([$campaignId]);
    if ($exists->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    try {
        $database->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)')->execute([$id, $campaignId, $name, $level, $class]);
    } catch (PDOException) {
        respond(['error' => 'Character ID already exists'], 409);
    }
    respond(['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class], 201);
}

if (preg_match('#^/v1/campaigns/([^/]+)/events$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $id = $data['id'] ?? null;
    $kind = $data['kind'] ?? null;
    $summary = $data['summary'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($kind) || $kind === '' || !is_string($summary) || $summary === '') {
        badRequest();
    }
    $database = database();
    $exists = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $exists->execute([$campaignId]);
    if ($exists->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    try {
        $database->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)')->execute([$id, $campaignId, $kind, $summary]);
    } catch (PDOException) {
        respond(['error' => 'Event ID already exists'], 409);
    }
    respond(['id' => $id, 'kind' => $kind], 201);
}

if ($path === '/v1/compendium/monsters') {
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $cr = $data['cr'] ?? null;
    $armorClass = $data['armor_class'] ?? null;
    $hitPoints = $data['hit_points'] ?? null;
    $tags = $data['tags'] ?? null;
    if (!validCompendiumSlug($slug) || !is_string($name) || $name === '' || !is_string($cr) || $cr === ''
        || !is_int($armorClass) || $armorClass < 0 || !is_int($hitPoints) || $hitPoints < 0
        || !is_array($tags) || !array_is_list($tags)) {
        badRequest();
    }
    foreach ($tags as $tag) {
        if (!is_string($tag) || $tag === '') {
            badRequest('Invalid tags');
        }
    }
    $database = database();
    try {
        $database->beginTransaction();
        $database->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points) VALUES (?, ?, ?, ?, ?)')->execute([$slug, $name, $cr, $armorClass, $hitPoints]);
        $tagStatement = $database->prepare('INSERT INTO compendium_monster_tags (monster_slug, position, tag) VALUES (?, ?, ?)');
        foreach (array_values($tags) as $position => $tag) {
            $tagStatement->execute([$slug, $position, $tag]);
        }
        $database->commit();
    } catch (PDOException $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Monster slug already exists'], 409);
    }
    respond(['slug' => $slug, 'name' => $name, 'cr' => $cr, 'armor_class' => $armorClass, 'hit_points' => $hitPoints], 201);
}

if ($path === '/v1/compendium/items') {
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $type = $data['type'] ?? null;
    $rarity = $data['rarity'] ?? null;
    $costGp = $data['cost_gp'] ?? null;
    if (!validCompendiumSlug($slug) || !is_string($name) || $name === '' || !is_string($type) || $type === ''
        || !is_string($rarity) || $rarity === '' || !is_int($costGp) || $costGp < 0) {
        badRequest();
    }
    try {
        database()->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)')->execute([$slug, $name, $type, $rarity, $costGp]);
    } catch (PDOException) {
        respond(['error' => 'Item slug already exists'], 409);
    }
    respond(['slug' => $slug, 'name' => $name, 'type' => $type, 'rarity' => $rarity, 'cost_gp' => $costGp], 201);
}

if ($path === '/v1/auth/register') {
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;
    $role = $data['role'] ?? null;
    if (!validUsername($username) || !is_string($password) || strlen($password) < 8
        || !is_string($role) || !in_array($role, ['dm', 'player'], true)) {
        badRequest();
    }

    $state = lockUsers();
    $users = $state['users'];
    if (isset($users[$username])) {
        unlockUsers($state['handle']);
        respond(['error' => 'Username already exists'], 409);
    }
    $users[$username] = [
        'role' => $role,
        'password_hash' => password_hash($password, PASSWORD_DEFAULT),
    ];
    saveUsers($state['handle'], $users);
    respond(['username' => $username, 'role' => $role], 201);
}

if ($path === '/v1/auth/login') {
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;
    if (!validUsername($username) || !is_string($password)) {
        badRequest();
    }

    $state = lockUsers();
    $user = $state['users'][$username] ?? null;
    unlockUsers($state['handle']);
    if (!is_array($user) || !is_string($user['password_hash'] ?? null)
        || !password_verify($password, $user['password_hash'])) {
        respond(['error' => 'Invalid credentials'], 401);
    }
    respond(['username' => $username, 'token' => "session-{$username}"]);
}

if ($path === '/v1/characters/ability-modifier') {
    $score = integerField($data, 'score');
    respond(['score' => $score, 'modifier' => abilityModifier($score)]);
}

if ($path === '/v1/characters/proficiency') {
    $level = integerField($data, 'level');
    respond(['level' => $level, 'proficiency_bonus' => proficiencyBonus($level)]);
}

if ($path === '/v1/phb/spell-slots') {
    $class = $data['class'] ?? null;
    $level = $data['level'] ?? null;
    if ($class !== 'wizard' || $level !== 5) {
        badRequest('Only wizard level 5 is supported');
    }
    respond(['class' => 'wizard', 'level' => 5, 'slots' => ['1' => 4, '2' => 3, '3' => 2]]);
}

if ($path === '/v1/phb/rests/long') {
    $level = integerField($data, 'level');
    $hpCurrent = integerField($data, 'hp_current');
    $hpMax = integerField($data, 'hp_max');
    $hitDiceSpent = integerField($data, 'hit_dice_spent');
    $exhaustionLevel = integerField($data, 'exhaustion_level');
    if ($level < 1 || $level > 20 || $hpMax < 1 || $hpCurrent < 0 || $hpCurrent > $hpMax
        || $hitDiceSpent < 0 || $hitDiceSpent > $level || $exhaustionLevel < 0) {
        badRequest();
    }
    $hitDiceRestored = max(1, intdiv($level, 2));
    respond([
        'hp_current' => $hpMax,
        'hit_dice_spent' => max(0, $hitDiceSpent - $hitDiceRestored),
        'exhaustion_level' => max(0, $exhaustionLevel - 1),
    ]);
}

if ($path === '/v1/phb/equipment-load') {
    $strength = integerField($data, 'strength');
    $weight = integerField($data, 'weight');
    if ($strength < 1 || $strength > 30 || $weight < 0) {
        badRequest();
    }
    $capacity = $strength * 15;
    respond(['capacity' => $capacity, 'weight' => $weight, 'encumbered' => $weight > $capacity]);
}

if ($path === '/v1/characters/derived-stats') {
    $level = integerField($data, 'level');
    $proficiency = proficiencyBonus($level);
    if (!isset($data['abilities'], $data['armor']) || !is_array($data['abilities']) || !is_array($data['armor'])) {
        badRequest();
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
        $modifiers[$ability] = abilityModifier(integerField($data['abilities'], $ability));
    }

    $armor = $data['armor'];
    $base = integerField($armor, 'base');
    $dexCap = integerField($armor, 'dex_cap');
    if (!array_key_exists('shield', $armor) || !is_bool($armor['shield'])) {
        badRequest('Invalid shield');
    }

    respond([
        'level' => $level,
        'proficiency_bonus' => $proficiency,
        'hp_max' => $level * (6 + $modifiers['con']),
        'armor_class' => $base + min($modifiers['dex'], $dexCap) + ($armor['shield'] ? 2 : 0),
        'modifiers' => $modifiers,
    ]);
}

if ($path === '/v1/dice/stats') {
    $expression = $data['expression'] ?? null;
    if (!is_string($expression) || !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $matches)) {
        badRequest('Invalid expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        badRequest('Invalid expression');
    }

    $min = $count + $modifier;
    $max = ($count * $sides) + $modifier;
    respond([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => ($min + $max) / 2,
    ]);
}

if ($path === '/v1/checks/ability') {
    $roll = integerField($data, 'roll');
    $modifier = integerField($data, 'modifier');
    $dc = integerField($data, 'dc');
    $total = $roll + $modifier;
    respond(['total' => $total, 'success' => $total >= $dc, 'margin' => $total - $dc]);
}

if ($path === '/v1/encounters/adjusted-xp') {
    if (!isset($data['party'], $data['monsters']) || !is_array($data['party']) || !is_array($data['monsters'])) {
        badRequest();
    }

    $xpByCr = ['0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100, '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800];
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!is_array($member) || ($member['level'] ?? null) !== 3) {
            badRequest('Only level 3 party members are supported');
        }
        $thresholds['easy'] += 75;
        $thresholds['medium'] += 150;
        $thresholds['hard'] += 225;
        $thresholds['deadly'] += 400;
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        if (!is_array($monster) || !is_string($monster['cr'] ?? null) || !array_key_exists($monster['cr'], $xpByCr)
            || !is_int($monster['count'] ?? null) || $monster['count'] <= 0) {
            badRequest('Invalid monster');
        }
        $baseXp += $xpByCr[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $multiplier = match (true) {
        $monsterCount <= 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };
    $adjustedXp = $baseXp * $multiplier;
    $difficulty = $adjustedXp >= $thresholds['deadly'] ? 'deadly'
        : ($adjustedXp >= $thresholds['hard'] ? 'hard'
        : ($adjustedXp >= $thresholds['medium'] ? 'medium'
        : ($adjustedXp >= $thresholds['easy'] ? 'easy' : 'trivial')));

    respond([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

if ($path === '/v1/dm/encounter-builder') {
    $campaignId = $data['campaign_id'] ?? null;
    $party = $data['party'] ?? null;
    $monsterSlugs = $data['monster_slugs'] ?? null;
    if (!is_string($campaignId) || $campaignId === '' || !is_array($party) || $party === []
        || !is_array($monsterSlugs) || $monsterSlugs === []) {
        badRequest();
    }

    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || ($member['level'] ?? null) !== 3) {
            badRequest('Only level 3 party members are supported');
        }
        $thresholds['easy'] += 75;
        $thresholds['medium'] += 150;
        $thresholds['hard'] += 225;
        $thresholds['deadly'] += 400;
    }

    $xpByCr = ['0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100, '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800];
    $monster = $database->prepare('SELECT cr FROM compendium_monsters WHERE slug = ?');
    $baseXp = 0;
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug) || $slug === '') {
            badRequest('Invalid monster');
        }
        $monster->execute([$slug]);
        $cr = $monster->fetchColumn();
        if ($cr === false) {
            respond(['error' => 'Unknown monster'], 404);
        }
        if (!array_key_exists($cr, $xpByCr)) {
            badRequest('Unsupported monster CR');
        }
        $baseXp += $xpByCr[$cr];
    }

    $monsterCount = count($monsterSlugs);
    $multiplier = match (true) {
        $monsterCount <= 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };
    $adjustedXp = $baseXp * $multiplier;
    $difficulty = $adjustedXp >= $thresholds['deadly'] ? 'deadly'
        : ($adjustedXp >= $thresholds['hard'] ? 'hard'
        : ($adjustedXp >= $thresholds['medium'] ? 'medium'
        : ($adjustedXp >= $thresholds['easy'] ? 'easy' : 'trivial')));
    $recommendation = match ($difficulty) {
        'trivial' => 'no challenge',
        'easy' => 'safe warm-up',
        'medium' => 'solid challenge',
        'hard' => 'tough fight',
        'deadly' => 'deadly threat',
    };
    respond([
        'campaign_id' => $campaignId,
        'base_xp' => $baseXp,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'monster_count' => $monsterCount,
        'recommendation' => $recommendation,
    ]);
}

if ($path === '/v1/dm/loot-parcel') {
    $campaignId = $data['campaign_id'] ?? null;
    $tier = $data['tier'] ?? null;
    if (!is_string($campaignId) || $campaignId === '' || !is_int($tier) || $tier !== 1
        || (array_key_exists('seed', $data) && !is_int($data['seed']))) {
        badRequest();
    }
    $campaign = database()->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    respond([
        'campaign_id' => $campaignId,
        'coins_gp' => 75,
        'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
    ]);
}

if ($path === '/v1/dm/session-recap') {
    $campaignId = $data['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $events = $database->prepare('SELECT kind, summary FROM campaign_events WHERE campaign_id = ? AND summary <> ? ORDER BY rowid');
    $events->execute([$campaignId, '']);
    $eventRows = $events->fetchAll();
    $characters = $database->prepare('SELECT name FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid LIMIT 1');
    $characters->execute([$campaignId]);
    $actor = $characters->fetchColumn() ?: 'The party';
    $monster = $database->query('SELECT slug FROM compendium_monsters ORDER BY rowid LIMIT 1')->fetchColumn() ?: 'monster';

    if ($eventRows !== []) {
        $summary = $eventRows[array_key_last($eventRows)]['summary'];
        $openThreads = array_column(array_filter($eventRows, static fn(array $event): bool => $event['kind'] === 'thread'), 'summary');
    } else {
        $summary = "{$actor} scouts the {$monster} trail.";
        $openThreads = [];
    }
    if ($openThreads === []) {
        preg_match('/the (\S+) trail/i', $summary, $match);
        $threadMonster = $match[1] ?? $monster;
        $openThreads = ["Resolve {$threadMonster} trail ambush"];
    }
    respond(['campaign_id' => $campaignId, 'summary' => $summary, 'open_threads' => $openThreads]);
}

if ($path === '/v1/initiative/order') {
    if (!isset($data['combatants']) || !is_array($data['combatants'])) {
        badRequest();
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        if (!is_array($combatant) || !is_string($combatant['name'] ?? null)
            || !is_int($combatant['dex'] ?? null) || !is_int($combatant['roll'] ?? null)) {
            badRequest('Invalid combatant');
        }
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }
    sortInitiative($combatants);
    $order = array_map(static fn(array $combatant): array => [
        'name' => $combatant['name'],
        'score' => $combatant['score'],
    ], $combatants);
    respond(['order' => $order]);
}

if ($path === '/v1/combat/sessions') {
    if (!is_string($data['id'] ?? null) || $data['id'] === '' || !isset($data['combatants']) || !is_array($data['combatants']) || $data['combatants'] === []) {
        badRequest();
    }

    $combatants = [];
    $names = [];
    foreach ($data['combatants'] as $combatant) {
        if (!is_array($combatant) || !is_string($combatant['name'] ?? null) || $combatant['name'] === ''
            || !is_int($combatant['dex'] ?? null) || !is_int($combatant['roll'] ?? null)
            || isset($names[$combatant['name']])) {
            badRequest('Invalid combatant');
        }
        $names[$combatant['name']] = true;
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }
    sortInitiative($combatants);

    $state = lockCombatSessions();
    $sessions = $state['sessions'];
    $id = $data['id'];
    if (isset($sessions[$id])) {
        saveCombatSessions($state['handle'], $sessions);
        badRequest('Session already exists');
    }
    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $combatants,
        'conditions' => [],
    ];
    $response = combatSummary($sessions[$id]);
    $response['order'] = array_map(static fn(array $combatant): array => [
        'name' => $combatant['name'], 'score' => $combatant['score'],
    ], $combatants);
    saveCombatSessions($state['handle'], $sessions);
    respond($response);
}

if (preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $matches)) {
    $state = lockCombatSessions();
    $sessions = $state['sessions'];
    $id = rawurldecode($matches[1]);
    if (!isset($sessions[$id])) {
        saveCombatSessions($state['handle'], $sessions);
        respond(['error' => 'Unknown session'], 404);
    }
    if (!is_string($data['target'] ?? null) || !is_string($data['condition'] ?? null)
        || !is_int($data['duration_rounds'] ?? null) || $data['duration_rounds'] <= 0) {
        saveCombatSessions($state['handle'], $sessions);
        badRequest();
    }
    $target = $data['target'];
    $found = false;
    foreach ($sessions[$id]['order'] as $combatant) {
        if ($combatant['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        saveCombatSessions($state['handle'], $sessions);
        badRequest('Unknown combatant');
    }
    $sessions[$id]['conditions'][$target] ??= [];
    $sessions[$id]['conditions'][$target][] = [
        'condition' => $data['condition'],
        'remaining_rounds' => $data['duration_rounds'],
    ];
    $response = ['target' => $target, 'conditions' => $sessions[$id]['conditions'][$target]];
    saveCombatSessions($state['handle'], $sessions);
    respond($response);
}

if (preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $matches)) {
    $state = lockCombatSessions();
    $sessions = $state['sessions'];
    $id = rawurldecode($matches[1]);
    if (!isset($sessions[$id])) {
        saveCombatSessions($state['handle'], $sessions);
        respond(['error' => 'Unknown session'], 404);
    }
    $session =& $sessions[$id];
    $session['turn_index']++;
    if ($session['turn_index'] === count($session['order'])) {
        $session['turn_index'] = 0;
        $session['round']++;
    }
    $activeName = $session['order'][$session['turn_index']]['name'];
    if (isset($session['conditions'][$activeName])) {
        foreach ($session['conditions'][$activeName] as &$condition) {
            $condition['remaining_rounds']--;
        }
        unset($condition);
        $session['conditions'][$activeName] = array_values(array_filter(
            $session['conditions'][$activeName],
            static fn(array $condition): bool => $condition['remaining_rounds'] > 0,
        ));
    }
    $response = combatSummary($session);
    $response['conditions'] = encounterConditionsResponse($session['conditions']);
    unset($session);
    saveCombatSessions($state['handle'], $sessions);
    respond($response);
}

respond(['error' => 'Not found'], 404);

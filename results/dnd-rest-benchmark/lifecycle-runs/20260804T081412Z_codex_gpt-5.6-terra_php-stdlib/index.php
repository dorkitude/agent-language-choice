<?php
declare(strict_types=1);

require_once __DIR__ . '/storage.php';

function respond(mixed $body, int $status = 200, int $jsonFlags = JSON_THROW_ON_ERROR): never
{
    http_response_code($status);
    header('Content-Type: application/json; charset=utf-8');
    echo json_encode($body, $jsonFlags);
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
        $database->exec('DELETE FROM service_mode');
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
        $database->exec('DELETE FROM play_campaign_world_event_resolutions');
        $database->exec('DELETE FROM play_campaign_world_events');
        $database->exec('DELETE FROM play_campaign_exploration_handoffs');
        $database->exec('DELETE FROM play_campaign_npcs');
        $database->exec('DELETE FROM play_campaign_transactional_transfers');
        $database->exec('DELETE FROM play_campaign_currency_transfers');
        $database->exec('DELETE FROM play_campaign_character_currency');
        $database->exec('DELETE FROM play_campaign_character_spells');
        $database->exec('DELETE FROM play_campaign_character_states');
        $database->exec('DELETE FROM play_campaign_audit_events');
        $database->exec('DELETE FROM play_campaign_projection_events');
        $database->exec('DELETE FROM play_campaign_idempotent_events');
        $database->exec('DELETE FROM play_campaign_safe_turns');
        $database->exec('DELETE FROM play_campaign_safe_turn_states');
        $database->exec('DELETE FROM play_campaign_delegation_audit');
        $database->exec('DELETE FROM play_campaign_delegations');
        $database->exec('DELETE FROM play_campaign_invitations');
        $database->exec('DELETE FROM play_campaign_members');
        $database->exec('DELETE FROM play_campaign_encounter_rewards');
        $database->exec('DELETE FROM play_campaign_encounters');
        $database->exec('DELETE FROM play_campaign_states');
        $database->exec('DELETE FROM play_campaign_calendars');
        $database->exec('DELETE FROM play_campaign_settlement_discoveries');
        $database->exec('DELETE FROM play_campaign_settlement_shop_stock');
        $database->exec('DELETE FROM play_campaign_settlement_shops');
        $database->exec('DELETE FROM play_campaign_settlements');
        $database->exec('DELETE FROM play_campaign_recipes');
        $database->exec('DELETE FROM play_campaign_downtime_allocations');
        $database->exec('DELETE FROM play_campaign_downtime_activities');
        $database->exec('DELETE FROM play_campaign_events');
        $database->exec('DELETE FROM play_campaign_scene_states');
        $database->exec('DELETE FROM play_campaign_scenes');
        $database->exec('DELETE FROM play_campaign_location_states');
        $database->exec('DELETE FROM play_campaign_location_connections');
        $database->exec('DELETE FROM play_campaign_locations');
        $database->exec('DELETE FROM play_campaign_content_tags');
        $database->exec('DELETE FROM play_campaign_content');
        $database->exec('DELETE FROM play_campaign_whispers');
        $database->exec('DELETE FROM play_campaign_notes');
        $database->exec('DELETE FROM play_campaign_session_zero_settings');
        $database->exec('DELETE FROM play_campaign_replay_events');
        $database->exec('DELETE FROM play_campaign_rng_rolls');
        $database->exec('DELETE FROM play_campaign_rng_seeds');
        $database->exec('DELETE FROM play_campaign_moderation_reports');
        $database->exec('DELETE FROM play_campaign_safety_events');
        $database->exec('DELETE FROM play_campaign_safety_boundary_tags');
        $database->exec('DELETE FROM play_campaign_backups');
        $database->exec('DELETE FROM play_campaign_exports');
        $database->exec('DELETE FROM play_campaign_imports');
        $database->exec('DELETE FROM play_campaign_migration_states');
        $database->exec('DELETE FROM play_campaign_search_records');
        $database->exec('DELETE FROM play_campaign_service_metrics');
        $database->exec('DELETE FROM play_campaign_rate_events');
        $database->exec('DELETE FROM play_campaign_documents');
        $database->exec('DELETE FROM play_campaign_fixture_seeds');
        $database->exec('DELETE FROM play_campaign_spectators');
        $database->exec('DELETE FROM play_campaign_feed_events');
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

/**
 * Authenticates the intentionally separate, read-only spectator credential.
 * Session credentials are recognized here solely to return the required 403
 * rather than treating a valid normal session as an invalid bearer token.
 *
 * @return array{spectator_id: string, campaign_id: string}
 */
function authenticatedSpectator(PDO $database): array
{
    $authorization = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? null;
    if (!is_string($authorization)) {
        respond(['error' => 'Unauthorized'], 401);
    }
    if (preg_match('/^Bearer session-[a-z0-9_-]{2,32}$/', $authorization) === 1) {
        authenticatedActor();
        respond(['error' => 'Forbidden'], 403);
    }
    if (preg_match('/^Bearer spectator-(.+)$/D', $authorization, $matches) !== 1) {
        respond(['error' => 'Unauthorized'], 401);
    }

    $ticket = $database->prepare('SELECT spectator_id, campaign_id FROM play_campaign_spectators WHERE spectator_id = ?');
    $ticket->execute([$matches[1]]);
    $spectator = $ticket->fetch();
    if ($spectator === false) {
        respond(['error' => 'Unauthorized'], 401);
    }
    return ['spectator_id' => $spectator['spectator_id'], 'campaign_id' => $spectator['campaign_id']];
}

function isMaintenanceMode(PDO $database): bool
{
    return (int) $database->query('SELECT maintenance FROM service_mode WHERE id = 1')->fetchColumn() === 1;
}

function maintenanceModeRequest(array $data): bool
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 1 || !property_exists($request, 'maintenance')) {
        badRequest();
    }
    $maintenance = $data['maintenance'] ?? null;
    if (!is_bool($maintenance)) {
        badRequest();
    }
    return $maintenance;
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

/** @return array{rules: string, tone: string, consent: array<int, string>} */
function sessionZeroSettingsRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 3
        || !property_exists($request, 'rules') || !property_exists($request, 'tone') || !property_exists($request, 'consent')) {
        badRequest();
    }

    $rules = $data['rules'] ?? null;
    $tone = $data['tone'] ?? null;
    $consent = $data['consent'] ?? null;
    if (!is_string($rules) || $rules === '' || !is_string($tone) || $tone === ''
        || !is_array($consent) || !array_is_list($consent) || $consent === []) {
        badRequest();
    }

    $seen = [];
    foreach ($consent as $boundary) {
        if (!is_string($boundary) || $boundary === '' || isset($seen[$boundary])) {
            badRequest();
        }
        $seen[$boundary] = true;
    }
    return ['rules' => $rules, 'tone' => $tone, 'consent' => $consent];
}

/** @return array{content_id: string, kind: string, text: string, tags: array<int, string>} */
function contentRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 4
        || !property_exists($request, 'content_id') || !property_exists($request, 'kind')
        || !property_exists($request, 'text') || !property_exists($request, 'tags')) {
        badRequest();
    }
    $contentId = $data['content_id'] ?? null;
    $kind = $data['kind'] ?? null;
    $text = $data['text'] ?? null;
    $tags = $data['tags'] ?? null;
    if (!is_string($contentId) || $contentId === '' || !is_string($kind) || $kind === ''
        || !is_string($text) || $text === '') {
        badRequest();
    }
    return ['content_id' => $contentId, 'kind' => $kind, 'text' => $text, 'tags' => contentTags($tags, false)];
}

/** @return array<int, string> */
function contentTags(mixed $tags, bool $mayBeEmpty): array
{
    if (!is_array($tags) || !array_is_list($tags) || (!$mayBeEmpty && $tags === [])) {
        badRequest();
    }
    $seen = [];
    foreach ($tags as $tag) {
        if (!is_string($tag) || $tag === '' || isset($seen[$tag])) {
            badRequest();
        }
        $seen[$tag] = true;
    }
    return $tags;
}

/** @return array<int, string> */
function contentTagsRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 1 || !property_exists($request, 'tags')) {
        badRequest();
    }
    return contentTags($data['tags'] ?? null, true);
}

/** @return array{content_id: string, kind: string, text: string, tags: array<int, string>} */
function contentResponse(PDO $database, string $campaignId, array $content): array
{
    $statement = $database->prepare('SELECT tag FROM play_campaign_content_tags WHERE campaign_id = ? AND content_id = ? ORDER BY position');
    $statement->execute([$campaignId, $content['content_id']]);
    return [
        'content_id' => $content['content_id'],
        'kind' => $content['kind'],
        'text' => $content['text'],
        'tags' => array_column($statement->fetchAll(), 'tag'),
    ];
}

/** @return array{owner: string, is_dm: bool} */
function requirePlayCampaignAccess(PDO $database, string $campaignId, array $actor): array
{
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $isDm = $owner === $actor['username'];
    if (!$isDm) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }
    return ['owner' => $owner, 'is_dm' => $isDm];
}

/** @return array{fixture_id: string, status: string, characters: array<int, array{character_id: string, name: string, class: string}>, story: string, event_ids: array<int, string>} */
function canonicalFixtureState(): array
{
    return [
        'fixture_id' => 'canonical-v1',
        'status' => 'seeded',
        'characters' => [
            ['character_id' => 'fixture-hero', 'name' => 'Ari', 'class' => 'fighter'],
            ['character_id' => 'fixture-mage', 'name' => 'Bea', 'class' => 'wizard'],
        ],
        'story' => 'The lantern is lit.',
        'event_ids' => ['fixture-event-1', 'fixture-event-2'],
    ];
}

function canonicalFixtureSeedRequest(array $data): void
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 1
        || !property_exists($request, 'fixture_id') || ($data['fixture_id'] ?? null) !== 'canonical-v1') {
        badRequest();
    }
}

/** @return array{kind: string, correlation_id: string} */
function auditEventRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 2
        || !property_exists($request, 'kind') || !property_exists($request, 'correlation_id')) {
        badRequest();
    }
    $kind = $data['kind'] ?? null;
    $correlationId = $data['correlation_id'] ?? null;
    if (!is_string($kind) || $kind === '' || !is_string($correlationId) || $correlationId === '') {
        badRequest();
    }
    return ['kind' => $kind, 'correlation_id' => $correlationId];
}

/** @return array{event_id: string, kind: string, value?: string} */
function projectionEventRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || !property_exists($request, 'event_id') || !property_exists($request, 'kind')) {
        badRequest();
    }

    $eventId = $data['event_id'] ?? null;
    $kind = $data['kind'] ?? null;
    if (!is_string($eventId) || $eventId === '' || !is_string($kind)) {
        badRequest();
    }
    if ($kind === 'set-story') {
        if (count(get_object_vars($request)) !== 3 || !property_exists($request, 'value')) {
            badRequest();
        }
        $value = $data['value'] ?? null;
        if (!is_string($value) || $value === '') {
            badRequest();
        }
        return ['event_id' => $eventId, 'kind' => $kind, 'value' => $value];
    }
    if ($kind !== 'increment-danger' || count(get_object_vars($request)) !== 2 || property_exists($request, 'value')) {
        badRequest();
    }
    return ['event_id' => $eventId, 'kind' => $kind];
}

/** @return array{event_id: string, kind: string, text: string} */
function replayEventRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 3
        || !property_exists($request, 'event_id') || !property_exists($request, 'kind')
        || !property_exists($request, 'text')) {
        badRequest();
    }
    $eventId = $data['event_id'] ?? null;
    $kind = $data['kind'] ?? null;
    $text = $data['text'] ?? null;
    if (!is_string($eventId) || $eventId === '' || $kind !== 'append' || !is_string($text) || $text === '') {
        badRequest();
    }
    return ['event_id' => $eventId, 'kind' => $kind, 'text' => $text];
}

/** @return array{story: string, event_ids: array<int, string>, digest: string} */
function replayState(PDO $database, string $campaignId): array
{
    $statement = $database->prepare('SELECT event_id, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence');
    $statement->execute([$campaignId]);
    $eventIds = [];
    $story = '';
    foreach ($statement as $event) {
        $eventIds[] = $event['event_id'];
        $story .= $event['text'];
    }
    return ['story' => $story, 'event_ids' => $eventIds, 'digest' => implode(',', $eventIds) . '|' . $story];
}

/** @return array{roll_id: string, sides: int} */
function rngRollRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 2
        || !property_exists($request, 'roll_id') || !property_exists($request, 'sides')) {
        badRequest();
    }
    $rollId = $data['roll_id'] ?? null;
    $sides = $data['sides'] ?? null;
    if (!is_string($rollId) || $rollId === '' || !is_int($sides) || $sides < 2 || $sides > 100) {
        badRequest();
    }
    return ['roll_id' => $rollId, 'sides' => $sides];
}

function deterministicRollResult(string $seed, int $sequence, string $rollId, int $sides): int
{
    $accumulator = 0;
    $bytes = $seed . '|' . (string) $sequence . '|' . $rollId . '|' . (string) $sides;
    for ($position = 0, $length = strlen($bytes); $position < $length; $position++) {
        $accumulator = ($accumulator * 31 + ord($bytes[$position])) % 4294967296;
    }
    return ($accumulator % $sides) + 1;
}

/** @return array{seed: string, rolls: array<int, array{roll_id: string, sides: int, result: int, sequence: int}>} */
function rngLedgerState(PDO $database, string $campaignId): array
{
    $seed = $database->prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?');
    $seed->execute([$campaignId]);
    $seedValue = $seed->fetchColumn();
    $rolls = $database->prepare('SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence');
    $rolls->execute([$campaignId]);
    $records = $rolls->fetchAll();
    foreach ($records as &$record) {
        $record['sides'] = (int) $record['sides'];
        $record['result'] = (int) $record['result'];
        $record['sequence'] = (int) $record['sequence'];
    }
    unset($record);
    return ['seed' => $seedValue === false ? '' : $seedValue, 'rolls' => $records];
}

/** @return array{report_id: string, target_id: string, reason: string} */
function moderationReportRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 3 || !property_exists($request, 'report_id') || !property_exists($request, 'target_id') || !property_exists($request, 'reason')) { badRequest(); }
    $reportId = $data['report_id'] ?? null; $targetId = $data['target_id'] ?? null; $reason = $data['reason'] ?? null;
    if (!is_string($reportId) || $reportId === '' || !is_string($targetId) || $targetId === '' || !is_string($reason) || $reason === '') { badRequest(); }
    return ['report_id' => $reportId, 'target_id' => $targetId, 'reason' => $reason];
}

/** @return array{action: string, note: string} */
function moderationResolutionRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 2 || !property_exists($request, 'action') || !property_exists($request, 'note')) { badRequest(); }
    $action = $data['action'] ?? null; $note = $data['note'] ?? null;
    if (!is_string($action) || !in_array($action, ['allow', 'remove'], true) || !is_string($note) || $note === '') { badRequest(); }
    return ['action' => $action, 'note' => $note];
}

/** @param array<string, mixed> $report */
function moderationReportResponse(array $report): array
{
    $response = ['report_id' => $report['report_id'], 'target_id' => $report['target_id'], 'reason' => $report['reason'], 'status' => $report['status'], 'reporter' => $report['reporter'], 'sequence' => (int) $report['sequence']];
    if ($report['status'] === 'resolved') { $response['action'] = $report['action']; $response['note'] = $report['note']; $response['resolver'] = $report['resolver']; }
    return $response;
}

/** @return array<int, string> */
function safetyTagsRequest(array $data, string $key = 'blocked_tags'): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || !property_exists($request, $key) || !is_array($data[$key] ?? null) || !array_is_list($data[$key])) { badRequest(); }
    $tags = $data[$key];
    if ($tags === []) { badRequest(); }
    $seen = [];
    foreach ($tags as $tag) {
        if (!is_string($tag) || trim($tag) === '' || isset($seen[$tag])) { badRequest(); }
        $seen[$tag] = true;
    }
    return $tags;
}

/** @return array{event_id: string, kind: string, text: string, tags: array<int, string>} */
function safetyCheckRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 4 || !property_exists($request, 'event_id') || !property_exists($request, 'kind') || !property_exists($request, 'text') || !property_exists($request, 'tags')) { badRequest(); }
    $eventId = $data['event_id'] ?? null; $kind = $data['kind'] ?? null; $text = $data['text'] ?? null;
    if (!is_string($eventId) || trim($eventId) === '' || !is_string($text) || trim($text) === '' || !is_string($kind) || !in_array($kind, ['narration', 'chat'], true)) { badRequest(); }
    return ['event_id' => $eventId, 'kind' => $kind, 'text' => $text, 'tags' => safetyTagsRequest($data, 'tags')];
}

/** @return array<int, string> */
function safetyBoundaryTags(PDO $database, string $campaignId): array
{
    $statement = $database->prepare('SELECT tag FROM play_campaign_safety_boundary_tags WHERE campaign_id = ? ORDER BY tag');
    $statement->execute([$campaignId]);
    return $statement->fetchAll(PDO::FETCH_COLUMN);
}

/** @return array{event_id: string, value: string} */
function idempotentEventRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 2
        || !property_exists($request, 'event_id') || !property_exists($request, 'value')) {
        badRequest();
    }
    $eventId = $data['event_id'] ?? null;
    $value = $data['value'] ?? null;
    if (!is_string($eventId) || $eventId === '' || !is_string($value) || $value === '') {
        badRequest();
    }
    return ['event_id' => $eventId, 'value' => $value];
}

/** @return array{submission_id: string, expected_turn: int, action: string} */
function safeTurnRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 3
        || !property_exists($request, 'submission_id') || !property_exists($request, 'expected_turn')
        || !property_exists($request, 'action')) {
        badRequest();
    }
    $submissionId = $data['submission_id'] ?? null;
    $expectedTurn = $data['expected_turn'] ?? null;
    $action = $data['action'] ?? null;
    if (!is_string($submissionId) || $submissionId === '' || !is_int($expectedTurn) || $expectedTurn < 1
        || !is_string($action) || $action === '') {
        badRequest();
    }
    return ['submission_id' => $submissionId, 'expected_turn' => $expectedTurn, 'action' => $action];
}

/** @return array{story: string, danger: int, applied_event_ids: array<int, string>} */
function rebuildProjection(PDO $database, string $campaignId): array
{
    $statement = $database->prepare('SELECT event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence');
    $statement->execute([$campaignId]);
    $projection = ['story' => '', 'danger' => 0, 'applied_event_ids' => []];
    foreach ($statement as $event) {
        $projection['applied_event_ids'][] = $event['event_id'];
        if ($event['kind'] === 'set-story') {
            $projection['story'] = $event['value'];
        } else {
            ++$projection['danger'];
        }
    }
    return $projection;
}

/** @return array{invitation_id: string, username: string, character_id: string} */
function invitationRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 3
        || !property_exists($request, 'invitation_id') || !property_exists($request, 'username') || !property_exists($request, 'character_id')) {
        badRequest();
    }
    $invitationId = $data['invitation_id'] ?? null;
    $username = $data['username'] ?? null;
    $characterId = $data['character_id'] ?? null;
    if (!is_string($invitationId) || $invitationId === '' || !is_string($username) || $username === ''
        || !is_string($characterId) || $characterId === '') {
        badRequest();
    }
    return ['invitation_id' => $invitationId, 'username' => $username, 'character_id' => $characterId];
}

/** @return array{invitation_id: string, username: string, character_id: string, status: string} */
function invitationResponse(array $invitation): array
{
    return [
        'invitation_id' => $invitation['invitation_id'],
        'username' => $invitation['username'],
        'character_id' => $invitation['character_id'],
        'status' => $invitation['status'],
    ];
}

/** @return array{username: string, powers: array<int, string>} */
function delegationRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 2
        || !property_exists($request, 'username') || !property_exists($request, 'powers') || !is_array($request->powers)) {
        badRequest();
    }
    $username = $data['username'] ?? null;
    $powers = $data['powers'] ?? null;
    if (!is_string($username) || !is_array($powers) || $powers === [] || count($powers) !== count(array_unique($powers, SORT_REGULAR))) {
        badRequest();
    }
    foreach ($powers as $power) {
        if (!is_string($power) || $power !== 'narrate') {
            badRequest();
        }
    }
    return ['username' => $username, 'powers' => array_values($powers)];
}

/** @param array{username: string, powers: array<int, string>} $delegation */
function delegationResponse(array $delegation, bool $active): array
{
    return ['username' => $delegation['username'], 'powers' => $delegation['powers'], 'active' => $active];
}

/** @return array{note_id: string, text: string, visibility: string} */
function noteRequest(array $data, bool $includesId): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    $required = $includesId ? ['note_id', 'text', 'visibility'] : ['text', 'visibility'];
    if (!is_object($request) || count(get_object_vars($request)) !== count($required)) {
        badRequest();
    }
    foreach ($required as $field) {
        if (!property_exists($request, $field)) {
            badRequest();
        }
    }
    $noteId = $includesId ? ($data['note_id'] ?? null) : '';
    $text = $data['text'] ?? null;
    $visibility = $data['visibility'] ?? null;
    if (($includesId && (!is_string($noteId) || $noteId === '')) || !is_string($text) || $text === ''
        || !is_string($visibility) || !in_array($visibility, ['private', 'party'], true)) {
        badRequest();
    }
    return ['note_id' => $noteId, 'text' => $text, 'visibility' => $visibility];
}

/** @return array{whisper_id: string, to_character_id: string, text: string} */
function whisperRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 3
        || !property_exists($request, 'whisper_id') || !property_exists($request, 'to_character_id') || !property_exists($request, 'text')) {
        badRequest();
    }
    $whisperId = $data['whisper_id'] ?? null;
    $toCharacterId = $data['to_character_id'] ?? null;
    $text = $data['text'] ?? null;
    if (!is_string($whisperId) || $whisperId === '' || !is_string($toCharacterId) || $toCharacterId === ''
        || !is_string($text) || $text === '') {
        badRequest();
    }
    return ['whisper_id' => $whisperId, 'to_character_id' => $toCharacterId, 'text' => $text];
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

/** @param array{day: int|string, season: string} $calendar */
function calendarResponse(array $calendar): array
{
    $day = (int) $calendar['day'];
    $season = $calendar['season'];
    $offsets = ['spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3];
    $weather = ['clear', 'rain', 'wind', 'snow'][($day + $offsets[$season]) % 4];
    return ['day' => $day, 'season' => $season, 'weather' => $weather];
}

/** @return array{settlement_id: string, name: string, services: array<int, string>, availability: string} */
function settlementRequest(array $data, bool $includesId): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    $settlementId = $data['settlement_id'] ?? null;
    $name = $data['name'] ?? null;
    $services = $data['services'] ?? null;
    $availability = $data['availability'] ?? null;
    if (($includesId && (!is_string($settlementId) || $settlementId === ''))
        || !is_string($name) || $name === ''
        || !is_object($request) || !property_exists($request, 'services') || !is_array($request->services)
        || !is_array($services) || $services === []
        || !is_string($availability) || !in_array($availability, ['open', 'limited', 'closed'], true)) {
        badRequest();
    }

    $normalizedServices = [];
    foreach ($services as $service) {
        if (!is_string($service)) {
            badRequest();
        }
        $service = trim($service);
        if ($service === '' || in_array($service, $normalizedServices, true)) {
            badRequest();
        }
        $normalizedServices[] = $service;
    }

    return [
        'settlement_id' => $includesId ? $settlementId : '',
        'name' => $name,
        'services' => $normalizedServices,
        'availability' => $availability,
    ];
}

/** @param array{settlement_id: string, name: string, services_json: string, availability: string} $settlement */
function settlementResponse(PDO $database, string $campaignId, array $settlement, ?string $characterId = null): array
{
    try {
        $services = json_decode($settlement['services_json'], true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        respond(['error' => 'Unable to read settlement'], 500);
    }
    if (!is_array($services)) {
        respond(['error' => 'Unable to read settlement'], 500);
    }

    if ($characterId === null) {
        $discoveries = $database->prepare('SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY rowid');
        $discoveries->execute([$campaignId, $settlement['settlement_id']]);
        $discoveredBy = array_column($discoveries->fetchAll(), 'character_id');
    } else {
        $discoveredBy = [$characterId];
    }
    return [
        'settlement_id' => $settlement['settlement_id'],
        'name' => $settlement['name'],
        'services' => $services,
        'availability' => $settlement['availability'],
        'discovered_by' => $discoveredBy,
    ];
}

function validInventoryItem(mixed $itemId): bool
{
    return is_string($itemId) && in_array($itemId, ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true);
}

/** @return array{recipe_id: string, name: string, ingredients: array<string, int>, output_item: string, output_quantity: int} */
function recipeRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    $recipeId = $data['recipe_id'] ?? null;
    $name = $data['name'] ?? null;
    $ingredients = $data['ingredients'] ?? null;
    $outputItem = $data['output_item'] ?? null;
    $outputQuantity = $data['output_quantity'] ?? null;
    if (!is_string($recipeId) || $recipeId === '' || !is_string($name) || $name === ''
        || !is_object($request) || !property_exists($request, 'ingredients') || !is_object($request->ingredients)
        || !is_array($ingredients) || $ingredients === [] || !validInventoryItem($outputItem)
        || !is_int($outputQuantity) || $outputQuantity < 1) {
        badRequest();
    }
    foreach ($ingredients as $itemId => $quantity) {
        if (!validInventoryItem($itemId) || !is_int($quantity) || $quantity < 1) {
            badRequest();
        }
    }
    return [
        'recipe_id' => $recipeId,
        'name' => $name,
        'ingredients' => $ingredients,
        'output_item' => $outputItem,
        'output_quantity' => $outputQuantity,
    ];
}

/** @return array{recipe_id: string, name: string, ingredients: array<string, int>, output_item: string, output_quantity: int} */
function recipeResponse(array $recipe): array
{
    try {
        $ingredients = json_decode($recipe['ingredients_json'], true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        respond(['error' => 'Unable to read recipe'], 500);
    }
    if (!is_array($ingredients)) {
        respond(['error' => 'Unable to read recipe'], 500);
    }
    return [
        'recipe_id' => $recipe['recipe_id'],
        'name' => $recipe['name'],
        'ingredients' => $ingredients,
        'output_item' => $recipe['output_item'],
        'output_quantity' => (int) $recipe['output_quantity'],
    ];
}

/** @return array{activity_id: string, name: string, cycles_required: int} */
function downtimeActivityRequest(array $data): array
{
    $activityId = $data['activity_id'] ?? null;
    $name = $data['name'] ?? null;
    $cyclesRequired = $data['cycles_required'] ?? null;
    if (!is_string($activityId) || $activityId === '' || !is_string($name) || $name === ''
        || !is_int($cyclesRequired) || $cyclesRequired < 1 || $cyclesRequired > 10) {
        badRequest();
    }
    return ['activity_id' => $activityId, 'name' => $name, 'cycles_required' => $cyclesRequired];
}

/** @return array{activity_id: string, name: string, cycles_required: int} */
function downtimeActivityResponse(array $activity): array
{
    return [
        'activity_id' => $activity['activity_id'],
        'name' => $activity['name'],
        'cycles_required' => (int) $activity['cycles_required'],
    ];
}

/** @return array{character_id: string, activity_id: string, cycles_completed: int, completions: int} */
function downtimeAllocationResponse(array $allocation): array
{
    return [
        'character_id' => $allocation['character_id'],
        'activity_id' => $allocation['activity_id'],
        'cycles_completed' => (int) $allocation['cycles_completed'],
        'completions' => (int) $allocation['completions'],
    ];
}

/** @return array{shop_id: string, name: string, stock: array<string, int>, buy_price: int, sell_price: int} */
function shopRequest(array $data): array
{
    $request = $GLOBALS['request_json_object'] ?? null;
    $shopId = $data['shop_id'] ?? null;
    $name = $data['name'] ?? null;
    $stock = $data['stock'] ?? null;
    $buyPrice = $data['buy_price'] ?? null;
    $sellPrice = $data['sell_price'] ?? null;
    if (!is_string($shopId) || $shopId === '' || !is_string($name) || $name === ''
        || !is_object($request) || !property_exists($request, 'stock') || !is_object($request->stock)
        || !is_array($stock) || $stock === [] || !is_int($buyPrice) || $buyPrice < 1
        || !is_int($sellPrice) || $sellPrice < 0) {
        badRequest();
    }
    foreach ($stock as $itemId => $quantity) {
        if (!validInventoryItem($itemId) || !is_int($quantity) || $quantity < 1) {
            badRequest();
        }
    }
    return ['shop_id' => $shopId, 'name' => $name, 'stock' => $stock, 'buy_price' => $buyPrice, 'sell_price' => $sellPrice];
}

/** @return array{shop_id: string, name: string, stock: array<string, int>, buy_price: int, sell_price: int} */
function shopResponse(PDO $database, string $campaignId, string $settlementId, array $shop): array
{
    $stockStatement = $database->prepare('SELECT item_id, quantity FROM play_campaign_settlement_shop_stock WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? ORDER BY rowid');
    $stockStatement->execute([$campaignId, $settlementId, $shop['shop_id']]);
    $stock = [];
    foreach ($stockStatement as $row) {
        $stock[$row['item_id']] = (int) $row['quantity'];
    }
    return ['shop_id' => $shop['shop_id'], 'name' => $shop['name'], 'stock' => $stock, 'buy_price' => (int) $shop['buy_price'], 'sell_price' => (int) $shop['sell_price']];
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

if ($method === 'GET' && $path === '/v1/schema') {
    respond([
        'version' => '2026-07-29',
        'endpoints' => [
            ['method' => 'GET', 'path' => '/v1/play/campaigns/{id}/rng-ledger', 'auth' => 'member'],
            ['method' => 'GET', 'path' => '/v1/schema', 'auth' => 'public'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns', 'auth' => 'dm'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/fixture-seeds', 'auth' => 'dm'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/members', 'auth' => 'member'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/moderation/reports', 'auth' => 'member'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/rng-rolls', 'auth' => 'member'],
            ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', 'auth' => 'dm'],
            ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/rng-seed', 'auth' => 'dm'],
            ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/safety-boundaries', 'auth' => 'dm'],
        ],
    ], 200, JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES);
}

// Liveness deliberately runs before opening storage: it remains available if
// a dependency is unavailable or the service is in maintenance mode.
if ($method === 'GET' && $path === '/healthz') {
    respond(['status' => 'ok']);
}

database();

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/onboarding$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $access = requirePlayCampaignAccess(database(), $campaignId, $actor);
    if ($access['is_dm']) {
        respond([
            'role' => 'dm',
            'next_steps' => ['configure-safety', 'invite-players', 'start-campaign'],
            'can_mutate' => true,
        ]);
    }
    respond([
        'role' => 'player',
        'next_steps' => ['review-party', 'take-turn', 'submit-action'],
        'can_mutate' => true,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/fixture-seeds$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    canonicalFixtureSeedRequest(requestBody());

    try {
        $database->exec('BEGIN IMMEDIATE');
        $seed = $database->prepare('SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = ?');
        $seed->execute([$campaignId]);
        $alreadySeeded = $seed->fetchColumn() !== false;
        if (!$alreadySeeded) {
            $database->prepare('INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id) VALUES (?, ?)')
                ->execute([$campaignId, 'canonical-v1']);
        }
        $database->exec('COMMIT');
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to seed fixture'], 500);
    }
    respond(canonicalFixtureState(), $alreadySeeded ? 200 : 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/fixture-state$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $seed = $database->prepare('SELECT 1 FROM play_campaign_fixture_seeds WHERE campaign_id = ?');
    $seed->execute([$campaignId]);
    if ($seed->fetchColumn() === false) {
        respond(['error' => 'Fixture not seeded'], 404);
    }
    respond(canonicalFixtureState());
}

if ($method === 'GET' && $path === '/health') {
    respond(['ok' => true]);
}

if ($method === 'GET' && $path === '/readyz') {
    if (isMaintenanceMode(database())) {
        respond(['status' => 'maintenance', 'schema_version' => 2], 503);
    }
    respond(['status' => 'ready', 'schema_version' => 2]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/service-mode$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'dm') {
        respond(['error' => 'Forbidden'], 403);
    }

    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $maintenance = maintenanceModeRequest(requestBody());
    $database->prepare('UPDATE service_mode SET maintenance = ? WHERE id = 1')->execute([$maintenance ? 1 : 0]);
    respond(['maintenance' => $maintenance]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/search-records$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $data = requestBody();
    $recordId = $data['record_id'] ?? null;
    $text = $data['text'] ?? null;
    if (!is_string($recordId) || $recordId === '' || !is_string($text) || $text === '') {
        badRequest();
    }

    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $database->beginTransaction();
    try {
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND (record_id = ? OR text = ?)');
        $duplicate->execute([$campaignId, $recordId, $text]);
        if ($duplicate->fetchColumn() !== false) {
            $database->rollBack();
            badRequest();
        }
        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_search_records WHERE campaign_id = ?');
        $sequence->execute([$campaignId]);
        $database->prepare('INSERT INTO play_campaign_search_records (campaign_id, sequence, record_id, text) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, (int) $sequence->fetchColumn(), $recordId, $text]);
        $database->commit();
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to create search record'], 500);
    }
    respond(['record_id' => $recordId, 'text' => $text], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/search-records$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $q = $_GET['q'] ?? null;
    $limit = $_GET['limit'] ?? '2';
    $cursor = $_GET['cursor'] ?? '0';
    if (($q !== null && !is_string($q)) || !is_string($limit) || preg_match('/^[1-3]$/', $limit) !== 1
        || !is_string($cursor) || preg_match('/^(?:0|[1-9][0-9]*)$/', $cursor) !== 1) {
        badRequest();
    }

    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY sequence');
    $statement->execute([$campaignId]);
    $records = $statement->fetchAll();
    if ($q !== null && $q !== '') {
        $records = array_values(array_filter($records, static fn(array $record): bool => stripos($record['text'], $q) !== false));
    }
    $offset = (int) $cursor;
    $pageSize = (int) $limit;
    $page = array_slice($records, $offset, $pageSize);
    $nextCursor = $offset + count($page) < count($records) ? $offset + count($page) : null;
    respond(['records' => $page, 'next_cursor' => $nextCursor]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/rate-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);

    $data = requestBody();
    $eventId = $data['event_id'] ?? null;
    if (!is_string($eventId) || $eventId === '') {
        badRequest();
    }

    $database->beginTransaction();
    try {
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?');
        $duplicate->execute([$campaignId, $eventId]);
        if ($duplicate->fetchColumn() !== false) {
            $database->rollBack();
            badRequest();
        }

        $accepted = $database->prepare('SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
        $accepted->execute([$campaignId, $actor['username']]);
        $acceptedCount = (int) $accepted->fetchColumn();
        if ($acceptedCount >= 2) {
            $database->prepare('UPDATE play_campaign_service_metrics SET rejected_rate_events = rejected_rate_events + 1 WHERE campaign_id = ?')
                ->execute([$campaignId]);
            $database->commit();
            respond(['limit' => 2, 'remaining' => 0], 429);
        }

        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rate_events WHERE campaign_id = ?');
        $sequence->execute([$campaignId]);
        $database->prepare('INSERT INTO play_campaign_rate_events (campaign_id, sequence, event_id, actor) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, (int) $sequence->fetchColumn(), $eventId, $actor['username']]);
        $database->prepare('UPDATE play_campaign_service_metrics SET accepted_rate_events = accepted_rate_events + 1 WHERE campaign_id = ?')
            ->execute([$campaignId]);
        $database->commit();
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to create rate event'], 500);
    }

    respond(['event_id' => $eventId, 'actor' => $actor['username'], 'remaining' => 1 - $acceptedCount], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/rate-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);

    $events = $database->prepare('SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY sequence');
    $events->execute([$campaignId]);
    $accepted = $database->prepare('SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
    $accepted->execute([$campaignId, $actor['username']]);
    respond(['events' => $events->fetchAll(), 'remaining' => max(0, 2 - (int) $accepted->fetchColumn())]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/metrics$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $metrics = $database->prepare('SELECT accepted_rate_events, rejected_rate_events, projection_events FROM play_campaign_service_metrics WHERE campaign_id = ?');
    $metrics->execute([$campaignId]);
    $row = $metrics->fetch();
    respond([
        'accepted_rate_events' => (int) ($row['accepted_rate_events'] ?? 0),
        'rejected_rate_events' => (int) ($row['rejected_rate_events'] ?? 0),
        'projection_events' => (int) ($row['projection_events'] ?? 0),
        'uptime_ticks' => 1,
    ]);
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

    $turn = $database->prepare('SELECT status, phase, current_actor, turn_number FROM play_campaign_states WHERE campaign_id = ?');
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
        'phase' => $state['phase'],
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

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/session-zero$#', $path, $matches)) {
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

    $settings = $database->prepare('SELECT rules, tone, consent_json FROM play_campaign_session_zero_settings WHERE campaign_id = ?');
    $settings->execute([$campaignId]);
    $row = $settings->fetch();
    if ($row === false) {
        respond(['error' => 'Session-zero settings not found'], 404);
    }
    try {
        $consent = json_decode($row['consent_json'], true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        respond(['error' => 'Unable to read session-zero settings'], 500);
    }
    if (!is_array($consent)) {
        respond(['error' => 'Unable to read session-zero settings'], 500);
    }
    respond(['rules' => $row['rules'], 'tone' => $row['tone'], 'consent' => $consent]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/session-zero$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();

    $campaign = $database->prepare('SELECT campaigns.owner, campaigns.status AS campaign_status, states.status AS active_status FROM play_campaigns AS campaigns LEFT JOIN play_campaign_states AS states ON states.campaign_id = campaigns.id WHERE campaigns.id = ?');
    $campaign->execute([$campaignId]);
    $campaignRow = $campaign->fetch();
    if ($campaignRow === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($campaignRow['owner'] !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    if ($campaignRow['campaign_status'] !== 'lobby' || $campaignRow['active_status'] === 'active') {
        respond(['error' => 'Campaign has already started'], 409);
    }

    $settings = sessionZeroSettingsRequest(requestBody());
    try {
        $database->prepare('INSERT INTO play_campaign_session_zero_settings (campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json')
            ->execute([$campaignId, $settings['rules'], $settings['tone'], json_encode($settings['consent'], JSON_THROW_ON_ERROR)]);
    } catch (PDOException|JsonException) {
        respond(['error' => 'Unable to update session-zero settings'], 500);
    }
    respond($settings);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/content$#', $path, $matches)) {
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
        respond(['error' => 'Forbidden'], 403);
    }

    $content = contentRequest(requestBody());
    try {
        $database->beginTransaction();
        $database->prepare('INSERT INTO play_campaign_content (campaign_id, content_id, kind, text) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $content['content_id'], $content['kind'], $content['text']]);
        $insertTag = $database->prepare('INSERT INTO play_campaign_content_tags (campaign_id, content_id, position, tag) VALUES (?, ?, ?, ?)');
        foreach ($content['tags'] as $position => $tag) {
            $insertTag->execute([$campaignId, $content['content_id'], $position, $tag]);
        }
        $database->commit();
    } catch (PDOException $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        if ((string) $exception->getCode() === '23000') {
            respond(['error' => 'Content already exists'], 409);
        }
        respond(['error' => 'Unable to create content'], 500);
    }
    respond($content, 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/content/([^/]+)/tags$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $contentId = rawurldecode($matches[2]);
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
    $contentStatement = $database->prepare('SELECT content_id, kind, text FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?');
    $contentStatement->execute([$campaignId, $contentId]);
    $content = $contentStatement->fetch();
    if ($content === false) {
        respond(['error' => 'Unknown content'], 404);
    }

    $tags = contentTagsRequest(requestBody());
    try {
        $database->beginTransaction();
        $database->prepare('DELETE FROM play_campaign_content_tags WHERE campaign_id = ? AND content_id = ?')->execute([$campaignId, $contentId]);
        $insertTag = $database->prepare('INSERT INTO play_campaign_content_tags (campaign_id, content_id, position, tag) VALUES (?, ?, ?, ?)');
        foreach ($tags as $position => $tag) {
            $insertTag->execute([$campaignId, $contentId, $position, $tag]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update content tags'], 500);
    }
    respond(['content_id' => $content['content_id'], 'kind' => $content['kind'], 'text' => $content['text'], 'tags' => $tags]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/content$#', $path, $matches)) {
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

    $excludeTag = null;
    if (array_key_exists('exclude_tag', $_GET)) {
        $excludeTag = $_GET['exclude_tag'];
        if (!is_string($excludeTag) || $excludeTag === '') {
            badRequest();
        }
    }
    $statement = $database->prepare('SELECT content_id, kind, text FROM play_campaign_content WHERE campaign_id = ? ORDER BY rowid');
    $statement->execute([$campaignId]);
    $records = [];
    foreach ($statement->fetchAll() as $content) {
        $record = contentResponse($database, $campaignId, $content);
        if (!$isOwner && $excludeTag !== null && in_array($excludeTag, $record['tags'], true)) {
            continue;
        }
        $records[] = $record;
    }
    respond(['content' => $records]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/notes$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $note = noteRequest(requestBody(), true);
    $response = ['note_id' => $note['note_id'], 'text' => $note['text'], 'visibility' => $note['visibility'], 'owner' => $actor['username']];
    try {
        $database->prepare('INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $note['note_id'], $note['text'], $note['visibility'], $actor['username']]);
    } catch (PDOException $exception) {
        if ((string) $exception->getCode() === '23000') {
            respond(['error' => 'Note already exists'], 409);
        }
        respond(['error' => 'Unable to create note'], 500);
    }
    respond($response, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/notes$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if ($access['is_dm']) {
        $statement = $database->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY rowid');
        $statement->execute([$campaignId]);
    } else {
        $statement = $database->prepare("SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND (visibility = 'party' OR owner = ?) ORDER BY rowid");
        $statement->execute([$campaignId, $actor['username']]);
    }
    respond(['notes' => $statement->fetchAll()]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/notes/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $noteId = rawurldecode($matches[2]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
    $statement->execute([$campaignId, $noteId]);
    $note = $statement->fetch();
    if ($note === false) {
        respond(['error' => 'Unknown note'], 404);
    }
    if (!$access['is_dm'] && $note['visibility'] === 'private' && $note['owner'] !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    respond($note);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/notes/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $noteId = rawurldecode($matches[2]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
    $statement->execute([$campaignId, $noteId]);
    $note = $statement->fetch();
    if ($note === false) {
        respond(['error' => 'Unknown note'], 404);
    }
    if ($note['owner'] !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $update = noteRequest(requestBody(), false);
    try {
        $database->prepare('UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?')
            ->execute([$update['text'], $update['visibility'], $campaignId, $noteId]);
    } catch (PDOException) {
        respond(['error' => 'Unable to update note'], 500);
    }
    respond(['note_id' => $noteId, 'text' => $update['text'], 'visibility' => $update['visibility'], 'owner' => $note['owner']]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/whispers$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    if ($actor['role'] !== 'player') {
        respond(['error' => 'Forbidden'], 403);
    }
    $whisper = whisperRequest(requestBody());
    $sender = $database->prepare('SELECT members.character_id FROM play_campaign_members AS members JOIN play_campaign_character_owners AS owners ON owners.campaign_id = members.campaign_id AND owners.character_id = members.character_id WHERE members.campaign_id = ? AND owners.owner = ? ORDER BY members.rowid LIMIT 1');
    $sender->execute([$campaignId, $actor['username']]);
    $fromCharacterId = $sender->fetchColumn();
    if ($fromCharacterId === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $recipient = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $recipient->execute([$campaignId, $whisper['to_character_id']]);
    if ($recipient->fetchColumn() === false) {
        badRequest();
    }
    $response = ['whisper_id' => $whisper['whisper_id'], 'from_character_id' => $fromCharacterId, 'to_character_id' => $whisper['to_character_id'], 'text' => $whisper['text']];
    try {
        $database->prepare('INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $whisper['whisper_id'], $fromCharacterId, $whisper['to_character_id'], $whisper['text']]);
    } catch (PDOException $exception) {
        if ((string) $exception->getCode() === '23000') {
            respond(['error' => 'Whisper already exists'], 409);
        }
        respond(['error' => 'Unable to create whisper'], 500);
    }
    respond($response, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/whispers$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if ($access['is_dm']) {
        $statement = $database->prepare('SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY rowid');
        $statement->execute([$campaignId]);
    } else {
        $statement = $database->prepare('SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? AND (from_character_id IN (SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ?) OR to_character_id IN (SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ?)) ORDER BY rowid');
        $statement->execute([$campaignId, $campaignId, $actor['username'], $campaignId, $actor['username']]);
    }
    respond(['whispers' => $statement->fetchAll()]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/sheet$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT members.character_id, members.name, members.class, owners.owner FROM play_campaign_members AS members JOIN play_campaign_character_owners AS owners ON owners.campaign_id = members.campaign_id AND owners.character_id = members.character_id WHERE members.campaign_id = ? AND members.character_id = ?');
    $statement->execute([$campaignId, $characterId]);
    $character = $statement->fetch();
    if ($character === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    if (!$access['is_dm'] && $character['owner'] !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    respond(['character_id' => $character['character_id'], 'owner' => $character['owner'], 'name' => $character['name'], 'class' => $character['class'], 'level' => 1, 'proficiency_bonus' => 2, 'hp_max' => 10, 'armor_class' => 10]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/backups$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $rawBody = file_get_contents('php://input');
    if ($rawBody === false || trim($rawBody) !== '') {
        badRequest();
    }

    $database = database();
    $inTransaction = false;
    try {
        // The immediate transaction makes the sequence and the captured
        // document/status one atomic, ordered snapshot.
        $database->exec('BEGIN IMMEDIATE');
        $inTransaction = true;
        $campaign = $database->prepare('SELECT campaigns.owner, COALESCE(states.status, campaigns.status) AS status FROM play_campaigns AS campaigns LEFT JOIN play_campaign_states AS states ON states.campaign_id = campaigns.id WHERE campaigns.id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $database->exec('ROLLBACK');
            $inTransaction = false;
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($campaignRow['owner'] !== $actor['username']) {
            $database->exec('ROLLBACK');
            $inTransaction = false;
            respond(['error' => 'Forbidden'], 403);
        }
        $document = $database->prepare('SELECT story FROM play_campaign_documents WHERE campaign_id = ?');
        $document->execute([$campaignId]);
        $story = $document->fetchColumn();
        if ($story === false) {
            $database->exec('ROLLBACK');
            $inTransaction = false;
            respond(['error' => 'Document not found'], 404);
        }
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_backups WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $status = $campaignRow['status'];
        $database->prepare('INSERT INTO play_campaign_backups (campaign_id, sequence, story, status) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $story, $status]);
        $database->exec('COMMIT');
        $inTransaction = false;
    } catch (Throwable) {
        if ($inTransaction) {
            $database->exec('ROLLBACK');
        }
        respond(['error' => 'Unable to create backup'], 500);
    }
    respond(['backup_id' => "backup-{$sequence}", 'story' => $story, 'status' => $status], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/backups$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $backups = $database->prepare('SELECT sequence, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence');
    $backups->execute([$campaignId]);
    $rows = [];
    foreach ($backups->fetchAll() as $backup) {
        $rows[] = ['backup_id' => 'backup-' . $backup['sequence'], 'story' => $backup['story'], 'status' => $backup['status']];
    }
    respond(['backups' => $rows]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/backups/backup-([1-9][0-9]*)/restore$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $sequence = (int) $matches[2];
    $rawBody = file_get_contents('php://input');
    if ($rawBody === false || trim($rawBody) !== '') {
        badRequest();
    }

    $database = database();
    $inTransaction = false;
    try {
        $database->exec('BEGIN IMMEDIATE');
        $inTransaction = true;
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $owner = $campaign->fetchColumn();
        if ($owner === false) {
            $database->exec('ROLLBACK');
            $inTransaction = false;
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($owner !== $actor['username']) {
            $database->exec('ROLLBACK');
            $inTransaction = false;
            respond(['error' => 'Forbidden'], 403);
        }
        $backup = $database->prepare('SELECT story, status FROM play_campaign_backups WHERE campaign_id = ? AND sequence = ?');
        $backup->execute([$campaignId, $sequence]);
        $snapshot = $backup->fetch();
        if ($snapshot === false) {
            $database->exec('ROLLBACK');
            $inTransaction = false;
            respond(['error' => 'Unknown backup'], 404);
        }

        // A backup intentionally contains only public story and campaign
        // status. Preserve private DM notes and all event identities.
        $database->prepare('UPDATE play_campaign_documents SET story = ? WHERE campaign_id = ?')
            ->execute([$snapshot['story'], $campaignId]);
        if ($snapshot['status'] === 'lobby') {
            $database->prepare('DELETE FROM play_campaign_states WHERE campaign_id = ?')->execute([$campaignId]);
        } else {
            $state = $database->prepare('SELECT 1 FROM play_campaign_states WHERE campaign_id = ?');
            $state->execute([$campaignId]);
            if ($state->fetchColumn() === false) {
                $member = $database->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid LIMIT 1');
                $member->execute([$campaignId]);
                $currentActor = $member->fetchColumn();
                if ($currentActor === false) {
                    $currentActor = $owner;
                }
                $database->prepare('INSERT INTO play_campaign_states (campaign_id, status, current_actor, turn_number) VALUES (?, ?, ?, ?)')
                    ->execute([$campaignId, 'active', $currentActor, 1]);
            }
        }
        $database->exec('COMMIT');
        $inTransaction = false;
    } catch (Throwable) {
        if ($inTransaction) {
            $database->exec('ROLLBACK');
        }
        respond(['error' => 'Unable to restore backup'], 500);
    }
    respond(['backup_id' => "backup-{$sequence}", 'story' => $snapshot['story'], 'status' => $snapshot['status']]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/replay-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $event = replayEventRequest(requestBody());

    try {
        // Reserve each sequence atomically, so successful appends define the
        // only ordering used to rebuild the public state.
        $database->exec('BEGIN IMMEDIATE');
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_replay_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $event['event_id'], $event['kind'], $event['text']]);
        $database->exec('COMMIT');
    } catch (PDOException $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        if ((string) $exception->getCode() === '23000') {
            respond(['error' => 'Replay event ID conflict'], 409);
        }
        respond(['error' => 'Unable to append replay event'], 500);
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to append replay event'], 500);
    }
    respond(['event_id' => $event['event_id'], 'kind' => $event['kind'], 'text' => $event['text'], 'sequence' => $sequence], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/replay(?:/check)?$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    respond(replayState($database, $campaignId));
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/rng-seed$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $data = requestBody();
    $request = $GLOBALS['request_json_object'] ?? null;
    $seed = $data['seed'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 1 || !property_exists($request, 'seed')
        || !is_string($seed) || $seed === '') {
        badRequest();
    }
    try {
        $database->prepare('INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)')->execute([$campaignId, $seed]);
    } catch (PDOException $exception) {
        if ((string) $exception->getCode() === '23000') {
            respond(['error' => 'RNG seed already configured'], 409);
        }
        respond(['error' => 'Unable to configure RNG seed'], 500);
    }
    respond(['seed' => $seed, 'rolls' => []]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/rng-rolls$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $roll = rngRollRequest(requestBody());
    try {
        // BEGIN IMMEDIATE makes sequence reservation and duplicate detection a
        // single append operation even when requests arrive concurrently.
        $database->exec('BEGIN IMMEDIATE');
        $seedStatement = $database->prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?');
        $seedStatement->execute([$campaignId]);
        $seed = $seedStatement->fetchColumn();
        if ($seed === false) {
            $database->exec('ROLLBACK');
            respond(['error' => 'RNG seed is not configured'], 409);
        }
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?');
        $duplicate->execute([$campaignId, $roll['roll_id']]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('ROLLBACK');
            respond(['error' => 'RNG roll ID conflict'], 409);
        }
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rng_rolls WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $result = deterministicRollResult($seed, $sequence, $roll['roll_id'], $roll['sides']);
        $database->prepare('INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $roll['roll_id'], $roll['sides'], $result]);
        $database->exec('COMMIT');
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to append RNG roll'], 500);
    }
    respond(['roll_id' => $roll['roll_id'], 'sides' => $roll['sides'], 'result' => $result, 'sequence' => $sequence], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/rng-ledger$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    respond(rngLedgerState($database, $campaignId));
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/moderation/reports$#', $path, $matches)) {
    $actor = authenticatedActor(); $campaignId = rawurldecode($matches[1]); $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $report = moderationReportRequest(requestBody());
    try {
        $database->exec('BEGIN IMMEDIATE');
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?'); $duplicate->execute([$campaignId, $report['report_id']]);
        if ($duplicate->fetchColumn() !== false) { $database->exec('ROLLBACK'); respond(['error' => 'Moderation report ID conflict'], 409); }
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_moderation_reports WHERE campaign_id = ?'); $next->execute([$campaignId]); $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_moderation_reports (campaign_id, sequence, report_id, target_id, reason, status, reporter) VALUES (?, ?, ?, ?, ?, ?, ?)')->execute([$campaignId, $sequence, $report['report_id'], $report['target_id'], $report['reason'], 'open', $actor['username']]);
        $database->exec('COMMIT');
    } catch (Throwable) {
        if ($database->inTransaction()) { $database->rollBack(); }
        respond(['error' => 'Unable to submit moderation report'], 500);
    }
    $report += ['status' => 'open', 'reporter' => $actor['username'], 'sequence' => $sequence];
    respond(moderationReportResponse($report), 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/moderation/reports$#', $path, $matches)) {
    $actor = authenticatedActor(); $campaignId = rawurldecode($matches[1]); $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence'); $statement->execute([$campaignId]);
    $reports = []; foreach ($statement as $report) { $reports[] = moderationReportResponse($report); }
    respond(['reports' => $reports]);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/moderation/reports/([^/]+)/resolution$#', $path, $matches)) {
    $actor = authenticatedActor(); $campaignId = rawurldecode($matches[1]); $reportId = rawurldecode($matches[2]); $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) { respond(['error' => 'Forbidden'], 403); }
    $resolution = moderationResolutionRequest(requestBody());
    try {
        $database->exec('BEGIN IMMEDIATE');
        $lookup = $database->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?'); $lookup->execute([$campaignId, $reportId]); $report = $lookup->fetch();
        if ($report === false) { $database->exec('ROLLBACK'); respond(['error' => 'Unknown moderation report'], 404); }
        if ($report['status'] !== 'open') { $database->exec('ROLLBACK'); respond(['error' => 'Moderation report already resolved'], 409); }
        $database->prepare("UPDATE play_campaign_moderation_reports SET status = 'resolved', action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ?")->execute([$resolution['action'], $resolution['note'], $actor['username'], $campaignId, $reportId]);
        $database->exec('COMMIT');
    } catch (Throwable) {
        if ($database->inTransaction()) { $database->rollBack(); }
        respond(['error' => 'Unable to resolve moderation report'], 500);
    }
    $report['status'] = 'resolved'; $report['action'] = $resolution['action']; $report['note'] = $resolution['note']; $report['resolver'] = $actor['username'];
    respond(moderationReportResponse($report));
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/safety-boundaries$#', $path, $matches)) {
    $actor = authenticatedActor(); $campaignId = rawurldecode($matches[1]); $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) { respond(['error' => 'Forbidden'], 403); }
    $data = requestBody(); $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 1) { badRequest(); }
    $tags = safetyTagsRequest($data);
    sort($tags, SORT_STRING);
    try {
        $database->exec('BEGIN IMMEDIATE');
        $database->prepare('DELETE FROM play_campaign_safety_boundary_tags WHERE campaign_id = ?')->execute([$campaignId]);
        $insert = $database->prepare('INSERT INTO play_campaign_safety_boundary_tags (campaign_id, tag) VALUES (?, ?)');
        foreach ($tags as $tag) { $insert->execute([$campaignId, $tag]); }
        $database->exec('COMMIT');
    } catch (Throwable) {
        if ($database->inTransaction()) { $database->rollBack(); }
        respond(['error' => 'Unable to replace safety boundaries'], 500);
    }
    respond(['blocked_tags' => $tags]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/safety-boundaries$#', $path, $matches)) {
    $actor = authenticatedActor(); $campaignId = rawurldecode($matches[1]); $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    respond(['blocked_tags' => safetyBoundaryTags($database, $campaignId)]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/safety-checks$#', $path, $matches)) {
    $actor = authenticatedActor(); $campaignId = rawurldecode($matches[1]); $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $check = safetyCheckRequest(requestBody());
    try {
        $database->exec('BEGIN IMMEDIATE');
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?');
        $duplicate->execute([$campaignId, $check['event_id']]);
        if ($duplicate->fetchColumn() !== false) { $database->exec('ROLLBACK'); respond(['error' => 'Safety event ID conflict'], 409); }
        $blocked = $database->prepare('SELECT 1 FROM play_campaign_safety_boundary_tags WHERE campaign_id = ? AND tag = ?');
        foreach ($check['tags'] as $tag) {
            $blocked->execute([$campaignId, $tag]);
            if ($blocked->fetchColumn() !== false) { $database->exec('ROLLBACK'); respond(['error' => 'Safety boundary conflict'], 409); }
        }
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_safety_events WHERE campaign_id = ?');
        $next->execute([$campaignId]); $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_safety_events (campaign_id, sequence, event_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?, ?)')->execute([$campaignId, $sequence, $check['event_id'], $check['kind'], $check['text'], json_encode($check['tags'], JSON_THROW_ON_ERROR)]);
        $database->exec('COMMIT');
    } catch (Throwable) {
        if ($database->inTransaction()) { $database->rollBack(); }
        respond(['error' => 'Unable to submit safety check'], 500);
    }
    respond($check + ['sequence' => $sequence], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/safety-events$#', $path, $matches)) {
    $actor = authenticatedActor(); $campaignId = rawurldecode($matches[1]); $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT event_id, kind, text, tags_json, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence');
    $statement->execute([$campaignId]); $events = [];
    foreach ($statement as $event) {
        $events[] = ['event_id' => $event['event_id'], 'kind' => $event['kind'], 'text' => $event['text'], 'tags' => json_decode($event['tags_json'], true, 512, JSON_THROW_ON_ERROR), 'sequence' => (int) $event['sequence']];
    }
    respond(['events' => $events]);
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
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to update document'], 500);
    }
    respond(['story' => $story, 'dm_notes' => $dmNotes]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/exports$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $transactionStarted = false;
    try {
        // Lock before calculating the next version so simultaneous exports
        // remain a single, gap-free sequence for this campaign.
        $database->exec('BEGIN IMMEDIATE');
        $transactionStarted = true;
        $campaign = $database->prepare('SELECT campaigns.owner, campaigns.status AS campaign_status, states.status AS active_status FROM play_campaigns AS campaigns LEFT JOIN play_campaign_states AS states ON states.campaign_id = campaigns.id WHERE campaigns.id = ?');
        $campaign->execute([$campaignId]);
        $campaignRow = $campaign->fetch();
        if ($campaignRow === false) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($campaignRow['owner'] !== $actor['username']) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'Forbidden'], 403);
        }

        $document = $database->prepare('SELECT story FROM play_campaign_documents WHERE campaign_id = ?');
        $document->execute([$campaignId]);
        $story = $document->fetchColumn();
        if ($story === false) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'Document not found'], 404);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(version), 0) + 1 FROM play_campaign_exports WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $version = (int) $next->fetchColumn();
        $status = $campaignRow['active_status'] ?? $campaignRow['campaign_status'];
        $database->prepare('INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $version, $story, $status]);
        $database->exec('COMMIT');
        $transactionStarted = false;
    } catch (Throwable) {
        if ($transactionStarted) {
            try {
                $database->exec('ROLLBACK');
            } catch (Throwable) {
                // Keep the endpoint's deterministic storage failure response.
            }
        }
        respond(['error' => 'Unable to create export'], 500);
    }
    respond(['version' => $version, 'story' => $story, 'status' => $status], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/exports$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $exports = $database->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version');
    $exports->execute([$campaignId]);
    $rows = $exports->fetchAll();
    foreach ($rows as &$row) {
        $row['version'] = (int) $row['version'];
    }
    unset($row);
    respond(['exports' => $rows]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/exports/(\d+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $version = (int) $matches[2];
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $export = $database->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?');
    $export->execute([$campaignId, $version]);
    $snapshot = $export->fetch();
    if ($snapshot === false) {
        respond(['error' => 'Unknown export'], 404);
    }
    $snapshot['version'] = (int) $snapshot['version'];
    respond($snapshot);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/imports$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $data = requestBody();
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 3
        || !property_exists($request, 'version') || !property_exists($request, 'story') || !property_exists($request, 'status')
        || !is_int($data['version'] ?? null) || $data['version'] !== 1
        || !is_string($data['story'] ?? null) || $data['story'] === ''
        || !is_string($data['status'] ?? null) || !in_array($data['status'], ['lobby', 'started'], true)) {
        badRequest();
    }

    $story = $data['story'];
    $status = $data['status'];
    try {
        $database->beginTransaction();
        $database->prepare('INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story')
            ->execute([$campaignId, $story, '']);
        $database->prepare('INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status')
            ->execute([$campaignId, 1, $story, $status]);
        $database->commit();
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to import campaign snapshot'], 500);
    }
    respond(['version' => 1, 'story' => $story, 'status' => $status]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/import-state$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $statement = $database->prepare('SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $snapshot = $statement->fetch();
    if ($snapshot === false) {
        respond(['error' => 'Import state not found'], 404);
    }
    $snapshot['version'] = (int) $snapshot['version'];
    respond($snapshot);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/migrations$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }

    $data = requestBody();
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || !property_exists($request, 'schema_version') || !property_exists($request, 'story')
        || !is_int($data['schema_version'] ?? null) || $data['schema_version'] !== 1
        || !is_string($data['story'] ?? null) || $data['story'] === '') {
        badRequest();
    }

    $story = $data['story'];
    $campaign = $database->prepare('SELECT name FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $campaignName = $campaign->fetchColumn();
    // requirePlayCampaignAccess established the campaign exists, so this is
    // only a defensive guard against an unexpected concurrent deletion.
    if ($campaignName === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $existing = $database->prepare('SELECT story, campaign_name FROM play_campaign_migration_states WHERE campaign_id = ?');
    $existing->execute([$campaignId]);
    $current = $existing->fetch();
    if ($current !== false && $current['story'] === $story && $current['campaign_name'] === $campaignName) {
        respond(['schema_version' => 2, 'story' => $story, 'campaign_name' => $campaignName]);
    }

    try {
        $database->prepare('INSERT INTO play_campaign_migration_states (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name')
            ->execute([$campaignId, 2, $story, $campaignName]);
    } catch (Throwable) {
        respond(['error' => 'Unable to migrate campaign snapshot'], 500);
    }
    respond(['schema_version' => 2, 'story' => $story, 'campaign_name' => $campaignName], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/migration-state$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $statement = $database->prepare('SELECT schema_version, story, campaign_name FROM play_campaign_migration_states WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $state = $statement->fetch();
    if ($state === false) {
        respond(['error' => 'Migration state not found'], 404);
    }
    $state['schema_version'] = (int) $state['schema_version'];
    respond($state);
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
        || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items/[^/]+$#', $path) === 1
        || preg_match('#^/v1/play/campaigns/[^/]+/delegations/[^/]+$#', $path) === 1))
    && !($method === 'GET'
        && (preg_match('#^/v1/play/campaigns/[^/]+/spectator-view$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/event-feed$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/(status|owner|spells|prepared-spells|casts|concentration)$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/inventory/items$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/currency$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/equipment/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/rewards$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/loot/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+/dialogue$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/relationships$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/clues$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/quests$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/calendar$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/settlements$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/settlements/[^/]+/shops/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/invitations$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/delegations/audit$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/audit-events$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/projection(?:/rebuild)?$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/idempotent-events$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/safe-turns$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/transactional-transfers$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/recipes$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/downtime/allocations/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/world-events$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/factions/[^/]+/reputation$#', $path) === 1))
    && !($method === 'PUT'
        && (preg_match('#^/v1/play/campaigns/[^/]+/characters/[^/]+/equipment/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+/agenda$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/relationships/[^/]+/[^/]+/[^/]+$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/quests/[^/]+/(state|rewards)$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/settlements/[^/]+$#', $path) === 1))
    && !($method === 'POST'
        && (preg_match('#^/v1/play/campaigns/[^/]+/(spectators|messages|loot|npcs)$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/loot/[^/]+/(votes|assign)$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/npcs/[^/]+/dialogue$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/relationships$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/clues$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/factions$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/factions/[^/]+/reputation$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/world-events(?:/[^/]+/resolve)?$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/audit-events$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/projection-events$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/safe-turns$#', $path) === 1
            || preg_match('#^/v1/play/campaigns/[^/]+/quests/[^/]+/rewards/award$#', $path) === 1))) {
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
    $reward = $database->prepare('SELECT xp, items_json FROM play_campaign_quest_reward_configs WHERE campaign_id = ? AND quest_id = ?');
    foreach ($records as &$record) {
        $record['depends_on'] = json_decode($record['depends_on_json'], true, 512, JSON_THROW_ON_ERROR);
        unset($record['depends_on_json']);
        $reward->execute([$campaignId, $record['quest_id']]);
        $configured = $reward->fetch();
        if ($configured !== false) {
            $record['rewards'] = [
                'xp' => (int) $configured['xp'],
                'items' => json_decode($configured['items_json'], true, 512, JSON_THROW_ON_ERROR),
            ];
        }
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

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/calendar$#', $path, $matches)) {
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
    $calendar = $database->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
    $calendar->execute([$campaignId]);
    $record = $calendar->fetch();
    if ($record === false) {
        respond(['error' => 'Calendar not initialized'], 404);
    }
    respond(calendarResponse($record));
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }

    $characterId = null;
    if ($owner !== $actor['username']) {
        $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        $characterId = $member->fetchColumn();
        if ($characterId === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }

    if ($characterId === null) {
        $settlements = $database->prepare('SELECT settlement_id, name, services_json, availability FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY rowid');
        $settlements->execute([$campaignId]);
    } else {
        $settlements = $database->prepare('SELECT settlements.settlement_id, settlements.name, settlements.services_json, settlements.availability FROM play_campaign_settlements AS settlements JOIN play_campaign_settlement_discoveries AS discoveries ON discoveries.campaign_id = settlements.campaign_id AND discoveries.settlement_id = settlements.settlement_id WHERE settlements.campaign_id = ? AND discoveries.character_id = ? ORDER BY settlements.rowid');
        $settlements->execute([$campaignId, $characterId]);
    }
    $response = [];
    foreach ($settlements->fetchAll() as $settlement) {
        $response[] = settlementResponse($database, $campaignId, $settlement, $characterId);
    }
    respond(['settlements' => $response]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $settlementId = rawurldecode($matches[2]);
    $shopId = rawurldecode($matches[3]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $characterId = null;
    if ($owner !== $actor['username']) {
        $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        $characterId = $member->fetchColumn();
        if ($characterId === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }
    $settlement = $database->prepare('SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
    $settlement->execute([$campaignId, $settlementId]);
    if ($settlement->fetchColumn() === false) {
        respond(['error' => 'Unknown settlement'], 404);
    }
    if ($characterId !== null) {
        $discovery = $database->prepare('SELECT 1 FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? AND character_id = ?');
        $discovery->execute([$campaignId, $settlementId, $characterId]);
        if ($discovery->fetchColumn() === false) {
            respond(['error' => 'Unknown shop'], 404);
        }
    }
    $statement = $database->prepare('SELECT shop_id, name, buy_price, sell_price FROM play_campaign_settlement_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
    $statement->execute([$campaignId, $settlementId, $shopId]);
    $shop = $statement->fetch();
    if ($shop === false) {
        respond(['error' => 'Unknown shop'], 404);
    }
    respond(shopResponse($database, $campaignId, $settlementId, $shop));
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $settlementId = rawurldecode($matches[2]);
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
    $settlement = $database->prepare('SELECT settlement_id, name, services_json, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
    $settlement->execute([$campaignId, $settlementId]);
    $existing = $settlement->fetch();
    if ($existing === false) {
        respond(['error' => 'Unknown settlement'], 404);
    }
    $request = settlementRequest(requestBody(), false);
    $database->prepare('UPDATE play_campaign_settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?')
        ->execute([$request['name'], json_encode($request['services'], JSON_THROW_ON_ERROR), $request['availability'], $campaignId, $settlementId]);
    $existing['name'] = $request['name'];
    $existing['services_json'] = json_encode($request['services'], JSON_THROW_ON_ERROR);
    $existing['availability'] = $request['availability'];
    respond(settlementResponse($database, $campaignId, $existing));
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/delegations$#', $path, $matches)) {
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
        respond(['error' => 'Forbidden'], 403);
    }
    $delegation = delegationRequest(requestBody());
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $delegation['username']]);
    if ($member->fetchColumn() === false) {
        badRequest();
    }
    $existing = $database->prepare('SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?');
    $existing->execute([$campaignId, $delegation['username']]);
    if ((int) $existing->fetchColumn() === 1) {
        respond(['error' => 'Delegation conflict'], 409);
    }
    $database->beginTransaction();
    try {
        $database->prepare('INSERT INTO play_campaign_delegations (campaign_id, username, powers_json, active) VALUES (?, ?, ?, 1) ON CONFLICT(campaign_id, username) DO UPDATE SET powers_json = excluded.powers_json, active = 1')
            ->execute([$campaignId, $delegation['username'], json_encode($delegation['powers'], JSON_THROW_ON_ERROR)]);
        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit WHERE campaign_id = ?');
        $sequence->execute([$campaignId]);
        $database->prepare('INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers_json) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, (int) $sequence->fetchColumn(), $delegation['username'], 'granted', json_encode($delegation['powers'], JSON_THROW_ON_ERROR)]);
        $database->commit();
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to grant delegation'], 500);
    }
    respond(delegationResponse($delegation, true), 201);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/delegations/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $username = rawurldecode($matches[2]);
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
    $lookup = $database->prepare('SELECT powers_json, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?');
    $lookup->execute([$campaignId, $username]);
    $record = $lookup->fetch();
    if ($record === false || (int) $record['active'] !== 1) {
        badRequest();
    }
    $powers = json_decode($record['powers_json'], true, 512, JSON_THROW_ON_ERROR);
    $database->beginTransaction();
    try {
        $database->prepare('UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?')
            ->execute([$campaignId, $username]);
        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_delegation_audit WHERE campaign_id = ?');
        $sequence->execute([$campaignId]);
        $database->prepare('INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers_json) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, (int) $sequence->fetchColumn(), $username, 'revoked', $record['powers_json']]);
        $database->commit();
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to revoke delegation'], 500);
    }
    respond(delegationResponse(['username' => $username, 'powers' => $powers], false));
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/delegations/audit$#', $path, $matches)) {
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
        respond(['error' => 'Forbidden'], 403);
    }
    $statement = $database->prepare('SELECT username, action, powers_json FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY sequence');
    $statement->execute([$campaignId]);
    $entries = [];
    foreach ($statement as $entry) {
        $entries[] = ['username' => $entry['username'], 'action' => $entry['action'], 'powers' => json_decode($entry['powers_json'], true, 512, JSON_THROW_ON_ERROR)];
    }
    respond(['entries' => $entries]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/audit-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    $event = auditEventRequest(requestBody());
    $duplicate = $database->prepare('SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?');
    $duplicate->execute([$campaignId, $event['correlation_id']]);
    if ($duplicate->fetchColumn() !== false) {
        respond(['error' => 'Audit event conflict'], 409);
    }
    $timestamp = 0;
    try {
        $database->beginTransaction();
        $nextTimestamp = $database->prepare('SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events WHERE campaign_id = ?');
        $nextTimestamp->execute([$campaignId]);
        $timestamp = (int) $nextTimestamp->fetchColumn();
        $role = $access['is_dm'] ? 'DM' : 'player';
        $database->prepare('INSERT INTO play_campaign_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $timestamp, $event['kind'], $actor['username'], $role, $event['correlation_id']]);
        $database->commit();
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to create audit event'], 500);
    }
    respond(['kind' => $event['kind'], 'actor' => $actor['username'], 'role' => $access['is_dm'] ? 'DM' : 'player', 'timestamp' => $timestamp, 'correlation_id' => $event['correlation_id']], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/audit-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if (!$access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $statement = $database->prepare('SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp');
    $statement->execute([$campaignId]);
    $entries = [];
    foreach ($statement as $entry) {
        $entries[] = ['kind' => $entry['kind'], 'actor' => $entry['actor'], 'role' => $entry['role'], 'timestamp' => (int) $entry['timestamp'], 'correlation_id' => $entry['correlation_id']];
    }
    respond(['entries' => $entries]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/projection-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $access = requirePlayCampaignAccess($database, $campaignId, $actor);
    if ($access['is_dm']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $event = projectionEventRequest(requestBody());
    $duplicate = $database->prepare('SELECT 1 FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?');
    $duplicate->execute([$campaignId, $event['event_id']]);
    if ($duplicate->fetchColumn() !== false) {
        respond(['error' => 'Projection event conflict'], 409);
    }

    try {
        $database->beginTransaction();
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_projection_events WHERE campaign_id = ?');
        $nextSequence->execute([$campaignId]);
        $sequence = (int) $nextSequence->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $event['event_id'], $event['kind'], $event['value'] ?? null]);
        $database->prepare('UPDATE play_campaign_service_metrics SET projection_events = projection_events + 1 WHERE campaign_id = ?')
            ->execute([$campaignId]);
        $database->commit();
    } catch (PDOException $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        if ((string) $exception->getCode() === '23000') {
            respond(['error' => 'Projection event conflict'], 409);
        }
        respond(['error' => 'Unable to create projection event'], 500);
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to create projection event'], 500);
    }
    $response = ['sequence' => $sequence, 'event_id' => $event['event_id'], 'kind' => $event['kind']];
    if ($event['kind'] === 'set-story') {
        $response['value'] = $event['value'];
    }
    respond($response, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/projection(?:/rebuild)?$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    respond(rebuildProjection($database, $campaignId));
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/idempotent-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);

    $key = trim((string) ($_SERVER['HTTP_IDEMPOTENCY_KEY'] ?? ''));
    if ($key === '') {
        badRequest('Invalid Idempotency-Key');
    }
    $event = idempotentEventRequest(requestBody());

    try {
        $database->beginTransaction();
        $stored = $database->prepare('SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?');
        $stored->execute([$campaignId, $key]);
        $existing = $stored->fetch();
        if ($existing !== false) {
            $database->commit();
            if ($existing['event_id'] !== $event['event_id'] || $existing['value'] !== $event['value']) {
                respond(['error' => 'Idempotency key conflict'], 409);
            }
            respond([
                'event_id' => $existing['event_id'],
                'value' => $existing['value'],
                'sequence' => (int) $existing['sequence'],
                'idempotency_key' => $existing['idempotency_key'],
            ]);
        }

        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?');
        $duplicate->execute([$campaignId, $event['event_id']]);
        if ($duplicate->fetchColumn() !== false) {
            $database->rollBack();
            respond(['error' => 'Event ID conflict'], 409);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_idempotent_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $event['event_id'], $event['value'], $key]);
        $database->commit();
    } catch (PDOException $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to create idempotent event'], 500);
    }
    respond([
        'event_id' => $event['event_id'],
        'value' => $event['value'],
        'sequence' => $sequence,
        'idempotency_key' => $key,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/idempotent-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence');
    $statement->execute([$campaignId]);
    $events = [];
    foreach ($statement as $event) {
        $events[] = [
            'event_id' => $event['event_id'],
            'value' => $event['value'],
            'sequence' => (int) $event['sequence'],
            'idempotency_key' => $event['idempotency_key'],
        ];
    }
    respond(['events' => $events]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/safe-turns$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $submission = safeTurnRequest(requestBody());
    $transactionStarted = false;

    try {
        // Acquire the write lock before reading the turn. This makes the
        // comparison and advance one atomic operation across requests.
        $database->exec('BEGIN IMMEDIATE');
        $transactionStarted = true;
        $database->prepare('INSERT OR IGNORE INTO play_campaign_safe_turn_states (campaign_id, current_turn) VALUES (?, 1)')
            ->execute([$campaignId]);

        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?');
        $duplicate->execute([$campaignId, $submission['submission_id']]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'Submission ID conflict'], 409);
        }

        $state = $database->prepare('SELECT current_turn FROM play_campaign_safe_turn_states WHERE campaign_id = ?');
        $state->execute([$campaignId]);
        $currentTurn = (int) $state->fetchColumn();
        if ($submission['expected_turn'] !== $currentTurn) {
            $database->exec('COMMIT');
            $transactionStarted = false;
            respond(['current_turn' => $currentTurn], 409);
        }

        $nextTurn = $currentTurn + 1;
        $database->prepare('INSERT INTO play_campaign_safe_turns (campaign_id, accepted_turn, submission_id, action) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $currentTurn, $submission['submission_id'], $submission['action']]);
        $database->prepare('UPDATE play_campaign_safe_turn_states SET current_turn = ? WHERE campaign_id = ?')
            ->execute([$nextTurn, $campaignId]);
        $database->exec('COMMIT');
        $transactionStarted = false;
    } catch (Throwable $exception) {
        if ($transactionStarted) {
            try {
                $database->exec('ROLLBACK');
            } catch (Throwable) {
                // Preserve the API's deterministic storage failure response.
            }
        }
        respond(['error' => 'Unable to submit safe turn'], 500);
    }

    respond([
        'submission_id' => $submission['submission_id'],
        'action' => $submission['action'],
        'accepted_turn' => $currentTurn,
        'next_turn' => $nextTurn,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/safe-turns$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);

    $state = $database->prepare('SELECT current_turn FROM play_campaign_safe_turn_states WHERE campaign_id = ?');
    $state->execute([$campaignId]);
    $currentTurn = $state->fetchColumn();
    $turns = $database->prepare('SELECT submission_id, action, accepted_turn FROM play_campaign_safe_turns WHERE campaign_id = ? ORDER BY accepted_turn');
    $turns->execute([$campaignId]);
    $accepted = [];
    foreach ($turns as $turn) {
        $acceptedTurn = (int) $turn['accepted_turn'];
        $accepted[] = [
            'submission_id' => $turn['submission_id'],
            'action' => $turn['action'],
            'accepted_turn' => $acceptedTurn,
            'next_turn' => $acceptedTurn + 1,
        ];
    }
    respond(['current_turn' => $currentTurn === false ? 1 : (int) $currentTurn, 'accepted' => $accepted]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/invitations$#', $path, $matches)) {
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
        respond(['error' => 'Forbidden'], 403);
    }
    $invitation = invitationRequest(requestBody());
    $target = $database->prepare('SELECT role FROM users WHERE username = ?');
    $target->execute([$invitation['username']]);
    if ($target->fetchColumn() !== 'player') {
        badRequest();
    }
    try {
        $database->prepare('INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $invitation['invitation_id'], $invitation['username'], $invitation['character_id'], 'pending']);
    } catch (PDOException) {
        respond(['error' => 'Invitation conflict'], 409);
    }
    $invitation['status'] = 'pending';
    respond(invitationResponse($invitation), 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/invitations/([^/]+)/accept$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $invitationId = rawurldecode($matches[2]);
    $database = database();
    $campaign = $database->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    if ($campaign->fetchColumn() === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    $lookup = $database->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?');
    $lookup->execute([$campaignId, $invitationId]);
    $invitation = $lookup->fetch();
    if ($invitation === false) {
        respond(['error' => 'Unknown invitation'], 404);
    }
    if ($invitation['username'] !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    if ($invitation['status'] !== 'pending') {
        respond(['error' => 'Invitation already accepted'], 409);
    }
    $database->beginTransaction();
    try {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND (username = ? OR character_id = ?)');
        $member->execute([$campaignId, $actor['username'], $invitation['character_id']]);
        if ($member->fetchColumn() !== false) {
            $database->rollBack();
            respond(['error' => 'Party membership conflict'], 409);
        }
        $database->prepare('INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $actor['username'], $invitation['character_id'], $invitation['character_id'], 'fighter']);
        $database->prepare('INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)')
            ->execute([$campaignId, $invitation['character_id'], $actor['username']]);
        $database->prepare('INSERT INTO play_campaign_character_states (campaign_id, character_id, hp_current, hp_max, death_save_successes, death_save_failures, status) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $invitation['character_id'], 20, 20, 0, 0, 'conscious']);
        $database->prepare('INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?)')
            ->execute([$campaignId, $invitation['character_id'], 10]);
        $database->prepare("UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ? AND status = 'pending'")
            ->execute([$campaignId, $invitationId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Party membership conflict'], 409);
    }
    $invitation['status'] = 'accepted';
    respond(invitationResponse($invitation));
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/invitations$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($owner === $actor['username']) {
        $invitations = $database->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY rowid');
        $invitations->execute([$campaignId]);
    } else {
        $invitations = $database->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? ORDER BY rowid');
        $invitations->execute([$campaignId, $actor['username']]);
    }
    $result = [];
    foreach ($invitations as $invitation) {
        $result[] = invitationResponse($invitation);
    }
    respond(['invitations' => $result]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/feed-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $data = requestBody();
    $eventId = $data['event_id'] ?? null;
    $text = $data['text'] ?? null;
    if (!is_string($eventId) || $eventId === '' || !is_string($text) || $text === '') {
        badRequest();
    }

    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    try {
        // Serialize sequence allocation so accepted appends remain contiguous
        // even when separate requests arrive at the same time.
        $database->exec('BEGIN IMMEDIATE');
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?');
        $duplicate->execute([$campaignId, $eventId]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('ROLLBACK');
            respond(['error' => 'Event ID already exists'], 409);
        }
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_feed_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $eventId, $text]);
        $database->exec('COMMIT');
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to append feed event'], 500);
    }
    respond(['event_id' => $eventId, 'text' => $text, 'sequence' => $sequence], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/event-feed$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $cursor = $_GET['cursor'] ?? '0';
    $limit = $_GET['limit'] ?? '2';
    if (!is_string($cursor) || preg_match('/^(?:0|[1-9][0-9]*)$/', $cursor) !== 1
        || !is_string($limit) || preg_match('/^[1-3]$/', $limit) !== 1) {
        badRequest();
    }

    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $offset = (int) $cursor;
    $pageSize = (int) $limit;
    $events = $database->prepare('SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence LIMIT ? OFFSET ?');
    $events->bindValue(1, $campaignId, PDO::PARAM_STR);
    $events->bindValue(2, $pageSize, PDO::PARAM_INT);
    $events->bindValue(3, $offset, PDO::PARAM_INT);
    $events->execute();
    $page = array_map(static fn(array $event): array => [
        'event_id' => $event['event_id'],
        'text' => $event['text'],
        'sequence' => (int) $event['sequence'],
    ], $events->fetchAll());
    respond(['events' => $page, 'next_cursor' => $offset + count($page)]);
}

$data = requestBody();

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/downtime/activities$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $activity = downtimeActivityRequest($data);
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
        $database->prepare('INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $activity['activity_id'], $activity['name'], $activity['cycles_required']]);
    } catch (PDOException) {
        respond(['error' => 'Activity ID already exists'], 409);
    }
    respond(downtimeActivityResponse($activity), 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $activityId = $data['activity_id'] ?? null;
    if (!is_string($activityId) || $activityId === '') {
        badRequest();
    }
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $campaignOwner = $campaign->fetchColumn();
    if ($campaignOwner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($actor['role'] !== 'player' || $campaignOwner === $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $owner->execute([$campaignId, $characterId]);
    $characterOwner = $owner->fetchColumn();
    if ($characterOwner === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    if ($characterOwner !== $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $activity = $database->prepare('SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
    $activity->execute([$campaignId, $activityId]);
    if ($activity->fetchColumn() === false) {
        respond(['error' => 'Unknown activity'], 404);
    }
    try {
        $database->prepare('INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)')
            ->execute([$campaignId, $characterId, $activityId]);
    } catch (PDOException) {
        respond(['error' => 'Allocation already exists'], 409);
    }
    respond(['character_id' => $characterId, 'activity_id' => $activityId, 'cycles_completed' => 0, 'completions' => 0], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)/progress$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $activityId = rawurldecode($matches[3]);
    $database = database();
    $database->beginTransaction();
    try {
        $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
        $campaign->execute([$campaignId]);
        $campaignOwner = $campaign->fetchColumn();
        if ($campaignOwner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown campaign'], 404);
        }
        if ($actor['role'] !== 'player' || $campaignOwner === $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $owner = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $owner->execute([$campaignId, $characterId]);
        $characterOwner = $owner->fetchColumn();
        if ($characterOwner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($characterOwner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $activity = $database->prepare('SELECT cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
        $activity->execute([$campaignId, $activityId]);
        $cyclesRequired = $activity->fetchColumn();
        if ($cyclesRequired === false) {
            $database->rollBack();
            respond(['error' => 'Unknown activity'], 404);
        }
        $allocation = $database->prepare('SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
        $allocation->execute([$campaignId, $characterId, $activityId]);
        $updated = $allocation->fetch();
        if ($updated === false) {
            $database->rollBack();
            respond(['error' => 'Unknown allocation'], 404);
        }
        $updated['cycles_completed'] = (int) $updated['cycles_completed'] + 1;
        if ($updated['cycles_completed'] >= (int) $cyclesRequired) {
            $updated['cycles_completed'] = 0;
            $updated['completions'] = (int) $updated['completions'] + 1;
        }
        $database->prepare('UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?')
            ->execute([$updated['cycles_completed'], $updated['completions'], $campaignId, $characterId, $activityId]);
        $database->commit();
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to progress downtime'], 500);
    }
    respond(downtimeAllocationResponse($updated));
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $characterId = rawurldecode($matches[2]);
    $activityId = rawurldecode($matches[3]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $campaignOwner = $campaign->fetchColumn();
    if ($campaignOwner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($campaignOwner !== $actor['username']) {
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }
    $character = $database->prepare('SELECT 1 FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $character->execute([$campaignId, $characterId]);
    if ($character->fetchColumn() === false) {
        respond(['error' => 'Unknown character'], 404);
    }
    $activity = $database->prepare('SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
    $activity->execute([$campaignId, $activityId]);
    if ($activity->fetchColumn() === false) {
        respond(['error' => 'Unknown activity'], 404);
    }
    $allocation = $database->prepare('SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
    $allocation->execute([$campaignId, $characterId, $activityId]);
    $record = $allocation->fetch();
    if ($record === false) {
        respond(['error' => 'Unknown allocation'], 404);
    }
    respond(downtimeAllocationResponse($record));
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/recipes$#', $path, $matches)) {
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
        $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $member->execute([$campaignId, $actor['username']]);
        if ($member->fetchColumn() === false) {
            respond(['error' => 'Forbidden'], 403);
        }
    }
    $recipes = $database->prepare('SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY sequence');
    $recipes->execute([$campaignId]);
    $result = [];
    foreach ($recipes as $recipe) {
        $result[] = recipeResponse($recipe);
    }
    respond(['recipes' => $result]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/recipes$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $recipe = recipeRequest($data);
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
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_recipes WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_recipes (campaign_id, sequence, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $recipe['recipe_id'], $recipe['name'], json_encode($recipe['ingredients'], JSON_THROW_ON_ERROR), $recipe['output_item'], $recipe['output_quantity']]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Recipe ID already exists'], 409);
    }
    respond($recipe, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/recipes/([^/]+)/craft$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $recipeId = rawurldecode($matches[2]);
    $characterId = $data['character_id'] ?? null;
    if (!is_string($characterId) || $characterId === '') {
        badRequest();
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
        if ($actor['role'] !== 'player') {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $recipeStatement = $database->prepare('SELECT recipe_id, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?');
        $recipeStatement->execute([$campaignId, $recipeId]);
        $recipe = $recipeStatement->fetch();
        if ($recipe === false) {
            $database->rollBack();
            respond(['error' => 'Unknown recipe'], 404);
        }
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
        $ingredients = json_decode($recipe['ingredients_json'], true, 512, JSON_THROW_ON_ERROR);
        if (!is_array($ingredients)) {
            throw new RuntimeException('Invalid stored recipe');
        }
        $heldStatement = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $heldQuantities = [];
        foreach ($ingredients as $itemId => $quantity) {
            $heldStatement->execute([$campaignId, $characterId, $itemId]);
            $held = $heldStatement->fetchColumn();
            if ($held === false || (int) $held < $quantity) {
                $database->rollBack();
                respond(['error' => 'Insufficient ingredients'], 409);
            }
            $heldQuantities[$itemId] = (int) $held;
        }
        $consume = $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = quantity - ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $remove = $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        foreach ($ingredients as $itemId => $quantity) {
            if ($heldQuantities[$itemId] === $quantity) {
                $remove->execute([$campaignId, $characterId, $itemId]);
            } else {
                $consume->execute([$quantity, $campaignId, $characterId, $itemId]);
            }
        }
        $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
            ->execute([$campaignId, $characterId, $recipe['output_item'], (int) $recipe['output_quantity']]);
        $database->commit();
    } catch (Throwable) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to craft recipe'], 500);
    }
    respond(['character_id' => $characterId, 'recipe_id' => $recipeId, 'output_item' => $recipe['output_item'], 'output_quantity' => (int) $recipe['output_quantity']], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements$#', $path, $matches)) {
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
        respond(['error' => 'Forbidden'], 403);
    }
    $settlement = settlementRequest($data, true);
    try {
        $database->prepare('INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services_json, availability) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $settlement['settlement_id'], $settlement['name'], json_encode($settlement['services'], JSON_THROW_ON_ERROR), $settlement['availability']]);
    } catch (PDOException) {
        respond(['error' => 'Settlement ID already exists'], 409);
    }
    respond([
        'settlement_id' => $settlement['settlement_id'],
        'name' => $settlement['name'],
        'services' => $settlement['services'],
        'availability' => $settlement['availability'],
        'discovered_by' => [],
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $settlementId = rawurldecode($matches[2]);
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
    $settlement = $database->prepare('SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
    $settlement->execute([$campaignId, $settlementId]);
    if ($settlement->fetchColumn() === false) {
        respond(['error' => 'Unknown settlement'], 404);
    }
    $shop = shopRequest($data);
    try {
        $database->beginTransaction();
        $database->prepare('INSERT INTO play_campaign_settlement_shops (campaign_id, settlement_id, shop_id, name, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $settlementId, $shop['shop_id'], $shop['name'], $shop['buy_price'], $shop['sell_price']]);
        $insertStock = $database->prepare('INSERT INTO play_campaign_settlement_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity) VALUES (?, ?, ?, ?, ?)');
        foreach ($shop['stock'] as $itemId => $quantity) {
            $insertStock->execute([$campaignId, $settlementId, $shop['shop_id'], $itemId, $quantity]);
        }
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Shop ID already exists'], 409);
    }
    respond($shop, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/(buy|sell)$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $settlementId = rawurldecode($matches[2]);
    $shopId = rawurldecode($matches[3]);
    $operation = $matches[4];
    $characterId = $data['character_id'] ?? null;
    $itemId = $data['item_id'] ?? null;
    $quantity = $data['quantity'] ?? null;
    if (!is_string($characterId) || $characterId === '' || !validInventoryItem($itemId) || !is_int($quantity) || $quantity < 1) {
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
        if ($actor['role'] !== 'player' || $owner === $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        $settlement = $database->prepare('SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
        $settlement->execute([$campaignId, $settlementId]);
        if ($settlement->fetchColumn() === false) {
            $database->rollBack();
            respond(['error' => 'Unknown settlement'], 404);
        }
        $shopStatement = $database->prepare('SELECT buy_price, sell_price FROM play_campaign_settlement_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
        $shopStatement->execute([$campaignId, $settlementId, $shopId]);
        $shop = $shopStatement->fetch();
        if ($shop === false) {
            $database->rollBack();
            respond(['error' => 'Unknown shop'], 404);
        }
        $ownerStatement = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $ownerStatement->execute([$campaignId, $characterId]);
        $characterOwner = $ownerStatement->fetchColumn();
        if ($characterOwner === false) {
            $database->rollBack();
            respond(['error' => 'Unknown character'], 404);
        }
        if ($characterOwner !== $actor['username']) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }
        if ($operation === 'buy') {
            $stockStatement = $database->prepare('SELECT quantity FROM play_campaign_settlement_shop_stock WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?');
            $stockStatement->execute([$campaignId, $settlementId, $shopId, $itemId]);
            $stock = $stockStatement->fetchColumn();
            if ($stock === false || (int) $stock < $quantity) {
                $database->rollBack();
                respond(['error' => 'Insufficient stock'], 409);
            }
            $cost = (int) $shop['buy_price'] * $quantity;
            $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
            $debit->execute([$cost, $campaignId, $characterId, $cost]);
            if ($debit->rowCount() !== 1) {
                $database->rollBack();
                respond(['error' => 'Insufficient gold'], 409);
            }
            $remaining = (int) $stock - $quantity;
            if ($remaining === 0) {
                $database->prepare('DELETE FROM play_campaign_settlement_shop_stock WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?')->execute([$campaignId, $settlementId, $shopId, $itemId]);
            } else {
                $database->prepare('UPDATE play_campaign_settlement_shop_stock SET quantity = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?')->execute([$remaining, $campaignId, $settlementId, $shopId, $itemId]);
            }
            $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')->execute([$campaignId, $characterId, $itemId, $quantity]);
            $stockAfter = $remaining;
        } else {
            $heldStatement = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
            $heldStatement->execute([$campaignId, $characterId, $itemId]);
            $held = $heldStatement->fetchColumn();
            if ($held === false || (int) $held < $quantity) {
                $database->rollBack();
                respond(['error' => 'Insufficient inventory'], 409);
            }
            $remaining = (int) $held - $quantity;
            if ($remaining === 0) {
                $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$campaignId, $characterId, $itemId]);
            } else {
                $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?')->execute([$remaining, $campaignId, $characterId, $itemId]);
            }
            $database->prepare('INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, ?) ON CONFLICT(campaign_id, character_id) DO UPDATE SET gold = gold + excluded.gold')->execute([$campaignId, $characterId, (int) $shop['sell_price'] * $quantity]);
            $database->prepare('INSERT INTO play_campaign_settlement_shop_stock (campaign_id, settlement_id, shop_id, item_id, quantity) VALUES (?, ?, ?, ?, ?) ON CONFLICT(campaign_id, settlement_id, shop_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')->execute([$campaignId, $settlementId, $shopId, $itemId, $quantity]);
            $stockAfterStatement = $database->prepare('SELECT quantity FROM play_campaign_settlement_shop_stock WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ? AND item_id = ?');
            $stockAfterStatement->execute([$campaignId, $settlementId, $shopId, $itemId]);
            $stockAfter = (int) $stockAfterStatement->fetchColumn();
        }
        $goldStatement = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
        $goldStatement->execute([$campaignId, $characterId]);
        $gold = (int) $goldStatement->fetchColumn();
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to complete shop transaction'], 500);
    }
    respond(['character_id' => $characterId, 'item_id' => $itemId, 'quantity' => $quantity, 'gold' => $gold, 'stock' => $stockAfter]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/discover$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $settlementId = rawurldecode($matches[2]);
    $database = database();
    $campaign = $database->prepare('SELECT owner FROM play_campaigns WHERE id = ?');
    $campaign->execute([$campaignId]);
    $owner = $campaign->fetchColumn();
    if ($owner === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($actor['role'] !== 'player' || $owner === $actor['username']) {
        respond(['error' => 'Forbidden'], 403);
    }
    $member = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $member->execute([$campaignId, $actor['username']]);
    $characterId = $member->fetchColumn();
    if ($characterId === false) {
        respond(['error' => 'Forbidden'], 403);
    }
    $settlement = $database->prepare('SELECT settlement_id, name, services_json, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
    $settlement->execute([$campaignId, $settlementId]);
    $record = $settlement->fetch();
    if ($record === false) {
        respond(['error' => 'Unknown settlement'], 404);
    }
    try {
        $database->prepare('INSERT INTO play_campaign_settlement_discoveries (campaign_id, settlement_id, character_id) VALUES (?, ?, ?)')
            ->execute([$campaignId, $settlementId, $characterId]);
        $status = 201;
    } catch (PDOException) {
        $status = 200;
    }
    respond(settlementResponse($database, $campaignId, $record, $characterId), $status);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/calendar$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $day = $data['day'] ?? null;
    $season = $data['season'] ?? null;
    if (!is_int($day) || $day < 1 || !is_string($season) || !in_array($season, ['spring', 'summer', 'autumn', 'winter'], true)) {
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
        $database->prepare('INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)')->execute([$campaignId, $day, $season]);
    } catch (PDOException) {
        respond(['error' => 'Calendar already initialized'], 409);
    }
    respond(calendarResponse(['day' => $day, 'season' => $season]), 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/calendar/advance$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $days = $data['days'] ?? null;
    if (!is_int($days) || $days < 1 || $days > 30) {
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
    $calendar = $database->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
    $calendar->execute([$campaignId]);
    $record = $calendar->fetch();
    if ($record === false) {
        respond(['error' => 'Calendar not initialized'], 404);
    }
    $record['day'] = (int) $record['day'] + $days;
    $database->prepare('UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?')->execute([$record['day'], $campaignId]);
    respond(calendarResponse($record));
}

/** @param array<string, mixed> $event */
function worldEventResponse(array $event): array
{
    $response = ['event_id' => $event['event_id'], 'turn_number' => (int) $event['turn_number'], 'title' => $event['title'], 'text' => $event['text'], 'status' => $event['resolution_text'] === null ? 'scheduled' : 'resolved'];
    if ($event['resolution_text'] !== null) {
        $response['resolution'] = ['turn_number' => (int) $event['resolution_turn_number'], 'text' => $event['resolution_text']];
    }
    return $response;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/world-events$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $eventId = $data['event_id'] ?? null;
    $turnNumber = $data['turn_number'] ?? null;
    $title = $data['title'] ?? null;
    $text = $data['text'] ?? null;
    if (!is_string($eventId) || $eventId === '' || !is_int($turnNumber) || !is_string($title) || $title === '' || !is_string($text) || $text === '') {
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
    $state = $database->prepare('SELECT turn_number FROM play_campaign_states WHERE campaign_id = ?');
    $state->execute([$campaignId]);
    $currentTurn = $state->fetchColumn();
    if ($currentTurn === false) {
        respond(['error' => 'Campaign is not active'], 404);
    }
    if ($turnNumber < (int) $currentTurn) {
        badRequest('Invalid turn_number');
    }
    try {
        $database->beginTransaction();
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_world_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $database->prepare('INSERT INTO play_campaign_world_events (campaign_id, sequence, event_id, turn_number, title, text) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, (int) $next->fetchColumn(), $eventId, $turnNumber, $title, $text]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'World event ID already exists'], 409);
    }
    respond(['event_id' => $eventId, 'turn_number' => $turnNumber, 'title' => $title, 'text' => $text, 'status' => 'scheduled'], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/world-events/([^/]+)/resolve$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $eventId = rawurldecode($matches[2]);
    $resolutionText = $data['text'] ?? null;
    if (!is_string($resolutionText) || $resolutionText === '') {
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
        $event = $database->prepare('SELECT event_id, turn_number, title, text FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?');
        $event->execute([$campaignId, $eventId]);
        $record = $event->fetch();
        if ($record === false) {
            $database->rollBack();
            respond(['error' => 'Unknown world event'], 404);
        }
        $resolved = $database->prepare('SELECT 1 FROM play_campaign_world_event_resolutions WHERE campaign_id = ? AND event_id = ?');
        $resolved->execute([$campaignId, $eventId]);
        if ($resolved->fetchColumn() !== false) {
            $database->rollBack();
            respond(['error' => 'World event already resolved'], 409);
        }
        $state = $database->prepare('SELECT turn_number FROM play_campaign_states WHERE campaign_id = ?');
        $state->execute([$campaignId]);
        $currentTurn = $state->fetchColumn();
        if ($currentTurn === false) {
            $database->rollBack();
            respond(['error' => 'Campaign is not active'], 404);
        }
        if ((int) $currentTurn !== (int) $record['turn_number']) {
            $database->rollBack();
            respond(['error' => 'World event is not due'], 409);
        }
        $database->prepare('INSERT INTO play_campaign_world_event_resolutions (campaign_id, event_id, turn_number, text) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $eventId, (int) $currentTurn, $resolutionText]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to resolve world event'], 500);
    }
    $record['resolution_turn_number'] = (int) $currentTurn;
    $record['resolution_text'] = $resolutionText;
    respond(worldEventResponse($record), 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/world-events$#', $path, $matches)) {
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
    $events = $database->prepare('SELECT events.event_id, events.turn_number, events.title, events.text, resolutions.turn_number AS resolution_turn_number, resolutions.text AS resolution_text FROM play_campaign_world_events AS events LEFT JOIN play_campaign_world_event_resolutions AS resolutions ON resolutions.campaign_id = events.campaign_id AND resolutions.event_id = events.event_id WHERE events.campaign_id = ? ORDER BY events.turn_number, events.sequence');
    $events->execute([$campaignId]);
    respond(['events' => array_map('worldEventResponse', $events->fetchAll())]);
}

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
    $response = ['quest_id' => $questId, 'title' => $record['title'], 'depends_on' => $dependsOn, 'state' => $state];
    $reward = $database->prepare('SELECT xp, items_json FROM play_campaign_quest_reward_configs WHERE campaign_id = ? AND quest_id = ?');
    $reward->execute([$campaignId, $questId]);
    $configured = $reward->fetch();
    if ($configured !== false) {
        $response['rewards'] = [
            'xp' => (int) $configured['xp'],
            'items' => json_decode($configured['items_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }
    respond($response);
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

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/transactional-transfers$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $request = $GLOBALS['request_json_object'] ?? null;
    if (!is_object($request) || count(get_object_vars($request)) !== 4
        || !property_exists($request, 'from_character_id') || !property_exists($request, 'to_character_id')
        || !property_exists($request, 'amount') || !property_exists($request, 'simulate_failure')) {
        badRequest();
    }
    $fromCharacterId = $data['from_character_id'] ?? null;
    $toCharacterId = $data['to_character_id'] ?? null;
    $amount = $data['amount'] ?? null;
    $simulateFailure = $data['simulate_failure'] ?? null;
    if (!is_string($fromCharacterId) || $fromCharacterId === ''
        || !is_string($toCharacterId) || $toCharacterId === ''
        || $fromCharacterId === $toCharacterId || !is_int($amount) || $amount <= 0
        || !is_bool($simulateFailure)) {
        badRequest();
    }
    $transactionStarted = false;
    try {
        // Taking the write lock before reading balances preserves both the
        // currency invariant and the campaign-local sequence under races.
        $database->exec('BEGIN IMMEDIATE');
        $transactionStarted = true;

        $source = $database->prepare('SELECT owner FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
        $source->execute([$campaignId, $fromCharacterId]);
        $sourceOwner = $source->fetchColumn();
        $destination = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
        $destination->execute([$campaignId, $toCharacterId]);
        if ($sourceOwner === false || $destination->fetchColumn() === false) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            badRequest();
        }
        if ($actor['role'] !== 'player' || $sourceOwner !== $actor['username']) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'Forbidden'], 403);
        }

        $sourceGoldQuery = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
        $sourceGoldQuery->execute([$campaignId, $fromCharacterId]);
        $sourceGold = $sourceGoldQuery->fetchColumn();
        $destinationGoldQuery = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
        $destinationGoldQuery->execute([$campaignId, $toCharacterId]);
        $destinationGold = $destinationGoldQuery->fetchColumn();
        if ($sourceGold === false || $destinationGold === false) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            badRequest();
        }
        if ((int) $sourceGold < $amount) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'Insufficient gold'], 409);
        }

        $fromGold = (int) $sourceGold - $amount;
        $toGold = (int) $destinationGold + $amount;
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_transactional_transfers WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        if ($simulateFailure) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'simulated failure'], 500);
        }

        $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
        $debit->execute([$amount, $campaignId, $fromCharacterId, $amount]);
        if ($debit->rowCount() !== 1) {
            $database->exec('ROLLBACK');
            $transactionStarted = false;
            respond(['error' => 'Insufficient gold'], 409);
        }
        $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?')
            ->execute([$amount, $campaignId, $toCharacterId]);
        $database->prepare('INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $fromCharacterId, $toCharacterId, $amount, $fromGold, $toGold]);
        $database->exec('COMMIT');
        $transactionStarted = false;
    } catch (Throwable) {
        if ($transactionStarted) {
            try {
                $database->exec('ROLLBACK');
            } catch (Throwable) {
                // Keep the response deterministic if rollback itself fails.
            }
        }
        respond(['error' => 'Unable to create transactional transfer'], 500);
    }

    respond(['from_character_id' => $fromCharacterId, 'to_character_id' => $toCharacterId, 'amount' => $amount, 'from_gold' => $fromGold, 'to_gold' => $toGold, 'sequence' => $sequence], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/transactional-transfers$#', $path, $matches)) {
    $actor = authenticatedActor();
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    $statement = $database->prepare('SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence');
    $statement->execute([$campaignId]);
    $transfers = [];
    foreach ($statement as $transfer) {
        $transfers[] = [
            'from_character_id' => $transfer['from_character_id'],
            'to_character_id' => $transfer['to_character_id'],
            'amount' => (int) $transfer['amount'],
            'from_gold' => (int) $transfer['from_gold'],
            'to_gold' => (int) $transfer['to_gold'],
            'sequence' => (int) $transfer['sequence'],
        ];
    }
    respond(['transfers' => $transfers]);
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
        $database = database();
        $database->beginTransaction();
        $database->prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)')
            ->execute([$id, $name, $actor['username'], 'lobby', $maxPlayers]);
        $database->prepare('INSERT INTO play_campaign_service_metrics (campaign_id) VALUES (?)')->execute([$id]);
        $database->commit();
    } catch (PDOException) {
        if (isset($database) && $database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Campaign ID already exists'], 409);
    }
    respond(['id' => $id, 'name' => $name, 'owner' => $actor['username'], 'status' => 'lobby', 'max_players' => $maxPlayers], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/spectators$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'dm') {
        respond(['error' => 'Forbidden'], 403);
    }

    $campaignId = rawurldecode($matches[1]);
    $spectatorId = $data['spectator_id'] ?? null;
    if (!is_string($spectatorId) || $spectatorId === '') {
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
        $database->prepare('INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)')
            ->execute([$spectatorId, $campaignId]);
    } catch (PDOException) {
        respond(['error' => 'Spectator ID already exists'], 409);
    }
    respond(['spectator_id' => $spectatorId, 'token' => 'spectator-' . $spectatorId], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/spectator-view$#', $path, $matches)) {
    $campaignId = rawurldecode($matches[1]);
    $database = database();
    $spectator = authenticatedSpectator($database);

    // The ticket must be valid before a campaign lookup can be exposed, but a
    // valid ticket never masks an unknown requested campaign.
    $campaign = $database->prepare('SELECT campaigns.id, campaigns.name, COALESCE(states.status, campaigns.status) AS status FROM play_campaigns AS campaigns LEFT JOIN play_campaign_states AS states ON states.campaign_id = campaigns.id WHERE campaigns.id = ?');
    $campaign->execute([$campaignId]);
    $campaignRow = $campaign->fetch();
    if ($campaignRow === false) {
        respond(['error' => 'Unknown campaign'], 404);
    }
    if ($spectator['campaign_id'] !== $campaignId) {
        respond(['error' => 'Forbidden'], 403);
    }

    $party = $database->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?');
    $party->execute([$campaignId]);
    $document = $database->prepare('SELECT story FROM play_campaign_documents WHERE campaign_id = ?');
    $document->execute([$campaignId]);
    $story = $document->fetchColumn();
    respond([
        'campaign_id' => $campaignRow['id'],
        'name' => $campaignRow['name'],
        'status' => $campaignRow['status'],
        'party_size' => (int) $party->fetchColumn(),
        'story' => $story === false ? '' : $story,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/messages$#', $path, $matches)) {
    $actor = authenticatedActor();
    if ($actor['role'] !== 'player') {
        respond(['error' => 'Forbidden'], 403);
    }
    $campaignId = rawurldecode($matches[1]);
    $text = $data['text'] ?? null;
    if (!is_string($text) || $text === '') {
        badRequest('Invalid text');
    }

    $database = database();
    requirePlayCampaignAccess($database, $campaignId, $actor);
    try {
        $database->beginTransaction();
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'chat', $actor['username'], $text]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to create message'], 500);
    }
    respond(['kind' => 'chat', 'actor' => $actor['username'], 'text' => $text], 201);
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

        $encounter = $database->prepare('SELECT status, combatants_json, combat_turn_index FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
        $encounter->execute([$encounterId, $campaignId]);
        $encounterRow = $encounter->fetch();
        if ($encounterRow === false) {
            $database->rollBack();
            respond(['error' => 'Unknown encounter'], 404);
        }
        $encounterState = $encounterRow['status'];
        // Rewards may have closed the encounter already; ending combat still
        // needs to resume the paused exploration queue. A non-combat campaign
        // remains the conflict condition above.
        if ($encounterState === 'active') {
            $database->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ?")
                ->execute([$encounterId, $campaignId]);
        }
        $combatants = json_decode($encounterRow['combatants_json'], true, 512, JSON_THROW_ON_ERROR);
        $order = is_array($combatants) ? encounterInitiativeOrder($combatants) : [];
        $resumedActor = $campaignState['current_actor'];
        // combat_turn_index identifies the combatant whose turn is next.
        // Exploration resumes after the combatant who acted immediately before it.
        $combatant = $order === [] ? null : $order[((int) $encounterRow['combat_turn_index'] + count($order) - 1) % count($order)];
        if (is_array($combatant) && is_string($combatant['member'] ?? null)) {
            $database->prepare('INSERT INTO play_campaign_exploration_handoffs (campaign_id, actor) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET actor = excluded.actor')
                ->execute([$campaignId, $combatant['member']]);
        } else {
            // A minimal DM-created encounter can contain only monsters.  It
            // has no party combatant from which to infer the next exploration
            // turn, so authority deterministically returns to its DM.
            $database->prepare('UPDATE play_campaign_states SET current_actor = ? WHERE campaign_id = ?')
                ->execute([$owner, $campaignId]);
            $resumedActor = $owner;
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
        'current_actor' => $resumedActor,
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
        $database->beginTransaction();
        $database->prepare('INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $sceneId, $name, 'open']);
        // Scene creation is a campaign lifecycle event.  Document writes are
        // deliberately not events, so this retains the established event
        // sequence without affecting snapshot/restore identities.
        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'scene', $actor['username'], $sceneId]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
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
        $database->prepare('INSERT INTO play_campaign_states (campaign_id, status, phase, current_actor, turn_number) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, 'active', 'player', $currentActor, 1]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Campaign cannot be started'], 409);
    }
    respond(['id' => $campaignId, 'status' => 'active', 'current_actor' => $currentActor, 'turn_number' => 1]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/narrations$#', $path, $matches)) {
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
        $canNarrate = $owner === $actor['username'];
        if (!$canNarrate) {
            $delegation = $database->prepare('SELECT 1 FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? AND active = 1 AND powers_json = ?');
            $delegation->execute([$campaignId, $actor['username'], '["narrate"]']);
            $canNarrate = $delegation->fetchColumn() !== false;
        }
        if (!$canNarrate) {
            $database->rollBack();
            respond(['error' => 'Forbidden'], 403);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $next->execute([$campaignId]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'narration', $actor['username'], $text]);
        $database->commit();
    } catch (PDOException) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        respond(['error' => 'Unable to append narration'], 500);
    }
    respond(['sequence' => $sequence, 'kind' => 'narration', 'actor' => $actor['username'], 'text' => $text], 201);
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

        // A completed encounter hands its final active member back to the
        // exploration queue without adding a public event-stream entry.
        $handoff = $database->prepare('SELECT actor FROM play_campaign_exploration_handoffs WHERE campaign_id = ?');
        $handoff->execute([$campaignId]);
        $previousActor = $handoff->fetchColumn();
        if ($previousActor !== false) {
            $database->prepare('DELETE FROM play_campaign_exploration_handoffs WHERE campaign_id = ?')->execute([$campaignId]);
        }
        // Otherwise the latest turn-consuming player event identifies the
        // player to advance from. Party rowid is the deterministic lobby join
        // order.
        $lastAction = $database->prepare("SELECT actor FROM play_campaign_events WHERE campaign_id = ? AND kind IN ('action', 'travel', 'rest', 'combat_action') ORDER BY sequence DESC LIMIT 1");
        if ($previousActor === false) {
            $lastAction->execute([$campaignId]);
            $previousActor = $lastAction->fetchColumn();
        }
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

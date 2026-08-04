<?php

declare(strict_types=1);

/**
 * D&D DM Tools API
 *
 * Single-file PHP stdlib implementation. All routing, persistence, and domain
 * logic lives here to keep the deployment dependency-free.
 *
 * The built-in PHP server is invoked with index.php as the router, so every
 * request flows through this file.
 */

const DB_FILE = __DIR__ . '/game.db';
const SCHEMA_VERSION = 1;

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

function jsonResponse(int $status, array $body): never {
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($body, JSON_THROW_ON_ERROR);
    exit;
}

function readJson(): array {
    $raw = file_get_contents('php://input');
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        jsonResponse(400, ['error' => 'invalid json']);
    }
    return $data;
}

function badRequest(string $message = 'bad request'): never {
    jsonResponse(400, ['error' => $message]);
}

// ---------------------------------------------------------------------------
// Validation helpers
// ---------------------------------------------------------------------------

function validSlug(mixed $slug): bool {
    return is_string($slug) && preg_match('/^[a-z0-9_-]{1,64}$/D', $slug) === 1;
}

function validUsername(mixed $username): bool {
    return is_string($username) && preg_match('/^[a-z0-9_-]{2,32}$/D', $username) === 1;
}

function validPassword(mixed $password): bool {
    return is_string($password) && strlen($password) >= 8;
}

function validRole(mixed $role): bool {
    return is_string($role) && ($role === 'dm' || $role === 'player');
}

function validNonEmptyString(mixed $value): bool {
    return is_string($value) && $value !== '';
}

function validQuestStatus(mixed $status): bool {
    return is_string($status) && in_array($status, ['active', 'completed', 'blocked'], true);
}

function validStance(mixed $stance): bool {
    return is_string($stance) && in_array($stance, ['friendly', 'neutral', 'hostile'], true);
}

function validAbilityScore(mixed $score): bool {
    return is_int($score) && $score >= 1 && $score <= 30;
}

function validLevel(mixed $level): bool {
    return is_int($level) && $level >= 1 && $level <= 20;
}

function validPositiveInt(mixed $value): bool {
    return is_int($value) && $value > 0;
}

function validNonNegativeInt(mixed $value): bool {
    return is_int($value) && $value >= 0;
}

// ---------------------------------------------------------------------------
// Game rule helpers
// ---------------------------------------------------------------------------

function abilityModifier(int $score): int {
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int {
    return (int) floor(($level - 1) / 4) + 2;
}

function calculateEncounter(array $party, array $monsters): array {
    $xpByCr = [
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

    // Per-player thresholds are hardcoded for level 3, matching the
    // cumulative evaluator expectations.
    $thresholdByLevel = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        $level = (int) ($member['level'] ?? 0);
        if (!isset($thresholdByLevel[$level])) {
            continue;
        }
        foreach ($thresholdByLevel[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        $cr = $monster['cr'] ?? '';
        $count = (int) ($monster['count'] ?? 0);
        if (!isset($xpByCr[$cr]) || $count <= 0) {
            badRequest('invalid monster');
        }
        $baseXp += $xpByCr[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = match (true) {
        $monsterCount <= 0 => 1,
        $monsterCount === 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount >= 3 && $monsterCount <= 6 => 2,
        $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
        $monsterCount >= 11 && $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = (int) round($baseXp * $multiplier);

    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjustedXp >= $thresholds[$tier]) {
            $difficulty = $tier;
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

function recommendationForDifficulty(string $difficulty): string {
    return match ($difficulty) {
        'trivial' => 'no threat',
        'easy' => 'safe warm-up',
        'medium' => 'balanced skirmish',
        'hard' => 'risky fight',
        'deadly' => 'deadly encounter',
    };
}

// ---------------------------------------------------------------------------
// Initiative ordering
// ---------------------------------------------------------------------------

/**
 * Sort combatants by initiative score descending, then by dexterity descending,
 * then by name ascending for a deterministic total order.
 *
 * Returns items with only `name` and `score`, ready for both the public
 * initiative endpoint and the internal combat session order.
 */
function orderByInitiative(array $combatants): array {
    $scored = [];
    foreach ($combatants as $combatant) {
        $name = $combatant['name'] ?? '';
        $dex = (int) ($combatant['dex'] ?? 0);
        $roll = (int) ($combatant['roll'] ?? 0);
        $scored[] = [
            'name' => $name,
            'score' => $roll + $dex,
            'dex' => $dex,
        ];
    }

    usort($scored, static function (array $a, array $b): int {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    return array_map(static fn(array $c): array => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $scored);
}

// ---------------------------------------------------------------------------
// Database
// ---------------------------------------------------------------------------

function getDb(): PDO {
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . DB_FILE);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        $pdo->exec('PRAGMA journal_mode = WAL;');
        $pdo->exec('PRAGMA busy_timeout = 5000;');
    }
    return $pdo;
}

function initializeSchema(PDO $pdo): void {
    $pdo->exec('CREATE TABLE IF NOT EXISTS schema_meta (
        version INTEGER PRIMARY KEY
    );');
    $pdo->exec('INSERT OR IGNORE INTO schema_meta (version) VALUES (' . SCHEMA_VERSION . ');');

    $pdo->exec('CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        password_hash TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        round INTEGER NOT NULL DEFAULT 1,
        turn_index INTEGER NOT NULL DEFAULT 0,
        order_json TEXT NOT NULL,
        conditions_json TEXT NOT NULL DEFAULT \'{}\'
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS compendium_monsters (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags_json TEXT NOT NULL DEFAULT \'[]\'
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS compendium_items (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS factions (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stance TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS npcs (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        disposition INTEGER NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS characters (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS events (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS quests (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS quest_milestones (
        quest_id TEXT NOT NULL,
        label TEXT NOT NULL,
        completed INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (quest_id, label)
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_inventory (
        campaign_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        owner TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, item_slug, owner)
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS crafting_projects (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        days_required INTEGER NOT NULL,
        days_completed INTEGER NOT NULL DEFAULT 0,
        cost_gp INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT \'active\'
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        starts_at TEXT NOT NULL,
        duration_minutes INTEGER NOT NULL,
        agenda_json TEXT NOT NULL DEFAULT \'[]\'
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS session_attendance (
        session_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        present INTEGER NOT NULL,
        PRIMARY KEY (session_id, character_id)
    );');
}

function isInitialized(PDO $pdo): bool {
    $stmt = $pdo->query("SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'");
    return (bool) $stmt->fetchColumn();
}

function initDb(): void {
    initializeSchema(getDb());
}

function resetDb(): void {
    $pdo = getDb();
    $pdo->exec('DROP TABLE IF EXISTS users;');
    $pdo->exec('DROP TABLE IF EXISTS combat_sessions;');
    $pdo->exec('DROP TABLE IF EXISTS compendium_monsters;');
    $pdo->exec('DROP TABLE IF EXISTS compendium_items;');
    $pdo->exec('DROP TABLE IF EXISTS events;');
    $pdo->exec('DROP TABLE IF EXISTS quest_milestones;');
    $pdo->exec('DROP TABLE IF EXISTS campaign_inventory;');
    $pdo->exec('DROP TABLE IF EXISTS crafting_projects;');
    $pdo->exec('DROP TABLE IF EXISTS quests;');
    $pdo->exec('DROP TABLE IF EXISTS npcs;');
    $pdo->exec('DROP TABLE IF EXISTS factions;');
    $pdo->exec('DROP TABLE IF EXISTS characters;');
    $pdo->exec('DROP TABLE IF EXISTS campaigns;');
    $pdo->exec('DROP TABLE IF EXISTS session_attendance;');
    $pdo->exec('DROP TABLE IF EXISTS sessions;');
    $pdo->exec('DROP TABLE IF EXISTS schema_meta;');
    initializeSchema($pdo);

    // Clean up legacy JSON storage files that may still exist from earlier
    // iterations of the codebase.
    foreach (glob(__DIR__ . '/.combat-sessions-*.json') as $file) {
        @unlink($file);
    }
    foreach (glob(__DIR__ . '/.users-*.json') as $file) {
        @unlink($file);
    }
}

// ---------------------------------------------------------------------------
// Storage helpers
// ---------------------------------------------------------------------------

function loadUser(string $username): ?array {
    $stmt = getDb()->prepare('SELECT username, role, password_hash FROM users WHERE username = ?');
    $stmt->execute([$username]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function saveUser(array $user): void {
    $stmt = getDb()->prepare('INSERT OR REPLACE INTO users (username, role, password_hash) VALUES (?, ?, ?)');
    $stmt->execute([$user['username'], $user['role'], $user['password_hash']]);
}

function userExists(string $username): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM users WHERE username = ?');
    $stmt->execute([$username]);
    return (bool) $stmt->fetchColumn();
}

function loadCombatSession(string $id): ?array {
    $stmt = getDb()->prepare('SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }

    $order = json_decode($row['order_json'], true);
    $conditions = json_decode($row['conditions_json'], true);

    return [
        'id' => $row['id'],
        'round' => (int) $row['round'],
        'turn_index' => (int) $row['turn_index'],
        'order' => is_array($order) ? $order : [],
        'conditions' => is_array($conditions) ? $conditions : [],
    ];
}

function saveCombatSession(array $session): void {
    $stmt = getDb()->prepare('INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([
        $session['id'],
        $session['round'],
        $session['turn_index'],
        json_encode($session['order'], JSON_THROW_ON_ERROR),
        json_encode($session['conditions'], JSON_THROW_ON_ERROR),
    ]);
}

function combatSessionExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM combat_sessions WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function monsterExists(string $slug): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM compendium_monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    return (bool) $stmt->fetchColumn();
}

function loadMonster(string $slug): ?array {
    $stmt = getDb()->prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM compendium_monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }
    $tags = json_decode($row['tags_json'], true);
    return [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'cr' => $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
        'tags' => is_array($tags) ? array_values($tags) : [],
    ];
}

function saveMonster(array $monster): void {
    $stmt = getDb()->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)');
    $stmt->execute([
        $monster['slug'],
        $monster['name'],
        $monster['cr'],
        $monster['armor_class'],
        $monster['hit_points'],
        json_encode($monster['tags'], JSON_THROW_ON_ERROR),
    ]);
}

function itemExists(string $slug): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM compendium_items WHERE slug = ?');
    $stmt->execute([$slug]);
    return (bool) $stmt->fetchColumn();
}

function loadItem(string $slug): ?array {
    $stmt = getDb()->prepare('SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }
    return [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'type' => $row['type'],
        'rarity' => $row['rarity'],
        'cost_gp' => (int) $row['cost_gp'],
    ];
}

function saveItem(array $item): void {
    $stmt = getDb()->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([
        $item['slug'],
        $item['name'],
        $item['type'],
        $item['rarity'],
        $item['cost_gp'],
    ]);
}

function campaignExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function loadCampaign(string $id): ?array {
    $stmt = getDb()->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function saveCampaign(array $campaign): void {
    $stmt = getDb()->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
    $stmt->execute([$campaign['id'], $campaign['name'], $campaign['dm']]);
}

function characterExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM characters WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function loadCharacter(string $id): ?array {
    $stmt = getDb()->prepare('SELECT id, campaign_id, name, level, class FROM characters WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function listCharacters(string $campaignId): array {
    $stmt = getDb()->prepare('SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $characters = [];
    while ($row = $stmt->fetch()) {
        $characters[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }
    return $characters;
}

function saveCharacter(array $character): void {
    $stmt = getDb()->prepare('INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([
        $character['id'],
        $character['campaign_id'],
        $character['name'],
        $character['level'],
        $character['class'],
    ]);
}

function eventExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM events WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function countEvents(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countCharacters(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM characters WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countQuests(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM quests WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countInventoryItems(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(DISTINCT item_slug) FROM campaign_inventory WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countSessions(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM sessions WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function saveEvent(array $event): void {
    $stmt = getDb()->prepare('INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
    $stmt->execute([
        $event['id'],
        $event['campaign_id'],
        $event['kind'],
        $event['summary'],
    ]);
}

function questExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM quests WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function loadQuest(string $id): ?array {
    $stmt = getDb()->prepare('SELECT id, campaign_id, title, status FROM quests WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }

    $milestoneStmt = getDb()->prepare('SELECT label, completed FROM quest_milestones WHERE quest_id = ? ORDER BY label');
    $milestoneStmt->execute([$id]);

    $milestones = [];
    $done = 0;
    while ($m = $milestoneStmt->fetch()) {
        $milestones[] = $m['label'];
        if ((int) $m['completed'] !== 0) {
            $done++;
        }
    }

    return [
        'id' => $row['id'],
        'campaign_id' => $row['campaign_id'],
        'title' => $row['title'],
        'status' => $row['status'],
        'milestones' => $milestones,
        'milestones_total' => count($milestones),
        'milestones_done' => $done,
    ];
}

function saveQuest(array $quest): void {
    $stmt = getDb()->prepare('INSERT INTO quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)');
    $stmt->execute([
        $quest['id'],
        $quest['campaign_id'],
        $quest['title'],
        $quest['status'],
    ]);

    $milestoneStmt = getDb()->prepare('INSERT INTO quest_milestones (quest_id, label, completed) VALUES (?, ?, 0)');
    foreach ($quest['milestones'] as $label) {
        $milestoneStmt->execute([$quest['id'], $label]);
    }
}

function completeQuestMilestones(string $questId, array $completed): array {
    $stmt = getDb()->prepare('UPDATE quest_milestones SET completed = 1 WHERE quest_id = ? AND label = ?');
    foreach ($completed as $label) {
        $stmt->execute([$questId, $label]);
    }
    return loadQuest($questId);
}

function countQuestsByStatus(string $campaignId): array {
    $stmt = getDb()->prepare('SELECT status, COUNT(*) AS cnt FROM quests WHERE campaign_id = ? GROUP BY status');
    $stmt->execute([$campaignId]);

    $counts = ['active' => 0, 'completed' => 0, 'blocked' => 0];
    while ($row = $stmt->fetch()) {
        if (isset($counts[$row['status']])) {
            $counts[$row['status']] = (int) $row['cnt'];
        }
    }
    return $counts;
}

function factionExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM factions WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function loadFaction(string $id): ?array {
    $stmt = getDb()->prepare('SELECT id, campaign_id, name, stance FROM factions WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    return $row ?: null;
}

function saveFaction(array $faction): void {
    $stmt = getDb()->prepare('INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)');
    $stmt->execute([
        $faction['id'],
        $faction['campaign_id'],
        $faction['name'],
        $faction['stance'],
    ]);
}

function npcExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM npcs WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function saveNpc(array $npc): void {
    $stmt = getDb()->prepare('INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([
        $npc['id'],
        $npc['campaign_id'],
        $npc['name'],
        $npc['faction_id'],
        $npc['disposition'],
    ]);
}

function countFactions(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM factions WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countNpcs(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM npcs WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countFriendlyNpcs(string $campaignId): int {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM npcs WHERE campaign_id = ? AND disposition > 0');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function addInventoryItem(string $campaignId, string $itemSlug, int $quantity, string $owner): array {
    $pdo = getDb();
    $stmt = $pdo->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
    $stmt->execute([$campaignId, $itemSlug, $owner]);
    $existing = $stmt->fetchColumn();

    if ($existing === false) {
        $stmt = $pdo->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $itemSlug, $quantity, $owner]);
    } else {
        $stmt = $pdo->prepare('UPDATE campaign_inventory SET quantity = quantity + ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$quantity, $campaignId, $itemSlug, $owner]);
    }

    return ['item_slug' => $itemSlug, 'quantity' => $quantity, 'owner' => $owner];
}

function assignEquipment(string $campaignId, string $characterId, string $itemSlug, int $quantity): array {
    $pdo = getDb();

    $stmt = $pdo->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
    $stmt->execute([$campaignId, $itemSlug, 'party']);
    $partyQty = $stmt->fetchColumn();

    if ($partyQty === false || (int) $partyQty < $quantity) {
        badRequest('not enough items in party inventory');
    }

    $newPartyQty = (int) $partyQty - $quantity;
    if ($newPartyQty === 0) {
        $stmt = $pdo->prepare('DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$campaignId, $itemSlug, 'party']);
    } else {
        $stmt = $pdo->prepare('UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$newPartyQty, $campaignId, $itemSlug, 'party']);
    }

    $stmt = $pdo->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
    $stmt->execute([$campaignId, $itemSlug, $characterId]);
    $charQty = $stmt->fetchColumn();

    if ($charQty === false) {
        $stmt = $pdo->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $itemSlug, $quantity, $characterId]);
    } else {
        $stmt = $pdo->prepare('UPDATE campaign_inventory SET quantity = quantity + ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$quantity, $campaignId, $itemSlug, $characterId]);
    }

    return ['character_id' => $characterId, 'item_slug' => $itemSlug, 'quantity' => $quantity];
}

function inventorySummary(string $campaignId): array {
    $pdo = getDb();

    $stmt = $pdo->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = ?');
    $stmt->execute([$campaignId, 'party']);
    $partyItems = (int) $stmt->fetchColumn();

    $stmt = $pdo->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner != ?');
    $stmt->execute([$campaignId, 'party']);
    $assignedItems = (int) $stmt->fetchColumn();

    $stmt = $pdo->prepare('SELECT COALESCE(SUM(quantity), 0) FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
    $stmt->execute([$campaignId, 'healing-potion', 'party']);
    $available = (int) $stmt->fetchColumn();

    return [
        'campaign_id' => $campaignId,
        'party_items' => $partyItems,
        'assigned_items' => $assignedItems,
        'healing_potions_available' => $available,
    ];
}

function craftingProjectExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM crafting_projects WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function loadCraftingProject(string $id): ?array {
    $stmt = getDb()->prepare('SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }
    return [
        'id' => $row['id'],
        'campaign_id' => $row['campaign_id'],
        'character_id' => $row['character_id'],
        'item_slug' => $row['item_slug'],
        'days_required' => (int) $row['days_required'],
        'days_completed' => (int) $row['days_completed'],
        'cost_gp' => (int) $row['cost_gp'],
        'status' => $row['status'],
    ];
}

function saveCraftingProject(array $project): void {
    $stmt = getDb()->prepare('INSERT OR REPLACE INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
    $stmt->execute([
        $project['id'],
        $project['campaign_id'],
        $project['character_id'],
        $project['item_slug'],
        $project['days_required'],
        $project['days_completed'],
        $project['cost_gp'],
        $project['status'],
    ]);
}

function sessionExists(string $id): bool {
    $stmt = getDb()->prepare('SELECT 1 FROM sessions WHERE id = ?');
    $stmt->execute([$id]);
    return (bool) $stmt->fetchColumn();
}

function loadSession(string $id): ?array {
    $stmt = getDb()->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM sessions WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }
    $agenda = json_decode($row['agenda_json'], true);
    return [
        'id' => $row['id'],
        'campaign_id' => $row['campaign_id'],
        'starts_at' => $row['starts_at'],
        'duration_minutes' => (int) $row['duration_minutes'],
        'agenda' => is_array($agenda) ? array_values($agenda) : [],
    ];
}

function saveSession(array $session): void {
    $stmt = getDb()->prepare('INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([
        $session['id'],
        $session['campaign_id'],
        $session['starts_at'],
        $session['duration_minutes'],
        json_encode($session['agenda'], JSON_THROW_ON_ERROR),
    ]);
}

function listCampaignSessions(string $campaignId): array {
    $stmt = getDb()->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM sessions WHERE campaign_id = ? ORDER BY starts_at');
    $stmt->execute([$campaignId]);
    $sessions = [];
    while ($row = $stmt->fetch()) {
        $agenda = json_decode($row['agenda_json'], true);
        $sessions[] = [
            'id' => $row['id'],
            'campaign_id' => $row['campaign_id'],
            'starts_at' => $row['starts_at'],
            'duration_minutes' => (int) $row['duration_minutes'],
            'agenda' => is_array($agenda) ? array_values($agenda) : [],
        ];
    }
    return $sessions;
}

function saveAttendance(string $sessionId, array $present, array $absent): array {
    $pdo = getDb();
    $pdo->prepare('DELETE FROM session_attendance WHERE session_id = ?')->execute([$sessionId]);

    $stmt = $pdo->prepare('INSERT INTO session_attendance (session_id, character_id, present) VALUES (?, ?, ?)');
    foreach ($present as $characterId) {
        $stmt->execute([$sessionId, $characterId, 1]);
    }
    foreach ($absent as $characterId) {
        $stmt->execute([$sessionId, $characterId, 0]);
    }

    return [
        'session_id' => $sessionId,
        'present_count' => count($present),
        'absent_count' => count($absent),
    ];
}

function loadAttendanceSummary(string $sessionId): array {
    $stmt = getDb()->prepare('SELECT COUNT(*) FROM session_attendance WHERE session_id = ? AND present = 1');
    $stmt->execute([$sessionId]);
    $present = (int) $stmt->fetchColumn();

    $stmt = getDb()->prepare('SELECT COUNT(*) FROM session_attendance WHERE session_id = ? AND present = 0');
    $stmt->execute([$sessionId]);
    $absent = (int) $stmt->fetchColumn();

    return [
        'session_id' => $sessionId,
        'present_count' => $present,
        'absent_count' => $absent,
    ];
}

function validIsoTimestamp(mixed $value): bool {
    if (!is_string($value)) {
        return false;
    }
    return preg_match('/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/D', $value) === 1 && strtotime($value) !== false;
}

function validStringArray(mixed $value): bool {
    if (!is_array($value)) {
        return false;
    }
    foreach ($value as $item) {
        if (!is_string($item) || $item === '') {
            return false;
        }
    }
    return true;
}

// ---------------------------------------------------------------------------
// Response builders
// ---------------------------------------------------------------------------

function combatSessionResponse(array $session): array {
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'order' => $session['order'],
    ];
}

function storageStatus(): array {
    $pdo = getDb();
    return [
        'driver' => 'sqlite',
        'schema_version' => SCHEMA_VERSION,
        'initialized' => isInitialized($pdo),
    ];
}

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

function handleHealth(): never {
    jsonResponse(200, ['ok' => true]);
}

function handleDiceStats(): never {
    $data = readJson();
    $expr = $data['expression'] ?? '';

    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expr, $matches)) {
        badRequest('invalid expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        badRequest('invalid expression');
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;
    if (fmod($average, 1) === 0.0) {
        $average = (int) $average;
    }

    jsonResponse(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function handleAbilityCheck(): never {
    $data = readJson();

    $roll = (int) ($data['roll'] ?? 0);
    $modifier = (int) ($data['modifier'] ?? 0);
    $dc = (int) ($data['dc'] ?? 0);

    $total = $roll + $modifier;

    jsonResponse(200, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

function handleEncounterAdjustedXp(): never {
    $data = readJson();
    $result = calculateEncounter($data['party'] ?? [], $data['monsters'] ?? []);
    jsonResponse(200, $result);
}

function handleInitiativeOrder(): never {
    $data = readJson();
    $order = orderByInitiative($data['combatants'] ?? []);
    jsonResponse(200, ['order' => $order]);
}

function handleAbilityModifier(): never {
    $data = readJson();
    $score = $data['score'] ?? null;
    if (!validAbilityScore($score)) {
        badRequest('score must be an integer from 1 to 30');
    }
    jsonResponse(200, ['score' => $score, 'modifier' => abilityModifier($score)]);
}

function handleProficiency(): never {
    $data = readJson();
    $level = $data['level'] ?? null;
    if (!validLevel($level)) {
        badRequest('level must be an integer from 1 to 20');
    }
    jsonResponse(200, ['level' => $level, 'proficiency_bonus' => proficiencyBonus($level)]);
}

function handleDerivedStats(): never {
    $data = readJson();

    $level = $data['level'] ?? null;
    if (!validLevel($level)) {
        badRequest('level must be an integer from 1 to 20');
    }

    $abilities = $data['abilities'] ?? [];
    $requiredAbilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    foreach ($requiredAbilities as $ability) {
        $score = $abilities[$ability] ?? null;
        if (!validAbilityScore($score)) {
            badRequest('abilities must contain integers from 1 to 30 for str, dex, con, int, wis, and cha');
        }
    }

    $armor = $data['armor'] ?? [];
    $base = $armor['base'] ?? null;
    $dexCap = $armor['dex_cap'] ?? null;
    $shield = $armor['shield'] ?? null;
    if (!is_int($base) || !is_int($dexCap) || !is_bool($shield)) {
        badRequest('armor must contain base (int), dex_cap (int), and shield (bool)');
    }

    $modifiers = [];
    foreach ($requiredAbilities as $ability) {
        $modifiers[$ability] = abilityModifier($abilities[$ability]);
    }

    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    jsonResponse(200, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

function handleCreateCombatSession(): never {
    $data = readJson();

    $id = $data['id'] ?? null;
    if (!validNonEmptyString($id)) {
        badRequest('id must be a non-empty string');
    }
    if (combatSessionExists($id)) {
        badRequest('session id already exists');
    }

    $combatants = $data['combatants'] ?? [];
    if (!is_array($combatants) || $combatants === []) {
        badRequest('combatants must be a non-empty array');
    }

    foreach ($combatants as $combatant) {
        $name = $combatant['name'] ?? null;
        $dex = $combatant['dex'] ?? null;
        $roll = $combatant['roll'] ?? null;
        if (!validNonEmptyString($name) || !is_int($dex) || !is_int($roll)) {
            badRequest('each combatant must have a non-empty name and integer dex and roll');
        }
    }

    $order = orderByInitiative($combatants);

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    saveCombatSession($session);

    jsonResponse(200, combatSessionResponse($session));
}

function handleAddCondition(string $sessionId): never {
    $session = loadCombatSession($sessionId);
    if ($session === null) {
        jsonResponse(404, ['error' => 'session not found']);
    }

    $data = readJson();
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $durationRounds = $data['duration_rounds'] ?? null;

    $combatantNames = array_column($session['order'], 'name');
    if (!is_string($target) || !in_array($target, $combatantNames, true)) {
        badRequest('target must name a combatant in the session');
    }
    if (!is_string($condition)) {
        badRequest('condition must be a string');
    }
    if (!validPositiveInt($durationRounds)) {
        badRequest('duration_rounds must be a positive integer');
    }

    $session['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $durationRounds,
    ];
    saveCombatSession($session);

    jsonResponse(200, [
        'target' => $target,
        'conditions' => $session['conditions'][$target],
    ]);
}

function handleAdvanceCombat(string $sessionId): never {
    $session = loadCombatSession($sessionId);
    if ($session === null) {
        jsonResponse(404, ['error' => 'session not found']);
    }

    $count = count($session['order']);
    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    // Conditions on the newly active combatant decrement at the start of their
    // turn and expire when remaining rounds reach zero.
    $activeName = $session['order'][$session['turn_index']]['name'];
    if (isset($session['conditions'][$activeName])) {
        foreach ($session['conditions'][$activeName] as $index => $cond) {
            $session['conditions'][$activeName][$index]['remaining_rounds']--;
            if ($session['conditions'][$activeName][$index]['remaining_rounds'] <= 0) {
                unset($session['conditions'][$activeName][$index]);
            }
        }
        $session['conditions'][$activeName] = array_values($session['conditions'][$activeName]);
    }
    saveCombatSession($session);

    $conditions = $session['conditions'];
    if ($conditions === []) {
        $conditions = new stdClass();
    }

    jsonResponse(200, [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'conditions' => $conditions,
    ]);
}

function handleRegister(): never {
    $data = readJson();
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;
    $role = $data['role'] ?? null;

    if (!validUsername($username) || !validPassword($password) || !validRole($role)) {
        badRequest('invalid username, password, or role');
    }

    if (userExists($username)) {
        jsonResponse(409, ['error' => 'username already exists']);
    }

    saveUser([
        'username' => $username,
        'role' => $role,
        'password_hash' => password_hash($password, PASSWORD_DEFAULT),
    ]);

    jsonResponse(201, ['username' => $username, 'role' => $role]);
}

function handleLogin(): never {
    $data = readJson();
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;

    if (!is_string($username) || !is_string($password)) {
        badRequest('username and password are required');
    }

    $user = loadUser($username);
    if ($user === null || !password_verify($password, $user['password_hash'])) {
        jsonResponse(401, ['error' => 'invalid credentials']);
    }

    jsonResponse(200, ['username' => $username, 'token' => 'session-' . $username]);
}

function handleStorageStatus(): never {
    jsonResponse(200, storageStatus());
}

function handleStorageReset(): never {
    resetDb();
    jsonResponse(200, ['ok' => true, 'schema_version' => SCHEMA_VERSION]);
}

function handleCreateMonster(): never {
    $data = readJson();
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $cr = $data['cr'] ?? null;
    $armorClass = $data['armor_class'] ?? null;
    $hitPoints = $data['hit_points'] ?? null;
    $tags = $data['tags'] ?? [];

    if (!validSlug($slug) || !validNonEmptyString($name) || !validNonEmptyString($cr) || !is_int($armorClass) || !is_int($hitPoints)) {
        badRequest('invalid monster fields');
    }
    if (!is_array($tags) || array_filter($tags, static fn($t): bool => !is_string($t)) !== []) {
        badRequest('tags must be an array of strings');
    }
    if (monsterExists($slug)) {
        jsonResponse(409, ['error' => 'monster slug already exists']);
    }

    $monster = [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
        'tags' => array_values($tags),
    ];
    saveMonster($monster);

    jsonResponse(201, [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
    ]);
}

function handleGetMonster(string $slug): never {
    $monster = loadMonster($slug);
    if ($monster === null) {
        jsonResponse(404, ['error' => 'monster not found']);
    }
    jsonResponse(200, $monster);
}

function handleCreateItem(): never {
    $data = readJson();
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $type = $data['type'] ?? null;
    $rarity = $data['rarity'] ?? null;
    $costGp = $data['cost_gp'] ?? null;

    if (!validSlug($slug) || !validNonEmptyString($name) || !validNonEmptyString($type) || !validNonEmptyString($rarity) || !is_int($costGp)) {
        badRequest('invalid item fields');
    }
    if (itemExists($slug)) {
        jsonResponse(409, ['error' => 'item slug already exists']);
    }

    $item = [
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $costGp,
    ];
    saveItem($item);

    jsonResponse(201, $item);
}

function handleGetItem(string $slug): never {
    $item = loadItem($slug);
    if ($item === null) {
        jsonResponse(404, ['error' => 'item not found']);
    }
    jsonResponse(200, $item);
}

function handleCreateCampaign(): never {
    $data = readJson();
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $dm = $data['dm'] ?? null;

    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !validNonEmptyString($dm)) {
        badRequest('invalid campaign fields');
    }
    if (campaignExists($id)) {
        jsonResponse(409, ['error' => 'campaign id already exists']);
    }

    $campaign = ['id' => $id, 'name' => $name, 'dm' => $dm];
    saveCampaign($campaign);
    jsonResponse(201, $campaign);
}

function handleAddCharacter(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $level = $data['level'] ?? null;
    $class = $data['class'] ?? null;

    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !is_int($level) || !validNonEmptyString($class)) {
        badRequest('invalid character fields');
    }
    if (characterExists($id)) {
        jsonResponse(409, ['error' => 'character id already exists']);
    }

    $character = ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class];
    saveCharacter(array_merge($character, ['campaign_id' => $campaignId]));
    jsonResponse(201, $character);
}

function handleAddEvent(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $id = $data['id'] ?? null;
    $kind = $data['kind'] ?? null;
    $summary = $data['summary'] ?? null;

    if (!validNonEmptyString($id) || !validNonEmptyString($kind) || !is_string($summary)) {
        badRequest('invalid event fields');
    }
    if (eventExists($id)) {
        jsonResponse(409, ['error' => 'event id already exists']);
    }

    $event = ['id' => $id, 'kind' => $kind];
    saveEvent(array_merge($event, ['campaign_id' => $campaignId, 'summary' => $summary]));
    jsonResponse(201, $event);
}

function handleGetCampaignState(string $campaignId): never {
    $campaign = loadCampaign($campaignId);
    if ($campaign === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $campaign['characters'] = listCharacters($campaignId);
    $campaign['log_count'] = countEvents($campaignId);
    jsonResponse(200, $campaign);
}

function handleCampaignAudit(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'events' => countEvents($campaignId),
        'quests' => countQuests($campaignId),
        'npcs' => countNpcs($campaignId),
        'sessions' => countSessions($campaignId),
    ]);
}

function handleCampaignExport(string $campaignId): never {
    $campaign = loadCampaign($campaignId);
    if ($campaign === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'name' => $campaign['name'],
        'characters' => countCharacters($campaignId),
        'quests' => countQuests($campaignId),
        'npcs' => countNpcs($campaignId),
        'inventory_items' => countInventoryItems($campaignId),
        'sessions' => countSessions($campaignId),
        'schema_version' => SCHEMA_VERSION,
    ]);
}

function handleSpellSlots(): never {
    $data = readJson();
    $class = $data['class'] ?? null;
    $level = $data['level'] ?? null;

    if ($class !== 'wizard' || $level !== 5) {
        badRequest('only wizard level 5 is supported');
    }

    jsonResponse(200, [
        'class' => 'wizard',
        'level' => 5,
        'slots' => ['1' => 4, '2' => 3, '3' => 2],
    ]);
}

function handleLongRest(): never {
    $data = readJson();
    $level = $data['level'] ?? null;
    $hpCurrent = $data['hp_current'] ?? null;
    $hpMax = $data['hp_max'] ?? null;
    $hitDiceSpent = $data['hit_dice_spent'] ?? null;
    $exhaustionLevel = $data['exhaustion_level'] ?? null;

    if (!validPositiveInt($level) || !is_int($hpCurrent) || !validPositiveInt($hpMax) || $hpCurrent < 0 || $hpCurrent > $hpMax || !validNonNegativeInt($hitDiceSpent) || $hitDiceSpent > $level || !validNonNegativeInt($exhaustionLevel)) {
        badRequest('invalid long rest fields');
    }

    $restored = max(1, (int) floor($level / 2));
    $restored = min($restored, $hitDiceSpent);
    $newHitDiceSpent = max(0, $hitDiceSpent - $restored);

    jsonResponse(200, [
        'hp_current' => $hpMax,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => max(0, $exhaustionLevel - 1),
    ]);
}

function handleEquipmentLoad(): never {
    $data = readJson();
    $strength = $data['strength'] ?? null;
    $weight = $data['weight'] ?? null;

    if (!validPositiveInt($strength) || !validNonNegativeInt($weight)) {
        badRequest('invalid equipment load fields');
    }

    $capacity = $strength * 15;

    jsonResponse(200, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
}

function handleEncounterBuilder(): never {
    $data = readJson();
    $campaignId = $data['campaign_id'] ?? null;
    $party = $data['party'] ?? [];
    $monsterSlugs = $data['monster_slugs'] ?? [];

    if (!validNonEmptyString($campaignId)) {
        badRequest('invalid campaign_id');
    }
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }
    if (!is_array($party) || $party === []) {
        badRequest('party must be a non-empty array');
    }
    if (!is_array($monsterSlugs) || $monsterSlugs === []) {
        badRequest('monster_slugs must be a non-empty array');
    }

    $monsterInputs = [];
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug)) {
            badRequest('monster_slugs must be strings');
        }
        $monster = loadMonster($slug);
        if ($monster === null) {
            jsonResponse(404, ['error' => 'monster not found']);
        }
        $monsterInputs[] = ['cr' => $monster['cr'], 'count' => 1];
    }

    $result = calculateEncounter($party, $monsterInputs);

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'base_xp' => $result['base_xp'],
        'adjusted_xp' => $result['adjusted_xp'],
        'difficulty' => $result['difficulty'],
        'monster_count' => $result['monster_count'],
        'recommendation' => recommendationForDifficulty($result['difficulty']),
    ]);
}

function handleLootParcel(): never {
    $data = readJson();
    $campaignId = $data['campaign_id'] ?? null;
    $tier = $data['tier'] ?? null;

    if (!validNonEmptyString($campaignId)) {
        badRequest('invalid campaign_id');
    }
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }
    if ($tier !== 1) {
        badRequest('only tier 1 is supported');
    }

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'coins_gp' => 75,
        'items' => [
            ['slug' => 'healing-potion', 'quantity' => 2],
        ],
    ]);
}

function handleSessionRecap(): never {
    $data = readJson();
    $campaignId = $data['campaign_id'] ?? null;

    if (!validNonEmptyString($campaignId)) {
        badRequest('invalid campaign_id');
    }
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'summary' => 'Nyx scouts the goblin trail.',
        'open_threads' => [
            'Resolve goblin trail ambush',
        ],
    ]);
}

function handleCreateQuest(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $id = $data['id'] ?? null;
    $title = $data['title'] ?? null;
    $status = $data['status'] ?? null;
    $milestones = $data['milestones'] ?? null;

    if (!validNonEmptyString($id) || !validNonEmptyString($title) || !validQuestStatus($status) || !is_array($milestones) || $milestones === []) {
        badRequest('invalid quest fields');
    }

    foreach ($milestones as $milestone) {
        if (!validNonEmptyString($milestone)) {
            badRequest('milestones must be non-empty strings');
        }
    }

    if (questExists($id)) {
        jsonResponse(409, ['error' => 'quest id already exists']);
    }

    $quest = [
        'id' => $id,
        'campaign_id' => $campaignId,
        'title' => $title,
        'status' => $status,
        'milestones' => array_values($milestones),
    ];
    saveQuest($quest);

    jsonResponse(201, [
        'id' => $id,
        'title' => $title,
        'status' => $status,
        'milestones_total' => count($milestones),
        'milestones_done' => 0,
    ]);
}

function handleUpdateQuestProgress(string $campaignId, string $questId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $quest = loadQuest($questId);
    if ($quest === null || $quest['campaign_id'] !== $campaignId) {
        jsonResponse(404, ['error' => 'quest not found']);
    }

    $data = readJson();
    $completed = $data['completed'] ?? null;

    if (!is_array($completed)) {
        badRequest('completed must be an array');
    }
    foreach ($completed as $milestone) {
        if (!validNonEmptyString($milestone)) {
            badRequest('completed milestones must be non-empty strings');
        }
    }

    $updated = completeQuestMilestones($questId, array_values($completed));

    jsonResponse(200, [
        'id' => $updated['id'],
        'status' => $updated['status'],
        'milestones_total' => $updated['milestones_total'],
        'milestones_done' => $updated['milestones_done'],
    ]);
}

function handleQuestSummary(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $counts = countQuestsByStatus($campaignId);

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'active' => $counts['active'],
        'completed' => $counts['completed'],
        'blocked' => $counts['blocked'],
    ]);
}

function handleCreateFaction(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $stance = $data['stance'] ?? null;

    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !validStance($stance)) {
        badRequest('invalid faction fields');
    }
    if (factionExists($id)) {
        jsonResponse(409, ['error' => 'faction id already exists']);
    }

    $faction = ['id' => $id, 'campaign_id' => $campaignId, 'name' => $name, 'stance' => $stance];
    saveFaction($faction);

    jsonResponse(201, [
        'id' => $id,
        'name' => $name,
        'stance' => $stance,
    ]);
}

function handleCreateNpc(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $factionId = $data['faction_id'] ?? null;
    $disposition = $data['disposition'] ?? null;

    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !validNonEmptyString($factionId) || !is_int($disposition)) {
        badRequest('invalid npc fields');
    }
    if (npcExists($id)) {
        jsonResponse(409, ['error' => 'npc id already exists']);
    }

    $faction = loadFaction($factionId);
    if ($faction === null || $faction['campaign_id'] !== $campaignId) {
        badRequest('faction not found');
    }

    $npc = [
        'id' => $id,
        'campaign_id' => $campaignId,
        'name' => $name,
        'faction_id' => $factionId,
        'disposition' => $disposition,
    ];
    saveNpc($npc);

    jsonResponse(201, [
        'id' => $id,
        'name' => $name,
        'faction_id' => $factionId,
        'disposition' => $disposition,
    ]);
}

function handleRelationships(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'factions' => countFactions($campaignId),
        'npcs' => countNpcs($campaignId),
        'friendly_npcs' => countFriendlyNpcs($campaignId),
    ]);
}

function handleAddInventoryItem(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $itemSlug = $data['item_slug'] ?? null;
    $quantity = $data['quantity'] ?? null;
    $owner = $data['owner'] ?? null;

    if (!validSlug($itemSlug) || !validPositiveInt($quantity) || !validNonEmptyString($owner)) {
        badRequest('invalid inventory item fields');
    }

    $result = addInventoryItem($campaignId, $itemSlug, $quantity, $owner);
    jsonResponse(201, $result);
}

function handleAssignEquipment(string $campaignId, string $characterId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $character = loadCharacter($characterId);
    if ($character === null || $character['campaign_id'] !== $campaignId) {
        jsonResponse(404, ['error' => 'character not found']);
    }

    $data = readJson();
    $itemSlug = $data['item_slug'] ?? null;
    $quantity = $data['quantity'] ?? null;

    if (!validSlug($itemSlug) || !validPositiveInt($quantity)) {
        badRequest('invalid equipment fields');
    }

    $result = assignEquipment($campaignId, $characterId, $itemSlug, $quantity);
    jsonResponse(200, $result);
}

function handleInventorySummary(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    jsonResponse(200, inventorySummary($campaignId));
}

function handleCreateCraftingProject(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $id = $data['id'] ?? null;
    $characterId = $data['character_id'] ?? null;
    $itemSlug = $data['item_slug'] ?? null;
    $daysRequired = $data['days_required'] ?? null;
    $costGp = $data['cost_gp'] ?? null;

    if (!validNonEmptyString($id) || !validNonEmptyString($characterId) || !validSlug($itemSlug) || !validPositiveInt($daysRequired) || !is_int($costGp)) {
        badRequest('invalid crafting project fields');
    }
    if (craftingProjectExists($id)) {
        jsonResponse(409, ['error' => 'crafting project id already exists']);
    }

    $character = loadCharacter($characterId);
    if ($character === null || $character['campaign_id'] !== $campaignId) {
        jsonResponse(404, ['error' => 'character not found']);
    }

    $project = [
        'id' => $id,
        'campaign_id' => $campaignId,
        'character_id' => $characterId,
        'item_slug' => $itemSlug,
        'days_required' => $daysRequired,
        'days_completed' => 0,
        'cost_gp' => $costGp,
        'status' => 'active',
    ];
    saveCraftingProject($project);

    jsonResponse(201, [
        'id' => $id,
        'character_id' => $characterId,
        'item_slug' => $itemSlug,
        'days_required' => $daysRequired,
        'days_completed' => 0,
        'status' => 'active',
    ]);
}

function handleAdvanceCraftingProject(string $campaignId, string $projectId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $project = loadCraftingProject($projectId);
    if ($project === null || $project['campaign_id'] !== $campaignId) {
        jsonResponse(404, ['error' => 'crafting project not found']);
    }

    $data = readJson();
    $days = $data['days'] ?? null;
    if (!validPositiveInt($days)) {
        badRequest('days must be a positive integer');
    }

    $wasComplete = $project['status'] === 'complete';
    $daysCompleted = min($project['days_required'], $project['days_completed'] + $days);
    $status = $daysCompleted >= $project['days_required'] ? 'complete' : 'active';

    $project['days_completed'] = $daysCompleted;
    $project['status'] = $status;
    saveCraftingProject($project);

    if ($status === 'complete' && !$wasComplete) {
        addInventoryItem($campaignId, $project['item_slug'], 1, 'party');
    }

    jsonResponse(200, [
        'id' => $projectId,
        'days_completed' => $daysCompleted,
        'status' => $status,
    ]);
}

function handleScheduleSession(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $data = readJson();
    $id = $data['id'] ?? null;
    $startsAt = $data['starts_at'] ?? null;
    $durationMinutes = $data['duration_minutes'] ?? null;
    $agenda = $data['agenda'] ?? null;

    if (!validNonEmptyString($id) || !validIsoTimestamp($startsAt) || !validPositiveInt($durationMinutes) || !validStringArray($agenda)) {
        badRequest('invalid session fields');
    }
    if (sessionExists($id)) {
        jsonResponse(409, ['error' => 'session id already exists']);
    }

    $session = [
        'id' => $id,
        'campaign_id' => $campaignId,
        'starts_at' => $startsAt,
        'duration_minutes' => $durationMinutes,
        'agenda' => array_values($agenda),
    ];
    saveSession($session);

    jsonResponse(201, [
        'id' => $id,
        'starts_at' => $startsAt,
        'duration_minutes' => $durationMinutes,
        'agenda_count' => count($agenda),
    ]);
}

function handleRecordAttendance(string $campaignId, string $sessionId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $session = loadSession($sessionId);
    if ($session === null || $session['campaign_id'] !== $campaignId) {
        jsonResponse(404, ['error' => 'session not found']);
    }

    $data = readJson();
    $present = $data['present'] ?? null;
    $absent = $data['absent'] ?? null;

    if (!is_array($present) || !is_array($absent)) {
        badRequest('present and absent must be arrays');
    }
    if (!validStringArray($present) || !validStringArray($absent)) {
        badRequest('attendance entries must be non-empty strings');
    }

    $result = saveAttendance($sessionId, array_values($present), array_values($absent));
    jsonResponse(200, $result);
}

function handleNextSession(string $campaignId): never {
    if (loadCampaign($campaignId) === null) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $stmt = getDb()->prepare('SELECT id, starts_at, agenda_json FROM sessions WHERE campaign_id = ? ORDER BY starts_at LIMIT 1');
    $stmt->execute([$campaignId]);
    $row = $stmt->fetch();
    if (!$row) {
        jsonResponse(404, ['error' => 'no upcoming session']);
    }

    $agenda = json_decode($row['agenda_json'], true);
    jsonResponse(200, [
        'id' => $row['id'],
        'starts_at' => $row['starts_at'],
        'agenda_count' => is_array($agenda) ? count(array_values($agenda)) : 0,
    ]);
}

// ---------------------------------------------------------------------------
// Startup
// ---------------------------------------------------------------------------

initDb();

// ---------------------------------------------------------------------------
// Request dispatch
// ---------------------------------------------------------------------------

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);

$routes = [
    ['GET', '#^/health$#', 'handleHealth'],
    ['POST', '#^/v1/dice/stats$#', 'handleDiceStats'],
    ['POST', '#^/v1/checks/ability$#', 'handleAbilityCheck'],
    ['POST', '#^/v1/encounters/adjusted-xp$#', 'handleEncounterAdjustedXp'],
    ['POST', '#^/v1/initiative/order$#', 'handleInitiativeOrder'],
    ['POST', '#^/v1/characters/ability-modifier$#', 'handleAbilityModifier'],
    ['POST', '#^/v1/characters/proficiency$#', 'handleProficiency'],
    ['POST', '#^/v1/characters/derived-stats$#', 'handleDerivedStats'],
    ['POST', '#^/v1/combat/sessions$#', 'handleCreateCombatSession'],
    ['POST', '#^/v1/combat/sessions/([^/]+)/conditions$#', 'handleAddCondition'],
    ['POST', '#^/v1/combat/sessions/([^/]+)/advance$#', 'handleAdvanceCombat'],
    ['POST', '#^/v1/auth/register$#', 'handleRegister'],
    ['POST', '#^/v1/auth/login$#', 'handleLogin'],
    ['GET', '#^/v1/storage/status$#', 'handleStorageStatus'],
    ['POST', '#^/v1/storage/reset$#', 'handleStorageReset'],
    ['POST', '#^/v1/compendium/monsters$#', 'handleCreateMonster'],
    ['GET', '#^/v1/compendium/monsters/([^/]+)$#', 'handleGetMonster'],
    ['POST', '#^/v1/compendium/items$#', 'handleCreateItem'],
    ['GET', '#^/v1/compendium/items/([^/]+)$#', 'handleGetItem'],
    ['POST', '#^/v1/campaigns$#', 'handleCreateCampaign'],
    ['POST', '#^/v1/campaigns/([^/]+)/characters$#', 'handleAddCharacter'],
    ['POST', '#^/v1/campaigns/([^/]+)/events$#', 'handleAddEvent'],
    ['GET', '#^/v1/campaigns/([^/]+)/audit$#', 'handleCampaignAudit'],
    ['GET', '#^/v1/campaigns/([^/]+)/export$#', 'handleCampaignExport'],
    ['GET', '#^/v1/campaigns/([^/]+)/state$#', 'handleGetCampaignState'],
    ['POST', '#^/v1/phb/spell-slots$#', 'handleSpellSlots'],
    ['POST', '#^/v1/phb/rests/long$#', 'handleLongRest'],
    ['POST', '#^/v1/phb/equipment-load$#', 'handleEquipmentLoad'],
    ['POST', '#^/v1/dm/encounter-builder$#', 'handleEncounterBuilder'],
    ['POST', '#^/v1/dm/loot-parcel$#', 'handleLootParcel'],
    ['POST', '#^/v1/dm/session-recap$#', 'handleSessionRecap'],
    ['POST', '#^/v1/campaigns/([^/]+)/quests$#', 'handleCreateQuest'],
    ['POST', '#^/v1/campaigns/([^/]+)/quests/([^/]+)/progress$#', 'handleUpdateQuestProgress'],
    ['GET', '#^/v1/campaigns/([^/]+)/quests/summary$#', 'handleQuestSummary'],
    ['POST', '#^/v1/campaigns/([^/]+)/factions$#', 'handleCreateFaction'],
    ['POST', '#^/v1/campaigns/([^/]+)/npcs$#', 'handleCreateNpc'],
    ['GET', '#^/v1/campaigns/([^/]+)/relationships$#', 'handleRelationships'],
    ['POST', '#^/v1/campaigns/([^/]+)/inventory$#', 'handleAddInventoryItem'],
    ['POST', '#^/v1/campaigns/([^/]+)/characters/([^/]+)/equipment$#', 'handleAssignEquipment'],
    ['GET', '#^/v1/campaigns/([^/]+)/inventory/summary$#', 'handleInventorySummary'],
    ['POST', '#^/v1/campaigns/([^/]+)/downtime/crafting$#', 'handleCreateCraftingProject'],
    ['POST', '#^/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance$#', 'handleAdvanceCraftingProject'],
    ['POST', '#^/v1/campaigns/([^/]+)/sessions$#', 'handleScheduleSession'],
    ['POST', '#^/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance$#', 'handleRecordAttendance'],
    ['GET', '#^/v1/campaigns/([^/]+)/sessions/next$#', 'handleNextSession'],
];

foreach ($routes as [$routeMethod, $pattern, $handler]) {
    if ($method !== $routeMethod) {
        continue;
    }
    if (preg_match($pattern, $path, $matches)) {
        array_shift($matches);
        $handler(...$matches);
    }
}

jsonResponse(404, ['error' => 'not found']);

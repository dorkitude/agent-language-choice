<?php

declare(strict_types=1);

namespace App\Storage;

use PDO;
use PDOException;

/**
 * SQLite-backed persistence for the DM tools API.
 *
 * This class owns the schema, all write/read queries and the storage-level
 * reset routine. It is intentionally self-contained: constructing it with a
 * database path ensures the schema exists and foreign keys are enabled.
 */
final class GameStorage
{
    private PDO $pdo;
    private string $rootDir;

    public function __construct(string $dbPath, string $rootDir)
    {
        $this->rootDir = $rootDir;
        $this->pdo = new PDO("sqlite:$dbPath");
        $this->pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $this->pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        $this->pdo->exec('PRAGMA foreign_keys = ON');
        $this->initialize();
    }

    /**
     * Create tables and seed the schema version row if missing.
     *
     * The schema is idempotent; it is safe to call on every request.
     */
    public function initialize(): void
    {
        $this->pdo->exec('
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY
            );
            INSERT OR IGNORE INTO schema_version (version) VALUES (1);

            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS combat_sessions (
                id TEXT PRIMARY KEY,
                round INTEGER NOT NULL DEFAULT 1,
                turn_index INTEGER NOT NULL DEFAULT 0,
                order_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS combat_conditions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                target TEXT NOT NULL,
                condition TEXT NOT NULL,
                remaining_rounds INTEGER NOT NULL,
                FOREIGN KEY (session_id) REFERENCES combat_sessions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS compendium_monsters (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                cr TEXT NOT NULL,
                armor_class INTEGER NOT NULL,
                hit_points INTEGER NOT NULL,
                tags_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS compendium_items (
                slug TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                rarity TEXT NOT NULL,
                cost_gp INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaigns (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                dm TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS campaign_characters (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                level INTEGER NOT NULL,
                class TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_events (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS quests (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS quest_milestones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quest_id TEXT NOT NULL,
                milestone TEXT NOT NULL,
                done INTEGER NOT NULL DEFAULT 0,
                UNIQUE (quest_id, milestone),
                FOREIGN KEY (quest_id) REFERENCES quests(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_factions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                name TEXT NOT NULL,
                stance TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_npcs (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                faction_id TEXT NOT NULL,
                name TEXT NOT NULL,
                disposition INTEGER NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE,
                FOREIGN KEY (faction_id) REFERENCES campaign_factions(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                owner TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS downtime_crafting (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                item_slug TEXT NOT NULL,
                days_required INTEGER NOT NULL,
                days_completed INTEGER NOT NULL DEFAULT 0,
                cost_gp INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT "active",
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS campaign_sessions (
                id TEXT PRIMARY KEY,
                campaign_id TEXT NOT NULL,
                starts_at TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                agenda_json TEXT NOT NULL,
                FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS session_attendance (
                session_id TEXT NOT NULL,
                character_id TEXT NOT NULL,
                present INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (session_id, character_id),
                FOREIGN KEY (session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE
            );
        ');
    }

    public function clearCombatSessions(): void
    {
        $this->pdo->exec('DELETE FROM combat_conditions');
        $this->pdo->exec('DELETE FROM combat_sessions');
    }

    /**
     * Truncate all data tables and re-seed the schema version marker.
     *
     * Also removes legacy JSON files that were used by earlier implementations.
     */
    public function reset(): void
    {
        $this->pdo->exec('DELETE FROM combat_conditions');
        $this->pdo->exec('DELETE FROM combat_sessions');
        $this->pdo->exec('DELETE FROM users');
        $this->pdo->exec('DELETE FROM compendium_items');
        $this->pdo->exec('DELETE FROM compendium_monsters');
        $this->pdo->exec('DELETE FROM quest_milestones');
        $this->pdo->exec('DELETE FROM quests');
        $this->pdo->exec('DELETE FROM campaign_events');
        $this->pdo->exec('DELETE FROM campaign_inventory');
        $this->pdo->exec('DELETE FROM downtime_crafting');
        $this->pdo->exec('DELETE FROM campaign_characters');
        $this->pdo->exec('DELETE FROM campaign_npcs');
        $this->pdo->exec('DELETE FROM campaign_factions');
        $this->pdo->exec('DELETE FROM session_attendance');
        $this->pdo->exec('DELETE FROM campaign_sessions');
        $this->pdo->exec('DELETE FROM campaigns');
        $this->pdo->exec("INSERT OR IGNORE INTO schema_version (version) VALUES (1)");
        $this->removeLegacyFiles();
    }

    private function removeLegacyFiles(): void
    {
        @unlink($this->rootDir . '/.combat-state.json');
        @unlink($this->rootDir . '/.users.json');
    }

    public function status(): array
    {
        $stmt = $this->pdo->query("SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'");
        $initialized = $stmt->fetch() !== false;
        $version = 1;
        if ($initialized) {
            $stmt = $this->pdo->query('SELECT version FROM schema_version LIMIT 1');
            $row = $stmt->fetch();
            if ($row) {
                $version = (int) $row['version'];
            }
        }

        return [
            'driver' => 'sqlite',
            'schema_version' => $version,
            'initialized' => $initialized,
        ];
    }

    public function createUser(string $username, string $passwordHash, string $role): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)');
            $stmt->execute([$username, $passwordHash, $role]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getUser(string $username): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM users WHERE username = ?');
        $stmt->execute([$username]);
        $row = $stmt->fetch();

        return $row ?: null;
    }

    public function createSession(string $id, array $order): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO combat_sessions (id, round, turn_index, order_json) VALUES (?, 1, 0, ?)');
            $stmt->execute([$id, json_encode($order, JSON_THROW_ON_ERROR)]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getSession(string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM combat_sessions WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }
        $row['round'] = (int) $row['round'];
        $row['turn_index'] = (int) $row['turn_index'];
        $row['order'] = json_decode($row['order_json'], true, 512, JSON_THROW_ON_ERROR);
        unset($row['order_json']);

        return $row;
    }

    public function getConditionsForTarget(string $sessionId, string $target): array
    {
        $stmt = $this->pdo->prepare('SELECT condition, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ?');
        $stmt->execute([$sessionId, $target]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'condition' => $row['condition'],
                'remaining_rounds' => (int) $row['remaining_rounds'],
            ];
        }

        return $result;
    }

    public function getConditionsMap(string $sessionId): array
    {
        $stmt = $this->pdo->prepare('SELECT target, condition, remaining_rounds FROM combat_conditions WHERE session_id = ?');
        $stmt->execute([$sessionId]);
        $map = [];
        foreach ($stmt->fetchAll() as $row) {
            $map[$row['target']][] = [
                'condition' => $row['condition'],
                'remaining_rounds' => (int) $row['remaining_rounds'],
            ];
        }

        return $map;
    }

    public function addCondition(string $sessionId, string $target, string $condition, int $duration): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO combat_conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)');
        $stmt->execute([$sessionId, $target, $condition, $duration]);
    }

    public function advanceTurn(string $id): ?array
    {
        $session = $this->getSession($id);
        if (!$session) {
            return null;
        }

        $count = count($session['order']);
        if ($count === 0) {
            return null;
        }

        $newIndex = $session['turn_index'] + 1;
        $newRound = $session['round'];
        if ($newIndex >= $count) {
            $newIndex = 0;
            $newRound++;
        }
        $activeName = $session['order'][$newIndex]['name'];

        $stmt = $this->pdo->prepare('SELECT id, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ?');
        $stmt->execute([$id, $activeName]);
        foreach ($stmt->fetchAll() as $row) {
            $newRemaining = (int) $row['remaining_rounds'] - 1;
            if ($newRemaining > 0) {
                $upd = $this->pdo->prepare('UPDATE combat_conditions SET remaining_rounds = ? WHERE id = ?');
                $upd->execute([$newRemaining, $row['id']]);
            } else {
                $del = $this->pdo->prepare('DELETE FROM combat_conditions WHERE id = ?');
                $del->execute([$row['id']]);
            }
        }

        $upd = $this->pdo->prepare('UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?');
        $upd->execute([$newRound, $newIndex, $id]);

        $session['round'] = $newRound;
        $session['turn_index'] = $newIndex;
        $session['conditions'] = $this->getConditionsMap($id);
        foreach ($session['order'] as $combatant) {
            $name = $combatant['name'];
            if (!isset($session['conditions'][$name])) {
                $session['conditions'][$name] = [];
            }
        }

        return $session;
    }

    public function createMonster(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)');
            $stmt->execute([
                $data['slug'],
                $data['name'],
                $data['cr'],
                $data['armor_class'],
                $data['hit_points'],
                json_encode($data['tags'] ?? [], JSON_THROW_ON_ERROR),
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getMonster(string $slug): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM compendium_monsters WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'slug' => $row['slug'],
            'name' => $row['name'],
            'cr' => $row['cr'],
            'armor_class' => (int) $row['armor_class'],
            'hit_points' => (int) $row['hit_points'],
            'tags' => json_decode($row['tags_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function createItem(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([
                $data['slug'],
                $data['name'],
                $data['type'],
                $data['rarity'],
                $data['cost_gp'],
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getItem(string $slug): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM compendium_items WHERE slug = ?');
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

    public function createCampaign(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
            $stmt->execute([$data['id'], $data['name'], $data['dm']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCampaign(string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM campaigns WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'dm' => $row['dm'],
        ];
    }

    public function createCampaignCharacter(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['name'], $data['level'], $data['class']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCampaignCharacters(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'id' => $row['id'],
                'name' => $row['name'],
                'level' => (int) $row['level'],
                'class' => $row['class'],
            ];
        }

        return $result;
    }

    public function getCampaignCharacter(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, level, class FROM campaign_characters WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$characterId, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }

    public function createCampaignEvent(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['kind'], $data['summary'] ?? null]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCampaignEventCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();

        return (int) ($row['count'] ?? 0);
    }

    public function getLatestCampaignEvent(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id DESC LIMIT 1');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();

        return $row ?: null;
    }

    public function getCampaignCharacterCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignQuestCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM quests WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignNpcCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignInventoryItemCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(DISTINCT item_slug) AS count FROM campaign_inventory WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getCampaignSessionCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) ($stmt->fetch()['count'] ?? 0);
    }

    public function getSchemaVersion(): int
    {
        $stmt = $this->pdo->query('SELECT version FROM schema_version LIMIT 1');
        $row = $stmt->fetch();

        return (int) ($row['version'] ?? 1);
    }

    public function createQuest(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO quests (id, campaign_id, title, status) VALUES (?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['title'], $data['status']]);
            $insert = $this->pdo->prepare('INSERT INTO quest_milestones (quest_id, milestone, done) VALUES (?, ?, 0)');
            foreach ($data['milestones'] as $milestone) {
                $insert->execute([$data['id'], $milestone]);
            }

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getQuest(string $questId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, campaign_id, title, status FROM quests WHERE id = ?');
        $stmt->execute([$questId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateQuest($row);
    }

    private function hydrateQuest(array $row): array
    {
        $stmt = $this->pdo->prepare('SELECT milestone, done FROM quest_milestones WHERE quest_id = ? ORDER BY id');
        $stmt->execute([$row['id']]);
        $milestones = [];
        $doneCount = 0;
        foreach ($stmt->fetchAll() as $m) {
            $isDone = (int) $m['done'] === 1;
            $milestones[] = [
                'milestone' => $m['milestone'],
                'done' => $isDone,
            ];
            if ($isDone) {
                $doneCount++;
            }
        }
        $total = count($milestones);
        $status = $row['status'];
        if ($total > 0 && $doneCount === $total) {
            $status = 'completed';
        }

        return [
            'id' => $row['id'],
            'campaign_id' => $row['campaign_id'],
            'title' => $row['title'],
            'status' => $status,
            'milestones_total' => $total,
            'milestones_done' => $doneCount,
            'milestones' => $milestones,
        ];
    }

    public function updateQuestProgress(string $campaignId, string $questId, array $completed): ?array
    {
        $quest = $this->getQuest($questId);
        if (!$quest || $quest['campaign_id'] !== $campaignId) {
            return null;
        }

        $stmt = $this->pdo->prepare('UPDATE quest_milestones SET done = 1 WHERE quest_id = ? AND milestone = ?');
        foreach ($completed as $milestone) {
            $stmt->execute([$questId, $milestone]);
        }

        return $this->getQuest($questId);
    }

    public function getQuestSummary(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id FROM quests WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $active = 0;
        $completed = 0;
        $blocked = 0;
        foreach ($stmt->fetchAll() as $row) {
            $quest = $this->getQuest($row['id']);
            if (!$quest) {
                continue;
            }
            if ($quest['milestones_done'] === $quest['milestones_total'] && $quest['milestones_total'] > 0) {
                $completed++;
            } elseif ($quest['status'] === 'blocked') {
                $blocked++;
            } elseif ($quest['status'] === 'active') {
                $active++;
            }
        }

        return [
            'campaign_id' => $campaignId,
            'active' => $active,
            'completed' => $completed,
            'blocked' => $blocked,
        ];
    }

    public function createFaction(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['name'], $data['stance']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getFaction(string $campaignId, string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, stance FROM campaign_factions WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$id, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'name' => $row['name'],
            'stance' => $row['stance'],
        ];
    }

    public function getFactions(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id, name, stance FROM campaign_factions WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'id' => $row['id'],
                'name' => $row['name'],
                'stance' => $row['stance'],
            ];
        }

        return $result;
    }

    public function createNpc(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_npcs (id, campaign_id, faction_id, name, disposition) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([$data['id'], $campaignId, $data['faction_id'], $data['name'], $data['disposition']]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getNpc(string $campaignId, string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, faction_id, name, disposition FROM campaign_npcs WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$id, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return [
            'id' => $row['id'],
            'faction_id' => $row['faction_id'],
            'name' => $row['name'],
            'disposition' => (int) $row['disposition'],
        ];
    }

    public function getNpcs(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT id, faction_id, name, disposition FROM campaign_npcs WHERE campaign_id = ? ORDER BY id');
        $stmt->execute([$campaignId]);
        $result = [];
        foreach ($stmt->fetchAll() as $row) {
            $result[] = [
                'id' => $row['id'],
                'faction_id' => $row['faction_id'],
                'name' => $row['name'],
                'disposition' => (int) $row['disposition'],
            ];
        }

        return $result;
    }

    public function getRelationshipSummary(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $factions = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $npcs = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0');
        $stmt->execute([$campaignId]);
        $friendlyNpcs = (int) ($stmt->fetch()['count'] ?? 0);

        return [
            'campaign_id' => $campaignId,
            'factions' => $factions,
            'npcs' => $npcs,
            'friendly_npcs' => $friendlyNpcs,
        ];
    }

    public function addInventoryItem(string $campaignId, string $itemSlug, int $quantity, string $owner): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $itemSlug, $quantity, $owner]);
    }

    public function hasAvailablePartyQuantity(string $campaignId, string $itemSlug, int $quantity): bool
    {
        $stmt = $this->pdo->prepare("
            SELECT COALESCE(SUM(CASE WHEN owner = 'party' THEN quantity ELSE 0 END), 0)
                 - COALESCE(SUM(CASE WHEN owner != 'party' THEN quantity ELSE 0 END), 0) AS available
            FROM campaign_inventory
            WHERE campaign_id = ? AND item_slug = ?
        ");
        $stmt->execute([$campaignId, $itemSlug]);
        $available = (int) ($stmt->fetch()['available'] ?? 0);

        return $available >= $quantity;
    }

    public function getInventorySummary(string $campaignId): array
    {
        $stmt = $this->pdo->prepare("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'");
        $stmt->execute([$campaignId]);
        $partyItems = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = ? AND owner != 'party'");
        $stmt->execute([$campaignId]);
        $assignedItems = (int) ($stmt->fetch()['count'] ?? 0);

        $stmt = $this->pdo->prepare("
            SELECT item_slug, SUM(quantity) AS total
            FROM campaign_inventory
            WHERE campaign_id = ? AND owner = 'party'
            GROUP BY item_slug
        ");
        $stmt->execute([$campaignId]);
        $partyQuantities = [];
        foreach ($stmt->fetchAll() as $row) {
            $partyQuantities[$row['item_slug']] = (int) $row['total'];
        }

        $stmt = $this->pdo->prepare("
            SELECT item_slug, SUM(quantity) AS total
            FROM campaign_inventory
            WHERE campaign_id = ? AND owner != 'party'
            GROUP BY item_slug
        ");
        $stmt->execute([$campaignId]);
        $assignedQuantities = [];
        foreach ($stmt->fetchAll() as $row) {
            $assignedQuantities[$row['item_slug']] = (int) $row['total'];
        }

        $result = [
            'campaign_id' => $campaignId,
            'party_items' => $partyItems,
            'assigned_items' => $assignedItems,
        ];

        foreach ($partyQuantities as $slug => $qty) {
            $available = $qty - ($assignedQuantities[$slug] ?? 0);
            $key = $this->pluralizeSlug($slug) . '_available';
            $result[$key] = $available;
        }

        return $result;
    }

    public function createCraftingProject(array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO downtime_crafting (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, 0, ?, ?)');
            $stmt->execute([
                $data['id'],
                $data['campaign_id'],
                $data['character_id'],
                $data['item_slug'],
                $data['days_required'],
                $data['cost_gp'],
                'active',
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCraftingProject(string $projectId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT * FROM downtime_crafting WHERE id = ?');
        $stmt->execute([$projectId]);
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

    public function advanceCraftingProject(string $projectId, int $days): ?array
    {
        $project = $this->getCraftingProject($projectId);
        if (!$project) {
            return null;
        }

        $remaining = $project['days_required'] - $project['days_completed'];
        if ($remaining <= 0) {
            return $project;
        }

        $completed = min($project['days_completed'] + $days, $project['days_required']);
        $status = $completed >= $project['days_required'] ? 'complete' : 'active';

        $stmt = $this->pdo->prepare('UPDATE downtime_crafting SET days_completed = ?, status = ? WHERE id = ?');
        $stmt->execute([$completed, $status, $projectId]);

        $project['days_completed'] = $completed;
        $project['status'] = $status;

        return $project;
    }

    public function createCampaignSession(string $campaignId, array $data): bool
    {
        try {
            $stmt = $this->pdo->prepare('INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)');
            $stmt->execute([
                $data['id'],
                $campaignId,
                $data['starts_at'],
                $data['duration_minutes'],
                json_encode($data['agenda'], JSON_THROW_ON_ERROR),
            ]);

            return true;
        } catch (PDOException $e) {
            if ($e->getCode() === '23000') {
                return false;
            }
            throw $e;
        }
    }

    public function getCampaignSession(string $campaignId, string $sessionId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$sessionId, $campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateSession($row);
    }

    public function getNextCampaignSession(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch();
        if (!$row) {
            return null;
        }

        return $this->hydrateSession($row);
    }

    private function hydrateSession(array $row): array
    {
        return [
            'id' => $row['id'],
            'campaign_id' => $row['campaign_id'],
            'starts_at' => $row['starts_at'],
            'duration_minutes' => (int) $row['duration_minutes'],
            'agenda' => json_decode($row['agenda_json'], true, 512, JSON_THROW_ON_ERROR),
        ];
    }

    public function recordAttendance(string $campaignId, string $sessionId, array $present, array $absent): ?array
    {
        $session = $this->getCampaignSession($campaignId, $sessionId);
        if (!$session) {
            return null;
        }

        $stmt = $this->pdo->prepare('INSERT OR REPLACE INTO session_attendance (session_id, character_id, present) VALUES (?, ?, ?)');
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

    private function pluralizeSlug(string $slug): string
    {
        $segments = explode('-', $slug);
        $lastIndex = count($segments) - 1;
        $last = $segments[$lastIndex];
        if (!str_ends_with($last, 's')) {
            $segments[$lastIndex] = $last . 's';
        }

        return implode('_', $segments);
    }
}

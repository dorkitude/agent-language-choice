<?php

declare(strict_types=1);

namespace App\Storage;

use PDO;

final class CampaignRepository
{
    public function __construct(private readonly PDO $pdo)
    {
    }

    public function fetch(string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaigns WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function insert(array $campaign): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaigns (id, data) VALUES (?, ?)');
        $stmt->execute([$campaign['id'], json_encode($campaign)]);
    }

    public function characterExists(string $characterId): bool
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_characters WHERE id = ?');
        $stmt->execute([$characterId]);

        return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    }

    public function insertCharacter(string $campaignId, array $character): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_characters (id, campaign_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$character['id'], $campaignId, json_encode($character)]);
    }

    public function characters(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_characters WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        $characters = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $characters[] = json_decode($row['data'], true);
        }

        return $characters;
    }

    public function eventExists(string $eventId): bool
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_events WHERE id = ?');
        $stmt->execute([$eventId]);

        return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    }

    public function insertEvent(string $campaignId, array $event): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_events (id, campaign_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$event['id'], $campaignId, json_encode($event)]);
    }

    public function eventCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS c FROM campaign_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return (int) $row['c'];
    }

    public function questExists(string $questId): bool
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_quests WHERE id = ?');
        $stmt->execute([$questId]);

        return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    }

    public function insertQuest(string $campaignId, array $quest): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_quests (id, campaign_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$quest['id'], $campaignId, json_encode($quest)]);
    }

    public function fetchQuest(string $campaignId, string $questId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_quests WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$questId, $campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function updateQuest(array $quest): void
    {
        $stmt = $this->pdo->prepare('UPDATE campaign_quests SET data = ? WHERE id = ?');
        $stmt->execute([json_encode($quest), $quest['id']]);
    }

    public function quests(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_quests WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        $quests = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $quests[] = json_decode($row['data'], true);
        }

        return $quests;
    }

    public function factionExists(string $factionId): bool
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_factions WHERE id = ?');
        $stmt->execute([$factionId]);

        return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    }

    public function insertFaction(string $campaignId, array $faction): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_factions (id, campaign_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$faction['id'], $campaignId, json_encode($faction)]);
    }

    public function fetchFaction(string $campaignId, string $factionId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_factions WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$factionId, $campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function factions(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_factions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        $factions = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $factions[] = json_decode($row['data'], true);
        }

        return $factions;
    }

    public function npcExists(string $npcId): bool
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_npcs WHERE id = ?');
        $stmt->execute([$npcId]);

        return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    }

    public function insertNpc(string $campaignId, array $npc): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_npcs (id, campaign_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$npc['id'], $campaignId, json_encode($npc)]);
    }

    public function npcs(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        $npcs = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $npcs[] = json_decode($row['data'], true);
        }

        return $npcs;
    }

    public function fetchCharacter(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_characters WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$characterId, $campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function insertInventoryItem(string $campaignId, array $item): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_inventory (campaign_id, data) VALUES (?, ?)');
        $stmt->execute([$campaignId, json_encode($item)]);
    }

    public function inventoryItems(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_inventory WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        $items = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $items[] = json_decode($row['data'], true);
        }

        return $items;
    }

    public function insertEquipment(string $campaignId, string $characterId, array $item): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_equipment (campaign_id, character_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $characterId, json_encode($item)]);
    }

    public function equipmentAssignments(string $campaignId): array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_equipment WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        $items = [];
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $items[] = json_decode($row['data'], true);
        }

        return $items;
    }

    public function craftingProjectExists(string $projectId): bool
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_crafting WHERE id = ?');
        $stmt->execute([$projectId]);

        return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    }

    public function insertCraftingProject(string $campaignId, array $project): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_crafting (id, campaign_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$project['id'], $campaignId, json_encode($project)]);
    }

    public function fetchCraftingProject(string $campaignId, string $projectId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_crafting WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$projectId, $campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function updateCraftingProject(array $project): void
    {
        $stmt = $this->pdo->prepare('UPDATE campaign_crafting SET data = ? WHERE id = ?');
        $stmt->execute([json_encode($project), $project['id']]);
    }

    public function sessionExists(string $sessionId): bool
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_sessions WHERE id = ?');
        $stmt->execute([$sessionId]);

        return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    }

    public function insertSession(string $campaignId, array $session): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO campaign_sessions (id, campaign_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$session['id'], $campaignId, json_encode($session)]);
    }

    public function fetchSession(string $campaignId, string $sessionId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_sessions WHERE id = ? AND campaign_id = ?');
        $stmt->execute([$sessionId, $campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function updateSession(array $session): void
    {
        $stmt = $this->pdo->prepare('UPDATE campaign_sessions SET data = ? WHERE id = ?');
        $stmt->execute([json_encode($session), $session['id']]);
    }

    public function sessionCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS c FROM campaign_sessions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return (int) $row['c'];
    }

    public function questCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS c FROM campaign_quests WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return (int) $row['c'];
    }

    public function npcCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS c FROM campaign_npcs WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return (int) $row['c'];
    }

    public function characterCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS c FROM campaign_characters WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return (int) $row['c'];
    }

    public function inventoryItemCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) AS c FROM campaign_inventory WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return (int) $row['c'];
    }

    public function nextSession(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM campaign_sessions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        $earliest = null;
        foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
            $session = json_decode($row['data'], true);
            if ($earliest === null || $session['starts_at'] < $earliest['starts_at']) {
                $earliest = $session;
            }
        }

        return $earliest;
    }
}

<?php

declare(strict_types=1);

namespace App\Storage;

use PDO;

final class PlayCampaignRepository
{
    public function __construct(private readonly PDO $pdo)
    {
    }

    public function fetch(string $id): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM play_campaigns WHERE id = ?');
        $stmt->execute([$id]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function insert(array $campaign): void
    {
        $stmt = $this->pdo->prepare('INSERT INTO play_campaigns (id, data) VALUES (?, ?)');
        $stmt->execute([$campaign['id'], json_encode($campaign)]);
    }

    public function memberCount(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);

        return (int) $stmt->fetchColumn();
    }

    public function memberByUsername(string $campaignId, string $username): ?array
    {
        $stmt = $this->pdo->prepare('SELECT data FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $username]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function characterIdExists(string $campaignId, string $characterId): bool
    {
        $stmt = $this->pdo->prepare(
            'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?'
        );
        $stmt->execute([$campaignId, $characterId]);

        return $stmt->fetchColumn() !== false;
    }

    public function memberByCharacterId(string $campaignId, string $characterId): ?array
    {
        $stmt = $this->pdo->prepare(
            'SELECT data FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?'
        );
        $stmt->execute([$campaignId, $characterId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    /** Returns the first member to join (lowest autoincrement id), or null if none. */
    public function firstMember(string $campaignId): ?array
    {
        $stmt = $this->pdo->prepare(
            'SELECT data FROM play_campaign_members WHERE campaign_id = ? ORDER BY id ASC LIMIT 1'
        );
        $stmt->execute([$campaignId]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    /** Returns all members in join order (lowest autoincrement id first). */
    public function membersInJoinOrder(string $campaignId): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT data FROM play_campaign_members WHERE campaign_id = ? ORDER BY id ASC'
        );
        $stmt->execute([$campaignId]);

        return array_map(
            static fn (array $row) => json_decode($row['data'], true),
            $stmt->fetchAll(PDO::FETCH_ASSOC)
        );
    }

    public function update(array $campaign): void
    {
        $stmt = $this->pdo->prepare('UPDATE play_campaigns SET data = ? WHERE id = ?');
        $stmt->execute([json_encode($campaign), $campaign['id']]);
    }

    public function insertMember(string $campaignId, string $username, string $characterId, array $member): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO play_campaign_members (campaign_id, username, character_id, data) VALUES (?, ?, ?, ?)'
        );
        $stmt->execute([$campaignId, $username, $characterId, json_encode($member)]);
    }

    public function updateMember(string $campaignId, string $username, array $member): void
    {
        $stmt = $this->pdo->prepare(
            'UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?'
        );
        $stmt->execute([json_encode($member), $campaignId, $username]);
    }

    public function nextEventSequence(string $campaignId): int
    {
        $stmt = $this->pdo->prepare('SELECT MAX(sequence) FROM play_campaign_events WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $max = $stmt->fetchColumn();

        return $max === null ? 1 : ((int) $max) + 1;
    }

    public function insertEvent(string $campaignId, int $sequence, array $event): void
    {
        $stmt = $this->pdo->prepare(
            'INSERT INTO play_campaign_events (campaign_id, sequence, data) VALUES (?, ?, ?)'
        );
        $stmt->execute([$campaignId, $sequence, json_encode($event)]);
    }

    /** Returns up to $limit most recent events, oldest first. */
    public function recentEvents(string $campaignId, int $limit): array
    {
        $stmt = $this->pdo->prepare(
            'SELECT data FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence DESC LIMIT ?'
        );
        $stmt->bindValue(1, $campaignId, PDO::PARAM_STR);
        $stmt->bindValue(2, $limit, PDO::PARAM_INT);
        $stmt->execute();

        $rows = array_map(
            static fn (array $row) => json_decode($row['data'], true),
            $stmt->fetchAll(PDO::FETCH_ASSOC)
        );

        return array_reverse($rows);
    }
}

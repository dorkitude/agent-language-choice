<?php

declare(strict_types=1);

namespace App\Storage;

use PDO;

/**
 * Persists combat sessions as one JSON blob per session id. Sessions are
 * always read/modified/written as a whole map rather than partial updates,
 * matching the small write volume of a single active combat.
 */
final class CombatSessionRepository
{
    public function __construct(private readonly PDO $pdo)
    {
    }

    public function all(): array
    {
        $sessions = [];
        foreach ($this->pdo->query('SELECT id, data FROM combat_sessions') as $row) {
            $sessions[$row['id']] = json_decode($row['data'], true);
        }

        return $sessions;
    }

    public function save(string $id, array $session): void
    {
        $stmt = $this->pdo->prepare('INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)');
        $stmt->execute([$id, json_encode($session)]);
    }

    public static function orderEntry(array $combatant): array
    {
        return ['name' => $combatant['name'], 'score' => $combatant['score']];
    }

    public static function conditionsForCombatant(array $conditions): array
    {
        return array_map(
            static fn (array $cond) => ['condition' => $cond['condition'], 'remaining_rounds' => $cond['remaining_rounds']],
            $conditions
        );
    }
}

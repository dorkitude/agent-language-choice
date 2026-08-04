<?php

declare(strict_types=1);

namespace App\Storage;

use PDO;

/**
 * Generic slug -> JSON-blob storage shared by the monsters and items tables
 * (both are simple, immutable-once-created compendium entries).
 */
final class CompendiumRepository
{
    public function __construct(private readonly PDO $pdo)
    {
    }

    public function fetch(string $table, string $slug): ?array
    {
        $stmt = $this->pdo->prepare("SELECT data FROM {$table} WHERE slug = ?");
        $stmt->execute([$slug]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);

        return $row ? json_decode($row['data'], true) : null;
    }

    public function insert(string $table, string $slug, array $data): void
    {
        $stmt = $this->pdo->prepare("INSERT INTO {$table} (slug, data) VALUES (?, ?)");
        $stmt->execute([$slug, json_encode($data)]);
    }
}

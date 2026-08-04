<?php

namespace App\Storage;

/**
 * Generic read-modify-write helper for document-shaped state stored as JSON
 * under a single key in the kv_store table (e.g. "combat_sessions", "users").
 *
 * The whole read -> mutate -> write cycle runs inside a SQLite IMMEDIATE
 * transaction so concurrent requests against the same key serialize instead
 * of racing on a read-modify-write.
 */
final class KvStore
{
    private function __construct()
    {
    }

    /**
     * @param array $default used when the key has never been written
     * @param callable(array &$state): mixed $fn mutates $state by reference; its
     *   return value becomes the return value of withState()
     */
    public static function withState(string $key, array $default, callable $fn): mixed
    {
        $db = Database::connection();
        $db->exec('BEGIN IMMEDIATE');
        try {
            $stmt = $db->prepare('SELECT value FROM kv_store WHERE key = ?');
            $stmt->execute([$key]);
            $raw = $stmt->fetchColumn();
            $state = $raw !== false ? json_decode($raw, true) : null;
            if (!is_array($state)) {
                $state = $default;
            }

            $result = $fn($state);

            $upsert = $db->prepare(
                'INSERT INTO kv_store (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value'
            );
            $upsert->execute([$key, json_encode($state)]);

            $db->exec('COMMIT');
        } catch (\Throwable $e) {
            $db->exec('ROLLBACK');
            throw $e;
        }

        return $result;
    }
}

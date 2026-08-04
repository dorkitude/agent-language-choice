<?php

namespace App\Storage;

use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for the storage introspection/reset endpoints (/v1/storage/*). */
final class StorageController
{
    public function status(): JsonResponse
    {
        $db = Database::connection();
        $stmt = $db->prepare('SELECT value FROM schema_meta WHERE key = ?');
        $stmt->execute(['initialized']);
        $initialized = $stmt->fetchColumn();

        return new JsonResponse([
            'driver' => 'sqlite',
            'schema_version' => Database::SCHEMA_VERSION,
            'initialized' => $initialized === '1',
        ]);
    }

    public function reset(): JsonResponse
    {
        Database::resetSchema(Database::connection());

        return new JsonResponse([
            'ok' => true,
            'schema_version' => Database::SCHEMA_VERSION,
        ]);
    }
}

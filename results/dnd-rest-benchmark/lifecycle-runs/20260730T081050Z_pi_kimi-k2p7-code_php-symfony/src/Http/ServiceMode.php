<?php

declare(strict_types=1);

namespace App\Http;

/**
 * Process-global maintenance switch.
 *
 * The built-in PHP development server resets static/global state between
 * requests, so this uses a small workspace file for persistence. The file
 * is reset via reset.php before each server start, so each test-run begins
 * with maintenance disabled.
 */
final class ServiceMode
{
    private static string $stateFile = __DIR__ . '/../../.service_mode';

    public static function setStateFile(string $path): void
    {
        self::$stateFile = $path;
    }

    public static function isMaintenance(): bool
    {
        if (!file_exists(self::$stateFile)) {
            return false;
        }

        $content = @file_get_contents(self::$stateFile);
        if ($content === false || $content === '') {
            return false;
        }

        $data = json_decode($content, true);
        return is_array($data) && ($data['maintenance'] ?? false) === true;
    }

    public static function setMaintenance(bool $maintenance): void
    {
        if ($maintenance) {
            file_put_contents(self::$stateFile, json_encode(['maintenance' => true]));
        } elseif (file_exists(self::$stateFile)) {
            @unlink(self::$stateFile);
        }
    }

    public static function reset(): void
    {
        if (file_exists(self::$stateFile)) {
            @unlink(self::$stateFile);
        }
    }
}

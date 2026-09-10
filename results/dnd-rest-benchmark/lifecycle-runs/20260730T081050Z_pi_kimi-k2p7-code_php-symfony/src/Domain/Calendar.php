<?php

declare(strict_types=1);

namespace App\Domain;

/**
 * Deterministic campaign-calendar weather.
 *
 * Weather is derived from the current day and season only.
 */
final class Calendar
{
    private const SEASON_OFFSETS = [
        'spring' => 0,
        'summer' => 1,
        'autumn' => 2,
        'winter' => 3,
    ];

    private const WEATHER_BY_REMAINDER = [
        0 => 'clear',
        1 => 'rain',
        2 => 'wind',
        3 => 'snow',
    ];

    /**
     * Return the list of supported seasons.
     */
    public static function seasons(): array
    {
        return array_keys(self::SEASON_OFFSETS);
    }

    /**
     * Compute the deterministic weather for a day and season.
     */
    public static function weather(int $day, string $season): string
    {
        $offset = self::SEASON_OFFSETS[$season] ?? 0;

        return self::WEATHER_BY_REMAINDER[($day + $offset) % 4];
    }
}

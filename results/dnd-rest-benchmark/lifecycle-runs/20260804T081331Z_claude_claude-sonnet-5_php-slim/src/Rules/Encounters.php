<?php

declare(strict_types=1);

namespace App\Rules;

/**
 * Pure D&D 5e encounter-difficulty math (XP-by-CR tables, party thresholds,
 * monster-count multiplier). No I/O; safe to unit test directly.
 */
final class Encounters
{
    /** XP award per challenge rating, keyed by the CR string as sent over the API. */
    public static function crXpTable(): array
    {
        return [
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
    }

    /**
     * DMG-style per-character XP thresholds by party level.
     * Only level 3 is populated; other levels are intentionally unsupported.
     */
    public static function xpThresholdsByLevel(): array
    {
        return [
            3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
        ];
    }

    /** DMG encounter-multiplier table, keyed by number of monsters. */
    public static function multiplier(int $monsterCount): float
    {
        if ($monsterCount === 1) {
            return 1;
        } elseif ($monsterCount === 2) {
            return 1.5;
        } elseif ($monsterCount >= 3 && $monsterCount <= 6) {
            return 2;
        } elseif ($monsterCount >= 7 && $monsterCount <= 10) {
            return 2.5;
        } elseif ($monsterCount >= 11 && $monsterCount <= 14) {
            return 3;
        }

        return 4;
    }

    /**
     * Sums per-character thresholds across the party. Returns null if any
     * member's level has no threshold entry (i.e. an unsupported level).
     */
    public static function partyXpThresholds(array $party): ?array
    {
        $thresholdsByLevel = self::xpThresholdsByLevel();
        $totalThresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];

        foreach ($party as $member) {
            $level = (int) ($member['level'] ?? 0);
            if (!isset($thresholdsByLevel[$level])) {
                return null;
            }
            foreach ($thresholdsByLevel[$level] as $key => $value) {
                $totalThresholds[$key] += $value;
            }
        }

        return $totalThresholds;
    }

    public static function difficultyForAdjustedXp(float $adjustedXp, array $totalThresholds): string
    {
        if ($adjustedXp >= $totalThresholds['deadly']) {
            return 'deadly';
        } elseif ($adjustedXp >= $totalThresholds['hard']) {
            return 'hard';
        } elseif ($adjustedXp >= $totalThresholds['medium']) {
            return 'medium';
        } elseif ($adjustedXp >= $totalThresholds['easy']) {
            return 'easy';
        }

        return 'trivial';
    }

    public static function recommendationForDifficulty(string $difficulty): string
    {
        return match ($difficulty) {
            'trivial' => 'negligible threat',
            'easy' => 'safe warm-up',
            'medium' => 'balanced challenge',
            'hard' => 'risky fight',
            'deadly' => 'deadly threat, prepare an escape plan',
            default => 'balanced challenge',
        };
    }
}

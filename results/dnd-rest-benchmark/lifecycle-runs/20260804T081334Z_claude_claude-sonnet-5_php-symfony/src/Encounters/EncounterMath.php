<?php

namespace App\Encounters;

/**
 * DMG encounter-difficulty math shared by the standalone adjusted-XP
 * endpoint (App\Dice\DiceController) and the campaign-aware encounter
 * builder (App\DmTools\DmToolsController).
 *
 * The reference tables only cover the CRs, party levels, and monster counts
 * exercised by the current API surface (party level 3, CR 0 through 5).
 * Extend the tables below when adding support for more values.
 */
final class EncounterMath
{
    private function __construct()
    {
    }

    /** XP value for a single monster of the given challenge rating, or null if unsupported. */
    public static function crXp(string $cr): ?int
    {
        $table = [
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
        return $table[$cr] ?? null;
    }

    /** DMG encounter-multiplier for the total number of monsters involved. */
    public static function countMultiplier(int $count): float
    {
        if ($count <= 1) {
            return 1;
        }
        if ($count === 2) {
            return 1.5;
        }
        if ($count <= 6) {
            return 2;
        }
        if ($count <= 10) {
            return 2.5;
        }
        if ($count <= 14) {
            return 3;
        }
        return 4;
    }

    /** Per-character XP thresholds (easy/medium/hard/deadly) for a party level, or null if unsupported. */
    public static function levelThresholds(int $level): ?array
    {
        $table = [
            3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
        ];
        return $table[$level] ?? null;
    }

    /** Classifies adjusted XP against a set of thresholds returned by levelThresholds(). */
    public static function difficultyFor(float $adjustedXp, array $thresholds): string
    {
        if ($adjustedXp >= $thresholds['deadly']) {
            return 'deadly';
        }
        if ($adjustedXp >= $thresholds['hard']) {
            return 'hard';
        }
        if ($adjustedXp >= $thresholds['medium']) {
            return 'medium';
        }
        if ($adjustedXp >= $thresholds['easy']) {
            return 'easy';
        }
        return 'trivial';
    }
}

<?php

declare(strict_types=1);

namespace App\Domain;

use App\Util\Numbers;

/**
 * Encounter difficulty calculation using the DMG encounter-building rules.
 *
 * The supported Challenge Ratings and party thresholds are intentionally small
 * and match the original implementation. Expanding the tables is a safe
 * additive change.
 */
final class Encounter
{
    private const XP_BY_CR = [
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

    private const THRESHOLDS_BY_LEVEL = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    /**
     * Calculate encounter metrics from a party and a list of monsters.
     *
     * The monster list must be pre-validated: each entry has 'cr' and 'count'.
     * The party list must have entries with an integer 'level'.
     *
     * Returns an array with 'error' on validation failure, otherwise the
     * encounter summary.
     */
    public static function calculate(array $party, array $monsters): array
    {
        $baseXp = 0;
        $monsterCount = 0;
        foreach ($monsters as $monster) {
            $cr = (string) $monster['cr'];
            if (!isset(self::XP_BY_CR[$cr])) {
                return ['error' => 'unsupported cr'];
            }

            $count = (int) $monster['count'];
            $monsterCount += $count;
            $baseXp += self::XP_BY_CR[$cr] * $count;
        }

        if ($monsterCount <= 0) {
            return ['error' => 'invalid monster count'];
        }

        $multiplier = match (true) {
            $monsterCount === 1 => 1,
            $monsterCount === 2 => 1.5,
            $monsterCount <= 6 => 2,
            $monsterCount <= 10 => 2.5,
            $monsterCount <= 14 => 3,
            default => 4,
        };

        $adjustedXp = $baseXp * $multiplier;

        $sumThresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
        foreach ($party as $member) {
            if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])) {
                return ['error' => 'invalid party member'];
            }

            $level = (int) $member['level'];
            if (!isset(self::THRESHOLDS_BY_LEVEL[$level])) {
                return ['error' => 'unsupported level'];
            }

            foreach (self::THRESHOLDS_BY_LEVEL[$level] as $key => $value) {
                $sumThresholds[$key] += $value;
            }
        }

        $difficulty = self::difficulty($adjustedXp, $sumThresholds);

        return [
            'base_xp' => Numbers::toIntegerWhenWhole($baseXp),
            'monster_count' => $monsterCount,
            'multiplier' => Numbers::toIntegerWhenWhole($multiplier),
            'adjusted_xp' => Numbers::toIntegerWhenWhole($adjustedXp),
            'difficulty' => $difficulty,
            'thresholds' => [
                'easy' => Numbers::toIntegerWhenWhole($sumThresholds['easy']),
                'medium' => Numbers::toIntegerWhenWhole($sumThresholds['medium']),
                'hard' => Numbers::toIntegerWhenWhole($sumThresholds['hard']),
                'deadly' => Numbers::toIntegerWhenWhole($sumThresholds['deadly']),
            ],
        ];
    }

    public static function difficulty(float|int $adjustedXp, array $thresholds): string
    {
        $difficulty = 'trivial';
        if ($adjustedXp >= $thresholds['easy']) {
            $difficulty = 'easy';
        }
        if ($adjustedXp >= $thresholds['medium']) {
            $difficulty = 'medium';
        }
        if ($adjustedXp >= $thresholds['hard']) {
            $difficulty = 'hard';
        }
        if ($adjustedXp >= $thresholds['deadly']) {
            $difficulty = 'deadly';
        }

        return $difficulty;
    }

    public static function xpByCr(): array
    {
        return self::XP_BY_CR;
    }
}

<?php

namespace App\Characters;

/** Core 5e ability-score/proficiency arithmetic, shared across character endpoints. */
final class AbilityMath
{
    private function __construct()
    {
    }

    public static function modifier(int $score): int
    {
        return (int) floor(($score - 10) / 2);
    }

    /** Proficiency bonus for a character level (1-20), or null outside that range. */
    public static function proficiencyBonus(int $level): ?int
    {
        if ($level >= 1 && $level <= 4) {
            return 2;
        }
        if ($level >= 5 && $level <= 8) {
            return 3;
        }
        if ($level >= 9 && $level <= 12) {
            return 4;
        }
        if ($level >= 13 && $level <= 16) {
            return 5;
        }
        if ($level >= 17 && $level <= 20) {
            return 6;
        }
        return null;
    }
}

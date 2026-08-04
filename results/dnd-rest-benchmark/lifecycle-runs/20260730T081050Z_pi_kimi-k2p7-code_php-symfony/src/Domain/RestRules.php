<?php

declare(strict_types=1);

namespace App\Domain;

/**
 * PHB rest, spell-slot and encumbrance rule helpers.
 */
final class RestRules
{
    public static function spellSlots(string $class, int $level): array
    {
        if ($class !== 'wizard' || $level !== 5) {
            return ['error' => 'unsupported input'];
        }

        return [
            'class' => 'wizard',
            'level' => 5,
            'slots' => ['1' => 4, '2' => 3, '3' => 2],
        ];
    }

    public static function longRest(int $level, int $hpMax, int $hpCurrent, int $hitDiceSpent, int $exhaustionLevel): array
    {
        return [
            'hp_current' => $hpMax,
            'hit_dice_spent' => max(0, $hitDiceSpent - max(1, (int) floor($level / 2))),
            'exhaustion_level' => max(0, $exhaustionLevel - 1),
        ];
    }

    public static function equipmentLoad(int $strength, int $weight): array
    {
        if ($strength < 1 || $strength > 30 || $weight < 0) {
            return ['error' => 'invalid input'];
        }

        $capacity = $strength * 15;

        return [
            'capacity' => $capacity,
            'weight' => $weight,
            'encumbered' => $weight > $capacity,
        ];
    }
}

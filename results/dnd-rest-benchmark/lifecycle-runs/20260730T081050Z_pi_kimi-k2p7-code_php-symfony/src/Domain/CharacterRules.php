<?php

declare(strict_types=1);

namespace App\Domain;

/**
 * Pure 5e character rule calculations.
 */
final class CharacterRules
{
    private const ABILITY_NAMES = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

    public static function modifier(int $score): int
    {
        return (int) floor(($score - 10) / 2);
    }

    public static function proficiencyBonus(int $level): int
    {
        return match (true) {
            $level <= 4 => 2,
            $level <= 8 => 3,
            $level <= 12 => 4,
            $level <= 16 => 5,
            default => 6,
        };
    }

    /**
     * Validate abilities and armour, then compute derived statistics.
     *
     * Returns an array with the same keys as the controller response, or an
     * array with a single 'error' key when validation fails. Callers translate
     * the error into the appropriate HTTP response.
     */
    public static function derivedStats(int $level, ?array $abilities, ?array $armor): array
    {
        if (!is_array($abilities)) {
            return ['error' => 'invalid abilities'];
        }
        if (!is_array($armor)) {
            return ['error' => 'invalid armor'];
        }

        foreach (self::ABILITY_NAMES as $name) {
            if (!isset($abilities[$name]) || !is_int($abilities[$name]) || $abilities[$name] < 1 || $abilities[$name] > 30) {
                return ['error' => 'invalid abilities'];
            }
        }

        if (!isset($armor['base']) || !is_int($armor['base'])
            || !isset($armor['shield']) || !is_bool($armor['shield'])
            || !isset($armor['dex_cap']) || !is_int($armor['dex_cap'])) {
            return ['error' => 'invalid armor'];
        }

        $modifiers = [];
        foreach (self::ABILITY_NAMES as $name) {
            $modifiers[$name] = self::modifier($abilities[$name]);
        }

        $hpMax = $level * (6 + $modifiers['con']);
        $shieldBonus = $armor['shield'] ? 2 : 0;
        $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;

        return [
            'level' => $level,
            'proficiency_bonus' => self::proficiencyBonus($level),
            'hp_max' => $hpMax,
            'armor_class' => $armorClass,
            'modifiers' => $modifiers,
        ];
    }
}

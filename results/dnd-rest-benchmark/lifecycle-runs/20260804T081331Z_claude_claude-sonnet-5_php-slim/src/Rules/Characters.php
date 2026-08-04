<?php

declare(strict_types=1);

namespace App\Rules;

/**
 * Pure D&D 5e character math (ability modifiers, proficiency bonus).
 */
final class Characters
{
    /** Valid player races for character creation. */
    public const RACES = [
        'human', 'elf', 'dwarf', 'halfling', 'dragonborn',
        'gnome', 'half-elf', 'half-orc', 'tiefling',
    ];

    /** Valid player classes for character creation. */
    public const CLASSES = [
        'barbarian', 'bard', 'cleric', 'druid', 'fighter', 'monk',
        'paladin', 'ranger', 'rogue', 'sorcerer', 'warlock', 'wizard',
    ];

    /** Valid backgrounds for character creation. */
    public const BACKGROUNDS = [
        'acolyte', 'charlatan', 'criminal', 'entertainer', 'folk-hero',
        'guild-artisan', 'hermit', 'noble', 'outlander', 'sage', 'sailor', 'soldier',
    ];

    /** Canonical ability governing each 5e skill. */
    public const SKILL_ABILITIES = [
        'acrobatics' => 'dex',
        'animal-handling' => 'wis',
        'arcana' => 'int',
        'athletics' => 'str',
        'deception' => 'cha',
        'history' => 'int',
        'insight' => 'wis',
        'intimidation' => 'cha',
        'investigation' => 'int',
        'medicine' => 'wis',
        'nature' => 'int',
        'perception' => 'wis',
        'performance' => 'cha',
        'persuasion' => 'cha',
        'religion' => 'int',
        'sleight-of-hand' => 'dex',
        'stealth' => 'dex',
        'survival' => 'wis',
    ];

    /** Level-1 hit die base (before CON modifier) by class. */
    private const HIT_DIE_BASE = [
        'barbarian' => 12,
        'fighter' => 10,
        'paladin' => 10,
        'ranger' => 10,
        'bard' => 8,
        'cleric' => 8,
        'druid' => 8,
        'monk' => 8,
        'rogue' => 8,
        'warlock' => 8,
        'sorcerer' => 6,
        'wizard' => 6,
    ];

    public static function abilityModifier(int $score): int
    {
        return (int) floor(($score - 10) / 2);
    }

    public static function proficiencyBonus(int $level): int
    {
        if ($level <= 4) {
            return 2;
        } elseif ($level <= 8) {
            return 3;
        } elseif ($level <= 12) {
            return 4;
        } elseif ($level <= 16) {
            return 5;
        }

        return 6;
    }

    /** Level-1 max HP for a class: hit die base + CON modifier. */
    public static function level1HpMax(string $class, int $conModifier): int
    {
        return self::HIT_DIE_BASE[$class] + $conModifier;
    }

    /** The class's hit die size (e.g. 8 for a d8). */
    public static function hitDieSize(string $class): int
    {
        return self::HIT_DIE_BASE[$class];
    }

    /** Deterministic per-level HP gain beyond level 1: fixed average hit die roll + CON modifier. */
    public static function levelUpHpGain(string $class, int $conModifier): int
    {
        return intdiv(self::HIT_DIE_BASE[$class], 2) + 1 + $conModifier;
    }
}

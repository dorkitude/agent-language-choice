<?php

declare(strict_types=1);

namespace App\Rules;

/**
 * Known spell registry and class-eligibility rules for the spellbook stage.
 */
final class Spells
{
    /** spell_id => [name, level, classes that may know it]. */
    public const SPELLS = [
        'fire-bolt' => ['name' => 'Fire Bolt', 'level' => 0, 'classes' => ['sorcerer', 'wizard']],
        'mage-hand' => ['name' => 'Mage Hand', 'level' => 0, 'classes' => ['bard', 'sorcerer', 'warlock', 'wizard']],
        'prestidigitation' => ['name' => 'Prestidigitation', 'level' => 0, 'classes' => ['bard', 'sorcerer', 'warlock', 'wizard']],
        'light' => ['name' => 'Light', 'level' => 0, 'classes' => ['bard', 'cleric', 'sorcerer', 'wizard']],
        'sacred-flame' => ['name' => 'Sacred Flame', 'level' => 0, 'classes' => ['cleric']],
        'guidance' => ['name' => 'Guidance', 'level' => 0, 'classes' => ['cleric', 'druid']],
        'druidcraft' => ['name' => 'Druidcraft', 'level' => 0, 'classes' => ['druid']],
        'vicious-mockery' => ['name' => 'Vicious Mockery', 'level' => 0, 'classes' => ['bard']],
        'eldritch-blast' => ['name' => 'Eldritch Blast', 'level' => 0, 'classes' => ['warlock']],
        'magic-missile' => ['name' => 'Magic Missile', 'level' => 1, 'classes' => ['sorcerer', 'wizard']],
        'shield' => ['name' => 'Shield', 'level' => 1, 'classes' => ['sorcerer', 'wizard']],
        'cure-wounds' => ['name' => 'Cure Wounds', 'level' => 1, 'classes' => ['bard', 'cleric', 'druid', 'paladin', 'ranger']],
        'healing-word' => ['name' => 'Healing Word', 'level' => 1, 'classes' => ['bard', 'cleric', 'druid']],
        'charm-person' => ['name' => 'Charm Person', 'level' => 1, 'classes' => ['bard', 'druid', 'sorcerer', 'warlock', 'wizard']],
        'faerie-fire' => ['name' => 'Faerie Fire', 'level' => 1, 'classes' => ['druid']],
        'hunters-mark' => ['name' => "Hunter's Mark", 'level' => 1, 'classes' => ['ranger']],
        'bless' => ['name' => 'Bless', 'level' => 1, 'classes' => ['cleric', 'paladin']],
        'thunderwave' => ['name' => 'Thunderwave', 'level' => 1, 'classes' => ['bard', 'druid', 'sorcerer', 'wizard']],
    ];

    /** True when the given class is allowed to know the given spell_id. */
    public static function isValidForClass(string $spellId, string $class): bool
    {
        $spell = self::SPELLS[$spellId] ?? null;

        return $spell !== null && in_array($class, $spell['classes'], true);
    }

    /**
     * Full-caster spell slot counts by character level, indexed by spell level (1-9).
     * Level 1 is deliberately a single first-level slot per the spellcasting stage spec.
     */
    private const SPELL_SLOTS_BY_CHARACTER_LEVEL = [
        1 => [1, 0, 0, 0, 0, 0, 0, 0, 0],
        2 => [3, 0, 0, 0, 0, 0, 0, 0, 0],
        3 => [4, 2, 0, 0, 0, 0, 0, 0, 0],
        4 => [4, 3, 0, 0, 0, 0, 0, 0, 0],
        5 => [4, 3, 2, 0, 0, 0, 0, 0, 0],
        6 => [4, 3, 3, 0, 0, 0, 0, 0, 0],
        7 => [4, 3, 3, 1, 0, 0, 0, 0, 0],
        8 => [4, 3, 3, 2, 0, 0, 0, 0, 0],
        9 => [4, 3, 3, 3, 1, 0, 0, 0, 0],
        10 => [4, 3, 3, 3, 2, 0, 0, 0, 0],
        11 => [4, 3, 3, 3, 2, 1, 0, 0, 0],
        12 => [4, 3, 3, 3, 2, 1, 0, 0, 0],
        13 => [4, 3, 3, 3, 2, 1, 1, 0, 0],
        14 => [4, 3, 3, 3, 2, 1, 1, 0, 0],
        15 => [4, 3, 3, 3, 2, 1, 1, 1, 0],
        16 => [4, 3, 3, 3, 2, 1, 1, 1, 0],
        17 => [4, 3, 3, 3, 2, 1, 1, 1, 1],
        18 => [4, 3, 3, 3, 3, 1, 1, 1, 1],
        19 => [4, 3, 3, 3, 3, 2, 1, 1, 1],
        20 => [4, 3, 3, 3, 3, 2, 2, 1, 1],
    ];

    /** Total spell slots a character of the given level has for the given spell level (1-9). Cantrips (0) are unlimited. */
    public static function slotsForCharacterLevel(int $characterLevel, int $spellLevel): int
    {
        if ($spellLevel <= 0) {
            return PHP_INT_MAX;
        }

        $characterLevel = max(1, min(20, $characterLevel));

        return self::SPELL_SLOTS_BY_CHARACTER_LEVEL[$characterLevel][$spellLevel - 1] ?? 0;
    }
}

<?php

declare(strict_types=1);

namespace App\Domain;

/**
 * Spell-book validation helpers.
 *
 * The current benchmark stage tracks known spells per character. A minimal
 * hard-coded wizard spell list is enough for the evaluator; future stages can
 * replace this with a compendium lookup.
 */
final class SpellRules
{
    /**
     * Map of wizard spell slugs to their display name and spell level.
     */
    public const WIZARD_SPELLS = [
        'acid-splash' => ['name' => 'Acid Splash', 'level' => 0],
        'chill-touch' => ['name' => 'Chill Touch', 'level' => 0],
        'dancing-lights' => ['name' => 'Dancing Lights', 'level' => 0],
        'fire-bolt' => ['name' => 'Fire Bolt', 'level' => 0],
        'light' => ['name' => 'Light', 'level' => 0],
        'mage-hand' => ['name' => 'Mage Hand', 'level' => 0],
        'minor-illusion' => ['name' => 'Minor Illusion', 'level' => 0],
        'poison-spray' => ['name' => 'Poison Spray', 'level' => 0],
        'prestidigitation' => ['name' => 'Prestidigitation', 'level' => 0],
        'ray-of-frost' => ['name' => 'Ray of Frost', 'level' => 0],
        'shocking-grasp' => ['name' => 'Shocking Grasp', 'level' => 0],
        'true-strike' => ['name' => 'True Strike', 'level' => 0],
        'alarm' => ['name' => 'Alarm', 'level' => 1],
        'burning-hands' => ['name' => 'Burning Hands', 'level' => 1],
        'charm-person' => ['name' => 'Charm Person', 'level' => 1],
        'detect-magic' => ['name' => 'Detect Magic', 'level' => 1],
        'disguise-self' => ['name' => 'Disguise Self', 'level' => 1],
        'expeditious-retreat' => ['name' => 'Expeditious Retreat', 'level' => 1],
        'false-life' => ['name' => 'False Life', 'level' => 1],
        'feather-fall' => ['name' => 'Feather Fall', 'level' => 1],
        'find-familiar' => ['name' => 'Find Familiar', 'level' => 1],
        'fog-cloud' => ['name' => 'Fog Cloud', 'level' => 1],
        'grease' => ['name' => 'Grease', 'level' => 1],
        'identify' => ['name' => 'Identify', 'level' => 1],
        'jump' => ['name' => 'Jump', 'level' => 1],
        'longstrider' => ['name' => 'Longstrider', 'level' => 1],
        'mage-armor' => ['name' => 'Mage Armor', 'level' => 1],
        'magic-missile' => ['name' => 'Magic Missile', 'level' => 1],
        'shield' => ['name' => 'Shield', 'level' => 1],
        'silent-image' => ['name' => 'Silent Image', 'level' => 1],
        'sleep' => ['name' => 'Sleep', 'level' => 1],
        'thunderwave' => ['name' => 'Thunderwave', 'level' => 1],
        'unseen-servant' => ['name' => 'Unseen Servant', 'level' => 1],
        'witch-bolt' => ['name' => "Witch Bolt", 'level' => 1],
        'arcane-lock' => ['name' => 'Arcane Lock', 'level' => 2],
        'blur' => ['name' => 'Blur', 'level' => 2],
        'darkness' => ['name' => 'Darkness', 'level' => 2],
        'flaming-sphere' => ['name' => 'Flaming Sphere', 'level' => 2],
        'hold-person' => ['name' => 'Hold Person', 'level' => 2],
        'invisibility' => ['name' => 'Invisibility', 'level' => 2],
        'knock' => ['name' => 'Knock', 'level' => 2],
        'levitate' => ['name' => 'Levitate', 'level' => 2],
        'mirror-image' => ['name' => 'Mirror Image', 'level' => 2],
        'misty-step' => ['name' => 'Misty Step', 'level' => 2],
        'scorching-ray' => ['name' => 'Scorching Ray', 'level' => 2],
        'shatter' => ['name' => 'Shatter', 'level' => 2],
        'web' => ['name' => 'Web', 'level' => 2],
        'counterspell' => ['name' => 'Counterspell', 'level' => 3],
        'dispel-magic' => ['name' => 'Dispel Magic', 'level' => 3],
        'fireball' => ['name' => 'Fireball', 'level' => 3],
        'fly' => ['name' => 'Fly', 'level' => 3],
        'haste' => ['name' => 'Haste', 'level' => 3],
        'lightning-bolt' => ['name' => 'Lightning Bolt', 'level' => 3],
        'slow' => ['name' => 'Slow', 'level' => 3],
        'banishment' => ['name' => 'Banishment', 'level' => 4],
        'dimension-door' => ['name' => 'Dimension Door', 'level' => 4],
        'greater-invisibility' => ['name' => 'Greater Invisibility', 'level' => 4],
        'ice-storm' => ['name' => 'Ice Storm', 'level' => 4],
        'polymorph' => ['name' => 'Polymorph', 'level' => 4],
        'stoneskin' => ['name' => 'Stoneskin', 'level' => 4],
        'wall-of-fire' => ['name' => 'Wall of Fire', 'level' => 4],
        'animate-objects' => ['name' => 'Animate Objects', 'level' => 5],
        'cloudkill' => ['name' => 'Cloudkill', 'level' => 5],
        'cone-of-cold' => ['name' => 'Cone of Cold', 'level' => 5],
        'hold-monster' => ['name' => 'Hold Monster', 'level' => 5],
        'telekinesis' => ['name' => 'Telekinesis', 'level' => 5],
        'teleportation-circle' => ['name' => 'Teleportation Circle', 'level' => 5],
        'wall-of-force' => ['name' => 'Wall of Force', 'level' => 5],
    ];

    public static function isKnownSpell(string $spellId): bool
    {
        return isset(self::WIZARD_SPELLS[$spellId]);
    }

    public static function canLearn(string $class, string $spellId): bool
    {
        if ($class !== 'wizard') {
            return false;
        }

        return self::isKnownSpell($spellId);
    }

    /**
     * Maximum number of spells a character of the given class and level may
     * have prepared at one time. Non-spellcasting classes return 0.
     */
    public static function maxPreparedSpells(string $class, int $level): int
    {
        if ($class !== 'wizard') {
            return 0;
        }

        return max(1, $level);
    }

    /**
     * Return whether the class is a spellcasting class for this benchmark.
     */
    public static function isSpellcaster(string $class): bool
    {
        return self::maxPreparedSpells($class, 1) > 0;
    }

    /**
     * Full caster spell slot counts per level. The level-one wizard is
     * intentionally given one first-level slot to match the stage contract.
     */
    public static function spellSlots(string $class, int $level): array
    {
        if ($class !== 'wizard') {
            return [];
        }

        return match ($level) {
            1 => [1 => 1],
            2 => [1 => 3],
            3 => [1 => 4, 2 => 2],
            4 => [1 => 4, 2 => 3],
            5 => [1 => 4, 2 => 3, 3 => 2],
            6 => [1 => 4, 2 => 3, 3 => 3],
            7 => [1 => 4, 2 => 3, 3 => 3, 4 => 1],
            8 => [1 => 4, 2 => 3, 3 => 3, 4 => 2],
            9 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 1],
            10 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2],
            11 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1],
            12 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1],
            13 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1],
            14 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1],
            15 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1],
            16 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1],
            17 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 2, 6 => 1, 7 => 1, 8 => 1, 9 => 1],
            18 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 1, 7 => 1, 8 => 1, 9 => 1],
            19 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 1, 8 => 1, 9 => 1],
            20 => [1 => 4, 2 => 3, 3 => 3, 4 => 3, 5 => 3, 6 => 2, 7 => 2, 8 => 1, 9 => 1],
            default => [1 => 1],
        };
    }
}

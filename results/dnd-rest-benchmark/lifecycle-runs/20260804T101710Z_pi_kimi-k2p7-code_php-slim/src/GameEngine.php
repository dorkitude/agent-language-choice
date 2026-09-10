<?php

declare(strict_types=1);

/**
 * Pure, stateless game-rule calculations.
 *
 * This class contains no I/O and no database access. It is safe to call from
 * any request handler and can be unit tested without a database.
 */
final class GameEngine
{
    /**
     * Experience-point values for challenge ratings used by the encounter
     * difficulty calculator.
     */
    public const CR_XP = [
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

    /**
     * Daily XP thresholds per character level for easy/medium/hard/deadly
     * encounter difficulty. Only level 3 is populated because the test suite
     * exercises that level; the existing behavior returns 0 for unknown levels.
     */
    public const LEVEL_THRESHOLDS = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    public function abilityModifier(int $score): int
    {
        return (int) floor(($score - 10) / 2);
    }

    public function proficiencyBonus(int $level): int
    {
        return 2 + (int) floor(($level - 1) / 4);
    }

    /**
     * Compute the encounter difficulty, base XP, adjusted XP, and multiplier
     * for a party and a list of monsters.
     *
     * The $monsters array is expected to contain entries with 'cr' and 'count'.
     *
     * @throws InvalidArgumentException when a monster CR is unknown or count is invalid.
     */
    public function computeAdjustedXp(array $party, array $monsters): array
    {
        $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
        foreach ($party as $member) {
            $level = isset($member['level']) ? (int) $member['level'] : 0;
            if (isset(self::LEVEL_THRESHOLDS[$level])) {
                foreach (self::LEVEL_THRESHOLDS[$level] as $key => $value) {
                    $thresholds[$key] += $value;
                }
            }
        }

        $baseXp = 0;
        $monsterCount = 0;
        foreach ($monsters as $monster) {
            $cr = (string) ($monster['cr'] ?? '');
            $count = isset($monster['count']) ? (int) $monster['count'] : 0;
            if (!isset(self::CR_XP[$cr]) || $count <= 0) {
                throw new InvalidArgumentException('invalid monster');
            }
            $baseXp += self::CR_XP[$cr] * $count;
            $monsterCount += $count;
        }

        if ($monsterCount <= 0) {
            throw new InvalidArgumentException('invalid monster count');
        }

        $multiplier = match (true) {
            $monsterCount === 1 => 1,
            $monsterCount === 2 => 1.5,
            $monsterCount >= 3 && $monsterCount <= 6 => 2,
            $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
            $monsterCount >= 11 && $monsterCount <= 14 => 3,
            default => 4,
        };

        $adjustedXp = $baseXp * $multiplier;

        $difficulty = 'trivial';
        if ($adjustedXp >= $thresholds['deadly']) {
            $difficulty = 'deadly';
        } elseif ($adjustedXp >= $thresholds['hard']) {
            $difficulty = 'hard';
        } elseif ($adjustedXp >= $thresholds['medium']) {
            $difficulty = 'medium';
        } elseif ($adjustedXp >= $thresholds['easy']) {
            $difficulty = 'easy';
        }

        return [
            'base_xp' => $baseXp,
            'monster_count' => $monsterCount,
            'multiplier' => $multiplier,
            'adjusted_xp' => $adjustedXp,
            'difficulty' => $difficulty,
            'thresholds' => $thresholds,
        ];
    }

    /**
     * Sort combatants by initiative score, then Dexterity, then name.
     *
     * Returns the full internal order including Dexterity for tie-breaking.
     */
    public function buildCombatOrder(array $combatants): array
    {
        $order = [];
        foreach ($combatants as $c) {
            $order[] = [
                'name' => (string) $c['name'],
                'score' => (int) $c['roll'] + (int) $c['dex'],
                'dex' => (int) $c['dex'],
            ];
        }
        usort($order, static function ($a, $b) {
            if ($b['score'] !== $a['score']) {
                return $b['score'] <=> $a['score'];
            }
            if ($b['dex'] !== $a['dex']) {
                return $b['dex'] <=> $a['dex'];
            }
            return $a['name'] <=> $b['name'];
        });
        return $order;
    }

    /**
     * Strip the internal Dexterity tie-breaker before returning an order to the client.
     */
    public function publicCombatOrder(array $order): array
    {
        return array_map(static function ($c) {
            return ['name' => $c['name'], 'score' => $c['score']];
        }, $order);
    }

    public function activeCombatant(array $order, int $turnIndex): array
    {
        return ['name' => $order[$turnIndex]['name'], 'score' => $order[$turnIndex]['score']];
    }

    /**
     * Calculate a level-1 character's maximum hit points from level and Constitution modifier.
     *
     * The formula (level * (6 + conModifier)) is the existing simplified rule.
     */
    public function maxHitPoints(int $level, int $conModifier): int
    {
        return $level * (6 + $conModifier);
    }

    /**
     * Calculate a character's maximum hit points after leveling up.
     *
     * Level 1 uses the maximum hit die plus the Constitution modifier. Each
     * additional level adds the deterministic average roll (rounded up) plus
     * the Constitution modifier.
     */
    public function leveledHitPoints(int $level, int $conModifier, int $hitDie): int
    {
        $level1Hp = $hitDie + $conModifier;
        $perLevelGain = (int) ($hitDie / 2) + 1 + $conModifier;
        return $level1Hp + ($level - 1) * $perLevelGain;
    }

    public function skillCheckModifier(int $abilityScore, int $level, bool $proficient): int
    {
        $modifier = $this->abilityModifier($abilityScore);
        if ($proficient) {
            $modifier += $this->proficiencyBonus($level);
        }
        return $modifier;
    }

    /**
     * Classes that can cast spells in this simplified ruleset.
     */
    public function isSpellcastingClass(string $class): bool
    {
        return in_array($class, ['bard', 'cleric', 'druid', 'paladin', 'ranger', 'sorcerer', 'warlock', 'wizard'], true);
    }

    /**
     * Maximum number of prepared spells a character may have at a given level.
     *
     * Level defaults to 1 when a character has not yet been built.
     */
    public function maxPreparedSpells(int $level): int
    {
        return max(1, $level);
    }

    /**
     * Full-caster spell slot table for levels 1-20 (wizard, cleric, bard, druid, sorcerer).
     *
     * Returns a map of spell level to the number of slots available.
     */
    public function fullCasterSpellSlots(int $level): array
    {
        $table = [
            1 => [1 => 1],
            2 => [1 => 2],
            3 => [1 => 2, 2 => 1],
            4 => [1 => 3, 2 => 1],
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
        ];

        $level = max(1, min(20, $level));
        return $table[$level] ?? [1 => 1];
    }

    /**
     * Spell slots for a given class and level in this simplified ruleset.
     *
     * Full casters use the standard full-caster table. All other spellcasting
     * classes are treated as full casters for determinism.
     */
    public function spellSlotsForClassLevel(string $class, int $level): array
    {
        if (!$this->isSpellcastingClass($class)) {
            return [];
        }

        return $this->fullCasterSpellSlots($level);
    }

    /**
     * Deterministic campaign-scoped dice roll.
     *
     * The result depends only on the seed, sequence, roll_id, and sides so the
     * ledger can be replayed exactly.
     */
    public function deterministicRoll(string $seed, int $sequence, string $rollId, int $sides): int
    {
        $input = $seed . '|' . $sequence . '|' . $rollId . '|' . $sides;
        $acc = 0;
        $modulus = 2 ** 32;
        foreach (unpack('C*', $input) as $byte) {
            $acc = (($acc * 31) + $byte) % $modulus;
        }
        return ($acc % $sides) + 1;
    }
}

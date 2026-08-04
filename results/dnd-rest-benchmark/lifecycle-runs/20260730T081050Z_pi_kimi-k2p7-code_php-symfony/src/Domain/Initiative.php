<?php

declare(strict_types=1);

namespace App\Domain;

/**
 * Determine initiative order for a list of combatants.
 *
 * Sorting is deterministic: highest score wins, ties broken by dexterity, then
 * by name in ascending lexicographic order.
 */
final class Initiative
{
    /**
     * Sort raw combatants into the public initiative order.
     *
     * Each input combatant should have keys 'name', 'dex' and 'roll'. Missing
     * values are coerced to defaults (empty string / 0) to match the original
     * validation behaviour of the callers.
     */
    public static function sort(array $combatants): array
    {
        $scored = [];
        foreach ($combatants as $combatant) {
            $name = (string) ($combatant['name'] ?? '');
            $dex = (int) ($combatant['dex'] ?? 0);
            $roll = (int) ($combatant['roll'] ?? 0);

            $scored[] = [
                'name' => $name,
                'score' => $roll + $dex,
                'dex' => $dex,
            ];
        }

        usort($scored, self::compare(...));

        return array_map(
            static fn (array $c): array => ['name' => $c['name'], 'score' => $c['score']],
            $scored,
        );
    }

    private static function compare(array $a, array $b): int
    {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }

        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }

        return strcmp($a['name'], $b['name']);
    }
}

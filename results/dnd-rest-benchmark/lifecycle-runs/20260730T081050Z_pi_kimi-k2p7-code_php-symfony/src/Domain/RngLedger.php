<?php

declare(strict_types=1);

namespace App\Domain;

/**
 * Deterministic campaign-scoped RNG ledger.
 *
 * Rolls are computed from a configured seed and an append-order sequence. The
 * algorithm uses only the seed, sequence, roll identifier, and die sides; it
 * never uses PHP's random facilities or wall-clock time.
 */
final class RngLedger
{
    /**
     * Compute a deterministic roll result for the given inputs.
     *
     * The byte string is: seed|sequence|roll_id|sides
     * An unsigned 32-bit accumulator is seeded by iterating over every UTF-8
     * byte: acc = (acc * 31 + byte) mod 2^32.
     * The result is (acc mod sides) + 1.
     */
    public static function roll(string $seed, int $sequence, string $rollId, int $sides): int
    {
        $input = $seed . '|' . $sequence . '|' . $rollId . '|' . $sides;
        $acc = 0;
        $mod = 2 ** 32;
        $length = strlen($input);
        for ($i = 0; $i < $length; $i++) {
            $acc = (($acc * 31) + ord($input[$i])) % $mod;
        }

        return ($acc % $sides) + 1;
    }
}

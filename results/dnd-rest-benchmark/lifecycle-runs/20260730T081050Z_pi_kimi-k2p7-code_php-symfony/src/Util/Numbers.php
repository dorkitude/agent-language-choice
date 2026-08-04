<?php

declare(strict_types=1);

namespace App\Util;

/**
 * Small numeric helpers used across the domain layer.
 */
final class Numbers
{
    /**
     * Convert a float that represents a whole number to an int, otherwise keep it as a float.
     *
     * This keeps JSON responses compact for deterministic benchmarks.
     */
    public static function toIntegerWhenWhole(float|int $n): float|int
    {
        if (is_float($n) && floor($n) == $n) {
            return (int) $n;
        }

        return $n;
    }
}

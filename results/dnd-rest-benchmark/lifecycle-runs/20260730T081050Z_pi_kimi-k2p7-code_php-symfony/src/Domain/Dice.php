<?php

declare(strict_types=1);

namespace App\Domain;

use App\Util\Numbers;

/**
 * Parse and analyse simple D&D dice expressions such as "2d6+3".
 */
final class Dice
{
    /**
     * Parse a dice expression of the form XdY[+|-Z].
     *
     * Returns null when the expression does not match the supported grammar.
     */
    public static function parse(string $expression): ?array
    {
        if (!preg_match('/^(?P<count>0*[1-9]\d*)d(?P<sides>0*[1-9]\d*)(?P<modifier>[+-]\d+)?$/', trim($expression), $matches)) {
            return null;
        }

        return [
            'count' => (int) $matches['count'],
            'sides' => (int) $matches['sides'],
            'modifier' => isset($matches['modifier']) ? (int) $matches['modifier'] : 0,
        ];
    }

    /**
     * Compute deterministic statistics for a parsed dice expression.
     */
    public static function stats(int $count, int $sides, int $modifier): array
    {
        return [
            'dice_count' => $count,
            'sides' => $sides,
            'modifier' => $modifier,
            'min' => $count + $modifier,
            'max' => $count * $sides + $modifier,
            'average' => Numbers::toIntegerWhenWhole($count * ($sides + 1) / 2 + $modifier),
        ];
    }
}

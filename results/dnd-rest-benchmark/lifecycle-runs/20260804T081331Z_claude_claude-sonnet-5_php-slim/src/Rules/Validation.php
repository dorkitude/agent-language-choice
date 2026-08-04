<?php

declare(strict_types=1);

namespace App\Rules;

/**
 * Small, reusable request-field validators shared across route groups.
 */
final class Validation
{
    public static function isIntInRange(mixed $value, int $min, int $max): bool
    {
        return is_int($value) && $value >= $min && $value <= $max;
    }

    /** Slugs are lowercase kebab-case identifiers used as compendium primary keys. */
    public static function isSlug(mixed $slug): bool
    {
        return is_string($slug) && preg_match('/^[a-z0-9]+(-[a-z0-9]+)*$/', $slug) === 1;
    }
}

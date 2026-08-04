<?php

namespace App\Support;

/**
 * Reusable input-shape checks used across request validation in every
 * controller. Kept dependency-free so any module can use them.
 */
final class Validators
{
    private function __construct()
    {
    }

    /** True for JSON numbers that represent a whole number (int or integral float). */
    public static function isValidInt(mixed $value): bool
    {
        return is_int($value) || (is_float($value) && floor($value) === $value);
    }

    /** True for non-empty string identifiers (campaign ids, character ids, ...). */
    public static function isValidId(mixed $value): bool
    {
        return is_string($value) && $value !== '';
    }

    /** True for lowercase, hyphen-separated slugs (e.g. "goblin-boss"). */
    public static function isValidSlug(mixed $value): bool
    {
        return is_string($value) && preg_match('/^[a-z0-9]+(-[a-z0-9]+)*$/', $value) === 1;
    }
}

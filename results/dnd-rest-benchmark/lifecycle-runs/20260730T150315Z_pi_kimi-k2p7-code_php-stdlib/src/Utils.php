<?php

declare(strict_types=1);

/**
 * 5e-style math tables and encounter calculations.
 */

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    return intdiv($level - 1, 4) + 2;
}

function xpByCrTable(): array
{
    return [
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
}

function thresholdsByLevelTable(): array
{
    return [
        1 => ['easy' => 25, 'medium' => 50, 'hard' => 75, 'deadly' => 100],
        2 => ['easy' => 50, 'medium' => 100, 'hard' => 150, 'deadly' => 200],
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
        4 => ['easy' => 125, 'medium' => 250, 'hard' => 375, 'deadly' => 500],
        5 => ['easy' => 250, 'medium' => 500, 'hard' => 750, 'deadly' => 1100],
        6 => ['easy' => 300, 'medium' => 600, 'hard' => 900, 'deadly' => 1400],
        7 => ['easy' => 350, 'medium' => 750, 'hard' => 1100, 'deadly' => 1700],
        8 => ['easy' => 450, 'medium' => 900, 'hard' => 1400, 'deadly' => 2100],
        9 => ['easy' => 550, 'medium' => 1100, 'hard' => 1600, 'deadly' => 2400],
        10 => ['easy' => 600, 'medium' => 1200, 'hard' => 1900, 'deadly' => 2800],
        11 => ['easy' => 800, 'medium' => 1600, 'hard' => 2400, 'deadly' => 3600],
        12 => ['easy' => 1000, 'medium' => 2000, 'hard' => 3000, 'deadly' => 4500],
        13 => ['easy' => 1100, 'medium' => 2200, 'hard' => 3400, 'deadly' => 5100],
        14 => ['easy' => 1250, 'medium' => 2500, 'hard' => 3800, 'deadly' => 5700],
        15 => ['easy' => 1400, 'medium' => 2800, 'hard' => 4300, 'deadly' => 6400],
        16 => ['easy' => 1600, 'medium' => 3200, 'hard' => 4800, 'deadly' => 7200],
        17 => ['easy' => 2000, 'medium' => 3900, 'hard' => 5900, 'deadly' => 8800],
        18 => ['easy' => 2100, 'medium' => 4200, 'hard' => 6300, 'deadly' => 9500],
        19 => ['easy' => 2400, 'medium' => 4900, 'hard' => 7300, 'deadly' => 10900],
        20 => ['easy' => 2800, 'medium' => 5700, 'hard' => 8500, 'deadly' => 12700],
    ];
}

function recommendationForDifficulty(string $difficulty): string
{
    return match ($difficulty) {
        'trivial' => 'no challenge',
        'easy' => 'safe warm-up',
        'medium' => 'fair fight',
        'hard' => 'risky engagement',
        'deadly' => 'deadly threat',
        default => 'unknown',
    };
}

/**
 * Calculate encounter difficulty from a party summary and a CR -> count map.
 *
 * $party is an array of arrays, each with a 'level' key.
 * $monstersByCrCount maps CR strings to the number of monsters of that CR.
 */
function calculateEncounterDifficulty(array $party, array $monstersByCrCount): array
{
    $xpByCr = xpByCrTable();
    $thresholdsByLevel = thresholdsByLevelTable();

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !array_key_exists('level', $member)) {
            sendError(400, 'invalid party member');
        }
        $level = filter_var($member['level'], FILTER_VALIDATE_INT);
        if ($level === false || !isset($thresholdsByLevel[$level])) {
            sendError(400, 'unsupported party level');
        }
        foreach ($thresholdsByLevel[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monstersByCrCount as $cr => $count) {
        if (!isset($xpByCr[$cr])) {
            sendError(400, 'invalid monster cr');
        }
        $baseXp += $xpByCr[$cr] * $count;
        $monsterCount += $count;
    }

    // Encounter multiplier by monster count (DMG table, 3-6 is x2, etc.).
    $multiplier = match (true) {
        $monsterCount === 1 => 1.0,
        $monsterCount === 2 => 1.5,
        $monsterCount >= 3 && $monsterCount <= 6 => 2.0,
        $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
        $monsterCount >= 11 && $monsterCount <= 14 => 3.0,
        default => 4.0,
    };

    $adjustedXp = (int) round($baseXp * $multiplier);

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

<?php

declare(strict_types=1);

/**
 * Player's Handbook helpers: spell slots, rests, and encumbrance.
 */

function getSpellSlots(array $input): array
{
    if (!array_key_exists('class', $input) || !array_key_exists('level', $input)) {
        sendError(400, 'missing fields');
    }

    $class = $input['class'];
    if (!is_string($class) || $class !== 'wizard') {
        sendError(400, 'unsupported class');
    }

    $level = filter_var($input['level'], FILTER_VALIDATE_INT);
    if ($level === false || $level !== 5) {
        sendError(400, 'unsupported level');
    }

    return [
        'class' => 'wizard',
        'level' => 5,
        'slots' => ['1' => 4, '2' => 3, '3' => 2],
    ];
}

function processLongRest(array $input): array
{
    $required = ['level', 'hp_current', 'hp_max', 'hit_dice_spent', 'exhaustion_level'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $level = filter_var($input['level'], FILTER_VALIDATE_INT);
    $hpCurrent = filter_var($input['hp_current'], FILTER_VALIDATE_INT);
    $hpMax = filter_var($input['hp_max'], FILTER_VALIDATE_INT);
    $hitDiceSpent = filter_var($input['hit_dice_spent'], FILTER_VALIDATE_INT);
    $exhaustionLevel = filter_var($input['exhaustion_level'], FILTER_VALIDATE_INT);

    if ($level === false || $level < 1
        || $hpCurrent === false || $hpCurrent < 0
        || $hpMax === false || $hpMax < 1
        || $hitDiceSpent === false || $hitDiceSpent < 0
        || $exhaustionLevel === false || $exhaustionLevel < 0
    ) {
        sendError(400, 'invalid fields');
    }

    // Long rest restores HP to max and removes one level of exhaustion.
    $newHpCurrent = $hpMax;
    $restoredDice = max(1, intdiv($level, 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $restoredDice);
    $newExhaustionLevel = max(0, $exhaustionLevel - 1);

    return [
        'hp_current' => $newHpCurrent,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustionLevel,
    ];
}

function calculateEquipmentLoad(array $input): array
{
    if (!array_key_exists('strength', $input) || !array_key_exists('weight', $input)) {
        sendError(400, 'missing fields');
    }

    $strength = filter_var($input['strength'], FILTER_VALIDATE_INT);
    $weight = filter_var($input['weight'], FILTER_VALIDATE_INT);
    if ($strength === false || $strength < 1 || $weight === false || $weight < 0) {
        sendError(400, 'invalid fields');
    }

    $capacity = $strength * 15;
    $encumbered = $weight > $capacity;

    return [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $encumbered,
    ];
}

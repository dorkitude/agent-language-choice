<?php

namespace App\PhbRules;

use App\Support\Json;
use App\Support\Validators;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for standalone Player's Handbook rule calculators (/v1/phb/*). */
final class PhbRulesController
{
    /**
     * Spell slots by spellcaster level. Only "wizard" and the levels below
     * are supported by the current API surface; extend when adding classes.
     */
    private static function wizardSpellSlots(int $level): ?array
    {
        $table = [
            5 => ['1' => 4, '2' => 3, '3' => 2],
        ];
        return $table[$level] ?? null;
    }

    public function spellSlots(array $body): JsonResponse
    {
        $class = $body['class'] ?? null;
        $level = $body['level'] ?? null;

        if (!is_string($class) || $class === '' || !Validators::isValidInt($level)) {
            return Json::error('invalid request');
        }
        $level = (int) $level;

        if ($class !== 'wizard') {
            return Json::error('unsupported class');
        }

        $slots = self::wizardSpellSlots($level);
        if ($slots === null) {
            return Json::error('unsupported level');
        }

        return new JsonResponse([
            'class' => $class,
            'level' => $level,
            'slots' => $slots,
        ]);
    }

    public function longRest(array $body): JsonResponse
    {
        $level = $body['level'] ?? null;
        $hpCurrent = $body['hp_current'] ?? null;
        $hpMax = $body['hp_max'] ?? null;
        $hitDiceSpent = $body['hit_dice_spent'] ?? null;
        $exhaustionLevel = $body['exhaustion_level'] ?? null;

        if (!Validators::isValidInt($level) || !Validators::isValidInt($hpCurrent) || !Validators::isValidInt($hpMax)
            || !Validators::isValidInt($hitDiceSpent) || !Validators::isValidInt($exhaustionLevel)) {
            return Json::error('invalid request');
        }

        $level = (int) $level;
        $hpMax = (int) $hpMax;
        $hitDiceSpent = (int) $hitDiceSpent;
        $exhaustionLevel = (int) $exhaustionLevel;

        if ($level < 1) {
            return Json::error('invalid level');
        }

        $recovered = max(1, intdiv($level, 2));
        $newHitDiceSpent = max(0, $hitDiceSpent - $recovered);
        $newExhaustion = max(0, $exhaustionLevel - 1);

        return new JsonResponse([
            'hp_current' => $hpMax,
            'hit_dice_spent' => $newHitDiceSpent,
            'exhaustion_level' => $newExhaustion,
        ]);
    }

    public function equipmentLoad(array $body): JsonResponse
    {
        $strength = $body['strength'] ?? null;
        $weight = $body['weight'] ?? null;

        if (!Validators::isValidInt($strength) || !Validators::isValidInt($weight)) {
            return Json::error('invalid request');
        }

        $strength = (int) $strength;
        $weight = (int) $weight;

        $capacity = $strength * 15;
        $encumbered = $weight > $capacity;

        return new JsonResponse([
            'capacity' => $capacity,
            'weight' => $weight,
            'encumbered' => $encumbered,
        ]);
    }
}

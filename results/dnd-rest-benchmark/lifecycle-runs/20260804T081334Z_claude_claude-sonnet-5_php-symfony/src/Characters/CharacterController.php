<?php

namespace App\Characters;

use App\Support\Json;
use App\Support\Validators;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for character-sheet arithmetic endpoints (/v1/characters/*). */
final class CharacterController
{
    public function abilityModifier(array $body): JsonResponse
    {
        $score = $body['score'] ?? null;
        if (!Validators::isValidInt($score)) {
            return Json::error('invalid score');
        }
        $score = (int) $score;
        if ($score < 1 || $score > 30) {
            return Json::error('score must be from 1 through 30');
        }

        return new JsonResponse([
            'score' => $score,
            'modifier' => AbilityMath::modifier($score),
        ]);
    }

    public function proficiency(array $body): JsonResponse
    {
        $level = $body['level'] ?? null;
        if (!Validators::isValidInt($level)) {
            return Json::error('invalid level');
        }
        $level = (int) $level;
        if ($level < 1 || $level > 20) {
            return Json::error('level must be from 1 through 20');
        }

        return new JsonResponse([
            'level' => $level,
            'proficiency_bonus' => AbilityMath::proficiencyBonus($level),
        ]);
    }

    public function derivedStats(array $body): JsonResponse
    {
        $level = $body['level'] ?? null;
        $abilities = $body['abilities'] ?? null;
        $armor = $body['armor'] ?? null;

        if (!Validators::isValidInt($level) || !is_array($abilities) || !is_array($armor)) {
            return Json::error('invalid request');
        }
        $level = (int) $level;
        if ($level < 1 || $level > 20) {
            return Json::error('level must be from 1 through 20');
        }

        $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
        $modifiers = [];
        foreach ($abilityKeys as $key) {
            if (!isset($abilities[$key]) || !Validators::isValidInt($abilities[$key])) {
                return Json::error('invalid abilities');
            }
            $modifiers[$key] = AbilityMath::modifier((int) $abilities[$key]);
        }

        if (!isset($armor['base']) || !Validators::isValidInt($armor['base'])) {
            return Json::error('invalid armor');
        }
        $base = (int) $armor['base'];
        $shield = !empty($armor['shield']);
        $dexCap = $armor['dex_cap'] ?? null;
        if ($dexCap !== null && !Validators::isValidInt($dexCap)) {
            return Json::error('invalid armor');
        }
        $dexCap = $dexCap === null ? PHP_INT_MAX : (int) $dexCap;

        $proficiencyBonus = AbilityMath::proficiencyBonus($level);

        $hpMax = $level * (6 + $modifiers['con']);
        $shieldBonus = $shield ? 2 : 0;
        $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

        return new JsonResponse([
            'level' => $level,
            'proficiency_bonus' => $proficiencyBonus,
            'hp_max' => $hpMax,
            'armor_class' => $armorClass,
            'modifiers' => $modifiers,
        ]);
    }
}

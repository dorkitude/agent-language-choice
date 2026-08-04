<?php

namespace App\Dice;

use App\Encounters\EncounterMath;
use App\Support\Json;
use Symfony\Component\HttpFoundation\JsonResponse;

/** Handlers for stateless dice/probability endpoints (/v1/dice, /v1/checks, /v1/encounters, /v1/initiative). */
final class DiceController
{
    public function stats(array $body): JsonResponse
    {
        $expression = $body['expression'] ?? null;
        if (!is_string($expression)) {
            return Json::error('invalid expression');
        }

        if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', trim($expression), $matches)) {
            return Json::error('invalid expression');
        }

        $count = (int) $matches[1];
        $sides = (int) $matches[2];
        $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

        if ($count <= 0 || $sides <= 0) {
            return Json::error('invalid expression');
        }

        $min = $count * 1 + $modifier;
        $max = $count * $sides + $modifier;
        $average = ($count * ($sides + 1) / 2) + $modifier;

        return new JsonResponse([
            'dice_count' => $count,
            'sides' => $sides,
            'modifier' => $modifier,
            'min' => $min,
            'max' => $max,
            'average' => $average,
        ]);
    }

    public function abilityCheck(array $body): JsonResponse
    {
        if (!isset($body['roll'], $body['modifier'], $body['dc'])
            || !is_numeric($body['roll']) || !is_numeric($body['modifier']) || !is_numeric($body['dc'])) {
            return Json::error('invalid request');
        }

        $roll = $body['roll'] + 0;
        $modifier = $body['modifier'] + 0;
        $dc = $body['dc'] + 0;

        $total = $roll + $modifier;
        $success = $total >= $dc;
        $margin = $total - $dc;

        return new JsonResponse([
            'total' => $total,
            'success' => $success,
            'margin' => $margin,
        ]);
    }

    public function adjustedXp(array $body): JsonResponse
    {
        $party = $body['party'] ?? null;
        $monsters = $body['monsters'] ?? null;

        if (!is_array($party) || !is_array($monsters)) {
            return Json::error('invalid request');
        }

        $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
        foreach ($party as $member) {
            if (!is_array($member) || !isset($member['level'])) {
                return Json::error('invalid request');
            }
            $memberThresholds = EncounterMath::levelThresholds((int) $member['level']);
            if ($memberThresholds === null) {
                return Json::error('unsupported level');
            }
            foreach ($memberThresholds as $key => $value) {
                $thresholds[$key] += $value;
            }
        }

        $baseXp = 0;
        $monsterCount = 0;
        foreach ($monsters as $monster) {
            if (!is_array($monster) || !isset($monster['cr'], $monster['count'])) {
                return Json::error('invalid request');
            }
            $xp = EncounterMath::crXp((string) $monster['cr']);
            if ($xp === null) {
                return Json::error('unsupported cr');
            }
            $count = (int) $monster['count'];
            $baseXp += $xp * $count;
            $monsterCount += $count;
        }

        $multiplier = EncounterMath::countMultiplier($monsterCount);
        $adjustedXp = $baseXp * $multiplier;
        $difficulty = EncounterMath::difficultyFor($adjustedXp, $thresholds);

        return new JsonResponse([
            'base_xp' => $baseXp,
            'monster_count' => $monsterCount,
            'multiplier' => $multiplier,
            'adjusted_xp' => $adjustedXp,
            'difficulty' => $difficulty,
            'thresholds' => $thresholds,
        ]);
    }

    public function initiativeOrder(array $body): JsonResponse
    {
        $combatants = $body['combatants'] ?? null;
        if (!is_array($combatants)) {
            return Json::error('invalid request');
        }

        $entries = [];
        foreach ($combatants as $combatant) {
            if (!is_array($combatant) || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])) {
                return Json::error('invalid request');
            }
            $dex = (int) $combatant['dex'];
            $roll = (int) $combatant['roll'];
            $entries[] = [
                'name' => (string) $combatant['name'],
                'dex' => $dex,
                'score' => $roll + $dex,
            ];
        }

        usort($entries, static function ($a, $b) {
            if ($a['score'] !== $b['score']) {
                return $b['score'] <=> $a['score'];
            }
            if ($a['dex'] !== $b['dex']) {
                return $b['dex'] <=> $a['dex'];
            }
            return $a['name'] <=> $b['name'];
        });

        $order = array_map(static function ($entry) {
            return [
                'name' => $entry['name'],
                'score' => $entry['score'],
            ];
        }, $entries);

        return new JsonResponse(['order' => $order]);
    }
}

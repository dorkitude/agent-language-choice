<?php

namespace App\Combat;

use App\Storage\KvStore;
use App\Support\Json;
use App\Support\Validators;
use Symfony\Component\HttpFoundation\JsonResponse;

/**
 * Handlers for initiative-tracking endpoints (/v1/combat/sessions/*).
 *
 * Sessions are stored as a single JSON document under the "combat_sessions"
 * kv_store key (see App\Storage\KvStore) rather than their own table, since
 * a session is small, always read/written as a whole, and never queried by
 * anything other than its id.
 */
final class CombatController
{
    private function withCombatState(callable $fn): mixed
    {
        return KvStore::withState('combat_sessions', ['sessions' => []], $fn);
    }

    private static function sessionActive(array $session): array
    {
        $entry = $session['order'][$session['turn_index']];
        return ['name' => $entry['name'], 'score' => $entry['score']];
    }

    private static function sessionSummary(array $session): array
    {
        return [
            'id' => $session['id'],
            'round' => $session['round'],
            'turn_index' => $session['turn_index'],
            'active' => self::sessionActive($session),
            'order' => array_map(static function ($entry) {
                return ['name' => $entry['name'], 'score' => $entry['score']];
            }, $session['order']),
        ];
    }

    public function createSession(array $body): JsonResponse
    {
        $id = $body['id'] ?? null;
        $combatants = $body['combatants'] ?? null;

        if (!is_string($id) || $id === '' || !is_array($combatants) || count($combatants) === 0) {
            return Json::error('invalid request');
        }

        $entries = [];
        foreach ($combatants as $combatant) {
            if (!is_array($combatant) || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])
                || !is_string($combatant['name']) || !Validators::isValidInt($combatant['dex']) || !Validators::isValidInt($combatant['roll'])) {
                return Json::error('invalid request');
            }
            $dex = (int) $combatant['dex'];
            $roll = (int) $combatant['roll'];
            $entries[] = [
                'name' => $combatant['name'],
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

        return $this->withCombatState(function (array &$state) use ($id, $entries) {
            if (isset($state['sessions'][$id])) {
                return Json::error('session already exists');
            }

            $conditions = [];
            foreach ($entries as $entry) {
                $conditions[$entry['name']] = [];
            }

            $session = [
                'id' => $id,
                'round' => 1,
                'turn_index' => 0,
                'order' => $entries,
                'conditions' => $conditions,
            ];

            $state['sessions'][$id] = $session;

            return new JsonResponse(self::sessionSummary($session));
        });
    }

    public function addCondition(array $body, string $id): JsonResponse
    {
        $target = $body['target'] ?? null;
        $condition = $body['condition'] ?? null;
        $duration = $body['duration_rounds'] ?? null;

        if (!is_string($target) || !is_string($condition) || !Validators::isValidInt($duration) || (int) $duration <= 0) {
            return Json::error('invalid request');
        }
        $duration = (int) $duration;

        return $this->withCombatState(function (array &$state) use ($id, $target, $condition, $duration) {
            if (!isset($state['sessions'][$id])) {
                return Json::error('session not found', 404);
            }
            $session = &$state['sessions'][$id];

            if (!isset($session['conditions'][$target])) {
                return Json::error('unknown target');
            }

            $session['conditions'][$target][] = [
                'condition' => $condition,
                'remaining_rounds' => $duration,
            ];

            return new JsonResponse([
                'target' => $target,
                'conditions' => $session['conditions'][$target],
            ]);
        });
    }

    public function advanceTurn(string $id): JsonResponse
    {
        return $this->withCombatState(function (array &$state) use ($id) {
            if (!isset($state['sessions'][$id])) {
                return Json::error('session not found', 404);
            }
            $session = &$state['sessions'][$id];

            $count = count($session['order']);
            $nextIndex = $session['turn_index'] + 1;
            if ($nextIndex >= $count) {
                $nextIndex = 0;
                $session['round'] += 1;
            }
            $session['turn_index'] = $nextIndex;

            $activeName = $session['order'][$nextIndex]['name'];
            $remaining = [];
            foreach ($session['conditions'][$activeName] as $cond) {
                $cond['remaining_rounds'] -= 1;
                if ($cond['remaining_rounds'] > 0) {
                    $remaining[] = $cond;
                }
            }
            $session['conditions'][$activeName] = $remaining;

            $conditionsOut = [];
            foreach ($session['conditions'] as $name => $conds) {
                $conditionsOut[$name] = $conds;
            }

            return new JsonResponse([
                'id' => $session['id'],
                'round' => $session['round'],
                'turn_index' => $session['turn_index'],
                'active' => self::sessionActive($session),
                'conditions' => empty($conditionsOut) ? new \stdClass() : $conditionsOut,
            ]);
        });
    }
}

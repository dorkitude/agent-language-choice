<?php

declare(strict_types=1);

/**
 * Combat state: initiative, turn order, and per-combatant conditions.
 */

function loadCombatState(): array
{
    $sessions = [];
    $stmt = db()->query('SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions');
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
        $sessions[$row['id']] = [
            'id' => $row['id'],
            'round' => (int) $row['round'],
            'turn_index' => (int) $row['turn_index'],
            'order' => json_decode($row['order_json'], true),
            'conditions' => json_decode($row['conditions_json'], true),
        ];
    }
    return $sessions;
}

function saveCombatState(array $state): void
{
    $pdo = db();
    $pdo->exec('DELETE FROM combat_sessions');
    $stmt = $pdo->prepare('INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)');
    foreach ($state as $session) {
        $stmt->execute([
            $session['id'],
            $session['round'],
            $session['turn_index'],
            json_encode($session['order'], JSON_UNESCAPED_SLASHES),
            json_encode($session['conditions'], JSON_UNESCAPED_SLASHES),
        ]);
    }
}

/**
 * Sort combatants by initiative score, then DEX, then name (deterministic).
 *
 * Each combatant must have name, dex, and roll keys. Errors are reported as
 * 400 'invalid combatant'.
 */
function sortCombatants(array $combatants): array
{
    $scored = [];
    foreach ($combatants as $c) {
        if (!is_array($c)
            || !array_key_exists('name', $c)
            || !array_key_exists('dex', $c)
            || !array_key_exists('roll', $c)
        ) {
            sendError(400, 'invalid combatant');
        }
        $name = $c['name'];
        $dex = filter_var($c['dex'], FILTER_VALIDATE_INT);
        $roll = filter_var($c['roll'], FILTER_VALIDATE_INT);
        if (!is_string($name) || $dex === false || $roll === false) {
            sendError(400, 'invalid combatant');
        }
        $scored[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($scored, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    return array_map(static function (array $c): array {
        return [
            'name' => $c['name'],
            'score' => $c['score'],
        ];
    }, $scored);
}

function createCombatSession(string $sessionId, array $combatants): array
{
    if ($sessionId === '') {
        sendError(400, 'invalid id');
    }

    $combatSessions = loadCombatState();
    if (isset($combatSessions[$sessionId])) {
        sendError(409, 'session already exists');
    }

    if (!is_array($combatants) || $combatants === []) {
        sendError(400, 'invalid combatants');
    }

    $order = sortCombatants($combatants);

    $combatSessions[$sessionId] = [
        'id' => $sessionId,
        'order' => $order,
        'round' => 1,
        'turn_index' => 0,
        'conditions' => [],
    ];
    saveCombatState($combatSessions);

    return [
        'id' => $sessionId,
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ];
}

function addCombatCondition(string $sessionId, mixed $input): array
{
    $combatSessions = loadCombatState();
    if (!isset($combatSessions[$sessionId])) {
        sendError(404, 'session not found');
    }

    if (!is_array($input)
        || !array_key_exists('target', $input)
        || !array_key_exists('condition', $input)
        || !array_key_exists('duration_rounds', $input)
    ) {
        sendError(400, 'missing fields');
    }

    $target = $input['target'];
    if (!is_string($target)) {
        sendError(400, 'invalid target');
    }

    $session = &$combatSessions[$sessionId];
    $combatantNames = array_column($session['order'], 'name');
    if (!in_array($target, $combatantNames, true)) {
        sendError(400, 'unknown target');
    }

    $condition = $input['condition'];
    if (!is_string($condition) || $condition === '') {
        sendError(400, 'invalid condition');
    }

    $duration = filter_var($input['duration_rounds'], FILTER_VALIDATE_INT);
    if ($duration === false || $duration <= 0) {
        sendError(400, 'invalid duration_rounds');
    }

    if (!isset($session['conditions'][$target])) {
        $session['conditions'][$target] = [];
    }
    $session['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    saveCombatState($combatSessions);

    return [
        'target' => $target,
        'conditions' => $session['conditions'][$target],
    ];
}

function advanceCombatTurn(string $sessionId): array
{
    $combatSessions = loadCombatState();
    if (!isset($combatSessions[$sessionId])) {
        sendError(404, 'session not found');
    }

    $session = &$combatSessions[$sessionId];
    $count = count($session['order']);
    $nextIndex = $session['turn_index'] + 1;
    if ($nextIndex >= $count) {
        $nextIndex = 0;
        $session['round'] += 1;
    }
    $session['turn_index'] = $nextIndex;

    // Conditions on the newly-active combatant decrement at the start of its turn.
    $activeName = $session['order'][$nextIndex]['name'];
    if (isset($session['conditions'][$activeName])) {
        $remaining = [];
        foreach ($session['conditions'][$activeName] as $cond) {
            $cond['remaining_rounds'] -= 1;
            if ($cond['remaining_rounds'] > 0) {
                $remaining[] = $cond;
            }
        }
        $session['conditions'][$activeName] = $remaining;
    }

    saveCombatState($combatSessions);

    // Cast to object so an empty conditions array serializes as {}, not [].
    return [
        'id' => $sessionId,
        'round' => $session['round'],
        'turn_index' => $nextIndex,
        'active' => $session['order'][$nextIndex],
        'conditions' => (object) $session['conditions'],
    ];
}

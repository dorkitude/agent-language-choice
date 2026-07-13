<?php

declare(strict_types=1);

header('Content-Type: application/json');

$method = $_SERVER['REQUEST_METHOD'];
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

function send_json(int $status, array $body): void
{
    http_response_code($status);
    echo json_encode($body, JSON_UNESCAPED_SLASHES);
    exit;
}

function read_json_body(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    $decoded = json_decode($raw, true);
    if (!is_array($decoded)) {
        return null;
    }
    return $decoded;
}

if ($method === 'GET' && $path === '/health') {
    send_json(200, ['ok' => true]);
}

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $body = read_json_body();
    $expression = $body['expression'] ?? null;
    if (!is_string($expression)) {
        send_json(400, ['error' => 'invalid expression']);
    }

    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $matches)) {
        send_json(400, ['error' => 'invalid expression']);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        send_json(400, ['error' => 'invalid expression']);
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;

    send_json(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

if ($method === 'POST' && $path === '/v1/checks/ability') {
    $body = read_json_body();
    if ($body === null || !isset($body['roll'], $body['modifier'], $body['dc'])) {
        send_json(400, ['error' => 'invalid request']);
    }

    $roll = $body['roll'];
    $modifier = $body['modifier'];
    $dc = $body['dc'];

    if (!is_numeric($roll) || !is_numeric($modifier) || !is_numeric($dc)) {
        send_json(400, ['error' => 'invalid request']);
    }

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    send_json(200, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $body = read_json_body();
    if ($body === null || !isset($body['party'], $body['monsters']) || !is_array($body['party']) || !is_array($body['monsters'])) {
        send_json(400, ['error' => 'invalid request']);
    }

    $crXp = [
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

    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        $cr = (string) ($monster['cr'] ?? '');
        $count = (int) ($monster['count'] ?? 0);
        if (!isset($crXp[$cr])) {
            send_json(400, ['error' => 'unsupported cr']);
        }
        $baseXp += $crXp[$cr] * $count;
        $monsterCount += $count;
    }

    if ($monsterCount === 1) {
        $multiplier = 1;
    } elseif ($monsterCount === 2) {
        $multiplier = 1.5;
    } elseif ($monsterCount >= 3 && $monsterCount <= 6) {
        $multiplier = 2;
    } elseif ($monsterCount >= 7 && $monsterCount <= 10) {
        $multiplier = 2.5;
    } elseif ($monsterCount >= 11 && $monsterCount <= 14) {
        $multiplier = 3;
    } else {
        $multiplier = 4;
    }

    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        $level = (int) ($member['level'] ?? 0);
        if (!isset($levelThresholds[$level])) {
            send_json(400, ['error' => 'unsupported level']);
        }
        foreach ($thresholds as $key => $_) {
            $thresholds[$key] += $levelThresholds[$level][$key];
        }
    }

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

    send_json(200, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

if ($method === 'POST' && $path === '/v1/initiative/order') {
    $body = read_json_body();
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        send_json(400, ['error' => 'invalid request']);
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        $name = $combatant['name'] ?? '';
        $dex = $combatant['dex'] ?? 0;
        $roll = $combatant['roll'] ?? 0;
        $score = $roll + $dex;
        $combatants[] = ['name' => $name, 'dex' => $dex, 'score' => $score];
    }

    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(function ($c) {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $combatants);

    send_json(200, ['order' => $order]);
}

function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int
{
    if ($level <= 4) {
        return 2;
    }
    if ($level <= 8) {
        return 3;
    }
    if ($level <= 12) {
        return 4;
    }
    if ($level <= 16) {
        return 5;
    }
    return 6;
}

if ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
    $body = read_json_body();
    if ($body === null || !isset($body['score']) || !is_int($body['score'])) {
        send_json(400, ['error' => 'invalid request']);
    }

    $score = $body['score'];
    if ($score < 1 || $score > 30) {
        send_json(400, ['error' => 'invalid request']);
    }

    send_json(200, [
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

if ($method === 'POST' && $path === '/v1/characters/proficiency') {
    $body = read_json_body();
    if ($body === null || !isset($body['level']) || !is_int($body['level'])) {
        send_json(400, ['error' => 'invalid request']);
    }

    $level = $body['level'];
    if ($level < 1 || $level > 20) {
        send_json(400, ['error' => 'invalid request']);
    }

    send_json(200, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

if ($method === 'POST' && $path === '/v1/characters/derived-stats') {
    $body = read_json_body();
    if ($body === null || !isset($body['level'], $body['abilities'], $body['armor'])
        || !is_int($body['level']) || !is_array($body['abilities']) || !is_array($body['armor'])) {
        send_json(400, ['error' => 'invalid request']);
    }

    $level = $body['level'];
    if ($level < 1 || $level > 20) {
        send_json(400, ['error' => 'invalid request']);
    }

    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $abilities = $body['abilities'];
    foreach ($abilityKeys as $key) {
        if (!isset($abilities[$key]) || !is_int($abilities[$key]) || $abilities[$key] < 1 || $abilities[$key] > 30) {
            send_json(400, ['error' => 'invalid request']);
        }
    }

    $armor = $body['armor'];
    if (!isset($armor['base']) || !is_int($armor['base']) || !isset($armor['dex_cap']) || !is_int($armor['dex_cap'])) {
        send_json(400, ['error' => 'invalid request']);
    }
    $shield = isset($armor['shield']) && $armor['shield'] === true;

    $modifiers = [];
    foreach ($abilityKeys as $key) {
        $modifiers[$key] = ability_modifier($abilities[$key]);
    }

    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;

    send_json(200, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

$combatStateFile = __DIR__ . '/combat_state.json';

function load_combat_state(string $file): array
{
    if (!file_exists($file)) {
        return [];
    }
    $raw = file_get_contents($file);
    if ($raw === false || $raw === '') {
        return [];
    }
    $decoded = json_decode($raw, true);
    return is_array($decoded) ? $decoded : [];
}

function save_combat_state(string $file, array $state): void
{
    file_put_contents($file, json_encode($state, JSON_UNESCAPED_SLASHES), LOCK_EX);
}

function combat_active(array $session): array
{
    $active = $session['order'][$session['turn_index']];
    return ['name' => $active['name'], 'score' => $active['score']];
}

function combat_conditions_response(array $session): object
{
    $result = new stdClass();
    foreach ($session['conditions'] as $name => $conditions) {
        if (count($conditions) > 0) {
            $result->$name = $conditions;
        }
    }
    return $result;
}

if ($method === 'POST' && $path === '/v1/combat/sessions') {
    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['combatants']) || !is_string($body['id']) || $body['id'] === '' || !is_array($body['combatants']) || count($body['combatants']) === 0) {
        send_json(400, ['error' => 'invalid request']);
    }

    $id = $body['id'];
    $state = load_combat_state($combatStateFile);
    if (isset($state[$id])) {
        send_json(400, ['error' => 'duplicate id']);
    }

    $combatants = [];
    $names = [];
    foreach ($body['combatants'] as $combatant) {
        if (!is_array($combatant) || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name']) || $combatant['name'] === ''
            || !is_numeric($combatant['dex']) || !is_numeric($combatant['roll'])) {
            send_json(400, ['error' => 'invalid combatant']);
        }
        $name = $combatant['name'];
        if (in_array($name, $names, true)) {
            send_json(400, ['error' => 'duplicate combatant name']);
        }
        $names[] = $name;
        $dex = $combatant['dex'];
        $roll = $combatant['roll'];
        $score = $roll + $dex;
        $combatants[] = ['name' => $name, 'dex' => $dex, 'roll' => $roll, 'score' => $score];
    }

    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $conditions = [];
    foreach ($names as $name) {
        $conditions[$name] = [];
    }

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $combatants,
        'conditions' => $conditions,
    ];

    $state[$id] = $session;
    save_combat_state($combatStateFile, $state);

    $order = array_map(function ($c) {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $combatants);

    send_json(200, [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => combat_active($session),
        'order' => $order,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $m)) {
    $id = $m[1];
    $state = load_combat_state($combatStateFile);
    if (!isset($state[$id])) {
        send_json(404, ['error' => 'session not found']);
    }
    $session = $state[$id];

    $body = read_json_body();
    if ($body === null || !isset($body['target'], $body['condition'], $body['duration_rounds'])
        || !is_string($body['target']) || !is_string($body['condition'])
        || !is_int($body['duration_rounds']) || $body['duration_rounds'] <= 0) {
        send_json(400, ['error' => 'invalid request']);
    }

    $target = $body['target'];
    if (!isset($session['conditions'][$target])) {
        send_json(400, ['error' => 'unknown target']);
    }

    $session['conditions'][$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];

    $state[$id] = $session;
    save_combat_state($combatStateFile, $state);

    send_json(200, [
        'target' => $target,
        'conditions' => $session['conditions'][$target],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $m)) {
    $id = $m[1];
    $state = load_combat_state($combatStateFile);
    if (!isset($state[$id])) {
        send_json(404, ['error' => 'session not found']);
    }
    $session = $state[$id];

    $count = count($session['order']);
    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    $updated = [];
    foreach ($session['conditions'][$activeName] as $condition) {
        $condition['remaining_rounds']--;
        if ($condition['remaining_rounds'] > 0) {
            $updated[] = $condition;
        }
    }
    $session['conditions'][$activeName] = $updated;

    $state[$id] = $session;
    save_combat_state($combatStateFile, $state);

    send_json(200, [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => combat_active($session),
        'conditions' => combat_conditions_response($session),
    ]);
}

send_json(404, ['error' => 'not found']);

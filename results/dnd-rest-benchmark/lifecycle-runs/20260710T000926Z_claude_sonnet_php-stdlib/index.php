<?php
declare(strict_types=1);

header('Content-Type: application/json');

function send_json($data, int $status = 200): void
{
    http_response_code($status);
    echo json_encode($data);
    exit;
}

function read_body(): array
{
    $raw = file_get_contents('php://input');
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        send_json(['error' => 'invalid json body'], 400);
    }
    return $data;
}

$method = $_SERVER['REQUEST_METHOD'];
$path = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

if ($method === 'GET' && $path === '/health') {
    send_json(['ok' => true]);
}

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $body = read_body();
    $expr = $body['expression'] ?? null;
    if (!is_string($expr)) {
        send_json(['error' => 'expression is required'], 400);
    }
    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expr, $m)) {
        send_json(['error' => 'invalid expression'], 400);
    }
    $count = (int)$m[1];
    $sides = (int)$m[2];
    $modifier = isset($m[3]) ? (int)$m[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        send_json(['error' => 'invalid expression'], 400);
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;

    send_json([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

if ($method === 'POST' && $path === '/v1/checks/ability') {
    $body = read_body();
    if (!isset($body['roll'], $body['modifier'], $body['dc'])) {
        send_json(['error' => 'roll, modifier, dc are required'], 400);
    }
    $roll = $body['roll'];
    $modifier = $body['modifier'];
    $dc = $body['dc'];
    if (!is_numeric($roll) || !is_numeric($modifier) || !is_numeric($dc)) {
        send_json(['error' => 'roll, modifier, dc must be numeric'], 400);
    }
    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    send_json([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $body = read_body();
    $party = $body['party'] ?? null;
    $monsters = $body['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        send_json(['error' => 'party and monsters are required'], 400);
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
    foreach ($monsters as $monster) {
        $cr = (string)($monster['cr'] ?? null);
        $count = (int)($monster['count'] ?? 0);
        if (!isset($crXp[$cr])) {
            send_json(['error' => 'unsupported cr: ' . $cr], 400);
        }
        $baseXp += $crXp[$cr] * $count;
        $monsterCount += $count;
    }

    if ($monsterCount <= 0) {
        $multiplier = 1;
    } elseif ($monsterCount === 1) {
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
    foreach ($party as $member) {
        $level = (int)($member['level'] ?? 0);
        if (!isset($levelThresholds[$level])) {
            send_json(['error' => 'unsupported level: ' . $level], 400);
        }
        foreach ($thresholds as $k => $v) {
            $thresholds[$k] += $levelThresholds[$level][$k];
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

    send_json([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

if ($method === 'POST' && $path === '/v1/initiative/order') {
    $body = read_body();
    $combatants = $body['combatants'] ?? null;
    if (!is_array($combatants)) {
        send_json(['error' => 'combatants is required'], 400);
    }

    $scored = [];
    foreach ($combatants as $c) {
        $name = (string)($c['name'] ?? '');
        $dex = (int)($c['dex'] ?? 0);
        $roll = (int)($c['roll'] ?? 0);
        $scored[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($scored, function ($a, $b) {
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
    }, $scored);

    send_json(['order' => $order]);
}

function ability_modifier(int $score): int
{
    return (int)floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int
{
    if ($level <= 4) return 2;
    if ($level <= 8) return 3;
    if ($level <= 12) return 4;
    if ($level <= 16) return 5;
    return 6;
}

if ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
    $body = read_body();
    $score = $body['score'] ?? null;
    if (!is_int($score) || $score < 1 || $score > 30) {
        send_json(['error' => 'score must be an integer from 1 through 30'], 400);
    }

    send_json([
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

if ($method === 'POST' && $path === '/v1/characters/proficiency') {
    $body = read_body();
    $level = $body['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        send_json(['error' => 'level must be an integer from 1 through 20'], 400);
    }

    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

if ($method === 'POST' && $path === '/v1/characters/derived-stats') {
    $body = read_body();
    $level = $body['level'] ?? null;
    $abilities = $body['abilities'] ?? null;
    $armor = $body['armor'] ?? null;

    if (!is_int($level) || $level < 1 || $level > 20) {
        send_json(['error' => 'level must be an integer from 1 through 20'], 400);
    }
    if (!is_array($abilities)) {
        send_json(['error' => 'abilities is required'], 400);
    }
    if (!is_array($armor)) {
        send_json(['error' => 'armor is required'], 400);
    }

    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilityKeys as $key) {
        $score = $abilities[$key] ?? null;
        if (!is_int($score) || $score < 1 || $score > 30) {
            send_json(['error' => "abilities.$key must be an integer from 1 through 30"], 400);
        }
        $modifiers[$key] = ability_modifier($score);
    }

    $armorBase = $armor['base'] ?? null;
    if (!is_int($armorBase)) {
        send_json(['error' => 'armor.base must be an integer'], 400);
    }
    $shield = $armor['shield'] ?? false;
    if (!is_bool($shield)) {
        send_json(['error' => 'armor.shield must be a boolean'], 400);
    }
    $dexCap = $armor['dex_cap'] ?? null;
    if (!is_int($dexCap)) {
        send_json(['error' => 'armor.dex_cap must be an integer'], 400);
    }

    $proficiencyBonus = proficiency_bonus($level);
    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $armorBase + min($modifiers['dex'], $dexCap) + $shieldBonus;

    send_json([
        'level' => $level,
        'proficiency_bonus' => $proficiencyBonus,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

$combatStateFile = __DIR__ . '/combat_state.json';

function combat_load_sessions(): array
{
    global $combatStateFile;
    if (!file_exists($combatStateFile)) {
        return [];
    }
    $raw = file_get_contents($combatStateFile);
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function combat_save_sessions(array $sessions): void
{
    global $combatStateFile;
    file_put_contents($combatStateFile, json_encode($sessions), LOCK_EX);
}

function combat_active(array $session): array
{
    $c = $session['order'][$session['turn_index']];
    return ['name' => $c['name'], 'score' => $c['score']];
}

if ($method === 'POST' && $path === '/v1/combat/sessions') {
    $body = read_body();
    $id = $body['id'] ?? null;
    $combatants = $body['combatants'] ?? null;

    if (!is_string($id) || $id === '') {
        send_json(['error' => 'id is required'], 400);
    }
    if (!is_array($combatants) || count($combatants) === 0) {
        send_json(['error' => 'combatants is required'], 400);
    }

    $sessions = combat_load_sessions();
    if (isset($sessions[$id])) {
        send_json(['error' => 'session id already exists'], 400);
    }

    $scored = [];
    foreach ($combatants as $c) {
        if (!isset($c['name']) || !is_string($c['name'])) {
            send_json(['error' => 'combatant name is required'], 400);
        }
        if (!isset($c['dex']) || !is_int($c['dex']) || !isset($c['roll']) || !is_int($c['roll'])) {
            send_json(['error' => 'combatant dex and roll must be integers'], 400);
        }
        $scored[] = [
            'name' => $c['name'],
            'dex' => $c['dex'],
            'score' => $c['roll'] + $c['dex'],
        ];
    }

    usort($scored, function ($a, $b) {
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
    }, $scored);

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];

    $sessions[$id] = $session;
    combat_save_sessions($sessions);

    send_json([
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => combat_active($session),
        'order' => $session['order'],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $pm)) {
    $id = $pm[1];
    $sessions = combat_load_sessions();
    if (!isset($sessions[$id])) {
        send_json(['error' => 'unknown session id'], 404);
    }
    $session = $sessions[$id];

    $body = read_body();
    $target = $body['target'] ?? null;
    $condition = $body['condition'] ?? null;
    $duration = $body['duration_rounds'] ?? null;

    if (!is_string($target) || $target === '') {
        send_json(['error' => 'target is required'], 400);
    }
    if (!is_string($condition) || $condition === '') {
        send_json(['error' => 'condition is required'], 400);
    }
    if (!is_int($duration) || $duration <= 0) {
        send_json(['error' => 'duration_rounds must be a positive integer'], 400);
    }

    $found = false;
    foreach ($session['order'] as $c) {
        if ($c['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        send_json(['error' => 'unknown target'], 400);
    }

    if (!isset($session['conditions'][$target])) {
        $session['conditions'][$target] = [];
    }
    $session['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];

    $sessions[$id] = $session;
    combat_save_sessions($sessions);

    send_json([
        'target' => $target,
        'conditions' => $session['conditions'][$target],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $pm)) {
    $id = $pm[1];
    $sessions = combat_load_sessions();
    if (!isset($sessions[$id])) {
        send_json(['error' => 'unknown session id'], 404);
    }
    $session = $sessions[$id];

    $count = count($session['order']);
    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    if (isset($session['conditions'][$activeName])) {
        $remaining = [];
        foreach ($session['conditions'][$activeName] as $cond) {
            $cond['remaining_rounds']--;
            if ($cond['remaining_rounds'] > 0) {
                $remaining[] = $cond;
            }
        }
        $session['conditions'][$activeName] = $remaining;
    }

    $sessions[$id] = $session;
    combat_save_sessions($sessions);

    send_json([
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => combat_active($session),
        'conditions' => (object)$session['conditions'],
    ]);
}

send_json(['error' => 'not found'], 404);

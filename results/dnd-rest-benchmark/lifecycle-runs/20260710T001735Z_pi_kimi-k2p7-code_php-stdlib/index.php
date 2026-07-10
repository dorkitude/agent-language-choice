<?php
declare(strict_types=1);

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = $_SERVER['REQUEST_URI'] ?? '/';
$path = parse_url($path, PHP_URL_PATH) ?: '/';
$path = rtrim($path, '/') ?: '/';

function send_json($data, int $code = 200): never {
    http_response_code($code);
    header('Content-Type: application/json');
    echo json_encode($data, JSON_UNESCAPED_SLASHES);
    exit;
}

function bad_request(string $message = 'Bad request'): never {
    send_json(['error' => $message], 400);
}

function read_body(): array {
    $raw = file_get_contents('php://input');
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        bad_request('Invalid JSON body');
    }
    return $data;
}

function require_int(mixed $value): int {
    if (!is_int($value)) {
        bad_request('Expected integer value');
    }
    return $value;
}

function require_positive_int(mixed $value): int {
    $v = require_int($value);
    if ($v <= 0) {
        bad_request('Expected positive integer value');
    }
    return $v;
}

function state_file(): string {
    return __DIR__ . '/combat_state.json';
}

function load_state(): array {
    $file = state_file();
    if (!file_exists($file)) {
        return [];
    }
    $raw = file_get_contents($file);
    if ($raw === false) {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function save_state(array $state): void {
    file_put_contents(state_file(), json_encode($state, JSON_UNESCAPED_SLASHES), LOCK_EX);
}

function ability_modifier(int $score): int {
    if ($score < 1 || $score > 30) {
        bad_request('Ability score must be between 1 and 30');
    }
    return (int) floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int {
    if ($level < 1 || $level > 20) {
        bad_request('Level must be between 1 and 20');
    }
    return match (true) {
        $level <= 4 => 2,
        $level <= 8 => 3,
        $level <= 12 => 4,
        $level <= 16 => 5,
        default => 6,
    };
}

if ($method === 'GET' && $path === '/health') {
    send_json(['ok' => true]);
}

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $data = read_body();
    $expression = isset($data['expression']) && is_string($data['expression']) ? $data['expression'] : '';

    if (!preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $expression, $matches)) {
        bad_request('Invalid dice expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        bad_request('Dice count and sides must be positive');
    }

    $modifier = 0;
    if (isset($matches[3])) {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier = -$modifier;
        }
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

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
    $data = read_body();

    $roll = require_int($data['roll'] ?? null);
    $modifier = require_int($data['modifier'] ?? null);
    $dc = require_int($data['dc'] ?? null);

    $total = $roll + $modifier;
    $margin = $total - $dc;

    send_json([
        'total' => $total,
        'success' => $margin >= 0,
        'margin' => $margin,
    ]);
}

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $data = read_body();

    if (!isset($data['party']) || !is_array($data['party']) ||
        !isset($data['monsters']) || !is_array($data['monsters'])) {
        bad_request('Missing party or monsters');
    }

    $xpByCr = [
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

    $thresholdsByLevel = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr']) || !isset($monster['count'])) {
            bad_request('Invalid monster entry');
        }
        if (!is_string($monster['cr']) || !isset($xpByCr[$monster['cr']])) {
            bad_request('Unsupported challenge rating');
        }
        $count = require_int($monster['count']);
        if ($count <= 0) {
            bad_request('Monster count must be positive');
        }
        $baseXp += $xpByCr[$monster['cr']] * $count;
        $monsterCount += $count;
    }

    $multiplier = match (true) {
        $monsterCount >= 15 => 4,
        $monsterCount >= 11 => 3,
        $monsterCount >= 7 => 2.5,
        $monsterCount >= 3 => 2,
        $monsterCount === 2 => 1.5,
        default => 1,
    };

    $adjustedXp = (int) round($baseXp * $multiplier);

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!is_array($member) || !isset($member['level'])) {
            bad_request('Invalid party member');
        }
        $level = require_int($member['level']);
        if (!isset($thresholdsByLevel[$level])) {
            bad_request('Unsupported party level');
        }
        foreach ($thresholdsByLevel[$level] as $key => $value) {
            $thresholds[$key] += $value;
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
    $data = read_body();

    if (!isset($data['combatants']) || !is_array($data['combatants'])) {
        bad_request('Missing combatants');
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        if (!is_array($combatant) ||
            !isset($combatant['name']) || !is_string($combatant['name']) ||
            !isset($combatant['dex']) || !isset($combatant['roll'])) {
            bad_request('Invalid combatant entry');
        }
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => require_int($combatant['dex']),
            'score' => require_int($combatant['roll']) + require_int($combatant['dex']),
        ];
    }

    usort($combatants, static function (array $a, array $b): int {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(static fn (array $c): array => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $combatants);

    send_json(['order' => $order]);
}

if ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
    $data = read_body();

    $score = require_int($data['score'] ?? null);
    $modifier = ability_modifier($score);

    send_json(['score' => $score, 'modifier' => $modifier]);
}

if ($method === 'POST' && $path === '/v1/characters/proficiency') {
    $data = read_body();

    $level = require_int($data['level'] ?? null);
    $bonus = proficiency_bonus($level);

    send_json(['level' => $level, 'proficiency_bonus' => $bonus]);
}

if ($method === 'POST' && $path === '/v1/characters/derived-stats') {
    $data = read_body();

    $level = require_int($data['level'] ?? null);
    proficiency_bonus($level);

    if (!isset($data['abilities']) || !is_array($data['abilities'])) {
        bad_request('Missing abilities');
    }
    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    foreach ($abilityNames as $name) {
        if (!isset($data['abilities'][$name])) {
            bad_request('Missing ability: ' . $name);
        }
    }

    $modifiers = [];
    foreach ($abilityNames as $name) {
        $modifiers[$name] = ability_modifier(require_int($data['abilities'][$name]));
    }

    if (!isset($data['armor']) || !is_array($data['armor'])) {
        bad_request('Missing armor');
    }
    $armor = $data['armor'];
    if (!isset($armor['base']) || !is_int($armor['base'])) {
        bad_request('Missing armor base');
    }
    if (!isset($armor['dex_cap']) || !is_int($armor['dex_cap'])) {
        bad_request('Missing armor dex_cap');
    }
    if (!isset($armor['shield']) || !is_bool($armor['shield'])) {
        bad_request('Missing armor shield');
    }

    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

if ($method === 'POST' && $path === '/v1/combat/sessions') {
    $data = read_body();

    if (!isset($data['id']) || !is_string($data['id']) || $data['id'] === '') {
        bad_request('Missing or invalid session id');
    }
    $sessionId = $data['id'];

    if (!isset($data['combatants']) || !is_array($data['combatants']) || count($data['combatants']) === 0) {
        bad_request('Missing or invalid combatants');
    }

    $state = load_state();
    if (isset($state[$sessionId])) {
        bad_request('Session id already exists');
    }

    $combatants = [];
    $names = [];
    foreach ($data['combatants'] as $combatant) {
        if (!is_array($combatant) || !isset($combatant['name']) || !is_string($combatant['name']) || $combatant['name'] === '') {
            bad_request('Invalid combatant entry');
        }
        $name = $combatant['name'];
        if (isset($names[$name])) {
            bad_request('Duplicate combatant name');
        }
        $names[$name] = true;
        $dex = require_int($combatant['dex'] ?? null);
        $roll = require_int($combatant['roll'] ?? null);
        $combatants[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($combatants, static function (array $a, array $b): int {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(static fn (array $c): array => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $combatants);

    $state[$sessionId] = [
        'id' => $sessionId,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    save_state($state);

    send_json([
        'id' => $sessionId,
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $matches)) {
    $sessionId = urldecode($matches[1]);
    $state = load_state();
    if (!isset($state[$sessionId])) {
        send_json(['error' => 'Session not found'], 404);
    }

    $data = read_body();
    if (!isset($data['target']) || !is_string($data['target']) || $data['target'] === '') {
        bad_request('Missing or invalid target');
    }
    $target = $data['target'];

    $found = false;
    foreach ($state[$sessionId]['order'] as $combatant) {
        if ($combatant['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        bad_request('Unknown combatant');
    }

    if (!isset($data['condition']) || !is_string($data['condition'])) {
        bad_request('Missing or invalid condition');
    }

    $duration = require_positive_int($data['duration_rounds'] ?? null);

    $state[$sessionId]['conditions'][$target][] = [
        'condition' => $data['condition'],
        'remaining_rounds' => $duration,
    ];
    save_state($state);

    send_json([
        'target' => $target,
        'conditions' => $state[$sessionId]['conditions'][$target],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $matches)) {
    $sessionId = urldecode($matches[1]);
    $state = load_state();
    if (!isset($state[$sessionId])) {
        send_json(['error' => 'Session not found'], 404);
    }

    $session = &$state[$sessionId];
    $count = count($session['order']);
    if ($count === 0) {
        bad_request('Session has no combatants');
    }

    $session['turn_index'] += 1;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round'] += 1;
    }

    $active = $session['order'][$session['turn_index']];
    $activeName = $active['name'];

    if (isset($session['conditions'][$activeName])) {
        $remaining = [];
        foreach ($session['conditions'][$activeName] as $condition) {
            $condition['remaining_rounds'] -= 1;
            if ($condition['remaining_rounds'] > 0) {
                $remaining[] = $condition;
            }
        }
        $session['conditions'][$activeName] = $remaining;
    }

    save_state($state);

    $conditions = $session['conditions'];
    if (count($conditions) === 0) {
        $conditions = (object) [];
    }

    send_json([
        'id' => $sessionId,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $active,
        'conditions' => $conditions,
    ]);
}

send_json(['error' => 'Not found'], 404);

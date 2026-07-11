<?php
declare(strict_types=1);

function send_json(mixed $body, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($body, JSON_UNESCAPED_SLASHES);
    exit;
}

function bad_request(string $message = 'bad request'): never
{
    send_json(['error' => $message], 400);
}

function read_json_body(): array
{
    $raw = file_get_contents('php://input');
    $data = json_decode($raw === false ? '' : $raw, true);
    if (!is_array($data) || json_last_error() !== JSON_ERROR_NONE) {
        bad_request('invalid json');
    }
    return $data;
}

function require_int(mixed $value, string $field): int
{
    if (!is_int($value)) {
        bad_request("invalid $field");
    }
    return $value;
}

function require_int_range(mixed $value, string $field, int $min, int $max): int
{
    $number = require_int($value, $field);
    if ($number < $min || $number > $max) {
        bad_request("invalid $field");
    }
    return $number;
}

function require_post(string $method): void
{
    if ($method !== 'POST') {
        send_json(['error' => 'not found'], 404);
    }
}

function ability_modifier(int $score): int
{
    return (int)floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int
{
    return 2 + intdiv($level - 1, 4);
}

function monster_multiplier(int $count): float|int
{
    if ($count <= 1) {
        return 1;
    }
    if ($count === 2) {
        return 1.5;
    }
    if ($count <= 6) {
        return 2;
    }
    if ($count <= 10) {
        return 2.5;
    }
    if ($count <= 14) {
        return 3;
    }
    return 4;
}

function initiative_order(array $combatants, bool $uniqueNames = false): array
{
    $rows = [];
    $names = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) || !is_string($combatant['name'] ?? null)) {
            bad_request('invalid combatant');
        }
        if ($uniqueNames) {
            if ($combatant['name'] === '') {
                bad_request('invalid combatant');
            }
            if (isset($names[$combatant['name']])) {
                bad_request('duplicate combatant');
            }
            $names[$combatant['name']] = true;
        }
        $dex = require_int($combatant['dex'] ?? null, 'dex');
        $roll = require_int($combatant['roll'] ?? null, 'roll');
        $rows[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($rows, function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: strcmp($a['name'], $b['name']);
    });

    return $rows;
}

function public_order(array $rows): array
{
    return array_map(
        fn (array $row): array => ['name' => $row['name'], 'score' => $row['score']],
        $rows
    );
}

function state_file(): string
{
    $configured = getenv('COMBAT_STATE_FILE');
    if (is_string($configured) && $configured !== '') {
        return $configured;
    }
    $port = $_SERVER['SERVER_PORT'] ?? getenv('PORT') ?: 'default';
    return sys_get_temp_dir() . '/dnd-rest-php-combat-' . preg_replace('/[^A-Za-z0-9_.-]/', '_', (string)$port) . '.json';
}

function load_combat_state(): array
{
    $path = state_file();
    if (!is_file($path)) {
        return ['sessions' => []];
    }
    $raw = file_get_contents($path);
    $state = json_decode($raw === false ? '' : $raw, true);
    if (!is_array($state) || !isset($state['sessions']) || !is_array($state['sessions'])) {
        return ['sessions' => []];
    }
    return $state;
}

function save_combat_state(array $state): void
{
    file_put_contents(state_file(), json_encode($state, JSON_UNESCAPED_SLASHES), LOCK_EX);
}

function active_combatant(array $session): array
{
    $active = $session['order'][$session['turn_index']];
    return ['name' => $active['name'], 'score' => $active['score']];
}

function public_conditions(array $conditions): array|stdClass
{
    $result = [];
    foreach ($conditions as $target => $items) {
        if ($items !== []) {
            $result[$target] = $items;
        }
    }
    return $result === [] ? new stdClass() : $result;
}

function session_response(array $session, bool $includeConditions = false): array
{
    $response = [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => active_combatant($session),
    ];
    if ($includeConditions) {
        $response['conditions'] = public_conditions($session['conditions']);
    } else {
        $response['order'] = public_order($session['order']);
    }
    return $response;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

if ($method === 'GET' && $path === '/health') {
    send_json(['ok' => true]);
}

if ($path === '/v1/dice/stats') {
    require_post($method);
    $data = read_json_body();
    $expression = $data['expression'] ?? null;
    if (!is_string($expression)) {
        bad_request('invalid expression');
    }
    if (!preg_match('/^([0-9]+)d([0-9]+)([+-][0-9]+)?$/', $expression, $matches)) {
        bad_request('invalid expression');
    }

    $count = (int)$matches[1];
    $sides = (int)$matches[2];
    $modifier = isset($matches[3]) && $matches[3] !== '' ? (int)$matches[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        bad_request('invalid expression');
    }

    send_json([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $count + $modifier,
        'max' => ($count * $sides) + $modifier,
        'average' => ($count * ($sides + 1) / 2) + $modifier,
    ]);
}

if ($path === '/v1/checks/ability') {
    require_post($method);
    $data = read_json_body();
    $roll = require_int($data['roll'] ?? null, 'roll');
    $modifier = require_int($data['modifier'] ?? null, 'modifier');
    $dc = require_int($data['dc'] ?? null, 'dc');
    $total = $roll + $modifier;

    send_json([
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

if ($path === '/v1/encounters/adjusted-xp') {
    require_post($method);
    $data = read_json_body();
    $party = $data['party'] ?? null;
    $monsters = $data['monsters'] ?? null;
    if (!is_array($party) || count($party) === 0 || !is_array($monsters) || count($monsters) === 0) {
        bad_request('invalid encounter');
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
    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member)) {
            bad_request('invalid party');
        }
        $level = require_int($member['level'] ?? null, 'level');
        if (!isset($levelThresholds[$level])) {
            bad_request('unsupported level');
        }
        foreach ($thresholds as $name => $_) {
            $thresholds[$name] += $levelThresholds[$level][$name];
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster)) {
            bad_request('invalid monsters');
        }
        $cr = $monster['cr'] ?? null;
        if (!is_string($cr) || !array_key_exists($cr, $xpByCr)) {
            bad_request('unsupported cr');
        }
        $count = require_int($monster['count'] ?? null, 'count');
        if ($count <= 0) {
            bad_request('invalid count');
        }
        $baseXp += $xpByCr[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = monster_multiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $name) {
        if ($adjustedXp >= $thresholds[$name]) {
            $difficulty = $name;
        }
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

if ($path === '/v1/characters/ability-modifier') {
    require_post($method);
    $data = read_json_body();
    $score = require_int_range($data['score'] ?? null, 'score', 1, 30);

    send_json([
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

if ($path === '/v1/characters/proficiency') {
    require_post($method);
    $data = read_json_body();
    $level = require_int_range($data['level'] ?? null, 'level', 1, 20);

    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

if ($path === '/v1/characters/derived-stats') {
    require_post($method);
    $data = read_json_body();
    $level = require_int_range($data['level'] ?? null, 'level', 1, 20);

    $abilities = $data['abilities'] ?? null;
    if (!is_array($abilities)) {
        bad_request('invalid abilities');
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
        $score = require_int_range($abilities[$ability] ?? null, $ability, 1, 30);
        $modifiers[$ability] = ability_modifier($score);
    }

    $armor = $data['armor'] ?? null;
    if (!is_array($armor)) {
        bad_request('invalid armor');
    }
    $armorBase = require_int($armor['base'] ?? null, 'base');
    $dexCap = require_int($armor['dex_cap'] ?? null, 'dex_cap');
    $shield = $armor['shield'] ?? null;
    if (!is_bool($shield)) {
        bad_request('invalid shield');
    }

    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $level * (6 + $modifiers['con']),
        'armor_class' => $armorBase + min($modifiers['dex'], $dexCap) + ($shield ? 2 : 0),
        'modifiers' => $modifiers,
    ]);
}

if ($path === '/v1/initiative/order') {
    require_post($method);
    $data = read_json_body();
    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants)) {
        bad_request('invalid combatants');
    }

    send_json(['order' => public_order(initiative_order($combatants))]);
}

if ($path === '/v1/combat/sessions') {
    require_post($method);
    $data = read_json_body();
    $id = $data['id'] ?? null;
    $combatants = $data['combatants'] ?? null;
    if (!is_string($id) || $id === '') {
        bad_request('invalid id');
    }
    if (!is_array($combatants) || count($combatants) === 0) {
        bad_request('invalid combatants');
    }

    $state = load_combat_state();
    if (isset($state['sessions'][$id])) {
        bad_request('duplicate session');
    }

    $order = initiative_order($combatants, true);
    $conditions = [];
    foreach ($order as $combatant) {
        $conditions[$combatant['name']] = [];
    }

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => $conditions,
    ];
    $state['sessions'][$id] = $session;
    save_combat_state($state);

    send_json(session_response($session));
}

if (preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $matches)) {
    require_post($method);
    $id = urldecode($matches[1]);
    $data = read_json_body();
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $duration = $data['duration_rounds'] ?? null;
    if (!is_string($target) || $target === '') {
        bad_request('invalid target');
    }
    if (!is_string($condition) || $condition === '') {
        bad_request('invalid condition');
    }
    $duration = require_int($duration, 'duration_rounds');
    if ($duration <= 0) {
        bad_request('invalid duration_rounds');
    }

    $state = load_combat_state();
    if (!isset($state['sessions'][$id])) {
        send_json(['error' => 'not found'], 404);
    }
    $session = $state['sessions'][$id];
    if (!array_key_exists($target, $session['conditions'])) {
        bad_request('unknown target');
    }

    $session['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    $state['sessions'][$id] = $session;
    save_combat_state($state);

    send_json([
        'target' => $target,
        'conditions' => $session['conditions'][$target],
    ]);
}

if (preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $matches)) {
    require_post($method);
    $id = urldecode($matches[1]);
    $state = load_combat_state();
    if (!isset($state['sessions'][$id])) {
        send_json(['error' => 'not found'], 404);
    }

    $session = $state['sessions'][$id];
    $nextIndex = $session['turn_index'] + 1;
    if ($nextIndex >= count($session['order'])) {
        $nextIndex = 0;
        $session['round']++;
    }
    $session['turn_index'] = $nextIndex;

    $active = active_combatant($session);
    $activeName = $active['name'];
    $remaining = [];
    foreach ($session['conditions'][$activeName] as $item) {
        $nextRemaining = $item['remaining_rounds'] - 1;
        if ($nextRemaining > 0) {
            $remaining[] = [
                'condition' => $item['condition'],
                'remaining_rounds' => $nextRemaining,
            ];
        }
    }
    $session['conditions'][$activeName] = $remaining;

    $state['sessions'][$id] = $session;
    save_combat_state($state);

    send_json(session_response($session, true));
}

send_json(['error' => 'not found'], 404);

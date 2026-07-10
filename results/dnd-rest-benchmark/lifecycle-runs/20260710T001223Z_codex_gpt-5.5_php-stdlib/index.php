<?php
declare(strict_types=1);

const JSON_FLAGS = JSON_UNESCAPED_SLASHES;

function send_json(mixed $body, int $status = 200): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($body, JSON_FLAGS);
}

function bad_request(string $message = 'bad request'): void
{
    send_json(['error' => $message], 400);
}

function read_json_body(): ?array
{
    $raw = file_get_contents('php://input');
    $data = json_decode($raw === false ? '' : $raw, true);

    return is_array($data) ? $data : null;
}

function is_int_value(mixed $value): bool
{
    return is_int($value);
}

function monster_multiplier(int $count): int|float
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

function difficulty_for(int|float $adjustedXp, array $thresholds): string
{
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $name) {
        if ($adjustedXp >= $thresholds[$name]) {
            $difficulty = $name;
        }
    }
    return $difficulty;
}

function is_valid_ability_score(mixed $value): bool
{
    return is_int_value($value) && $value >= 1 && $value <= 30;
}

function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function is_valid_character_level(mixed $value): bool
{
    return is_int_value($value) && $value >= 1 && $value <= 20;
}

function proficiency_bonus(int $level): int
{
    return 2 + intdiv($level - 1, 4);
}

function combat_state_file(): string
{
    return getenv('DND_COMBAT_STATE_FILE') ?: (__DIR__ . '/.combat-state.json');
}

function load_combat_sessions(): array
{
    $path = combat_state_file();
    if (!is_file($path)) {
        return [];
    }

    $data = json_decode((string) file_get_contents($path), true);
    return is_array($data) ? $data : [];
}

function save_combat_sessions(array $sessions): void
{
    file_put_contents(combat_state_file(), json_encode($sessions, JSON_FLAGS));
}

function combat_public_state(array $session, bool $includeConditions = false): array
{
    $active = $session['order'][$session['turn_index']];
    $response = [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
    ];

    if ($includeConditions) {
        $conditions = [];
        foreach ($session['conditions'] as $name => $entries) {
            if ($entries !== []) {
                $conditions[$name] = $entries;
            }
        }
        $response['conditions'] = $conditions === [] ? new stdClass() : $conditions;
    } else {
        $response['order'] = array_map(
            static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
            $session['order']
        );
    }

    return $response;
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH) ?: '/';

if ($method === 'GET' && $path === '/health') {
    send_json(['ok' => true]);
    return;
}

if ($method !== 'POST') {
    send_json(['error' => 'not found'], 404);
    return;
}

$isAdvanceCombat = preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path) === 1;
$body = $isAdvanceCombat ? [] : read_json_body();
if ($body === null) {
    bad_request('invalid json');
    return;
}

if ($path === '/v1/characters/ability-modifier') {
    $score = $body['score'] ?? null;
    if (!is_valid_ability_score($score)) {
        bad_request('invalid score');
        return;
    }

    send_json([
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
    return;
}

if ($path === '/v1/characters/proficiency') {
    $level = $body['level'] ?? null;
    if (!is_valid_character_level($level)) {
        bad_request('invalid level');
        return;
    }

    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
    return;
}

if ($path === '/v1/characters/derived-stats') {
    $level = $body['level'] ?? null;
    $abilities = $body['abilities'] ?? null;
    $armor = $body['armor'] ?? null;
    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

    if (!is_valid_character_level($level) || !is_array($abilities) || !is_array($armor)) {
        bad_request('invalid character');
        return;
    }

    $modifiers = [];
    foreach ($abilityNames as $name) {
        $score = $abilities[$name] ?? null;
        if (!is_valid_ability_score($score)) {
            bad_request('invalid character');
            return;
        }
        $modifiers[$name] = ability_modifier($score);
    }

    $armorBase = $armor['base'] ?? null;
    $shield = $armor['shield'] ?? null;
    $dexCap = $armor['dex_cap'] ?? null;
    if (!is_int_value($armorBase) || !is_bool($shield) || !is_int_value($dexCap)) {
        bad_request('invalid character');
        return;
    }

    $shieldBonus = $shield ? 2 : 0;
    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $level * (6 + $modifiers['con']),
        'armor_class' => $armorBase + min($modifiers['dex'], $dexCap) + $shieldBonus,
        'modifiers' => $modifiers,
    ]);
    return;
}

if ($path === '/v1/dice/stats') {
    $expression = $body['expression'] ?? null;
    if (!is_string($expression)) {
        bad_request('invalid expression');
        return;
    }

    if (!preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $expression, $matches)) {
        bad_request('invalid expression');
        return;
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        bad_request('invalid expression');
        return;
    }

    $modifier = 0;
    if (isset($matches[3], $matches[4]) && $matches[3] !== '') {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier *= -1;
        }
    }

    send_json([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $count + $modifier,
        'max' => ($count * $sides) + $modifier,
        'average' => ($count * ($sides + 1) / 2) + $modifier,
    ]);
    return;
}

if ($path === '/v1/checks/ability') {
    foreach (['roll', 'modifier', 'dc'] as $field) {
        if (!array_key_exists($field, $body) || !is_int_value($body[$field])) {
            bad_request('invalid ability check');
            return;
        }
    }

    $total = $body['roll'] + $body['modifier'];
    $margin = $total - $body['dc'];
    send_json([
        'total' => $total,
        'success' => $total >= $body['dc'],
        'margin' => $margin,
    ]);
    return;
}

if ($path === '/v1/encounters/adjusted-xp') {
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

    $party = $body['party'] ?? null;
    $monsters = $body['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        bad_request('invalid encounter');
        return;
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !array_key_exists('level', $member) || !is_int_value($member['level']) || !isset($thresholdsByLevel[$member['level']])) {
            bad_request('invalid encounter');
            return;
        }

        foreach ($thresholds as $name => $_) {
            $thresholds[$name] += $thresholdsByLevel[$member['level']][$name];
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (
            !is_array($monster)
            || !array_key_exists('cr', $monster)
            || !is_string($monster['cr'])
            || !isset($xpByCr[$monster['cr']])
            || !array_key_exists('count', $monster)
            || !is_int_value($monster['count'])
            || $monster['count'] <= 0
        ) {
            bad_request('invalid encounter');
            return;
        }

        $baseXp += $xpByCr[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $multiplier = monster_multiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;
    send_json([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => difficulty_for($adjustedXp, $thresholds),
        'thresholds' => $thresholds,
    ]);
    return;
}

if ($path === '/v1/initiative/order') {
    $combatants = $body['combatants'] ?? null;
    if (!is_array($combatants)) {
        bad_request('invalid initiative');
        return;
    }

    $order = [];
    foreach ($combatants as $combatant) {
        if (
            !is_array($combatant)
            || !array_key_exists('name', $combatant)
            || !is_string($combatant['name'])
            || !array_key_exists('dex', $combatant)
            || !is_int_value($combatant['dex'])
            || !array_key_exists('roll', $combatant)
            || !is_int_value($combatant['roll'])
        ) {
            bad_request('invalid initiative');
            return;
        }

        $order[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    usort($order, static function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: strcmp($a['name'], $b['name']);
    });

    send_json([
        'order' => array_map(
            static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
            $order
        ),
    ]);
    return;
}

if ($path === '/v1/combat/sessions') {
    $id = $body['id'] ?? null;
    $combatants = $body['combatants'] ?? null;
    if (!is_string($id) || $id === '' || !is_array($combatants) || $combatants === []) {
        bad_request('invalid combat session');
        return;
    }

    $sessions = load_combat_sessions();
    if (isset($sessions[$id])) {
        bad_request('duplicate combat session');
        return;
    }

    $order = [];
    $conditions = [];
    foreach ($combatants as $combatant) {
        if (
            !is_array($combatant)
            || !array_key_exists('name', $combatant)
            || !is_string($combatant['name'])
            || $combatant['name'] === ''
            || !array_key_exists('dex', $combatant)
            || !is_int_value($combatant['dex'])
            || !array_key_exists('roll', $combatant)
            || !is_int_value($combatant['roll'])
        ) {
            bad_request('invalid combat session');
            return;
        }

        $order[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
        $conditions[$combatant['name']] = [];
    }

    usort($order, static function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: strcmp($a['name'], $b['name']);
    });

    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => $conditions,
    ];
    save_combat_sessions($sessions);

    send_json(combat_public_state($sessions[$id]));
    return;
}

if (preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $matches) === 1) {
    $id = rawurldecode($matches[1]);
    $target = $body['target'] ?? null;
    $condition = $body['condition'] ?? null;
    $duration = $body['duration_rounds'] ?? null;
    if (!is_string($target) || !is_string($condition) || !is_int_value($duration) || $duration <= 0) {
        bad_request('invalid condition');
        return;
    }

    $sessions = load_combat_sessions();
    if (!isset($sessions[$id])) {
        send_json(['error' => 'not found'], 404);
        return;
    }
    if (!array_key_exists($target, $sessions[$id]['conditions'])) {
        bad_request('unknown combatant');
        return;
    }

    $sessions[$id]['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    save_combat_sessions($sessions);

    send_json([
        'target' => $target,
        'conditions' => $sessions[$id]['conditions'][$target],
    ]);
    return;
}

if (preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $matches) === 1) {
    $id = rawurldecode($matches[1]);
    $sessions = load_combat_sessions();
    if (!isset($sessions[$id])) {
        send_json(['error' => 'not found'], 404);
        return;
    }

    $session = $sessions[$id];
    $session['turn_index']++;
    if ($session['turn_index'] >= count($session['order'])) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    $remaining = [];
    foreach ($session['conditions'][$activeName] as $condition) {
        $condition['remaining_rounds']--;
        if ($condition['remaining_rounds'] > 0) {
            $remaining[] = $condition;
        }
    }
    $session['conditions'][$activeName] = $remaining;

    $sessions[$id] = $session;
    save_combat_sessions($sessions);

    send_json(combat_public_state($session, true));
    return;
}

send_json(['error' => 'not found'], 404);

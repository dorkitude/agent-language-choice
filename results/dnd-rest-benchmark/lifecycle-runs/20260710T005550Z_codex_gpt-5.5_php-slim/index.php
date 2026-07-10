<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

function jsonResponse(Response $response, array $payload, int $status = 200): Response
{
    $response->getBody()->write(json_encode($payload));
    return $response
        ->withHeader('Content-Type', 'application/json')
        ->withStatus($status);
}

function badRequest(Response $response): Response
{
    return jsonResponse($response, ['error' => 'bad request'], 400);
}

function notFound(Response $response): Response
{
    return jsonResponse($response, ['error' => 'not found'], 404);
}

function requestJson(Request $request): ?array
{
    $raw = (string) $request->getBody();
    $data = json_decode($raw, true);

    return is_array($data) ? $data : null;
}

function isIntegerValue(mixed $value): bool
{
    return is_int($value);
}

function isValidAbilityScore(mixed $value): bool
{
    return isIntegerValue($value) && $value >= 1 && $value <= 30;
}

function isValidLevel(mixed $value): bool
{
    return isIntegerValue($value) && $value >= 1 && $value <= 20;
}

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    return intdiv($level - 1, 4) + 2;
}

function buildInitiativeOrder(array $rawCombatants): ?array
{
    $combatants = [];
    foreach ($rawCombatants as $combatant) {
        if (
            !is_array($combatant)
            || !isset($combatant['name'])
            || !is_string($combatant['name'])
            || !isset($combatant['dex'])
            || !isset($combatant['roll'])
            || !isIntegerValue($combatant['dex'])
            || !isIntegerValue($combatant['roll'])
        ) {
            return null;
        }

        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    usort($combatants, function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: strcmp($a['name'], $b['name']);
    });

    return array_map(
        fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
        $combatants
    );
}

function combatSessionResponse(array $session): array
{
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'order' => $session['order'],
    ];
}

function visibleConditions(array $session): array
{
    $conditions = [];
    foreach ($session['conditions'] as $name => $entries) {
        if ($entries !== []) {
            $conditions[$name] = $entries;
        }
    }

    return $conditions;
}

function combatSessionsPath(): string
{
    $token = getenv('COMBAT_STATE_TOKEN');
    if ($token !== false && $token !== '') {
        return sys_get_temp_dir() . '/dnd-combat-sessions-' . md5(__DIR__ . ':' . $token) . '.json';
    }

    $port = getenv('PORT') ?: 'default';
    return sys_get_temp_dir() . '/dnd-combat-sessions-' . md5(__DIR__ . ':' . $port) . '.json';
}

function loadCombatSessions(): array
{
    $path = combatSessionsPath();
    if (!is_file($path)) {
        return [];
    }

    $data = json_decode((string) file_get_contents($path), true);
    return is_array($data) ? $data : [];
}

function saveCombatSessions(array $sessions): void
{
    file_put_contents(combatSessionsPath(), json_encode($sessions), LOCK_EX);
}

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = requestJson($request);
    if ($data === null || !isset($data['expression']) || !is_string($data['expression'])) {
        return badRequest($response);
    }

    if (!preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $data['expression'], $matches)) {
        return badRequest($response);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        return badRequest($response);
    }

    $modifier = 0;
    if (isset($matches[3], $matches[4]) && $matches[3] !== '') {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier *= -1;
        }
    }

    $min = $count + $modifier;
    $max = ($count * $sides) + $modifier;
    $average = ($min + $max) / 2;

    return jsonResponse($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $data = requestJson($request);
    if (
        $data === null
        || !array_key_exists('roll', $data)
        || !array_key_exists('modifier', $data)
        || !array_key_exists('dc', $data)
        || !isIntegerValue($data['roll'])
        || !isIntegerValue($data['modifier'])
        || !isIntegerValue($data['dc'])
    ) {
        return badRequest($response);
    }

    $total = $data['roll'] + $data['modifier'];
    $margin = $total - $data['dc'];

    return jsonResponse($response, [
        'total' => $total,
        'success' => $total >= $data['dc'],
        'margin' => $margin,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $data = requestJson($request);
    if (
        $data === null
        || !isset($data['party'])
        || !isset($data['monsters'])
        || !is_array($data['party'])
        || !is_array($data['monsters'])
    ) {
        return badRequest($response);
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

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !isIntegerValue($member['level']) || $member['level'] !== 3) {
            return badRequest($response);
        }

        $thresholds['easy'] += 75;
        $thresholds['medium'] += 150;
        $thresholds['hard'] += 225;
        $thresholds['deadly'] += 400;
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        if (
            !is_array($monster)
            || !isset($monster['cr'])
            || !is_string($monster['cr'])
            || !array_key_exists($monster['cr'], $xpByCr)
            || !isset($monster['count'])
            || !isIntegerValue($monster['count'])
            || $monster['count'] <= 0
        ) {
            return badRequest($response);
        }

        $baseXp += $xpByCr[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    if ($monsterCount === 1) {
        $multiplier = 1;
    } elseif ($monsterCount === 2) {
        $multiplier = 1.5;
    } elseif ($monsterCount <= 6) {
        $multiplier = 2;
    } elseif ($monsterCount <= 10) {
        $multiplier = 2.5;
    } elseif ($monsterCount <= 14) {
        $multiplier = 3;
    } else {
        $multiplier = 4;
    }

    $adjustedXp = $baseXp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $level) {
        if ($adjustedXp >= $thresholds[$level]) {
            $difficulty = $level;
        }
    }

    return jsonResponse($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $data = requestJson($request);
    if ($data === null || !isset($data['combatants']) || !is_array($data['combatants'])) {
        return badRequest($response);
    }

    $order = buildInitiativeOrder($data['combatants']);
    if ($order === null) {
        return badRequest($response);
    }

    return jsonResponse($response, ['order' => $order]);
});

$app->post('/v1/combat/sessions', function (Request $request, Response $response) {
    $combatSessions = loadCombatSessions();
    $data = requestJson($request);
    if (
        $data === null
        || !isset($data['id'])
        || !is_string($data['id'])
        || $data['id'] === ''
        || array_key_exists($data['id'], $combatSessions)
        || !isset($data['combatants'])
        || !is_array($data['combatants'])
        || $data['combatants'] === []
    ) {
        return badRequest($response);
    }

    $order = buildInitiativeOrder($data['combatants']);
    if ($order === null) {
        return badRequest($response);
    }

    $conditions = [];
    foreach ($order as $combatant) {
        $conditions[$combatant['name']] = [];
    }

    $session = [
        'id' => $data['id'],
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => $conditions,
    ];
    $combatSessions[$data['id']] = $session;
    saveCombatSessions($combatSessions);

    return jsonResponse($response, combatSessionResponse($session));
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) {
    $combatSessions = loadCombatSessions();
    $id = $args['id'];
    if (!array_key_exists($id, $combatSessions)) {
        return notFound($response);
    }

    $data = requestJson($request);
    if (
        $data === null
        || !isset($data['target'])
        || !is_string($data['target'])
        || !array_key_exists($data['target'], $combatSessions[$id]['conditions'])
        || !isset($data['condition'])
        || !is_string($data['condition'])
        || !isset($data['duration_rounds'])
        || !isIntegerValue($data['duration_rounds'])
        || $data['duration_rounds'] <= 0
    ) {
        return badRequest($response);
    }

    $combatSessions[$id]['conditions'][$data['target']][] = [
        'condition' => $data['condition'],
        'remaining_rounds' => $data['duration_rounds'],
    ];
    saveCombatSessions($combatSessions);

    return jsonResponse($response, [
        'target' => $data['target'],
        'conditions' => $combatSessions[$id]['conditions'][$data['target']],
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) {
    $combatSessions = loadCombatSessions();
    $id = $args['id'];
    if (!array_key_exists($id, $combatSessions)) {
        return notFound($response);
    }

    $session = &$combatSessions[$id];
    $session['turn_index'] += 1;
    if ($session['turn_index'] >= count($session['order'])) {
        $session['turn_index'] = 0;
        $session['round'] += 1;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    $remaining = [];
    foreach ($session['conditions'][$activeName] as $condition) {
        $condition['remaining_rounds'] -= 1;
        if ($condition['remaining_rounds'] > 0) {
            $remaining[] = $condition;
        }
    }
    $session['conditions'][$activeName] = $remaining;
    unset($session);
    saveCombatSessions($combatSessions);

    $session = $combatSessions[$id];

    return jsonResponse($response, [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'conditions' => visibleConditions($session),
    ]);
});

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $data = requestJson($request);
    if ($data === null || !array_key_exists('score', $data) || !isValidAbilityScore($data['score'])) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'score' => $data['score'],
        'modifier' => abilityModifier($data['score']),
    ]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $data = requestJson($request);
    if ($data === null || !array_key_exists('level', $data) || !isValidLevel($data['level'])) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'level' => $data['level'],
        'proficiency_bonus' => proficiencyBonus($data['level']),
    ]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $data = requestJson($request);
    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

    if (
        $data === null
        || !array_key_exists('level', $data)
        || !isValidLevel($data['level'])
        || !array_key_exists('abilities', $data)
        || !is_array($data['abilities'])
        || !array_key_exists('armor', $data)
        || !is_array($data['armor'])
        || !array_key_exists('base', $data['armor'])
        || !isIntegerValue($data['armor']['base'])
        || !array_key_exists('shield', $data['armor'])
        || !is_bool($data['armor']['shield'])
        || !array_key_exists('dex_cap', $data['armor'])
        || !isIntegerValue($data['armor']['dex_cap'])
    ) {
        return badRequest($response);
    }

    $modifiers = [];
    foreach ($abilityNames as $abilityName) {
        if (
            !array_key_exists($abilityName, $data['abilities'])
            || !isValidAbilityScore($data['abilities'][$abilityName])
        ) {
            return badRequest($response);
        }

        $modifiers[$abilityName] = abilityModifier($data['abilities'][$abilityName]);
    }

    $shieldBonus = $data['armor']['shield'] ? 2 : 0;
    $armorClass = $data['armor']['base'] + min($modifiers['dex'], $data['armor']['dex_cap']) + $shieldBonus;

    return jsonResponse($response, [
        'level' => $data['level'],
        'proficiency_bonus' => proficiencyBonus($data['level']),
        'hp_max' => $data['level'] * (6 + $modifiers['con']),
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
});

$app->run();

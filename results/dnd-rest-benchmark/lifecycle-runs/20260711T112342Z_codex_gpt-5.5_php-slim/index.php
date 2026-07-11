<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();
$combatStateFile = __DIR__ . '/.combat_sessions.json';

function jsonResponse(Response $response, array $payload, int $status = 200): Response
{
    $response->getBody()->write(json_encode($payload));
    return $response
        ->withStatus($status)
        ->withHeader('Content-Type', 'application/json');
}

function badRequest(Response $response): Response
{
    return jsonResponse($response, ['error' => 'bad request'], 400);
}

function jsonBody(Request $request): ?array
{
    $decoded = json_decode((string) $request->getBody(), true);
    return is_array($decoded) ? $decoded : null;
}

function boundedInt(mixed $value, int $min, int $max): ?int
{
    if (!is_int($value) || $value < $min || $value > $max) {
        return null;
    }

    return $value;
}

function requiredInt(mixed $value): ?int
{
    return is_int($value) ? $value : null;
}

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    return intdiv($level - 1, 4) + 2;
}

function notFound(Response $response): Response
{
    return jsonResponse($response, ['error' => 'not found'], 404);
}

function loadCombatSessions(string $stateFile): array
{
    if (!is_file($stateFile)) {
        return [];
    }

    $contents = file_get_contents($stateFile);
    if ($contents === false || $contents === '') {
        return [];
    }

    $decoded = json_decode($contents, true);
    return is_array($decoded) ? $decoded : [];
}

function saveCombatSessions(string $stateFile, array $sessions): void
{
    file_put_contents($stateFile, json_encode($sessions), LOCK_EX);
}

function initiativeOrder(array $combatants): array
{
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

function combatSessionPayload(string $id, array $session): array
{
    return [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'order' => $session['order'],
    ];
}

function visibleConditions(array $conditions): array
{
    return array_filter($conditions, fn (array $items): bool => count($items) > 0);
}

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $body = jsonBody($request);
    $expression = $body['expression'] ?? null;

    if (!is_string($expression) || !preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $expression, $matches)) {
        return badRequest($response);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        return badRequest($response);
    }

    $modifier = isset($matches[4]) ? (int) $matches[4] : 0;
    if (($matches[3] ?? '') === '-') {
        $modifier = -$modifier;
    }

    $min = $count + $modifier;
    $max = ($count * $sides) + $modifier;

    return jsonResponse($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => ($min + $max) / 2,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $body = jsonBody($request);
    if ($body === null) {
        return badRequest($response);
    }

    $roll = (int) ($body['roll'] ?? 0);
    $modifier = (int) ($body['modifier'] ?? 0);
    $dc = (int) ($body['dc'] ?? 0);
    $total = $roll + $modifier;
    $margin = $total - $dc;

    return jsonResponse($response, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $margin,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $body = jsonBody($request);
    if ($body === null || !isset($body['party'], $body['monsters']) || !is_array($body['party']) || !is_array($body['monsters'])) {
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

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count'])) {
            return badRequest($response);
        }

        $cr = (string) $monster['cr'];
        $count = (int) $monster['count'];
        if ($count < 0 || !array_key_exists($cr, $xpByCr)) {
            return badRequest($response);
        }

        $baseXp += $xpByCr[$cr] * $count;
        $monsterCount += $count;
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || (int) ($member['level'] ?? 0) !== 3) {
            return badRequest($response);
        }

        $thresholds['easy'] += 75;
        $thresholds['medium'] += 150;
        $thresholds['hard'] += 225;
        $thresholds['deadly'] += 400;
    }

    $multiplier = match (true) {
        $monsterCount <= 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = $baseXp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $name) {
        if ($adjustedXp >= $thresholds[$name]) {
            $difficulty = $name;
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
    $body = jsonBody($request);
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return badRequest($response);
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (!is_array($combatant) || !isset($combatant['name'])) {
            return badRequest($response);
        }

        $combatants[] = [
            'name' => (string) $combatant['name'],
            'dex' => (int) ($combatant['dex'] ?? 0),
            'score' => (int) ($combatant['roll'] ?? 0) + (int) ($combatant['dex'] ?? 0),
        ];
    }

    return jsonResponse($response, ['order' => initiativeOrder($combatants)]);
});

$app->post('/v1/combat/sessions', function (Request $request, Response $response) use ($combatStateFile) {
    $body = jsonBody($request);
    $combatSessions = loadCombatSessions($combatStateFile);
    if (
        $body === null
        || !isset($body['id'], $body['combatants'])
        || !is_string($body['id'])
        || $body['id'] === ''
        || !is_array($body['combatants'])
        || count($body['combatants']) === 0
        || isset($combatSessions[$body['id']])
    ) {
        return badRequest($response);
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (
            !is_array($combatant)
            || !isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name'])
            || $combatant['name'] === ''
            || !is_int($combatant['dex'])
            || !is_int($combatant['roll'])
        ) {
            return badRequest($response);
        }

        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    $id = $body['id'];
    $order = initiativeOrder($combatants);
    $conditions = [];
    foreach ($order as $combatant) {
        $conditions[$combatant['name']] = [];
    }

    $combatSessions[$id] = [
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => $conditions,
    ];
    saveCombatSessions($combatStateFile, $combatSessions);

    return jsonResponse($response, combatSessionPayload($id, $combatSessions[$id]));
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) use ($combatStateFile) {
    $id = $args['id'];
    $combatSessions = loadCombatSessions($combatStateFile);
    if (!isset($combatSessions[$id])) {
        return notFound($response);
    }

    $body = jsonBody($request);
    if (
        $body === null
        || !isset($body['target'], $body['condition'], $body['duration_rounds'])
        || !is_string($body['target'])
        || !is_string($body['condition'])
        || !is_int($body['duration_rounds'])
        || $body['duration_rounds'] <= 0
        || !array_key_exists($body['target'], $combatSessions[$id]['conditions'])
    ) {
        return badRequest($response);
    }

    $target = $body['target'];
    $combatSessions[$id]['conditions'][$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];
    saveCombatSessions($combatStateFile, $combatSessions);

    return jsonResponse($response, [
        'target' => $target,
        'conditions' => $combatSessions[$id]['conditions'][$target],
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) use ($combatStateFile) {
    $id = $args['id'];
    $combatSessions = loadCombatSessions($combatStateFile);
    if (!isset($combatSessions[$id])) {
        return notFound($response);
    }

    $session = &$combatSessions[$id];
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
    unset($session);
    saveCombatSessions($combatStateFile, $combatSessions);
    $session = $combatSessions[$id];

    return jsonResponse($response, [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'conditions' => (object) visibleConditions($session['conditions']),
    ]);
});

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $body = jsonBody($request);
    if ($body === null || !array_key_exists('score', $body)) {
        return badRequest($response);
    }

    $score = boundedInt($body['score'], 1, 30);
    if ($score === null) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $body = jsonBody($request);
    if ($body === null || !array_key_exists('level', $body)) {
        return badRequest($response);
    }

    $level = boundedInt($body['level'], 1, 20);
    if ($level === null) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $body = jsonBody($request);
    if (
        $body === null
        || !array_key_exists('level', $body)
        || !isset($body['abilities'], $body['armor'])
        || !is_array($body['abilities'])
        || !is_array($body['armor'])
    ) {
        return badRequest($response);
    }

    $level = boundedInt($body['level'], 1, 20);
    if ($level === null) {
        return badRequest($response);
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
        if (!array_key_exists($ability, $body['abilities'])) {
            return badRequest($response);
        }

        $score = boundedInt($body['abilities'][$ability], 1, 30);
        if ($score === null) {
            return badRequest($response);
        }

        $modifiers[$ability] = abilityModifier($score);
    }

    if (
        !array_key_exists('base', $body['armor'])
        || !array_key_exists('shield', $body['armor'])
        || !array_key_exists('dex_cap', $body['armor'])
        || !is_bool($body['armor']['shield'])
    ) {
        return badRequest($response);
    }

    $armorBase = requiredInt($body['armor']['base']);
    $dexCap = requiredInt($body['armor']['dex_cap']);
    if ($armorBase === null || $dexCap === null) {
        return badRequest($response);
    }

    $shieldBonus = $body['armor']['shield'] ? 2 : 0;

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $level * (6 + $modifiers['con']),
        'armor_class' => $armorBase + min($modifiers['dex'], $dexCap) + $shieldBonus,
        'modifiers' => $modifiers,
    ]);
});

$app->run();
?>

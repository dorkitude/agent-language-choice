<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

function jsonBody(Request $request): ?array
{
    $content = $request->getContent();
    if ($content === '' || $content === false) {
        return null;
    }
    try {
        $data = json_decode($content, true, 512, JSON_THROW_ON_ERROR);
    } catch (\JsonException) {
        return null;
    }
    return is_array($data) ? $data : null;
}

function badRequest(string $message = 'bad request'): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

$storeFile = __DIR__ . '/combat_state.json';

function loadSessions(): array
{
    global $storeFile;
    if (!file_exists($storeFile)) {
        return [];
    }
    $content = file_get_contents($storeFile);
    if ($content === false || $content === '') {
        return [];
    }
    try {
        $data = json_decode($content, true, 512, JSON_THROW_ON_ERROR);
    } catch (\JsonException) {
        return [];
    }
    return is_array($data) ? $data : [];
}

function saveSessions(array $sessions): void
{
    global $storeFile;
    file_put_contents($storeFile, json_encode($sessions, JSON_THROW_ON_ERROR), LOCK_EX);
}

function sortCombatants(array $combatants): array
{
    usort($combatants, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });
    return $combatants;
}

function createCombatSession(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data) || !isset($data['id']) || !is_string($data['id']) || $data['id'] === '') {
        return badRequest('missing or invalid id');
    }
    $sessions = loadSessions();
    if (isset($sessions[$data['id']])) {
        return badRequest('session already exists');
    }
    if (!isset($data['combatants']) || !is_array($data['combatants']) || $data['combatants'] === []) {
        return badRequest('missing or empty combatants');
    }

    $raw = [];
    $names = [];
    foreach ($data['combatants'] as $combatant) {
        if (!is_array($combatant)
            || !isset($combatant['name']) || !is_string($combatant['name']) || $combatant['name'] === ''
            || !isset($combatant['dex']) || !is_int($combatant['dex'])
            || !isset($combatant['roll']) || !is_int($combatant['roll'])
        ) {
            return badRequest('invalid combatant');
        }
        $raw[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'roll' => $combatant['roll'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
        $names[] = $combatant['name'];
    }
    if (count(array_unique($names, SORT_STRING)) !== count($names)) {
        return badRequest('duplicate combatant names');
    }

    $sorted = sortCombatants($raw);
    $order = array_map(static fn (array $c): array => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $sorted);

    $sessions[$data['id']] = [
        'id' => $data['id'],
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'combatants' => $raw,
        'conditions' => [],
    ];
    saveSessions($sessions);

    return new JsonResponse([
        'id' => $data['id'],
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]);
}

function addCondition(Request $request, string $id): JsonResponse
{
    $sessions = loadSessions();
    if (!isset($sessions[$id])) {
        return new JsonResponse(['error' => 'not found'], 404);
    }

    $data = jsonBody($request);
    if (!is_array($data)
        || !isset($data['target']) || !is_string($data['target']) || $data['target'] === ''
        || !isset($data['condition']) || !is_string($data['condition']) || $data['condition'] === ''
        || !isset($data['duration_rounds']) || !is_int($data['duration_rounds']) || $data['duration_rounds'] <= 0
    ) {
        return badRequest('missing or invalid fields');
    }

    $session = &$sessions[$id];
    $validNames = array_map(static fn (array $c): string => $c['name'], $session['combatants']);
    if (!in_array($data['target'], $validNames, true)) {
        return badRequest('invalid target');
    }

    $session['conditions'][$data['target']][] = [
        'condition' => $data['condition'],
        'remaining_rounds' => $data['duration_rounds'],
    ];
    saveSessions($sessions);

    $list = [];
    foreach ($session['conditions'][$data['target']] as $cond) {
        $list[] = [
            'condition' => $cond['condition'],
            'remaining_rounds' => $cond['remaining_rounds'],
        ];
    }

    return new JsonResponse([
        'target' => $data['target'],
        'conditions' => $list,
    ]);
}

function advanceTurn(Request $request, string $id): JsonResponse
{
    $sessions = loadSessions();
    if (!isset($sessions[$id])) {
        return new JsonResponse(['error' => 'not found'], 404);
    }

    $session = &$sessions[$id];
    $count = count($session['order']);
    if ($count === 0) {
        return new JsonResponse(['error' => 'not found'], 404);
    }

    if ($session['turn_index'] === $count - 1) {
        $session['turn_index'] = 0;
        $session['round']++;
    } else {
        $session['turn_index']++;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    if (isset($session['conditions'][$activeName])) {
        $updated = [];
        foreach ($session['conditions'][$activeName] as $cond) {
            $remaining = $cond['remaining_rounds'] - 1;
            if ($remaining > 0) {
                $updated[] = [
                    'condition' => $cond['condition'],
                    'remaining_rounds' => $remaining,
                ];
            }
        }
        $session['conditions'][$activeName] = $updated;
    }
    saveSessions($sessions);

    $conditionsResponse = [];
    foreach ($session['conditions'] as $name => $list) {
        $formatted = [];
        foreach ($list as $cond) {
            $formatted[] = [
                'condition' => $cond['condition'],
                'remaining_rounds' => $cond['remaining_rounds'],
            ];
        }
        $conditionsResponse[$name] = $formatted;
    }

    return new JsonResponse([
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'conditions' => $conditionsResponse === [] ? (object) [] : $conditionsResponse,
    ]);
}

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2.0);
}

function proficiencyBonus(int $level): int
{
    return match (true) {
        $level <= 4 => 2,
        $level <= 8 => 3,
        $level <= 12 => 4,
        $level <= 16 => 5,
        default => 6,
    };
}

function health(): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function diceStats(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data) || !isset($data['expression']) || !is_string($data['expression'])) {
        return badRequest('missing expression');
    }

    if (!preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $data['expression'], $matches)) {
        return badRequest('invalid expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = 0;
    if (isset($matches[3])) {
        $modifierValue = (int) $matches[4];
        $modifier = $matches[3] === '+' ? $modifierValue : -$modifierValue;
    }

    if ($count <= 0 || $sides <= 0) {
        return badRequest('invalid expression');
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2.0;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function abilityCheck(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data)) {
        return badRequest('invalid body');
    }

    foreach (['roll', 'modifier', 'dc'] as $field) {
        if (!array_key_exists($field, $data) || !is_int($data[$field])) {
            return badRequest("missing or invalid $field");
        }
    }

    $roll = $data['roll'];
    $modifier = $data['modifier'];
    $dc = $data['dc'];

    $total = $roll + $modifier;

    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

function adjustedXp(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data)) {
        return badRequest('invalid body');
    }

    $xpTable = [
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

    $thresholdsTable = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    if (!isset($data['party']) || !is_array($data['party']) || $data['party'] === []) {
        return badRequest('missing or empty party');
    }
    if (!isset($data['monsters']) || !is_array($data['monsters']) || $data['monsters'] === []) {
        return badRequest('missing or empty monsters');
    }

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])) {
            return badRequest('invalid party member');
        }
        $level = $member['level'];
        if (!isset($thresholdsTable[$level])) {
            return badRequest('unsupported level');
        }
        foreach ($thresholdsTable[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr']) || !is_string($monster['cr']) || !isset($monster['count']) || !is_int($monster['count'])) {
            return badRequest('invalid monster');
        }
        if (!array_key_exists($monster['cr'], $xpTable)) {
            return badRequest('unsupported cr');
        }
        if ($monster['count'] <= 0) {
            return badRequest('invalid monster count');
        }
        $baseXp += $xpTable[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $multiplier = match (true) {
        $monsterCount === 1 => 1.0,
        $monsterCount === 2 => 1.5,
        $monsterCount >= 3 && $monsterCount <= 6 => 2.0,
        $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
        $monsterCount >= 11 && $monsterCount <= 14 => 3.0,
        default => 4.0,
    };

    $adjustedXp = (int) round($baseXp * $multiplier);

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

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

function initiativeOrder(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data) || !isset($data['combatants']) || !is_array($data['combatants'])) {
        return badRequest('missing combatants');
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        if (!is_array($combatant) || !isset($combatant['name']) || !is_string($combatant['name']) || !isset($combatant['dex']) || !is_int($combatant['dex']) || !isset($combatant['roll']) || !is_int($combatant['roll'])) {
            return badRequest('invalid combatant');
        }
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'roll' => $combatant['roll'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    usort($combatants, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(static fn (array $c): array => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $combatants);

    return new JsonResponse(['order' => $order]);
}

$routes = new RouteCollection();
$routes->add('health', new Route('/health', methods: ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', methods: ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', methods: ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', methods: ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', methods: ['POST']));
$routes->add('combat_create', new Route('/v1/combat/sessions', methods: ['POST']));
$routes->add('combat_conditions', new Route('/v1/combat/sessions/{id}/conditions', methods: ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', methods: ['POST']));
$routes->add('character_ability_modifier', new Route('/v1/characters/ability-modifier', methods: ['POST']));
$routes->add('character_proficiency', new Route('/v1/characters/proficiency', methods: ['POST']));
$routes->add('character_derived_stats', new Route('/v1/characters/derived-stats', methods: ['POST']));

$request = Request::createFromGlobals();
$context = (new RequestContext())->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->match($request->getPathInfo());
} catch (\Symfony\Component\Routing\Exception\ResourceNotFoundException) {
    (new JsonResponse(['error' => 'not found'], 404))->send();
    exit;
}

$routeName = $parameters['_route'];
$response = match ($routeName) {
    'health' => health(),
    'dice_stats' => diceStats($request),
    'ability_check' => abilityCheck($request),
    'adjusted_xp' => adjustedXp($request),
    'initiative_order' => initiativeOrder($request),
    'combat_create' => createCombatSession($request),
    'combat_conditions' => addCondition($request, $parameters['id']),
    'combat_advance' => advanceTurn($request, $parameters['id']),
    'character_ability_modifier' => characterAbilityModifier($request),
    'character_proficiency' => characterProficiency($request),
    'character_derived_stats' => characterDerivedStats($request),
    default => new JsonResponse(['error' => 'not found'], 404),
};

function characterAbilityModifier(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data) || !array_key_exists('score', $data) || !is_int($data['score'])) {
        return badRequest('missing or invalid score');
    }
    $score = $data['score'];
    if ($score < 1 || $score > 30) {
        return badRequest('score out of range');
    }
    return new JsonResponse([
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
}

function characterProficiency(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data) || !array_key_exists('level', $data) || !is_int($data['level'])) {
        return badRequest('missing or invalid level');
    }
    $level = $data['level'];
    if ($level < 1 || $level > 20) {
        return badRequest('level out of range');
    }
    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
}

function characterDerivedStats(Request $request): JsonResponse
{
    $data = jsonBody($request);
    if (!is_array($data)) {
        return badRequest('invalid body');
    }
    if (!array_key_exists('level', $data) || !is_int($data['level']) || $data['level'] < 1 || $data['level'] > 20) {
        return badRequest('missing or invalid level');
    }
    if (!isset($data['abilities']) || !is_array($data['abilities'])) {
        return badRequest('missing or invalid abilities');
    }
    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilityNames as $name) {
        if (!array_key_exists($name, $data['abilities']) || !is_int($data['abilities'][$name])) {
            return badRequest("missing or invalid ability $name");
        }
        $score = $data['abilities'][$name];
        if ($score < 1 || $score > 30) {
            return badRequest("ability score $name out of range");
        }
        $modifiers[$name] = abilityModifier($score);
    }

    if (!isset($data['armor']) || !is_array($data['armor'])) {
        return badRequest('missing or invalid armor');
    }
    $armor = $data['armor'];
    if (!array_key_exists('base', $armor) || !is_int($armor['base']) || $armor['base'] < 0) {
        return badRequest('missing or invalid armor base');
    }
    if (!array_key_exists('shield', $armor) || !is_bool($armor['shield'])) {
        return badRequest('missing or invalid armor shield');
    }
    if (!array_key_exists('dex_cap', $armor) || !is_int($armor['dex_cap']) || $armor['dex_cap'] < 0) {
        return badRequest('missing or invalid armor dex_cap');
    }

    $level = $data['level'];
    $conModifier = $modifiers['con'];
    $dexModifier = $modifiers['dex'];
    $shieldBonus = $armor['shield'] ? 2 : 0;
    $hpMax = $level * (6 + $conModifier);
    $armorClass = $armor['base'] + min($dexModifier, $armor['dex_cap']) + $shieldBonus;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

$response->send();

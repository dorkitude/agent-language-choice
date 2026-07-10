<?php

declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

function json_body(Request $request): ?array
{
    $decoded = json_decode($request->getContent(), true);

    return is_array($decoded) ? $decoded : null;
}

function bad_request(): JsonResponse
{
    return new JsonResponse(['error' => 'bad request'], 400);
}

function is_int_value(mixed $value): bool
{
    return is_int($value);
}

function valid_ability_score(mixed $value): bool
{
    return is_int_value($value) && $value >= 1 && $value <= 30;
}

function ability_modifier_value(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function valid_level(mixed $value): bool
{
    return is_int_value($value) && $value >= 1 && $value <= 20;
}

function proficiency_bonus_value(int $level): int
{
    return 2 + intdiv($level - 1, 4);
}

function dice_stats(Request $request): JsonResponse
{
    $body = json_body($request);
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        return bad_request();
    }

    if (!preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $body['expression'], $matches)) {
        return bad_request();
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    if ($count <= 0 || $sides <= 0) {
        return bad_request();
    }

    $modifier = 0;
    if (isset($matches[4]) && $matches[4] !== '') {
        $modifier = (int) $matches[4];
        if ($matches[3] === '-') {
            $modifier = -$modifier;
        }
    }

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $count + $modifier,
        'max' => ($count * $sides) + $modifier,
        'average' => ($count * ($sides + 1) / 2) + $modifier,
    ]);
}

function ability_check(Request $request): JsonResponse
{
    $body = json_body($request);
    if (
        $body === null
        || !array_key_exists('roll', $body)
        || !array_key_exists('modifier', $body)
        || !array_key_exists('dc', $body)
        || !is_int_value($body['roll'])
        || !is_int_value($body['modifier'])
        || !is_int_value($body['dc'])
    ) {
        return bad_request();
    }

    $total = $body['roll'] + $body['modifier'];
    $margin = $total - $body['dc'];

    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $body['dc'],
        'margin' => $margin,
    ]);
}

function adjusted_xp(Request $request): JsonResponse
{
    $body = json_body($request);
    if (
        $body === null
        || !isset($body['party'])
        || !isset($body['monsters'])
        || !is_array($body['party'])
        || !is_array($body['monsters'])
    ) {
        return bad_request();
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

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int_value($member['level']) || !isset($thresholdsByLevel[$member['level']])) {
            return bad_request();
        }

        foreach ($thresholds as $name => $_) {
            $thresholds[$name] += $thresholdsByLevel[$member['level']][$name];
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (
            !is_array($monster)
            || !isset($monster['cr'])
            || !isset($monster['count'])
            || !is_string($monster['cr'])
            || !is_int_value($monster['count'])
            || $monster['count'] <= 0
            || !isset($xpByCr[$monster['cr']])
        ) {
            return bad_request();
        }

        $baseXp += $xpByCr[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $multiplier = match (true) {
        $monsterCount <= 0 => 0,
        $monsterCount === 1 => 1,
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

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

function initiative_order(Request $request): JsonResponse
{
    $body = json_body($request);
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return bad_request();
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (
            !is_array($combatant)
            || !isset($combatant['name'])
            || !isset($combatant['dex'])
            || !isset($combatant['roll'])
            || !is_string($combatant['name'])
            || !is_int_value($combatant['dex'])
            || !is_int_value($combatant['roll'])
        ) {
            return bad_request();
        }

        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    usort($combatants, static function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: ($a['name'] <=> $b['name']);
    });

    $order = array_map(
        static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
        $combatants
    );

    return new JsonResponse(['order' => $order]);
}

function combat_store_path(): string
{
    $port = getenv('PORT') ?: 'default';

    return sys_get_temp_dir() . '/dnd-combat-sessions-' . preg_replace('/[^A-Za-z0-9_.-]/', '_', $port) . '.json';
}

function load_combat_sessions(): array
{
    $path = combat_store_path();
    if (!is_file($path)) {
        return [];
    }

    $decoded = json_decode((string) file_get_contents($path), true);

    return is_array($decoded) ? $decoded : [];
}

function save_combat_sessions(array $sessions): void
{
    file_put_contents(combat_store_path(), json_encode($sessions, JSON_THROW_ON_ERROR));
}

function sorted_combat_order(array $combatants): ?array
{
    $order = [];
    foreach ($combatants as $combatant) {
        if (
            !is_array($combatant)
            || !isset($combatant['name'])
            || !isset($combatant['dex'])
            || !isset($combatant['roll'])
            || !is_string($combatant['name'])
            || !is_int_value($combatant['dex'])
            || !is_int_value($combatant['roll'])
        ) {
            return null;
        }

        $order[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
        ];
    }

    if ($order === []) {
        return null;
    }

    usort($order, static function (array $a, array $b): int {
        return ($b['score'] <=> $a['score'])
            ?: ($b['dex'] <=> $a['dex'])
            ?: ($a['name'] <=> $b['name']);
    });

    return array_map(
        static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']],
        $order
    );
}

function combat_session_response(array $session, bool $includeConditions = false): array
{
    $response = [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
    ];

    if ($includeConditions) {
        $conditions = array_filter(
            $session['conditions'],
            static fn (array $conditions): bool => $conditions !== []
        );
        foreach (($session['condition_targets'] ?? []) as $target => $_) {
            if (array_key_exists($target, $session['conditions']) && !array_key_exists($target, $conditions)) {
                $conditions[$target] = [];
            }
        }
        $response['conditions'] = $conditions === [] ? new stdClass() : $conditions;
    } else {
        $response['order'] = $session['order'];
    }

    return $response;
}

function combat_create_session(Request $request): JsonResponse
{
    $body = json_body($request);
    if (
        $body === null
        || !isset($body['id'])
        || !is_string($body['id'])
        || !isset($body['combatants'])
        || !is_array($body['combatants'])
    ) {
        return bad_request();
    }

    $sessions = load_combat_sessions();
    if (isset($sessions[$body['id']])) {
        return bad_request();
    }

    $order = sorted_combat_order($body['combatants']);
    if ($order === null) {
        return bad_request();
    }

    $conditions = [];
    foreach ($order as $combatant) {
        $conditions[$combatant['name']] = [];
    }

    $session = [
        'id' => $body['id'],
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => $conditions,
        'condition_targets' => [],
    ];
    $sessions[$body['id']] = $session;
    save_combat_sessions($sessions);

    return new JsonResponse(combat_session_response($session));
}

function combat_add_condition(Request $request): JsonResponse
{
    $sessionId = $request->attributes->get('id');
    $body = json_body($request);
    if (
        !is_string($sessionId)
        || $body === null
        || !isset($body['target'])
        || !isset($body['condition'])
        || !isset($body['duration_rounds'])
        || !is_string($body['target'])
        || !is_string($body['condition'])
        || !is_int_value($body['duration_rounds'])
        || $body['duration_rounds'] <= 0
    ) {
        return bad_request();
    }

    $sessions = load_combat_sessions();
    if (!isset($sessions[$sessionId])) {
        return new JsonResponse(['error' => 'not found'], 404);
    }

    if (!array_key_exists($body['target'], $sessions[$sessionId]['conditions'])) {
        return bad_request();
    }

    $sessions[$sessionId]['conditions'][$body['target']][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];
    $sessions[$sessionId]['condition_targets'][$body['target']] = true;
    save_combat_sessions($sessions);

    return new JsonResponse([
        'target' => $body['target'],
        'conditions' => $sessions[$sessionId]['conditions'][$body['target']],
    ]);
}

function combat_advance(Request $request): JsonResponse
{
    $sessionId = $request->attributes->get('id');
    if (!is_string($sessionId)) {
        return bad_request();
    }

    $sessions = load_combat_sessions();
    if (!isset($sessions[$sessionId])) {
        return new JsonResponse(['error' => 'not found'], 404);
    }

    $session = $sessions[$sessionId];
    $session['turn_index']++;
    if ($session['turn_index'] >= count($session['order'])) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    $remainingConditions = [];
    foreach ($session['conditions'][$activeName] ?? [] as $condition) {
        $condition['remaining_rounds']--;
        if ($condition['remaining_rounds'] > 0) {
            $remainingConditions[] = $condition;
        }
    }
    $session['conditions'][$activeName] = $remainingConditions;

    $sessions[$sessionId] = $session;
    save_combat_sessions($sessions);

    return new JsonResponse(combat_session_response($session, true));
}

function character_ability_modifier(Request $request): JsonResponse
{
    $body = json_body($request);
    if ($body === null || !array_key_exists('score', $body) || !valid_ability_score($body['score'])) {
        return bad_request();
    }

    return new JsonResponse([
        'score' => $body['score'],
        'modifier' => ability_modifier_value($body['score']),
    ]);
}

function character_proficiency(Request $request): JsonResponse
{
    $body = json_body($request);
    if ($body === null || !array_key_exists('level', $body) || !valid_level($body['level'])) {
        return bad_request();
    }

    return new JsonResponse([
        'level' => $body['level'],
        'proficiency_bonus' => proficiency_bonus_value($body['level']),
    ]);
}

function character_derived_stats(Request $request): JsonResponse
{
    $body = json_body($request);
    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

    if (
        $body === null
        || !array_key_exists('level', $body)
        || !valid_level($body['level'])
        || !array_key_exists('abilities', $body)
        || !is_array($body['abilities'])
        || !array_key_exists('armor', $body)
        || !is_array($body['armor'])
        || !array_key_exists('base', $body['armor'])
        || !array_key_exists('shield', $body['armor'])
        || !array_key_exists('dex_cap', $body['armor'])
        || !is_int_value($body['armor']['base'])
        || !is_bool($body['armor']['shield'])
        || !is_int_value($body['armor']['dex_cap'])
    ) {
        return bad_request();
    }

    $modifiers = [];
    foreach ($abilityNames as $abilityName) {
        if (!array_key_exists($abilityName, $body['abilities']) || !valid_ability_score($body['abilities'][$abilityName])) {
            return bad_request();
        }

        $modifiers[$abilityName] = ability_modifier_value($body['abilities'][$abilityName]);
    }

    $level = $body['level'];
    $shieldBonus = $body['armor']['shield'] ? 2 : 0;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus_value($level),
        'hp_max' => $level * (6 + $modifiers['con']),
        'armor_class' => $body['armor']['base'] + min($modifiers['dex'], $body['armor']['dex_cap']) + $shieldBonus,
        'modifiers' => $modifiers,
    ]);
}

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_controller' => static fn (Request $request): JsonResponse => new JsonResponse(['ok' => true])], [], [], '', [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => 'dice_stats'], [], [], '', [], ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_controller' => 'ability_check'], [], [], '', [], ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => 'adjusted_xp'], [], [], '', [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_controller' => 'initiative_order'], [], [], '', [], ['POST']));
$routes->add('character_ability_modifier', new Route('/v1/characters/ability-modifier', ['_controller' => 'character_ability_modifier'], [], [], '', [], ['POST']));
$routes->add('character_proficiency', new Route('/v1/characters/proficiency', ['_controller' => 'character_proficiency'], [], [], '', [], ['POST']));
$routes->add('character_derived_stats', new Route('/v1/characters/derived-stats', ['_controller' => 'character_derived_stats'], [], [], '', [], ['POST']));
$routes->add('combat_create_session', new Route('/v1/combat/sessions', ['_controller' => 'combat_create_session'], [], [], '', [], ['POST']));
$routes->add('combat_add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['_controller' => 'combat_add_condition'], [], [], '', [], ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['_controller' => 'combat_advance'], [], [], '', [], ['POST']));

$request = Request::createFromGlobals();
$context = (new RequestContext())->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->match($request->getPathInfo());
    $controller = $parameters['_controller'];
    $request->attributes->add($parameters);
    $response = $controller($request);
} catch (ResourceNotFoundException) {
    $response = new JsonResponse(['error' => 'not found'], 404);
} catch (MethodNotAllowedException) {
    $response = new JsonResponse(['error' => 'method not allowed'], 405);
}

$response->send();

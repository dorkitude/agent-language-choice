<?php
require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;
use Symfony\Component\Routing\Matcher\UrlMatcher;

/* ------------------------------------------------------------------ */
/* Helpers                                                            */
/* ------------------------------------------------------------------ */

function json_body(Request $request): ?array
{
    $raw = $request->getContent();
    if ($raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int
{
    return match (true) {
        $level >= 17 => 6,
        $level >= 13 => 5,
        $level >= 9 => 4,
        $level >= 5 => 3,
        default => 2,
    };
}

/* ------------------------------------------------------------------ */
/* Endpoint handlers                                                  */
/* ------------------------------------------------------------------ */

function health(Request $request): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function dice_stats(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $expr = $data['expression'] ?? '';
    if (!is_string($expr) || !preg_match('/^([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?$/', $expr, $m)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    if ($count <= 0 || $sides <= 0) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }
    $modifier = 0;
    if (isset($m[3])) {
        $mag = (int) $m[4];
        $modifier = $m[3] === '-' ? -$mag : $mag;
    }
    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function ability_check(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $roll = (int) ($data['roll'] ?? 0);
    $modifier = (int) ($data['modifier'] ?? 0);
    $dc = (int) ($data['dc'] ?? 0);
    $total = $roll + $modifier;

    return new JsonResponse([
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
}

function adjusted_xp(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }

    $xpTable = [
        '0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100,
        '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800,
    ];
    $levelThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach (($data['monsters'] ?? []) as $mon) {
        $cr = (string) ($mon['cr'] ?? '');
        if (!array_key_exists($cr, $xpTable)) {
            return new JsonResponse(['error' => 'unknown cr'], 400);
        }
        $cnt = (int) ($mon['count'] ?? 0);
        $baseXp += $xpTable[$cr] * $cnt;
        $monsterCount += $cnt;
    }

    $multiplier = match (true) {
        $monsterCount >= 15 => 4,
        $monsterCount >= 11 => 3,
        $monsterCount >= 7 => 2.5,
        $monsterCount >= 3 => 2,
        $monsterCount === 2 => 1.5,
        $monsterCount === 1 => 1,
        default => 1,
    };
    $adjustedXp = $baseXp * $multiplier;

    $easy = $medium = $hard = $deadly = 0;
    foreach (($data['party'] ?? []) as $member) {
        $level = (int) ($member['level'] ?? 0);
        $th = $levelThresholds[$level] ?? ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
        $easy += $th['easy'];
        $medium += $th['medium'];
        $hard += $th['hard'];
        $deadly += $th['deadly'];
    }

    if ($adjustedXp >= $deadly) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $hard) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $medium) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $easy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => $easy,
            'medium' => $medium,
            'hard' => $hard,
            'deadly' => $deadly,
        ],
    ]);
}

function character_ability_modifier(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $score = $data['score'] ?? null;
    if (!is_int($score) || $score < 1 || $score > 30) {
        return new JsonResponse(['error' => 'invalid score'], 400);
    }

    return new JsonResponse([
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

function character_proficiency(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $level = $data['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

function character_derived_stats(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $level = $data['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }

    $abilities = $data['abilities'] ?? null;
    if (!is_array($abilities)) {
        return new JsonResponse(['error' => 'invalid abilities'], 400);
    }
    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilityNames as $name) {
        $val = $abilities[$name] ?? null;
        if (!is_int($val) || $val < 1 || $val > 30) {
            return new JsonResponse(['error' => 'invalid ability: ' . $name], 400);
        }
        $modifiers[$name] = ability_modifier($val);
    }

    $armor = $data['armor'] ?? null;
    if (!is_array($armor)) {
        return new JsonResponse(['error' => 'invalid armor'], 400);
    }
    $base = $armor['base'] ?? null;
    if (!is_int($base)) {
        return new JsonResponse(['error' => 'invalid armor base'], 400);
    }
    $dexCap = $armor['dex_cap'] ?? null;
    if (!is_int($dexCap)) {
        return new JsonResponse(['error' => 'invalid armor dex_cap'], 400);
    }
    $shieldBonus = !empty($armor['shield']) ? 2 : 0;

    $hpMax = $level * (6 + $modifiers['con']);
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

function initiative_order(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $rows = [];
    foreach (($data['combatants'] ?? []) as $c) {
        $name = (string) ($c['name'] ?? '');
        $dex = (int) ($c['dex'] ?? 0);
        $roll = (int) ($c['roll'] ?? 0);
        $rows[] = ['name' => $name, 'dex' => $dex, 'score' => $roll + $dex];
    }
    usort($rows, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });
    $order = array_map(
        static fn (array $r): array => ['name' => $r['name'], 'score' => $r['score']],
        $rows
    );

    return new JsonResponse(['order' => $order]);
}

/* ------------------------------------------------------------------ */
/* Combat session state (persisted across requests via a per-process */
/* file; PHP's built-in server re-executes the router per request).   */
/* ------------------------------------------------------------------ */

function combat_sessions_file(): string
{
    return __DIR__ . '/.combat_sessions_' . getmypid() . '.json';
}

function combat_load_sessions(): array
{
    $file = combat_sessions_file();
    if (!is_file($file)) {
        return [];
    }
    $raw = file_get_contents($file);
    if ($raw === '' || $raw === false) {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function combat_save_sessions(array $sessions): void
{
    file_put_contents(combat_sessions_file(), json_encode($sessions), LOCK_EX);
}

function combat_conditions_view(array $conditions): array|object
{
    $out = [];
    foreach ($conditions as $name => $list) {
        if (is_array($list) && count($list) > 0) {
            $out[$name] = array_values($list);
        }
    }
    // PHP encodes an empty array as JSON `[]`; the spec models conditions as
    // an object (combatant -> list), so emit `{}` when there are none.
    return $out === [] ? new \stdClass() : $out;
}

function combat_session_view(array $session): JsonResponse
{
    return new JsonResponse([
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']] ?? null,
        'order' => $session['order'],
    ]);
}

function combat_advance_view(array $session): JsonResponse
{
    return new JsonResponse([
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']] ?? null,
        'conditions' => combat_conditions_view($session['conditions']),
    ]);
}

function combat_create_session(Request $request): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $id = $data['id'] ?? null;
    if (!is_string($id) || $id === '') {
        return new JsonResponse(['error' => 'invalid id'], 400);
    }
    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants) || count($combatants) === 0) {
        return new JsonResponse(['error' => 'invalid combatants'], 400);
    }
    $rows = [];
    foreach ($combatants as $c) {
        if (!is_array($c)) {
            return new JsonResponse(['error' => 'invalid combatant'], 400);
        }
        $name = $c['name'] ?? null;
        $dex = $c['dex'] ?? null;
        $roll = $c['roll'] ?? null;
        if (!is_string($name) || $name === '') {
            return new JsonResponse(['error' => 'invalid combatant name'], 400);
        }
        if (!is_int($dex)) {
            return new JsonResponse(['error' => 'invalid combatant dex'], 400);
        }
        if (!is_int($roll)) {
            return new JsonResponse(['error' => 'invalid combatant roll'], 400);
        }
        $rows[] = ['name' => $name, 'dex' => $dex, 'score' => $roll + $dex];
    }
    usort($rows, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });
    $order = array_map(
        static fn (array $r): array => ['name' => $r['name'], 'score' => $r['score']],
        $rows
    );

    $sessions = combat_load_sessions();
    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    combat_save_sessions($sessions);
    return combat_session_view($sessions[$id]);
}

function combat_add_condition(Request $request, string $sessionId): JsonResponse
{
    $data = json_body($request);
    if ($data === null) {
        return new JsonResponse(['error' => 'invalid json'], 400);
    }
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $duration = $data['duration_rounds'] ?? null;
    if (!is_string($target) || $target === '') {
        return new JsonResponse(['error' => 'invalid target'], 400);
    }
    if (!is_string($condition) || $condition === '') {
        return new JsonResponse(['error' => 'invalid condition'], 400);
    }
    if (!is_int($duration) || $duration <= 0) {
        return new JsonResponse(['error' => 'invalid duration_rounds'], 400);
    }

    $sessions = combat_load_sessions();
    if (!isset($sessions[$sessionId])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }
    $found = false;
    foreach ($sessions[$sessionId]['order'] as $c) {
        if ($c['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        return new JsonResponse(['error' => 'unknown target'], 400);
    }
    if (!isset($sessions[$sessionId]['conditions'][$target])) {
        $sessions[$sessionId]['conditions'][$target] = [];
    }
    $sessions[$sessionId]['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    combat_save_sessions($sessions);
    return new JsonResponse([
        'target' => $target,
        'conditions' => $sessions[$sessionId]['conditions'][$target],
    ]);
}

function combat_advance(Request $request, string $sessionId): JsonResponse
{
    $sessions = combat_load_sessions();
    if (!isset($sessions[$sessionId])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }
    $session = &$sessions[$sessionId];
    $count = count($session['order']);
    $next = $session['turn_index'] + 1;
    if ($next >= $count) {
        $next = 0;
        $session['round']++;
    }
    $session['turn_index'] = $next;
    $activeName = $session['order'][$next]['name'];
    if (isset($session['conditions'][$activeName])) {
        foreach ($session['conditions'][$activeName] as &$cond) {
            $cond['remaining_rounds']--;
        }
        unset($cond);
        $session['conditions'][$activeName] = array_values(array_filter(
            $session['conditions'][$activeName],
            static fn (array $c): bool => $c['remaining_rounds'] > 0
        ));
        if (count($session['conditions'][$activeName]) === 0) {
            unset($session['conditions'][$activeName]);
        }
    }
    combat_save_sessions($sessions);
    return combat_advance_view($session);
}

/* ------------------------------------------------------------------ */
/* Routing & dispatch                                                 */
/* ------------------------------------------------------------------ */

$request = Request::createFromGlobals();
$context = new RequestContext();
$context->fromRequest($request);

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_handler' => 'health'], methods: ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_handler' => 'dice_stats'], methods: ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_handler' => 'ability_check'], methods: ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_handler' => 'adjusted_xp'], methods: ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_handler' => 'initiative_order'], methods: ['POST']));
$routes->add('char_ability_modifier', new Route('/v1/characters/ability-modifier', ['_handler' => 'character_ability_modifier'], methods: ['POST']));
$routes->add('char_proficiency', new Route('/v1/characters/proficiency', ['_handler' => 'character_proficiency'], methods: ['POST']));
$routes->add('char_derived_stats', new Route('/v1/characters/derived-stats', ['_handler' => 'character_derived_stats'], methods: ['POST']));
$routes->add('combat_create_session', new Route('/v1/combat/sessions', ['_handler' => 'combat_create_session'], methods: ['POST']));
$routes->add('combat_add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['_handler' => 'combat_add_condition'], methods: ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['_handler' => 'combat_advance'], methods: ['POST']));

$handlers = [
    'health' => 'health',
    'dice_stats' => 'dice_stats',
    'ability_check' => 'ability_check',
    'adjusted_xp' => 'adjusted_xp',
    'initiative_order' => 'initiative_order',
    'character_ability_modifier' => 'character_ability_modifier',
    'character_proficiency' => 'character_proficiency',
    'character_derived_stats' => 'character_derived_stats',
    'combat_create_session' => 'combat_create_session',
    'combat_add_condition' => 'combat_add_condition',
    'combat_advance' => 'combat_advance',
];

$matcher = new UrlMatcher($routes, $context);
try {
    $match = $matcher->match($request->getPathInfo());
} catch (MethodNotAllowedException $e) {
    (new JsonResponse(['error' => 'method not allowed'], 405))->send();
    return;
} catch (ResourceNotFoundException $e) {
    (new JsonResponse(['error' => 'not found'], 404))->send();
    return;
}

$handler = $handlers[$match['_handler']] ?? null;
if ($handler === null) {
    (new JsonResponse(['error' => 'not found'], 404))->send();
    return;
}
$params = [];
foreach ($match as $k => $v) {
    if (is_string($k) && $k !== '' && $k[0] !== '_') {
        $params[] = $v;
    }
}
$handler($request, ...$params)->send();

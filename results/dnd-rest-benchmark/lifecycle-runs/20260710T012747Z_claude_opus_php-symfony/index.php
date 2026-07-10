<?php

require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

// ---------------------------------------------------------------------------
// Data tables
// ---------------------------------------------------------------------------

const CR_XP = [
    '0'   => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1'   => 200,
    '2'   => 450,
    '3'   => 700,
    '4'   => 1100,
    '5'   => 1800,
];

// Level => [easy, medium, hard, deadly]
const LEVEL_THRESHOLDS = [
    3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function json_error(string $message, int $status = 400): JsonResponse
{
    return new JsonResponse(['error' => $message], $status);
}

/**
 * Decode the JSON body of a request into an associative array.
 * Returns null when the body is missing or not a JSON object.
 */
function decode_body(Request $request): ?array
{
    $raw = $request->getContent();
    if ($raw === '') {
        return null;
    }
    $data = json_decode($raw, true);
    if (!is_array($data)) {
        return null;
    }
    return $data;
}

/** Monster-count encounter multiplier. */
function encounter_multiplier(int $count): float
{
    if ($count <= 0) {
        return 1.0;
    }
    if ($count === 1) {
        return 1.0;
    }
    if ($count === 2) {
        return 1.5;
    }
    if ($count <= 6) {
        return 2.0;
    }
    if ($count <= 10) {
        return 2.5;
    }
    if ($count <= 14) {
        return 3.0;
    }
    return 4.0;
}

/** Normalize a numeric value to int if it is integral, else keep as float. */
function num(float $value): int|float
{
    return ($value == (int) $value) ? (int) $value : $value;
}

// ---------------------------------------------------------------------------
// Handlers
// ---------------------------------------------------------------------------

function handle_health(): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function handle_dice_stats(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        return json_error('invalid expression');
    }

    $expr = trim($body['expression']);
    // <count>d<sides>[+<modifier>|-<modifier>]
    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expr, $m)) {
        return json_error('invalid expression');
    }

    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3]) && $m[3] !== '' ? (int) $m[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return json_error('invalid expression');
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2.0;

    return new JsonResponse([
        'dice_count' => $count,
        'sides'      => $sides,
        'modifier'   => $modifier,
        'min'        => $min,
        'max'        => $max,
        'average'    => num($average),
    ]);
}

function handle_ability_check(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null
        || !isset($body['roll'], $body['modifier'], $body['dc'])
        || !is_numeric($body['roll']) || !is_numeric($body['modifier']) || !is_numeric($body['dc'])) {
        return json_error('invalid check');
    }

    $roll = (int) $body['roll'];
    $modifier = (int) $body['modifier'];
    $dc = (int) $body['dc'];

    $total = $roll + $modifier;
    $margin = $total - $dc;

    return new JsonResponse([
        'total'   => $total,
        'success' => $total >= $dc,
        'margin'  => $margin,
    ]);
}

function handle_adjusted_xp(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null || !isset($body['party']) || !isset($body['monsters'])
        || !is_array($body['party']) || !is_array($body['monsters'])) {
        return json_error('invalid encounter');
    }

    // Base XP + monster count.
    $base_xp = 0;
    $monster_count = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count'])) {
            return json_error('invalid monster');
        }
        $cr = (string) $monster['cr'];
        if (!array_key_exists($cr, CR_XP)) {
            return json_error('unsupported cr: ' . $cr);
        }
        if (!is_numeric($monster['count'])) {
            return json_error('invalid count');
        }
        $count = (int) $monster['count'];
        $base_xp += CR_XP[$cr] * $count;
        $monster_count += $count;
    }

    $multiplier = encounter_multiplier($monster_count);
    $adjusted_xp = $base_xp * $multiplier;

    // Party thresholds summed across members.
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_numeric($member['level'])) {
            return json_error('invalid party member');
        }
        $level = (int) $member['level'];
        if (!isset(LEVEL_THRESHOLDS[$level])) {
            return json_error('unsupported level: ' . $level);
        }
        foreach (LEVEL_THRESHOLDS[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    // Highest threshold reached.
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $tier) {
        if ($adjusted_xp >= $thresholds[$tier]) {
            $difficulty = $tier;
        }
    }

    return new JsonResponse([
        'base_xp'       => num($base_xp),
        'monster_count' => $monster_count,
        'multiplier'    => num($multiplier),
        'adjusted_xp'   => num($adjusted_xp),
        'difficulty'    => $difficulty,
        'thresholds'    => [
            'easy'   => $thresholds['easy'],
            'medium' => $thresholds['medium'],
            'hard'   => $thresholds['hard'],
            'deadly' => $thresholds['deadly'],
        ],
    ]);
}

function handle_initiative_order(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return json_error('invalid combatants');
    }

    $combatants = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name']) || !is_numeric($c['dex']) || !is_numeric($c['roll'])) {
            return json_error('invalid combatant');
        }
        $dex = (int) $c['dex'];
        $roll = (int) $c['roll'];
        $combatants[] = [
            'name'  => $c['name'],
            'dex'   => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($combatants, function (array $a, array $b): int {
        // Score descending.
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        // Dex descending.
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        // Name ascending.
        return strcmp($a['name'], $b['name']);
    });

    $order = array_map(
        static fn (array $c): array => ['name' => $c['name'], 'score' => $c['score']],
        $combatants
    );

    return new JsonResponse(['order' => $order]);
}

/** Ability modifier from a score: floor((score - 10) / 2). */
function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

/** Proficiency bonus from level (1-20). */
function proficiency_bonus(int $level): int
{
    return intdiv($level + 3, 4) + 1;
}

function handle_ability_modifier(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null || !isset($body['score']) || !is_int($body['score'])) {
        return json_error('invalid score');
    }
    $score = $body['score'];
    if ($score < 1 || $score > 30) {
        return json_error('invalid score');
    }

    return new JsonResponse([
        'score'    => $score,
        'modifier' => ability_modifier($score),
    ]);
}

function handle_proficiency(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null || !isset($body['level']) || !is_int($body['level'])) {
        return json_error('invalid level');
    }
    $level = $body['level'];
    if ($level < 1 || $level > 20) {
        return json_error('invalid level');
    }

    return new JsonResponse([
        'level'             => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

function handle_derived_stats(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null || !isset($body['level']) || !is_int($body['level'])) {
        return json_error('invalid level');
    }
    $level = $body['level'];
    if ($level < 1 || $level > 20) {
        return json_error('invalid level');
    }

    if (!isset($body['abilities']) || !is_array($body['abilities'])) {
        return json_error('invalid abilities');
    }

    $abilities = $body['abilities'];
    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $key) {
        if (!isset($abilities[$key]) || !is_int($abilities[$key])) {
            return json_error('invalid abilities');
        }
        $score = $abilities[$key];
        if ($score < 1 || $score > 30) {
            return json_error('invalid abilities');
        }
        $modifiers[$key] = ability_modifier($score);
    }

    if (!isset($body['armor']) || !is_array($body['armor'])) {
        return json_error('invalid armor');
    }
    $armor = $body['armor'];
    if (!isset($armor['base']) || !is_int($armor['base'])
        || !isset($armor['dex_cap']) || !is_int($armor['dex_cap'])
        || !isset($armor['shield']) || !is_bool($armor['shield'])) {
        return json_error('invalid armor');
    }

    $proficiency = proficiency_bonus($level);
    $hp_max = $level * (6 + $modifiers['con']);
    $shield_bonus = $armor['shield'] ? 2 : 0;
    $armor_class = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shield_bonus;

    return new JsonResponse([
        'level'             => $level,
        'proficiency_bonus' => $proficiency,
        'hp_max'            => $hp_max,
        'armor_class'       => $armor_class,
        'modifiers'         => $modifiers,
    ]);
}

// ---------------------------------------------------------------------------
// Combat session state (persisted to a per-server-process temp file)
// ---------------------------------------------------------------------------

/** Path to the state file, unique per running server process. */
function combat_store_path(): string
{
    return sys_get_temp_dir() . '/dnd_combat_' . getmypid() . '.json';
}

/** Load all sessions. Returns an associative array keyed by session id. */
function combat_load(): array
{
    $path = combat_store_path();
    if (!is_file($path)) {
        return [];
    }
    $raw = file_get_contents($path);
    if ($raw === false || $raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

/** Persist all sessions. */
function combat_save(array $sessions): void
{
    file_put_contents(combat_store_path(), json_encode($sessions), LOCK_EX);
}

/** Public view of a combatant: name + score. */
function combatant_view(array $c): array
{
    return ['name' => $c['name'], 'score' => $c['score']];
}

/** Conditions map for combatants that currently carry any. */
function conditions_view(array $session): array
{
    $out = [];
    foreach ($session['order'] as $c) {
        $name = $c['name'];
        // Include any combatant that has ever carried a condition, even if its
        // list is now empty because every condition has expired.
        if (array_key_exists($name, $session['conditions'])) {
            $conds = $session['conditions'][$name];
            $out[$name] = array_map(
                static fn (array $cond): array => [
                    'condition'        => $cond['condition'],
                    'remaining_rounds' => $cond['remaining_rounds'],
                ],
                $conds
            );
        }
    }
    return $out;
}

function handle_combat_create(Request $request): JsonResponse
{
    $body = decode_body($request);
    if ($body === null || !isset($body['id']) || !is_string($body['id']) || $body['id'] === '') {
        return json_error('invalid session id');
    }
    if (!isset($body['combatants']) || !is_array($body['combatants']) || $body['combatants'] === []) {
        return json_error('invalid combatants');
    }

    $combatants = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name']) || !is_numeric($c['dex']) || !is_numeric($c['roll'])) {
            return json_error('invalid combatant');
        }
        $dex = (int) $c['dex'];
        $roll = (int) $c['roll'];
        $combatants[] = [
            'name'  => $c['name'],
            'dex'   => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($combatants, function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $sessions = combat_load();
    if (isset($sessions[$body['id']])) {
        return json_error('session id already exists');
    }

    $session = [
        'id'         => $body['id'],
        'round'      => 1,
        'turn_index' => 0,
        'order'      => $combatants,
        'conditions' => [],
    ];
    $sessions[$body['id']] = $session;
    combat_save($sessions);

    return new JsonResponse([
        'id'         => $session['id'],
        'round'      => $session['round'],
        'turn_index' => $session['turn_index'],
        'active'     => combatant_view($session['order'][$session['turn_index']]),
        'order'      => array_map('combatant_view', $session['order']),
    ]);
}

function handle_combat_condition(Request $request, string $id): JsonResponse
{
    $sessions = combat_load();
    if (!isset($sessions[$id])) {
        return json_error('unknown session', 404);
    }
    $session = $sessions[$id];

    $body = decode_body($request);
    if ($body === null || !isset($body['target']) || !is_string($body['target'])) {
        return json_error('invalid target');
    }
    if (!isset($body['condition']) || !is_string($body['condition']) || $body['condition'] === '') {
        return json_error('invalid condition');
    }
    if (!isset($body['duration_rounds']) || !is_int($body['duration_rounds']) || $body['duration_rounds'] < 1) {
        return json_error('invalid duration_rounds');
    }

    $target = $body['target'];
    $found = false;
    foreach ($session['order'] as $c) {
        if ($c['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        return json_error('unknown target');
    }

    $session['conditions'][$target][] = [
        'condition'        => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];
    $sessions[$id] = $session;
    combat_save($sessions);

    return new JsonResponse([
        'target'     => $target,
        'conditions' => array_map(
            static fn (array $cond): array => [
                'condition'        => $cond['condition'],
                'remaining_rounds' => $cond['remaining_rounds'],
            ],
            $session['conditions'][$target]
        ),
    ]);
}

function handle_combat_advance(Request $request, string $id): JsonResponse
{
    $sessions = combat_load();
    if (!isset($sessions[$id])) {
        return json_error('unknown session', 404);
    }
    $session = $sessions[$id];

    $count = count($session['order']);
    $next = $session['turn_index'] + 1;
    if ($next >= $count) {
        $next = 0;
        $session['round']++;
    }
    $session['turn_index'] = $next;

    // Decrement conditions on the newly active combatant at the start of its turn.
    $activeName = $session['order'][$next]['name'];
    if (!empty($session['conditions'][$activeName])) {
        $remaining = [];
        foreach ($session['conditions'][$activeName] as $cond) {
            $cond['remaining_rounds']--;
            if ($cond['remaining_rounds'] > 0) {
                $remaining[] = $cond;
            }
        }
        // Keep the combatant's key present (as an empty list) once it has been
        // acted on, even after its last condition expires.
        $session['conditions'][$activeName] = $remaining;
    }

    $sessions[$id] = $session;
    combat_save($sessions);

    return new JsonResponse([
        'id'         => $session['id'],
        'round'      => $session['round'],
        'turn_index' => $session['turn_index'],
        'active'     => combatant_view($session['order'][$next]),
        'conditions' => (object) conditions_view($session),
    ]);
}

// ---------------------------------------------------------------------------
// Routing (Symfony Routing component)
// ---------------------------------------------------------------------------

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_handler' => 'handle_health'], [], [], '', [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_handler' => 'handle_dice_stats'], [], [], '', [], ['POST']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_handler' => 'handle_ability_check'], [], [], '', [], ['POST']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_handler' => 'handle_adjusted_xp'], [], [], '', [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_handler' => 'handle_initiative_order'], [], [], '', [], ['POST']));
$routes->add('ability_modifier', new Route('/v1/characters/ability-modifier', ['_handler' => 'handle_ability_modifier'], [], [], '', [], ['POST']));
$routes->add('proficiency', new Route('/v1/characters/proficiency', ['_handler' => 'handle_proficiency'], [], [], '', [], ['POST']));
$routes->add('derived_stats', new Route('/v1/characters/derived-stats', ['_handler' => 'handle_derived_stats'], [], [], '', [], ['POST']));
$routes->add('combat_create', new Route('/v1/combat/sessions', ['_handler' => 'handle_combat_create'], [], [], '', [], ['POST']));
$routes->add('combat_condition', new Route('/v1/combat/sessions/{id}/conditions', ['_handler' => 'handle_combat_condition'], [], [], '', [], ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['_handler' => 'handle_combat_advance'], [], [], '', [], ['POST']));

$request = Request::createFromGlobals();

$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->match($request->getPathInfo());
    $handler = $parameters['_handler'];
    if ($handler === 'handle_health') {
        $response = $handler();
    } elseif (isset($parameters['id'])) {
        $response = $handler($request, $parameters['id']);
    } else {
        $response = $handler($request);
    }
} catch (ResourceNotFoundException) {
    $response = json_error('not found', 404);
} catch (MethodNotAllowedException) {
    $response = json_error('method not allowed', 405);
}

$response->send();

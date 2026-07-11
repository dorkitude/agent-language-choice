<?php
require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;

class SessionStore
{
    private static $shmId = null;
    private const int DATA_VAR_ID = 1;
    private const int BOOT_VAR_ID = 2;

    private static function key(): int
    {
        $port = getenv('PORT');
        if ($port !== false && is_numeric($port)) {
            return (int) $port;
        }
        return 123456789;
    }

    private static function init(): void
    {
        if (self::$shmId !== null) {
            return;
        }
        self::$shmId = @shm_attach(self::key(), 1024 * 1024);
        if (self::$shmId === false) {
            throw new RuntimeException('Failed to attach shared memory');
        }
    }

    public static function load(): array
    {
        self::init();
        $ppid = function_exists('posix_getppid') ? posix_getppid() : getmypid();
        $storedBoot = @shm_get_var(self::$shmId, self::BOOT_VAR_ID);
        if ($storedBoot === false || $storedBoot !== $ppid) {
            shm_put_var(self::$shmId, self::BOOT_VAR_ID, $ppid);
            shm_put_var(self::$shmId, self::DATA_VAR_ID, []);
            return [];
        }
        $data = @shm_get_var(self::$shmId, self::DATA_VAR_ID);
        return $data === false ? [] : $data;
    }

    public static function save(array $data): void
    {
        self::init();
        if (!shm_put_var(self::$shmId, self::DATA_VAR_ID, $data)) {
            throw new RuntimeException('Failed to write shared memory');
        }
    }
}

function health(): JsonResponse
{
    return new JsonResponse(['ok' => true]);
}

function diceStats(Request $request, array $params = []): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    $expression = is_array($data) && isset($data['expression']) ? $data['expression'] : '';

    if (!is_string($expression)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    if (!preg_match('/^([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?$/', $expression, $matches)) {
        return new JsonResponse(['error' => 'invalid expression'], 400);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
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

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function abilityCheck(Request $request, array $params = []): JsonResponse
{
    $data = json_decode($request->getContent(), true);

    $roll = $data['roll'] ?? null;
    $modifier = $data['modifier'] ?? null;
    $dc = $data['dc'] ?? null;

    if (!is_int($roll) || !is_int($modifier) || !is_int($dc)) {
        return new JsonResponse(['error' => 'invalid input'], 400);
    }

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return new JsonResponse([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

function adjustedXp(Request $request, array $params = []): JsonResponse
{
    $data = json_decode($request->getContent(), true);

    $party = $data['party'] ?? [];
    $monsters = $data['monsters'] ?? [];

    if (!is_array($party) || !is_array($monsters)) {
        return new JsonResponse(['error' => 'invalid input'], 400);
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
    foreach ($monsters as $monster) {
        if (!is_array($monster)) {
            return new JsonResponse(['error' => 'invalid monster'], 400);
        }
        $cr = $monster['cr'] ?? null;
        $count = $monster['count'] ?? null;
        if (!is_string($cr) || !is_int($count) || $count < 0 || !isset($xpByCr[$cr])) {
            return new JsonResponse(['error' => 'invalid monster'], 400);
        }
        $baseXp += $xpByCr[$cr] * $count;
        $monsterCount += $count;
    }

    if ($monsterCount <= 1) {
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

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member)) {
            return new JsonResponse(['error' => 'invalid party member'], 400);
        }
        $level = $member['level'] ?? null;
        if (!is_int($level) || !isset($thresholdsByLevel[$level])) {
            return new JsonResponse(['error' => 'invalid party member'], 400);
        }
        foreach ($thresholdsByLevel[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    if ($adjustedXp < $thresholds['easy']) {
        $difficulty = 'trivial';
    } elseif ($adjustedXp < $thresholds['medium']) {
        $difficulty = 'easy';
    } elseif ($adjustedXp < $thresholds['hard']) {
        $difficulty = 'medium';
    } elseif ($adjustedXp < $thresholds['deadly']) {
        $difficulty = 'hard';
    } else {
        $difficulty = 'deadly';
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

function initiativeOrder(Request $request, array $params = []): JsonResponse
{
    $data = json_decode($request->getContent(), true);
    $combatants = $data['combatants'] ?? [];

    if (!is_array($combatants)) {
        return new JsonResponse(['error' => 'invalid input'], 400);
    }

    $scored = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant)) {
            return new JsonResponse(['error' => 'invalid combatant'], 400);
        }
        $name = $combatant['name'] ?? null;
        $dex = $combatant['dex'] ?? null;
        $roll = $combatant['roll'] ?? null;

        if (!is_string($name) || !is_int($dex) || !is_int($roll)) {
            return new JsonResponse(['error' => 'invalid combatant'], 400);
        }

        $scored[] = [
            'name' => $name,
            'score' => $roll + $dex,
            'dex' => $dex,
        ];
    }

    usort($scored, function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(function (array $combatant): array {
        return [
            'name' => $combatant['name'],
            'score' => $combatant['score'],
        ];
    }, $scored);

    return new JsonResponse(['order' => $order]);
}

function abilityModifierFromScore(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function abilityModifier(Request $request, array $params = []): JsonResponse
{
    $data = json_decode($request->getContent(), true);

    $score = $data['score'] ?? null;
    if (!is_int($score) || $score < 1 || $score > 30) {
        return new JsonResponse(['error' => 'invalid score'], 400);
    }

    return new JsonResponse([
        'score' => $score,
        'modifier' => abilityModifierFromScore($score),
    ]);
}

function proficiencyBonus(int $level): int
{
    if ($level <= 4) {
        return 2;
    }
    if ($level <= 8) {
        return 3;
    }
    if ($level <= 12) {
        return 4;
    }
    if ($level <= 16) {
        return 5;
    }
    return 6;
}

function proficiency(Request $request, array $params = []): JsonResponse
{
    $data = json_decode($request->getContent(), true);

    $level = $data['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
}

function derivedStats(Request $request, array $params = []): JsonResponse
{
    $data = json_decode($request->getContent(), true);

    $level = $data['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        return new JsonResponse(['error' => 'invalid level'], 400);
    }

    $abilities = $data['abilities'] ?? [];
    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    if (!is_array($abilities)) {
        return new JsonResponse(['error' => 'invalid abilities'], 400);
    }
    foreach ($abilityKeys as $key) {
        if (!isset($abilities[$key]) || !is_int($abilities[$key]) || $abilities[$key] < 1 || $abilities[$key] > 30) {
            return new JsonResponse(['error' => 'invalid abilities'], 400);
        }
    }

    $armor = $data['armor'] ?? [];
    if (!is_array($armor) || !isset($armor['base']) || !is_int($armor['base']) || !isset($armor['shield']) || !is_bool($armor['shield']) || !isset($armor['dex_cap']) || !is_int($armor['dex_cap'])) {
        return new JsonResponse(['error' => 'invalid armor'], 400);
    }

    $modifiers = [];
    foreach ($abilityKeys as $key) {
        $modifiers[$key] = abilityModifierFromScore($abilities[$key]);
    }

    $proficiency = proficiencyBonus($level);
    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => $proficiency,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

function createCombatSession(Request $request, array $params = []): JsonResponse
{
    $sessions = SessionStore::load();
    $data = json_decode($request->getContent(), true);

    $id = $data['id'] ?? null;
    $combatants = $data['combatants'] ?? null;

    if (!is_string($id) || $id === '') {
        return new JsonResponse(['error' => 'invalid id'], 400);
    }

    if (isset($sessions[$id])) {
        return new JsonResponse(['error' => 'session already exists'], 400);
    }

    if (!is_array($combatants) || $combatants === []) {
        return new JsonResponse(['error' => 'invalid combatants'], 400);
    }

    $scored = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant)) {
            return new JsonResponse(['error' => 'invalid combatant'], 400);
        }
        $name = $combatant['name'] ?? null;
        $dex = $combatant['dex'] ?? null;
        $roll = $combatant['roll'] ?? null;

        if (!is_string($name) || $name === '' || !is_int($dex) || !is_int($roll)) {
            return new JsonResponse(['error' => 'invalid combatant'], 400);
        }

        $scored[] = [
            'name' => $name,
            'score' => $roll + $dex,
            'dex' => $dex,
        ];
    }

    usort($scored, function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(function (array $combatant): array {
        return [
            'name' => $combatant['name'],
            'score' => $combatant['score'],
        ];
    }, $scored);

    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    SessionStore::save($sessions);

    return new JsonResponse([
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]);
}

function addCondition(Request $request, array $params = []): JsonResponse
{
    $sessions = SessionStore::load();

    $id = $params['id'] ?? null;
    if (!is_string($id) || !isset($sessions[$id])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }

    $data = json_decode($request->getContent(), true);
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $durationRounds = $data['duration_rounds'] ?? null;

    if (!is_string($target) || $target === '' || !is_string($condition) || $condition === '' || !is_int($durationRounds) || $durationRounds < 1) {
        return new JsonResponse(['error' => 'invalid input'], 400);
    }

    $found = false;
    foreach ($sessions[$id]['order'] as $combatant) {
        if ($combatant['name'] === $target) {
            $found = true;
            break;
        }
    }

    if (!$found) {
        return new JsonResponse(['error' => 'target not found'], 400);
    }

    if (!isset($sessions[$id]['conditions'][$target])) {
        $sessions[$id]['conditions'][$target] = [];
    }

    $sessions[$id]['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $durationRounds,
    ];
    SessionStore::save($sessions);

    return new JsonResponse([
        'target' => $target,
        'conditions' => $sessions[$id]['conditions'][$target],
    ]);
}

function advanceTurn(Request $request, array $params = []): JsonResponse
{
    $sessions = SessionStore::load();

    $id = $params['id'] ?? null;
    if (!is_string($id) || !isset($sessions[$id])) {
        return new JsonResponse(['error' => 'session not found'], 404);
    }

    $orderCount = count($sessions[$id]['order']);
    if ($orderCount === 0) {
        return new JsonResponse(['error' => 'no combatants'], 400);
    }

    $sessions[$id]['turn_index']++;
    if ($sessions[$id]['turn_index'] >= $orderCount) {
        $sessions[$id]['turn_index'] = 0;
        $sessions[$id]['round']++;
    }

    $activeName = $sessions[$id]['order'][$sessions[$id]['turn_index']]['name'];
    if (isset($sessions[$id]['conditions'][$activeName])) {
        $updated = [];
        foreach ($sessions[$id]['conditions'][$activeName] as $cond) {
            $cond['remaining_rounds']--;
            if ($cond['remaining_rounds'] > 0) {
                $updated[] = $cond;
            }
        }
        if ($updated === []) {
            unset($sessions[$id]['conditions'][$activeName]);
        } else {
            $sessions[$id]['conditions'][$activeName] = $updated;
        }
    }
    SessionStore::save($sessions);

    $conditions = $sessions[$id]['conditions'];
    if (empty($conditions)) {
        $conditions = new stdClass();
    }

    return new JsonResponse([
        'id' => $id,
        'round' => $sessions[$id]['round'],
        'turn_index' => $sessions[$id]['turn_index'],
        'active' => $sessions[$id]['order'][$sessions[$id]['turn_index']],
        'conditions' => $conditions,
    ]);
}

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['_controller' => 'health']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['_controller' => 'diceStats']));
$routes->add('ability_check', new Route('/v1/checks/ability', ['_controller' => 'abilityCheck']));
$routes->add('adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['_controller' => 'adjustedXp']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['_controller' => 'initiativeOrder']));
$routes->add('ability_modifier', new Route('/v1/characters/ability-modifier', ['_controller' => 'abilityModifier']));
$routes->add('proficiency', new Route('/v1/characters/proficiency', ['_controller' => 'proficiency']));
$routes->add('derived_stats', new Route('/v1/characters/derived-stats', ['_controller' => 'derivedStats']));
$routes->add('create_combat_session', new Route('/v1/combat/sessions', ['_controller' => 'createCombatSession'], [], [], '', [], ['POST']));
$routes->add('add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['_controller' => 'addCondition'], [], [], '', [], ['POST']));
$routes->add('advance_turn', new Route('/v1/combat/sessions/{id}/advance', ['_controller' => 'advanceTurn'], [], [], '', [], ['POST']));

$request = Request::createFromGlobals();
$context = (new RequestContext())->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

try {
    $parameters = $matcher->match($request->getPathInfo());
    $controller = $parameters['_controller'];
    unset($parameters['_controller'], $parameters['_route']);
    $response = $controller($request, $parameters);
    $response->send();
} catch (Symfony\Component\Routing\Exception\ResourceNotFoundException) {
    (new JsonResponse(['error' => 'not found'], 404))->send();
} catch (Throwable) {
    (new JsonResponse(['error' => 'internal error'], 500))->send();
}

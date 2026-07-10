<?php
require __DIR__ . '/vendor/autoload.php';

use Symfony\Component\HttpFoundation\JsonResponse;
use Symfony\Component\HttpFoundation\Request;
use Symfony\Component\Routing\Matcher\UrlMatcher;
use Symfony\Component\Routing\RequestContext;
use Symfony\Component\Routing\Route;
use Symfony\Component\Routing\RouteCollection;
use Symfony\Component\Routing\Exception\ResourceNotFoundException;
use Symfony\Component\Routing\Exception\MethodNotAllowedException;

$request = Request::createFromGlobals();

$routes = new RouteCollection();
$routes->add('health', new Route('/health', ['handler' => 'health'], [], [], null, [], ['GET']));
$routes->add('dice_stats', new Route('/v1/dice/stats', ['handler' => 'dice_stats'], [], [], null, [], ['POST']));
$routes->add('checks_ability', new Route('/v1/checks/ability', ['handler' => 'checks_ability'], [], [], null, [], ['POST']));
$routes->add('encounters_adjusted_xp', new Route('/v1/encounters/adjusted-xp', ['handler' => 'encounters_adjusted_xp'], [], [], null, [], ['POST']));
$routes->add('initiative_order', new Route('/v1/initiative/order', ['handler' => 'initiative_order'], [], [], null, [], ['POST']));
$routes->add('characters_ability_modifier', new Route('/v1/characters/ability-modifier', ['handler' => 'characters_ability_modifier'], [], [], null, [], ['POST']));
$routes->add('characters_proficiency', new Route('/v1/characters/proficiency', ['handler' => 'characters_proficiency'], [], [], null, [], ['POST']));
$routes->add('characters_derived_stats', new Route('/v1/characters/derived-stats', ['handler' => 'characters_derived_stats'], [], [], null, [], ['POST']));
$routes->add('combat_create_session', new Route('/v1/combat/sessions', ['handler' => 'combat_create_session'], [], [], null, [], ['POST']));
$routes->add('combat_add_condition', new Route('/v1/combat/sessions/{id}/conditions', ['handler' => 'combat_add_condition'], [], [], null, [], ['POST']));
$routes->add('combat_advance', new Route('/v1/combat/sessions/{id}/advance', ['handler' => 'combat_advance'], [], [], null, [], ['POST']));

$context = new RequestContext();
$context->fromRequest($request);
$matcher = new UrlMatcher($routes, $context);

function jsonBody(Request $request): ?array
{
    $content = $request->getContent();
    if ($content === '' || $content === null) {
        return null;
    }
    $data = json_decode($content, true);
    if (!is_array($data)) {
        return null;
    }
    return $data;
}

function badRequest(string $message): JsonResponse
{
    return new JsonResponse(['error' => $message], 400);
}

function handleDiceStats(?array $body): JsonResponse
{
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        return badRequest('invalid expression');
    }

    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $body['expression'], $matches)) {
        return badRequest('invalid expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return badRequest('invalid expression');
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;

    return new JsonResponse([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function handleChecksAbility(?array $body): JsonResponse
{
    if ($body === null || !isset($body['roll'], $body['modifier'], $body['dc'])
        || !is_numeric($body['roll']) || !is_numeric($body['modifier']) || !is_numeric($body['dc'])) {
        return badRequest('invalid request');
    }

    $roll = $body['roll'] + 0;
    $modifier = $body['modifier'] + 0;
    $dc = $body['dc'] + 0;

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return new JsonResponse([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

function handleEncountersAdjustedXp(?array $body): JsonResponse
{
    if ($body === null || !isset($body['party'], $body['monsters'])
        || !is_array($body['party']) || !is_array($body['monsters'])) {
        return badRequest('invalid request');
    }

    $crXp = [
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

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (!isset($monster['cr'], $monster['count']) || !is_string($monster['cr']) && !is_numeric($monster['cr'])) {
            return badRequest('invalid monster');
        }
        $cr = (string) $monster['cr'];
        if (!isset($crXp[$cr]) || !is_numeric($monster['count'])) {
            return badRequest('invalid monster');
        }
        $count = (int) $monster['count'];
        $baseXp += $crXp[$cr] * $count;
        $monsterCount += $count;
    }

    if ($monsterCount === 1) {
        $multiplier = 1;
    } elseif ($monsterCount === 2) {
        $multiplier = 1.5;
    } elseif ($monsterCount >= 3 && $monsterCount <= 6) {
        $multiplier = 2;
    } elseif ($monsterCount >= 7 && $monsterCount <= 10) {
        $multiplier = 2.5;
    } elseif ($monsterCount >= 11 && $monsterCount <= 14) {
        $multiplier = 3;
    } else {
        $multiplier = 4;
    }

    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!isset($member['level']) || !is_numeric($member['level'])) {
            return badRequest('invalid party member');
        }
        $level = (int) $member['level'];
        if (!isset($levelThresholds[$level])) {
            return badRequest('unsupported level');
        }
        foreach ($thresholds as $key => $_) {
            $thresholds[$key] += $levelThresholds[$level][$key];
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

    return new JsonResponse([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

function handleInitiativeOrder(?array $body): JsonResponse
{
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return badRequest('invalid request');
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (!isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name']) || !is_numeric($combatant['dex']) || !is_numeric($combatant['roll'])) {
            return badRequest('invalid combatant');
        }
        $dex = $combatant['dex'] + 0;
        $roll = $combatant['roll'] + 0;
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(function ($c) {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $combatants);

    return new JsonResponse(['order' => $order]);
}

function isValidInteger($value): bool
{
    if (is_int($value)) {
        return true;
    }
    if (is_float($value)) {
        return floor($value) === $value;
    }
    return false;
}

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    return match (true) {
        $level >= 1 && $level <= 4 => 2,
        $level >= 5 && $level <= 8 => 3,
        $level >= 9 && $level <= 12 => 4,
        $level >= 13 && $level <= 16 => 5,
        default => 6,
    };
}

function handleCharactersAbilityModifier(?array $body): JsonResponse
{
    if ($body === null || !isset($body['score']) || !isValidInteger($body['score'])) {
        return badRequest('invalid request');
    }

    $score = (int) $body['score'];
    if ($score < 1 || $score > 30) {
        return badRequest('score must be between 1 and 30');
    }

    return new JsonResponse([
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
}

function handleCharactersProficiency(?array $body): JsonResponse
{
    if ($body === null || !isset($body['level']) || !isValidInteger($body['level'])) {
        return badRequest('invalid request');
    }

    $level = (int) $body['level'];
    if ($level < 1 || $level > 20) {
        return badRequest('level must be between 1 and 20');
    }

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
}

function handleCharactersDerivedStats(?array $body): JsonResponse
{
    if ($body === null || !isset($body['level'], $body['abilities'], $body['armor'])
        || !isValidInteger($body['level']) || !is_array($body['abilities']) || !is_array($body['armor'])) {
        return badRequest('invalid request');
    }

    $level = (int) $body['level'];
    if ($level < 1 || $level > 20) {
        return badRequest('level must be between 1 and 20');
    }

    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $abilities = $body['abilities'];
    foreach ($abilityKeys as $key) {
        if (!isset($abilities[$key]) || !isValidInteger($abilities[$key])) {
            return badRequest('invalid abilities');
        }
    }

    $armor = $body['armor'];
    if (!isset($armor['base']) || !isValidInteger($armor['base']) || !isset($armor['shield']) || !is_bool($armor['shield'])
        || !isset($armor['dex_cap']) || !isValidInteger($armor['dex_cap'])) {
        return badRequest('invalid armor');
    }

    $modifiers = [];
    foreach ($abilityKeys as $key) {
        $modifiers[$key] = abilityModifier((int) $abilities[$key]);
    }

    $proficiencyBonus = proficiencyBonus($level);
    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = (int) $armor['base'] + min($modifiers['dex'], (int) $armor['dex_cap']) + $shieldBonus;

    return new JsonResponse([
        'level' => $level,
        'proficiency_bonus' => $proficiencyBonus,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

const COMBAT_STATE_FILE = __DIR__ . '/var/combat_state.json';

function loadCombatSessions(): array
{
    if (!is_file(COMBAT_STATE_FILE)) {
        return [];
    }
    $content = file_get_contents(COMBAT_STATE_FILE);
    $data = json_decode($content, true);
    return is_array($data) ? $data : [];
}

function saveCombatSessions(array $sessions): void
{
    $dir = dirname(COMBAT_STATE_FILE);
    if (!is_dir($dir)) {
        mkdir($dir, 0777, true);
    }
    file_put_contents(COMBAT_STATE_FILE, json_encode($sessions), LOCK_EX);
}

function combatantOrderEntry(array $c): array
{
    return ['name' => $c['name'], 'score' => $c['score']];
}

function handleCombatCreateSession(?array $body): JsonResponse
{
    if ($body === null || !isset($body['id'], $body['combatants'])
        || !is_string($body['id']) || $body['id'] === '' || !is_array($body['combatants']) || count($body['combatants']) === 0) {
        return badRequest('invalid request');
    }

    $id = $body['id'];
    $sessions = loadCombatSessions();
    if (isset($sessions[$id])) {
        return badRequest('session already exists');
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (!isset($combatant['name'], $combatant['dex'], $combatant['roll'])
            || !is_string($combatant['name']) || !is_numeric($combatant['dex']) || !is_numeric($combatant['roll'])) {
            return badRequest('invalid combatant');
        }
        $dex = $combatant['dex'] + 0;
        $roll = $combatant['roll'] + 0;
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $conditions = [];
    foreach ($combatants as $c) {
        $conditions[$c['name']] = [];
    }

    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $combatants,
        'conditions' => $conditions,
    ];
    saveCombatSessions($sessions);

    $active = $combatants[0];

    return new JsonResponse([
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => combatantOrderEntry($active),
        'order' => array_map('combatantOrderEntry', $combatants),
    ]);
}

function handleCombatAddCondition(string $id, ?array $body): JsonResponse
{
    $sessions = loadCombatSessions();
    if (!isset($sessions[$id])) {
        return new JsonResponse(['error' => 'not found'], 404);
    }

    if ($body === null || !isset($body['target'], $body['condition'], $body['duration_rounds'])
        || !is_string($body['target']) || !is_string($body['condition']) || !isValidInteger($body['duration_rounds'])) {
        return badRequest('invalid request');
    }

    $target = $body['target'];
    $duration = (int) $body['duration_rounds'];
    if ($duration <= 0) {
        return badRequest('duration_rounds must be a positive integer');
    }

    $session = $sessions[$id];
    if (!isset($session['conditions'][$target])) {
        return badRequest('unknown combatant');
    }

    $session['conditions'][$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $duration,
    ];
    $sessions[$id] = $session;
    saveCombatSessions($sessions);

    return new JsonResponse([
        'target' => $target,
        'conditions' => $session['conditions'][$target],
    ]);
}

function handleCombatAdvance(string $id): JsonResponse
{
    $sessions = loadCombatSessions();
    if (!isset($sessions[$id])) {
        return new JsonResponse(['error' => 'not found'], 404);
    }

    $session = $sessions[$id];
    $order = $session['order'];
    $count = count($order);

    $nextIndex = $session['turn_index'] + 1;
    if ($nextIndex >= $count) {
        $nextIndex = 0;
        $session['round'] += 1;
    }
    $session['turn_index'] = $nextIndex;

    $activeName = $order[$nextIndex]['name'];
    if (isset($session['conditions'][$activeName])) {
        $updated = [];
        foreach ($session['conditions'][$activeName] as $condition) {
            $remaining = $condition['remaining_rounds'] - 1;
            if ($remaining > 0) {
                $updated[] = ['condition' => $condition['condition'], 'remaining_rounds' => $remaining];
            }
        }
        $session['conditions'][$activeName] = $updated;
    }

    $sessions[$id] = $session;
    saveCombatSessions($sessions);

    $conditionsOut = [];
    foreach ($session['conditions'] as $name => $conds) {
        if (count($conds) > 0) {
            $conditionsOut[$name] = $conds;
        }
    }

    return new JsonResponse([
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => combatantOrderEntry($order[$nextIndex]),
        'conditions' => count($conditionsOut) > 0 ? $conditionsOut : new stdClass(),
    ]);
}

try {
    $parameters = $matcher->match($request->getPathInfo());
    $handler = $parameters['handler'];
    $body = jsonBody($request);

    $response = match ($handler) {
        'health' => new JsonResponse(['ok' => true]),
        'dice_stats' => handleDiceStats($body),
        'checks_ability' => handleChecksAbility($body),
        'encounters_adjusted_xp' => handleEncountersAdjustedXp($body),
        'initiative_order' => handleInitiativeOrder($body),
        'characters_ability_modifier' => handleCharactersAbilityModifier($body),
        'characters_proficiency' => handleCharactersProficiency($body),
        'characters_derived_stats' => handleCharactersDerivedStats($body),
        'combat_create_session' => handleCombatCreateSession($body),
        'combat_add_condition' => handleCombatAddCondition($parameters['id'], $body),
        'combat_advance' => handleCombatAdvance($parameters['id']),
        default => new JsonResponse(['error' => 'not found'], 404),
    };
    $response->send();
} catch (ResourceNotFoundException $e) {
    (new JsonResponse(['error' => 'not found'], 404))->send();
} catch (MethodNotAllowedException $e) {
    (new JsonResponse(['error' => 'method not allowed'], 405))->send();
}

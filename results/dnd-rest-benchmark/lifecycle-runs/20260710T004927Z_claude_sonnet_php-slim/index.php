<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

function jsonResponse(Response $response, array $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data));
    return $response->withHeader('Content-Type', 'application/json')->withStatus($status);
}

function getJsonBody(Request $request): ?array
{
    $body = (string) $request->getBody();
    $data = json_decode($body, true);
    return is_array($data) ? $data : null;
}

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $data = getJsonBody($request);
    $expression = $data['expression'] ?? null;

    if (!is_string($expression)) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $matches)) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return jsonResponse($response, ['error' => 'invalid expression'], 400);
    }

    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;

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
    $data = getJsonBody($request);

    if (!isset($data['roll'], $data['modifier'], $data['dc'])) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $roll = $data['roll'];
    $modifier = $data['modifier'];
    $dc = $data['dc'];

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    return jsonResponse($response, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $data = getJsonBody($request);

    $monsterXp = [
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

    $partyThresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    if (!isset($data['party'], $data['monsters']) || !is_array($data['party']) || !is_array($data['monsters'])) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($data['monsters'] as $monster) {
        $cr = (string) ($monster['cr'] ?? '');
        $count = (int) ($monster['count'] ?? 0);
        if (!isset($monsterXp[$cr])) {
            return jsonResponse($response, ['error' => 'unsupported cr'], 400);
        }
        $baseXp += $monsterXp[$cr] * $count;
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

    $totalEasy = 0;
    $totalMedium = 0;
    $totalHard = 0;
    $totalDeadly = 0;
    foreach ($data['party'] as $member) {
        $level = (int) ($member['level'] ?? 0);
        if (!isset($partyThresholds[$level])) {
            return jsonResponse($response, ['error' => 'unsupported level'], 400);
        }
        $totalEasy += $partyThresholds[$level]['easy'];
        $totalMedium += $partyThresholds[$level]['medium'];
        $totalHard += $partyThresholds[$level]['hard'];
        $totalDeadly += $partyThresholds[$level]['deadly'];
    }

    if ($adjustedXp >= $totalDeadly) {
        $difficulty = 'deadly';
    } elseif ($adjustedXp >= $totalHard) {
        $difficulty = 'hard';
    } elseif ($adjustedXp >= $totalMedium) {
        $difficulty = 'medium';
    } elseif ($adjustedXp >= $totalEasy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    return jsonResponse($response, [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => $totalEasy,
            'medium' => $totalMedium,
            'hard' => $totalHard,
            'deadly' => $totalDeadly,
        ],
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $data = getJsonBody($request);

    if (!isset($data['combatants']) || !is_array($data['combatants'])) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        $name = (string) ($combatant['name'] ?? '');
        $dex = (int) ($combatant['dex'] ?? 0);
        $roll = (int) ($combatant['roll'] ?? 0);
        $score = $roll + $dex;
        $combatants[] = ['name' => $name, 'dex' => $dex, 'score' => $score];
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

    return jsonResponse($response, ['order' => $order]);
});

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
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

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $data = getJsonBody($request);
    $score = $data['score'] ?? null;

    if (!is_int($score) || $score < 1 || $score > 30) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    return jsonResponse($response, [
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $data = getJsonBody($request);
    $level = $data['level'] ?? null;

    if (!is_int($level) || $level < 1 || $level > 20) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $data = getJsonBody($request);

    $level = $data['level'] ?? null;
    $abilities = $data['abilities'] ?? null;
    $armor = $data['armor'] ?? null;

    if (!is_int($level) || $level < 1 || $level > 20) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    if (!is_array($abilities)) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilityKeys as $key) {
        $score = $abilities[$key] ?? null;
        if (!is_int($score) || $score < 1 || $score > 30) {
            return jsonResponse($response, ['error' => 'invalid request'], 400);
        }
        $modifiers[$key] = abilityModifier($score);
    }

    if (!is_array($armor)) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $armorBase = $armor['base'] ?? null;
    $shield = $armor['shield'] ?? false;
    $dexCap = $armor['dex_cap'] ?? null;

    if (!is_int($armorBase) || !is_bool($shield) || !is_int($dexCap)) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $proficiencyBonus = proficiencyBonus($level);
    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $armorBase + min($modifiers['dex'], $dexCap) + $shieldBonus;

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => $proficiencyBonus,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
});

$combatStateFile = __DIR__ . '/combat_state.json';

function loadCombatSessions(string $file): array
{
    if (!file_exists($file)) {
        return [];
    }
    $contents = file_get_contents($file);
    $data = json_decode($contents, true);
    return is_array($data) ? $data : [];
}

function saveCombatSessions(string $file, array $sessions): void
{
    file_put_contents($file, json_encode($sessions), LOCK_EX);
}

function buildCombatResponse(array $session): array
{
    $order = array_map(function ($c) {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $session['combatants']);

    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $order[$session['turn_index']],
        'order' => $order,
    ];
}

$app->post('/v1/combat/sessions', function (Request $request, Response $response) use ($combatStateFile) {
    $data = getJsonBody($request);

    if (!isset($data['id']) || !is_string($data['id']) || $data['id'] === '') {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $id = $data['id'];
    $combatSessions = loadCombatSessions($combatStateFile);

    if (isset($combatSessions[$id])) {
        return jsonResponse($response, ['error' => 'session already exists'], 400);
    }

    if (!isset($data['combatants']) || !is_array($data['combatants']) || count($data['combatants']) === 0) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        if (!isset($combatant['name']) || !is_string($combatant['name'])) {
            return jsonResponse($response, ['error' => 'invalid request'], 400);
        }
        $name = $combatant['name'];
        $dex = (int) ($combatant['dex'] ?? 0);
        $roll = (int) ($combatant['roll'] ?? 0);
        $score = $roll + $dex;
        $combatants[] = [
            'name' => $name,
            'dex' => $dex,
            'roll' => $roll,
            'score' => $score,
            'conditions' => [],
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

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'combatants' => $combatants,
    ];

    $combatSessions[$id] = $session;
    saveCombatSessions($combatStateFile, $combatSessions);

    return jsonResponse($response, buildCombatResponse($session));
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) use ($combatStateFile) {
    $id = $args['id'];
    $combatSessions = loadCombatSessions($combatStateFile);

    if (!isset($combatSessions[$id])) {
        return jsonResponse($response, ['error' => 'session not found'], 404);
    }

    $data = getJsonBody($request);

    if (!isset($data['target'], $data['condition'], $data['duration_rounds'])) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $target = $data['target'];
    $condition = $data['condition'];
    $duration = $data['duration_rounds'];

    if (!is_string($target) || !is_string($condition) || !is_int($duration) || $duration <= 0) {
        return jsonResponse($response, ['error' => 'invalid request'], 400);
    }

    $session = &$combatSessions[$id];
    $targetIndex = null;
    foreach ($session['combatants'] as $i => $c) {
        if ($c['name'] === $target) {
            $targetIndex = $i;
            break;
        }
    }

    if ($targetIndex === null) {
        return jsonResponse($response, ['error' => 'unknown target'], 400);
    }

    $session['combatants'][$targetIndex]['conditions'][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];

    $conditions = array_map(function ($cond) {
        return ['condition' => $cond['condition'], 'remaining_rounds' => $cond['remaining_rounds']];
    }, $session['combatants'][$targetIndex]['conditions']);

    saveCombatSessions($combatStateFile, $combatSessions);

    return jsonResponse($response, [
        'target' => $target,
        'conditions' => $conditions,
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) use ($combatStateFile) {
    $id = $args['id'];
    $combatSessions = loadCombatSessions($combatStateFile);

    if (!isset($combatSessions[$id])) {
        return jsonResponse($response, ['error' => 'session not found'], 404);
    }

    $session = &$combatSessions[$id];
    $count = count($session['combatants']);

    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $activeIndex = $session['turn_index'];
    $remainingConditions = [];
    foreach ($session['combatants'][$activeIndex]['conditions'] as $cond) {
        $cond['remaining_rounds']--;
        if ($cond['remaining_rounds'] > 0) {
            $remainingConditions[] = $cond;
        }
    }
    $session['combatants'][$activeIndex]['conditions'] = $remainingConditions;

    $conditions = [];
    foreach ($session['combatants'] as $i => $c) {
        if (count($c['conditions']) > 0 || $i === $activeIndex) {
            $conditions[$c['name']] = array_map(function ($cond) {
                return ['condition' => $cond['condition'], 'remaining_rounds' => $cond['remaining_rounds']];
            }, $c['conditions']);
        }
    }

    $order = array_map(function ($c) {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $session['combatants']);

    saveCombatSessions($combatStateFile, $combatSessions);

    return jsonResponse($response, [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $order[$activeIndex],
        'conditions' => (object) $conditions,
    ]);
});

$app->run();

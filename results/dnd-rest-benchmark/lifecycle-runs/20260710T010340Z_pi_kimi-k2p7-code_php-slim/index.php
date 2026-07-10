<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

$json = function (Response $response, array $data, int $status = 200): Response {
    $response->getBody()->write(json_encode($data, JSON_THROW_ON_ERROR));
    return $response->withStatus($status)->withHeader('Content-Type', 'application/json');
};

$badRequest = function (Response $response, string $message = 'Bad Request') use ($json): Response {
    return $json($response, ['error' => $message], 400);
};

$parseBody = function (Request $request): ?array {
    $body = (string) $request->getBody();
    if ($body === '') {
        return null;
    }
    try {
        $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException $e) {
        return null;
    }
    return is_array($data) ? $data : null;
};

$abilityModifier = function (int $score): int {
    return (int) floor(($score - 10) / 2);
};

$proficiencyBonus = function (int $level): int {
    return (int) floor(($level - 1) / 4) + 2;
};

$app->get('/health', function (Request $request, Response $response) use ($json) {
    return $json($response, ['ok' => true]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) use ($json, $badRequest, $parseBody) {
    $data = $parseBody($request);
    if ($data === null || !isset($data['expression']) || !is_string($data['expression'])) {
        return $badRequest($response, 'missing expression');
    }

    if (!preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $data['expression'], $matches)) {
        return $badRequest($response, 'invalid expression');
    }

    $dice_count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[4]) ? ((int) $matches[4]) * ($matches[3] === '-' ? -1 : 1) : 0;

    if ($dice_count <= 0 || $sides <= 0) {
        return $badRequest($response, 'invalid expression');
    }

    $min = $dice_count + $modifier;
    $max = $dice_count * $sides + $modifier;
    $average = $dice_count * ($sides + 1) / 2 + $modifier;

    return $json($response, [
        'dice_count' => $dice_count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) use ($json, $badRequest, $parseBody) {
    $data = $parseBody($request);
    if ($data === null) {
        return $badRequest($response, 'invalid body');
    }

    foreach (['roll', 'modifier', 'dc'] as $field) {
        if (!isset($data[$field]) || !is_int($data[$field])) {
            return $badRequest($response, "missing or invalid {$field}");
        }
    }

    $total = $data['roll'] + $data['modifier'];
    $success = $total >= $data['dc'];
    $margin = $total - $data['dc'];

    return $json($response, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) use ($json, $badRequest, $parseBody) {
    $data = $parseBody($request);
    if ($data === null) {
        return $badRequest($response, 'invalid body');
    }

    if (!isset($data['party']) || !is_array($data['party']) || !isset($data['monsters']) || !is_array($data['monsters'])) {
        return $badRequest($response, 'missing party or monsters');
    }

    $xp_table = [
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

    $thresholds_per_level = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $multipliers = [
        ['max' => 1, 'value' => 1],
        ['max' => 2, 'value' => 1.5],
        ['max' => 6, 'value' => 2],
        ['max' => 10, 'value' => 2.5],
        ['max' => 14, 'value' => 3],
        ['max' => PHP_INT_MAX, 'value' => 4],
    ];

    $base_xp = 0;
    $monster_count = 0;
    foreach ($data['monsters'] as $monster) {
        if (!isset($monster['cr']) || !is_string($monster['cr']) || !isset($monster['count']) || !is_int($monster['count'])) {
            return $badRequest($response, 'invalid monster entry');
        }
        if (!isset($xp_table[$monster['cr']]) || $monster['count'] <= 0) {
            return $badRequest($response, 'invalid monster entry');
        }
        $base_xp += $xp_table[$monster['cr']] * $monster['count'];
        $monster_count += $monster['count'];
    }

    $multiplier = 1;
    foreach ($multipliers as $rule) {
        if ($monster_count <= $rule['max']) {
            $multiplier = $rule['value'];
            break;
        }
    }

    $adjusted_xp = (int) round($base_xp * $multiplier);

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($data['party'] as $member) {
        if (!isset($member['level']) || !is_int($member['level']) || !isset($thresholds_per_level[$member['level']])) {
            return $badRequest($response, 'invalid party member');
        }
        foreach ($thresholds_per_level[$member['level']] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $difficulty = 'trivial';
    if ($adjusted_xp >= $thresholds['deadly']) {
        $difficulty = 'deadly';
    } elseif ($adjusted_xp >= $thresholds['hard']) {
        $difficulty = 'hard';
    } elseif ($adjusted_xp >= $thresholds['medium']) {
        $difficulty = 'medium';
    } elseif ($adjusted_xp >= $thresholds['easy']) {
        $difficulty = 'easy';
    }

    return $json($response, [
        'base_xp' => $base_xp,
        'monster_count' => $monster_count,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjusted_xp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) use ($json, $badRequest, $parseBody) {
    $data = $parseBody($request);
    if ($data === null) {
        return $badRequest($response, 'invalid body');
    }

    if (!isset($data['combatants']) || !is_array($data['combatants'])) {
        return $badRequest($response, 'missing combatants');
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        if (!isset($combatant['name']) || !is_string($combatant['name']) ||
            !isset($combatant['dex']) || !is_int($combatant['dex']) ||
            !isset($combatant['roll']) || !is_int($combatant['roll'])) {
            return $badRequest($response, 'invalid combatant');
        }
        $combatants[] = [
            'name' => $combatant['name'],
            'score' => $combatant['roll'] + $combatant['dex'],
            'dex' => $combatant['dex'],
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

    $order = array_map(function (array $combatant): array {
        return [
            'name' => $combatant['name'],
            'score' => $combatant['score'],
        ];
    }, $combatants);

    return $json($response, ['order' => $order]);
});

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) use ($json, $badRequest, $parseBody, $abilityModifier) {
    $data = $parseBody($request);
    if ($data === null || !isset($data['score']) || !is_int($data['score']) || $data['score'] < 1 || $data['score'] > 30) {
        return $badRequest($response, 'missing or invalid score');
    }

    $score = $data['score'];
    return $json($response, ['score' => $score, 'modifier' => $abilityModifier($score)]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) use ($json, $badRequest, $parseBody, $proficiencyBonus) {
    $data = $parseBody($request);
    if ($data === null || !isset($data['level']) || !is_int($data['level']) || $data['level'] < 1 || $data['level'] > 20) {
        return $badRequest($response, 'missing or invalid level');
    }

    $level = $data['level'];
    return $json($response, ['level' => $level, 'proficiency_bonus' => $proficiencyBonus($level)]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) use ($json, $badRequest, $parseBody, $abilityModifier, $proficiencyBonus) {
    $data = $parseBody($request);
    if ($data === null) {
        return $badRequest($response, 'invalid body');
    }

    if (!isset($data['level']) || !is_int($data['level']) || $data['level'] < 1 || $data['level'] > 20) {
        return $badRequest($response, 'missing or invalid level');
    }

    if (!isset($data['abilities']) || !is_array($data['abilities'])) {
        return $badRequest($response, 'missing or invalid abilities');
    }

    $abilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilities as $ability) {
        if (!isset($data['abilities'][$ability]) || !is_int($data['abilities'][$ability]) || $data['abilities'][$ability] < 1 || $data['abilities'][$ability] > 30) {
            return $badRequest($response, "missing or invalid {$ability}");
        }
        $modifiers[$ability] = $abilityModifier($data['abilities'][$ability]);
    }

    if (!isset($data['armor']) || !is_array($data['armor']) ||
        !isset($data['armor']['base']) || !is_int($data['armor']['base']) ||
        !isset($data['armor']['shield']) || !is_bool($data['armor']['shield']) ||
        !isset($data['armor']['dex_cap']) || !is_int($data['armor']['dex_cap'])) {
        return $badRequest($response, 'missing or invalid armor');
    }

    $shieldBonus = $data['armor']['shield'] ? 2 : 0;
    $armorClass = $data['armor']['base'] + min($modifiers['dex'], $data['armor']['dex_cap']) + $shieldBonus;
    $hpMax = $data['level'] * (6 + $modifiers['con']);

    return $json($response, [
        'level' => $data['level'],
        'proficiency_bonus' => $proficiencyBonus($data['level']),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
});

const SESSIONS_FILE = __DIR__ . '/.combat_sessions.json';

function loadSessions(): array {
    if (!file_exists(SESSIONS_FILE)) {
        return [];
    }
    $content = file_get_contents(SESSIONS_FILE);
    if ($content === false || $content === '') {
        return [];
    }
    try {
        $data = json_decode($content, true, 512, JSON_THROW_ON_ERROR);
        return is_array($data) ? $data : [];
    } catch (JsonException $e) {
        return [];
    }
}

function saveSessions(array $sessions): void {
    file_put_contents(SESSIONS_FILE, json_encode($sessions, JSON_THROW_ON_ERROR));
}

$sessions = loadSessions();

$app->post('/v1/combat/sessions', function (Request $request, Response $response) use (&$sessions, $json, $badRequest, $parseBody) {
    $data = $parseBody($request);
    if ($data === null) {
        return $badRequest($response, 'invalid body');
    }

    if (!isset($data['id']) || !is_string($data['id']) || $data['id'] === '') {
        return $badRequest($response, 'missing or invalid id');
    }

    if (isset($sessions[$data['id']])) {
        return $badRequest($response, 'session already exists');
    }

    if (!isset($data['combatants']) || !is_array($data['combatants']) || count($data['combatants']) === 0) {
        return $badRequest($response, 'missing or invalid combatants');
    }

    $combatants = [];
    foreach ($data['combatants'] as $combatant) {
        if (!isset($combatant['name']) || !is_string($combatant['name']) || $combatant['name'] === '' ||
            !isset($combatant['dex']) || !is_int($combatant['dex']) ||
            !isset($combatant['roll']) || !is_int($combatant['roll'])) {
            return $badRequest($response, 'invalid combatant');
        }
        $combatants[] = [
            'name' => $combatant['name'],
            'dex' => $combatant['dex'],
            'score' => $combatant['roll'] + $combatant['dex'],
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

    $order = array_map(function (array $combatant): array {
        return [
            'name' => $combatant['name'],
            'score' => $combatant['score'],
        ];
    }, $combatants);

    $sessions[$data['id']] = [
        'id' => $data['id'],
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    saveSessions($sessions);

    return $json($response, [
        'id' => $data['id'],
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]);
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) use (&$sessions, $json, $badRequest, $parseBody) {
    $id = $args['id'];
    if (!isset($sessions[$id])) {
        return $json($response, ['error' => 'Not Found'], 404);
    }

    $data = $parseBody($request);
    if ($data === null) {
        return $badRequest($response, 'invalid body');
    }

    if (!isset($data['target']) || !is_string($data['target']) ||
        !isset($data['condition']) || !is_string($data['condition']) ||
        !isset($data['duration_rounds']) || !is_int($data['duration_rounds']) || $data['duration_rounds'] <= 0) {
        return $badRequest($response, 'missing or invalid condition fields');
    }

    $found = false;
    foreach ($sessions[$id]['order'] as $combatant) {
        if ($combatant['name'] === $data['target']) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        return $badRequest($response, 'unknown target');
    }

    if (!isset($sessions[$id]['conditions'][$data['target']])) {
        $sessions[$id]['conditions'][$data['target']] = [];
    }
    $sessions[$id]['conditions'][$data['target']][] = [
        'condition' => $data['condition'],
        'remaining_rounds' => $data['duration_rounds'],
    ];
    saveSessions($sessions);

    return $json($response, [
        'target' => $data['target'],
        'conditions' => $sessions[$id]['conditions'][$data['target']],
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) use (&$sessions, $json) {
    $id = $args['id'];
    if (!isset($sessions[$id])) {
        return $json($response, ['error' => 'Not Found'], 404);
    }

    $session = &$sessions[$id];
    $count = count($session['order']);
    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    if (isset($session['conditions'][$activeName])) {
        $updated = [];
        foreach ($session['conditions'][$activeName] as $condition) {
            $condition['remaining_rounds']--;
            if ($condition['remaining_rounds'] > 0) {
                $updated[] = $condition;
            }
        }
        if (count($updated) === 0) {
            unset($session['conditions'][$activeName]);
        } else {
            $session['conditions'][$activeName] = $updated;
        }
    }
    saveSessions($sessions);

    return $json($response, [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $session['order'][$session['turn_index']],
        'conditions' => (object) $session['conditions'],
    ]);
});

$app->run();

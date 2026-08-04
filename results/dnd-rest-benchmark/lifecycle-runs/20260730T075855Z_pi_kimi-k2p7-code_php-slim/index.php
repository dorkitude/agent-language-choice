<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$dbPath = __DIR__ . '/game.db';

function getDb(): PDO
{
    global $dbPath;
    static $pdo = null;
    if ($pdo === null) {
        $pdo = new PDO('sqlite:' . $dbPath);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        $pdo->exec('PRAGMA busy_timeout = 5000');
    }
    return $pdo;
}

function initSchema(): void
{
    $db = getDb();
    $db->exec('CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        combatants TEXT NOT NULL,
        order_json TEXT NOT NULL,
        round INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        conditions TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_characters (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_events (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
    )');
}

function resetSchema(): void
{
    $db = getDb();
    $db->exec('DROP TABLE IF EXISTS campaign_events');
    $db->exec('DROP TABLE IF EXISTS campaign_characters');
    $db->exec('DROP TABLE IF EXISTS campaigns');
    $db->exec('DROP TABLE IF EXISTS combat_sessions');
    $db->exec('DROP TABLE IF EXISTS users');
    $db->exec('DROP TABLE IF EXISTS monsters');
    $db->exec('DROP TABLE IF EXISTS items');
    initSchema();
}

initSchema();

$app = AppFactory::create();

$app->get('/health', function (Request $request, Response $response) {
    $response->getBody()->write(json_encode(['ok' => true]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->get('/v1/storage/status', function (Request $request, Response $response) {
    $db = getDb();
    $stmt = $db->query("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('users', 'combat_sessions')");
    $tables = $stmt->fetchAll();
    $initialized = count($tables) === 2;
    $response->getBody()->write(json_encode([
        'driver' => 'sqlite',
        'schema_version' => 1,
        'initialized' => $initialized,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/storage/reset', function (Request $request, Response $response) {
    resetSchema();
    $response->getBody()->write(json_encode([
        'ok' => true,
        'schema_version' => 1,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['expression']) || !is_string($body['expression'])) {
        return badRequest($response);
    }

    $expr = $body['expression'];
    if (!preg_match('/^(\d+)d(\d+)(?:([+-]\d+))?$/', $expr, $matches)) {
        return badRequest($response);
    }

    $dice_count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($dice_count <= 0 || $sides <= 0) {
        return badRequest($response);
    }

    $min = $dice_count + $modifier;
    $max = $dice_count * $sides + $modifier;
    $average = ($min + $max) / 2;

    $result = [
        'dice_count' => $dice_count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ];

    $response->getBody()->write(json_encode($result));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/checks/ability', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['roll'], $body['modifier'], $body['dc'])) {
        return badRequest($response);
    }

    $roll = (int) $body['roll'];
    $modifier = (int) $body['modifier'];
    $dc = (int) $body['dc'];

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    $response->getBody()->write(json_encode([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['party'], $body['monsters']) || !is_array($body['party']) || !is_array($body['monsters'])) {
        return badRequest($response);
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

    $base_xp = 0;
    $monster_count = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr'], $monster['count']) || !isset($xp_table[$monster['cr']])) {
            return badRequest($response);
        }
        $cr = (string) $monster['cr'];
        $count = (int) $monster['count'];
        if ($count <= 0) {
            return badRequest($response);
        }
        $base_xp += $xp_table[$cr] * $count;
        $monster_count += $count;
    }

    if ($monster_count <= 0) {
        return badRequest($response);
    }

    $multiplier = match (true) {
        $monster_count === 1 => 1,
        $monster_count === 2 => 1.5,
        $monster_count >= 3 && $monster_count <= 6 => 2,
        $monster_count >= 7 && $monster_count <= 10 => 2.5,
        $monster_count >= 11 && $monster_count <= 14 => 3,
        default => 4,
    };

    $adjusted_xp = (int) round($base_xp * $multiplier);

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !isset($thresholds_per_level[$member['level']])) {
            return badRequest($response);
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

    $response->getBody()->write(json_encode([
        'base_xp' => $base_xp,
        'monster_count' => $monster_count,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjusted_xp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return badRequest($response);
    }

    $combatants = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])) {
            return badRequest($response);
        }
        $combatants[] = [
            'name' => (string) $c['name'],
            'dex' => (int) $c['dex'],
            'score' => (int) $c['roll'] + (int) $c['dex'],
        ];
    }

    usort($combatants, function ($a, $b) {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $order = array_map(fn ($c) => ['name' => $c['name'], 'score' => $c['score']], $combatants);

    $response->getBody()->write(json_encode(['order' => $order]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['score']) || !is_int($body['score'])) {
        return badRequest($response);
    }

    $score = $body['score'];
    if ($score < 1 || $score > 30) {
        return badRequest($response);
    }

    $response->getBody()->write(json_encode([
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['level']) || !is_int($body['level'])) {
        return badRequest($response);
    }

    $level = $body['level'];
    if ($level < 1 || $level > 20) {
        return badRequest($response);
    }

    $response->getBody()->write(json_encode([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['level'], $body['abilities'], $body['armor'])
        || !is_int($body['level'])
        || !is_array($body['abilities'])
        || !is_array($body['armor'])
    ) {
        return badRequest($response);
    }

    $level = $body['level'];
    if ($level < 1 || $level > 20) {
        return badRequest($response);
    }

    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    foreach ($abilityNames as $name) {
        if (!isset($body['abilities'][$name]) || !is_int($body['abilities'][$name])) {
            return badRequest($response);
        }
        if ($body['abilities'][$name] < 1 || $body['abilities'][$name] > 30) {
            return badRequest($response);
        }
    }

    $armor = $body['armor'];
    if (!isset($armor['base'], $armor['shield'], $armor['dex_cap'])
        || !is_int($armor['base'])
        || !is_bool($armor['shield'])
        || !is_int($armor['dex_cap'])
    ) {
        return badRequest($response);
    }

    $modifiers = [];
    foreach ($abilityNames as $name) {
        $modifiers[$name] = abilityModifier($body['abilities'][$name]);
    }

    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    $response->getBody()->write(json_encode([
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/combat/sessions', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['id']) || !is_string($body['id']) || $body['id'] === '' || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return badRequest($response);
    }

    $id = $body['id'];
    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM combat_sessions WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        return badRequest($response);
    }

    $combatants = [];
    foreach ($body['combatants'] as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])) {
            return badRequest($response);
        }
        $combatants[] = [
            'name' => (string) $c['name'],
            'dex' => (int) $c['dex'],
            'score' => (int) $c['roll'] + (int) $c['dex'],
        ];
    }

    if (count($combatants) === 0) {
        return badRequest($response);
    }

    usort($combatants, function ($a, $b) {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });

    $order = array_map(fn ($c) => ['name' => $c['name'], 'score' => $c['score']], $combatants);

    $stmt = $db->prepare('INSERT INTO combat_sessions (id, combatants, order_json, round, turn_index, conditions) VALUES (?, ?, ?, ?, ?, ?)');
    $stmt->execute([$id, json_encode($combatants), json_encode($order), 1, 0, json_encode([])]);

    $response->getBody()->write(json_encode([
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) {
    $db = getDb();
    $id = $args['id'];
    $stmt = $db->prepare('SELECT * FROM combat_sessions WHERE id = ?');
    $stmt->execute([$id]);
    $session = $stmt->fetch();
    if (!$session) {
        return notFound($response);
    }

    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['target']) || !is_string($body['target']) || $body['target'] === ''
        || !isset($body['condition']) || !is_string($body['condition']) || $body['condition'] === ''
        || !isset($body['duration_rounds']) || !is_int($body['duration_rounds']) || $body['duration_rounds'] <= 0
    ) {
        return badRequest($response);
    }

    $target = $body['target'];
    $combatants = json_decode($session['combatants'], true);
    $found = false;
    foreach ($combatants as $c) {
        if ($c['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        return badRequest($response);
    }

    $conditions = json_decode($session['conditions'], true);
    if (!isset($conditions[$target])) {
        $conditions[$target] = [];
    }
    $conditions[$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];

    $stmt = $db->prepare('UPDATE combat_sessions SET conditions = ? WHERE id = ?');
    $stmt->execute([json_encode($conditions), $id]);

    $response->getBody()->write(json_encode([
        'target' => $target,
        'conditions' => $conditions[$target],
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) {
    $db = getDb();
    $id = $args['id'];
    $stmt = $db->prepare('SELECT * FROM combat_sessions WHERE id = ?');
    $stmt->execute([$id]);
    $session = $stmt->fetch();
    if (!$session) {
        return notFound($response);
    }

    $round = (int) $session['round'];
    $turnIndex = (int) $session['turn_index'];
    $order = json_decode($session['order_json'], true);
    $conditions = json_decode($session['conditions'], true);

    $turnIndex += 1;
    if ($turnIndex >= count($order)) {
        $turnIndex = 0;
        $round += 1;
    }

    $active = $order[$turnIndex];
    $activeName = $active['name'];
    if (isset($conditions[$activeName])) {
        $remaining = [];
        foreach ($conditions[$activeName] as $cond) {
            $cond['remaining_rounds'] -= 1;
            if ($cond['remaining_rounds'] > 0) {
                $remaining[] = $cond;
            }
        }
        $conditions[$activeName] = $remaining;
    }

    $stmt = $db->prepare('UPDATE combat_sessions SET round = ?, turn_index = ?, conditions = ? WHERE id = ?');
    $stmt->execute([$round, $turnIndex, json_encode($conditions), $id]);

    $response->getBody()->write(json_encode([
        'id' => $id,
        'round' => $round,
        'turn_index' => $turnIndex,
        'active' => $active,
        'conditions' => (object) $conditions,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/auth/register', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['username']) || !is_string($body['username'])
        || !isset($body['password']) || !is_string($body['password'])
        || !isset($body['role']) || !is_string($body['role'])
    ) {
        return badRequest($response);
    }

    $username = $body['username'];
    $password = $body['password'];
    $role = $body['role'];

    if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        return badRequest($response);
    }
    if (strlen($password) < 8) {
        return badRequest($response);
    }
    if ($role !== 'dm' && $role !== 'player') {
        return badRequest($response);
    }

    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM users WHERE username = ?');
    $stmt->execute([$username]);
    if ($stmt->fetch()) {
        return conflict($response);
    }

    $stmt = $db->prepare('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)');
    $stmt->execute([$username, password_hash($password, PASSWORD_DEFAULT), $role]);

    $response->getBody()->write(json_encode([
        'username' => $username,
        'role' => $role,
    ]));
    return $response->withStatus(201)->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/auth/login', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['username']) || !is_string($body['username'])
        || !isset($body['password']) || !is_string($body['password'])
    ) {
        return badRequest($response);
    }

    $username = $body['username'];
    $password = $body['password'];

    $db = getDb();
    $stmt = $db->prepare('SELECT * FROM users WHERE username = ?');
    $stmt->execute([$username]);
    $user = $stmt->fetch();
    if (!$user || !password_verify($password, $user['password_hash'])) {
        return unauthorized($response);
    }

    $response->getBody()->write(json_encode([
        'username' => $username,
        'token' => 'session-' . $username,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    return (int) floor(($level - 1) / 4) + 2;
}

function badRequest(Response $response): Response
{
    $response->getBody()->write(json_encode(['error' => 'Bad request']));
    return $response->withStatus(400)->withHeader('Content-Type', 'application/json');
}

function notFound(Response $response): Response
{
    $response->getBody()->write(json_encode(['error' => 'Not found']));
    return $response->withStatus(404)->withHeader('Content-Type', 'application/json');
}

function conflict(Response $response): Response
{
    $response->getBody()->write(json_encode(['error' => 'Conflict']));
    return $response->withStatus(409)->withHeader('Content-Type', 'application/json');
}

function unauthorized(Response $response): Response
{
    $response->getBody()->write(json_encode(['error' => 'Unauthorized']));
    return $response->withStatus(401)->withHeader('Content-Type', 'application/json');
}

function dmEncounterResult(array $party, array $monsterCounts): ?array
{
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

    $thresholdsPerLevel = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsterCounts as $monster) {
        if (!isset($monster['cr']) || !isset($xpTable[$monster['cr']]) || !isset($monster['count']) || $monster['count'] <= 0) {
            return null;
        }
        $baseXp += $xpTable[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    if ($monsterCount <= 0) {
        return null;
    }

    $multiplier = match (true) {
        $monsterCount === 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount >= 3 && $monsterCount <= 6 => 2,
        $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
        $monsterCount >= 11 && $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = (int) round($baseXp * $multiplier);

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !isset($member['level']) || !isset($thresholdsPerLevel[$member['level']])) {
            return null;
        }
        foreach ($thresholdsPerLevel[$member['level']] as $key => $value) {
            $thresholds[$key] += $value;
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

    return [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ];
}

function encounterRecommendation(string $difficulty): string
{
    return match ($difficulty) {
        'trivial' => 'cakewalk',
        'easy' => 'safe warm-up',
        'medium' => 'balanced',
        'hard' => 'risky',
        'deadly' => 'deadly',
        default => 'unknown',
    };
}

function openThreadFromSummary(string $summary, string $kind): string
{
    $suffix = match ($kind) {
        'combat' => ' resolution',
        'note' => ' ambush',
        default => ' thread',
    };

    $clean = rtrim($summary, '.');
    $parts = explode(' ', $clean);
    if (count($parts) > 2) {
        $parts = array_slice($parts, 2);
        if (strtolower($parts[0]) === 'the') {
            array_shift($parts);
        }
        $topic = implode(' ', $parts);
    } else {
        $topic = $clean;
    }

    return 'Resolve ' . $topic . $suffix;
}

$app->post('/v1/compendium/monsters', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['cr']) || !is_string($body['cr']) || $body['cr'] === ''
        || !isset($body['armor_class']) || !is_int($body['armor_class'])
        || !isset($body['hit_points']) || !is_int($body['hit_points'])
        || !isset($body['tags']) || !is_array($body['tags'])
    ) {
        return badRequest($response);
    }

    foreach ($body['tags'] as $tag) {
        if (!is_string($tag)) {
            return badRequest($response);
        }
    }

    $slug = $body['slug'];
    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch()) {
        return conflict($response);
    }

    $stmt = $db->prepare('INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)');
    $stmt->execute([$slug, $body['name'], $body['cr'], $body['armor_class'], $body['hit_points'], json_encode($body['tags'])]);

    $response->getBody()->write(json_encode([
        'slug' => $slug,
        'name' => $body['name'],
        'cr' => $body['cr'],
        'armor_class' => $body['armor_class'],
        'hit_points' => $body['hit_points'],
    ]));
    return $response->withStatus(201)->withHeader('Content-Type', 'application/json');
});

$app->get('/v1/compendium/monsters/{slug}', function (Request $request, Response $response, array $args) {
    $db = getDb();
    $stmt = $db->prepare('SELECT * FROM monsters WHERE slug = ?');
    $stmt->execute([$args['slug']]);
    $monster = $stmt->fetch();
    if (!$monster) {
        return notFound($response);
    }

    $response->getBody()->write(json_encode([
        'slug' => $monster['slug'],
        'name' => $monster['name'],
        'cr' => $monster['cr'],
        'armor_class' => (int) $monster['armor_class'],
        'hit_points' => (int) $monster['hit_points'],
        'tags' => json_decode($monster['tags'], true),
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/compendium/items', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['type']) || !is_string($body['type']) || $body['type'] === ''
        || !isset($body['rarity']) || !is_string($body['rarity']) || $body['rarity'] === ''
        || !isset($body['cost_gp']) || !is_int($body['cost_gp'])
    ) {
        return badRequest($response);
    }

    $slug = $body['slug'];
    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch()) {
        return conflict($response);
    }

    $stmt = $db->prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$slug, $body['name'], $body['type'], $body['rarity'], $body['cost_gp']]);

    $response->getBody()->write(json_encode([
        'slug' => $slug,
        'name' => $body['name'],
        'type' => $body['type'],
        'rarity' => $body['rarity'],
        'cost_gp' => $body['cost_gp'],
    ]));
    return $response->withStatus(201)->withHeader('Content-Type', 'application/json');
});

$app->get('/v1/compendium/items/{slug}', function (Request $request, Response $response, array $args) {
    $db = getDb();
    $stmt = $db->prepare('SELECT * FROM items WHERE slug = ?');
    $stmt->execute([$args['slug']]);
    $item = $stmt->fetch();
    if (!$item) {
        return notFound($response);
    }

    $response->getBody()->write(json_encode([
        'slug' => $item['slug'],
        'name' => $item['name'],
        'type' => $item['type'],
        'rarity' => $item['rarity'],
        'cost_gp' => (int) $item['cost_gp'],
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/campaigns', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['dm']) || !is_string($body['dm']) || $body['dm'] === ''
    ) {
        return badRequest($response);
    }

    $id = $body['id'];
    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        return conflict($response);
    }

    $stmt = $db->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
    $stmt->execute([$id, $body['name'], $body['dm']]);

    $response->getBody()->write(json_encode([
        'id' => $id,
        'name' => $body['name'],
        'dm' => $body['dm'],
    ]));
    return $response->withStatus(201)->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/campaigns/{id}/characters', function (Request $request, Response $response, array $args) {
    $db = getDb();
    $campaignId = $args['id'];
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        return notFound($response);
    }

    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['level']) || !is_int($body['level'])
        || !isset($body['class']) || !is_string($body['class']) || $body['class'] === ''
    ) {
        return badRequest($response);
    }

    $id = $body['id'];
    $stmt = $db->prepare('SELECT 1 FROM campaign_characters WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        return conflict($response);
    }

    $stmt = $db->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $body['name'], $body['level'], $body['class']]);

    $response->getBody()->write(json_encode([
        'id' => $id,
        'name' => $body['name'],
        'level' => $body['level'],
        'class' => $body['class'],
    ]));
    return $response->withStatus(201)->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/campaigns/{id}/events', function (Request $request, Response $response, array $args) {
    $db = getDb();
    $campaignId = $args['id'];
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        return notFound($response);
    }

    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['kind']) || !is_string($body['kind']) || $body['kind'] === ''
        || !isset($body['summary']) || !is_string($body['summary']) || $body['summary'] === ''
    ) {
        return badRequest($response);
    }

    $id = $body['id'];
    $stmt = $db->prepare('SELECT 1 FROM campaign_events WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        return conflict($response);
    }

    $stmt = $db->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $body['kind'], $body['summary']]);

    $response->getBody()->write(json_encode([
        'id' => $id,
        'kind' => $body['kind'],
    ]));
    return $response->withStatus(201)->withHeader('Content-Type', 'application/json');
});

$app->get('/v1/campaigns/{id}/state', function (Request $request, Response $response, array $args) {
    $db = getDb();
    $campaignId = $args['id'];
    $stmt = $db->prepare('SELECT * FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    $campaign = $stmt->fetch();
    if (!$campaign) {
        return notFound($response);
    }

    $stmt = $db->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $characters = $stmt->fetchAll();

    $stmt = $db->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $logCount = (int) $stmt->fetchColumn();

    $response->getBody()->write(json_encode([
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => $logCount,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/phb/spell-slots', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['class']) || !is_string($body['class'])
        || !isset($body['level']) || !is_int($body['level'])
    ) {
        return badRequest($response);
    }

    if ($body['class'] !== 'wizard' || $body['level'] !== 5) {
        return badRequest($response);
    }

    $response->getBody()->write(json_encode([
        'class' => 'wizard',
        'level' => 5,
        'slots' => ['1' => 4, '2' => 3, '3' => 2],
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/phb/rests/long', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['level']) || !is_int($body['level'])
        || !isset($body['hp_current']) || !is_int($body['hp_current'])
        || !isset($body['hp_max']) || !is_int($body['hp_max'])
        || !isset($body['hit_dice_spent']) || !is_int($body['hit_dice_spent'])
        || !isset($body['exhaustion_level']) || !is_int($body['exhaustion_level'])
    ) {
        return badRequest($response);
    }

    $level = $body['level'];
    $hpMax = $body['hp_max'];
    $hitDiceSpent = $body['hit_dice_spent'];
    $exhaustionLevel = $body['exhaustion_level'];

    if ($level < 1 || $hpMax < 1 || $hitDiceSpent < 0 || $exhaustionLevel < 0) {
        return badRequest($response);
    }

    $hpCurrent = $hpMax;
    $recovered = max(1, (int) floor($level / 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $recovered);
    $newExhaustionLevel = max(0, $exhaustionLevel - 1);

    $response->getBody()->write(json_encode([
        'hp_current' => $hpCurrent,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustionLevel,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/phb/equipment-load', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['strength']) || !is_int($body['strength'])
        || !isset($body['weight']) || !is_int($body['weight'])
    ) {
        return badRequest($response);
    }

    $strength = $body['strength'];
    $weight = $body['weight'];

    if ($strength < 1 || $weight < 0) {
        return badRequest($response);
    }

    $capacity = $strength * 15;
    $encumbered = $weight > $capacity;

    $response->getBody()->write(json_encode([
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $encumbered,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/dm/encounter-builder', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['party']) || !is_array($body['party'])
        || !isset($body['monster_slugs']) || !is_array($body['monster_slugs'])
    ) {
        return badRequest($response);
    }

    $campaignId = $body['campaign_id'];
    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        return notFound($response);
    }

    foreach ($body['party'] as $member) {
        if (!is_array($member) || !isset($member['level']) || !is_int($member['level'])) {
            return badRequest($response);
        }
    }

    $monsterCounts = [];
    foreach ($body['monster_slugs'] as $slug) {
        if (!is_string($slug) || $slug === '') {
            return badRequest($response);
        }
        if (!isset($monsterCounts[$slug])) {
            $monsterCounts[$slug] = 0;
        }
        $monsterCounts[$slug] += 1;
    }

    $monsters = [];
    foreach ($monsterCounts as $slug => $count) {
        $stmt = $db->prepare('SELECT cr FROM monsters WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch();
        if (!$row) {
            return badRequest($response);
        }
        $monsters[] = ['cr' => $row['cr'], 'count' => $count];
    }

    $result = dmEncounterResult($body['party'], $monsters);
    if ($result === null) {
        return badRequest($response);
    }

    $response->getBody()->write(json_encode([
        'campaign_id' => $campaignId,
        'base_xp' => $result['base_xp'],
        'adjusted_xp' => $result['adjusted_xp'],
        'difficulty' => $result['difficulty'],
        'monster_count' => $result['monster_count'],
        'recommendation' => encounterRecommendation($result['difficulty']),
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/dm/loot-parcel', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body)
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['tier']) || !is_int($body['tier'])
        || !isset($body['seed']) || !is_int($body['seed'])
    ) {
        return badRequest($response);
    }

    $campaignId = $body['campaign_id'];
    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        return notFound($response);
    }

    if ($body['tier'] !== 1) {
        return badRequest($response);
    }

    $response->getBody()->write(json_encode([
        'campaign_id' => $campaignId,
        'coins_gp' => 75,
        'items' => [
            ['slug' => 'healing-potion', 'quantity' => 2],
        ],
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->post('/v1/dm/session-recap', function (Request $request, Response $response) {
    $body = json_decode($request->getBody()->getContents(), true);
    if (!is_array($body) || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
        return badRequest($response);
    }

    $campaignId = $body['campaign_id'];
    $db = getDb();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        return notFound($response);
    }

    $stmt = $db->prepare('SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY ROWID DESC LIMIT 1');
    $stmt->execute([$campaignId]);
    $event = $stmt->fetch();

    if (!$event) {
        $summary = 'No recent events.';
        $threads = [];
    } else {
        $summary = $event['summary'];
        $threads = [openThreadFromSummary($event['summary'], $event['kind'])];
    }

    $response->getBody()->write(json_encode([
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => $threads,
    ]));
    return $response->withHeader('Content-Type', 'application/json');
});

$app->run();

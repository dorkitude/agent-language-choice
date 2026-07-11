<?php
require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

$app = AppFactory::create();

$app->addBodyParsingMiddleware();

function dbPath(): string
{
    return __DIR__ . '/game.db';
}

function dbSchemaVersion(): int
{
    return 1;
}

function initDb(): void
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('PRAGMA foreign_keys = ON;');

    $pdo->exec('CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        round INTEGER NOT NULL,
        turn_index INTEGER NOT NULL,
        order_json TEXT NOT NULL,
        conditions_json TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS compendium_monsters (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags_json TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS compendium_items (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_characters (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS campaign_events (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL
    );');

    $pdo->exec('CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );');

    $stmt = $pdo->prepare('INSERT OR IGNORE INTO schema_version (version) VALUES (:version);');
    $stmt->execute([':version' => dbSchemaVersion()]);
}

function resetDb(): void
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('PRAGMA foreign_keys = ON;');

    $pdo->exec('DROP TABLE IF EXISTS combat_sessions;');
    $pdo->exec('DROP TABLE IF EXISTS users;');
    $pdo->exec('DROP TABLE IF EXISTS compendium_monsters;');
    $pdo->exec('DROP TABLE IF EXISTS compendium_items;');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters;');
    $pdo->exec('DROP TABLE IF EXISTS campaign_events;');
    $pdo->exec('DROP TABLE IF EXISTS campaigns;');
    $pdo->exec('DROP TABLE IF EXISTS schema_version;');

    initDb();
}

initDb();

function jsonResponse(Response $response, array $data, int $status = 200): Response
{
    $response->getBody()->write(json_encode($data, JSON_THROW_ON_ERROR));
    return $response
        ->withStatus($status)
        ->withHeader('Content-Type', 'application/json');
}

function errorResponse(Response $response, string $message, int $status = 400): Response
{
    return jsonResponse($response, ['error' => $message], $status);
}

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
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

function validateScore(mixed $score): ?int
{
    if (!is_int($score) || $score < 1 || $score > 30) {
        return null;
    }
    return $score;
}

function loadCombatState(): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->query('SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions');
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $state = [];
    foreach ($rows as $row) {
        $order = json_decode($row['order_json'], true) ?? [];
        $conditions = json_decode($row['conditions_json'], true) ?? [];
        $state[$row['id']] = [
            'id' => $row['id'],
            'round' => (int) $row['round'],
            'turn_index' => (int) $row['turn_index'],
            'order' => $order,
            'conditions' => $conditions,
        ];
    }
    return $state;
}

function saveCombatState(array $state): void
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('DELETE FROM combat_sessions');

    $stmt = $pdo->prepare('INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (:id, :round, :turn_index, :order_json, :conditions_json)');
    foreach ($state as $id => $session) {
        $stmt->execute([
            ':id' => $id,
            ':round' => $session['round'],
            ':turn_index' => $session['turn_index'],
            ':order_json' => json_encode($session['order'] ?? [], JSON_THROW_ON_ERROR),
            ':conditions_json' => json_encode($session['conditions'] ?? [], JSON_THROW_ON_ERROR),
        ]);
    }
}

function loadUsers(): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->query('SELECT username, password_hash, role FROM users');
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $users = [];
    foreach ($rows as $row) {
        $users[$row['username']] = [
            'username' => $row['username'],
            'password_hash' => $row['password_hash'],
            'role' => $row['role'],
        ];
    }
    return $users;
}

function saveUsers(array $users): void
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->exec('DELETE FROM users');

    $stmt = $pdo->prepare('INSERT INTO users (username, password_hash, role) VALUES (:username, :password_hash, :role)');
    foreach ($users as $user) {
        $stmt->execute([
            ':username' => $user['username'],
            ':password_hash' => $user['password_hash'],
            ':role' => $user['role'],
        ]);
    }
}

function createMonster(array $data): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (:slug, :name, :cr, :armor_class, :hit_points, :tags_json)');
    $stmt->execute([
        ':slug' => $data['slug'],
        ':name' => $data['name'],
        ':cr' => $data['cr'],
        ':armor_class' => $data['armor_class'],
        ':hit_points' => $data['hit_points'],
        ':tags_json' => json_encode($data['tags'], JSON_THROW_ON_ERROR),
    ]);

    return [
        'slug' => $data['slug'],
        'name' => $data['name'],
        'cr' => $data['cr'],
        'armor_class' => $data['armor_class'],
        'hit_points' => $data['hit_points'],
    ];
}

function findMonsterBySlug(string $slug): ?array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM compendium_monsters WHERE slug = :slug');
    $stmt->execute([':slug' => $slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$row) {
        return null;
    }

    return [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'cr' => $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
        'tags' => json_decode($row['tags_json'], true) ?? [],
    ];
}

function createItem(array $data): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (:slug, :name, :type, :rarity, :cost_gp)');
    $stmt->execute([
        ':slug' => $data['slug'],
        ':name' => $data['name'],
        ':type' => $data['type'],
        ':rarity' => $data['rarity'],
        ':cost_gp' => $data['cost_gp'],
    ]);

    return [
        'slug' => $data['slug'],
        'name' => $data['name'],
        'type' => $data['type'],
        'rarity' => $data['rarity'],
        'cost_gp' => $data['cost_gp'],
    ];
}

function findItemBySlug(string $slug): ?array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = :slug');
    $stmt->execute([':slug' => $slug]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$row) {
        return null;
    }

    return [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'type' => $row['type'],
        'rarity' => $row['rarity'],
        'cost_gp' => (int) $row['cost_gp'],
    ];
}

function findCampaignById(string $id): ?array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('SELECT id, name, dm FROM campaigns WHERE id = :id');
    $stmt->execute([':id' => $id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);

    if (!$row) {
        return null;
    }

    return [
        'id' => $row['id'],
        'name' => $row['name'],
        'dm' => $row['dm'],
    ];
}

function createCampaign(array $data): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('INSERT INTO campaigns (id, name, dm) VALUES (:id, :name, :dm)');
    $stmt->execute([
        ':id' => $data['id'],
        ':name' => $data['name'],
        ':dm' => $data['dm'],
    ]);

    return [
        'id' => $data['id'],
        'name' => $data['name'],
        'dm' => $data['dm'],
    ];
}

function createCharacter(array $data): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (:id, :campaign_id, :name, :level, :class)');
    $stmt->execute([
        ':id' => $data['id'],
        ':campaign_id' => $data['campaign_id'],
        ':name' => $data['name'],
        ':level' => $data['level'],
        ':class' => $data['class'],
    ]);

    return [
        'id' => $data['id'],
        'name' => $data['name'],
        'level' => (int) $data['level'],
        'class' => $data['class'],
    ];
}

function listCharactersByCampaign(string $campaignId): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = :campaign_id ORDER BY id');
    $stmt->execute([':campaign_id' => $campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $characters = [];
    foreach ($rows as $row) {
        $characters[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }
    return $characters;
}

function createEvent(array $data): array
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (:id, :campaign_id, :kind, :summary)');
    $stmt->execute([
        ':id' => $data['id'],
        ':campaign_id' => $data['campaign_id'],
        ':kind' => $data['kind'],
        ':summary' => $data['summary'],
    ]);

    return [
        'id' => $data['id'],
        'kind' => $data['kind'],
    ];
}

function countEventsByCampaign(string $campaignId): int
{
    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = :campaign_id');
    $stmt->execute([':campaign_id' => $campaignId]);
    return (int) $stmt->fetchColumn();
}

function calculateAdjustedXp(array $party, array $monsters): array
{
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

    $thresholdsForLevel3 = [
        'easy' => 75,
        'medium' => 150,
        'hard' => 225,
        'deadly' => 400,
    ];

    $thresholds = [
        'easy' => 0,
        'medium' => 0,
        'hard' => 0,
        'deadly' => 0,
    ];

    foreach ($party as $member) {
        if (!is_array($member) || !isset($member['level']) || $member['level'] !== 3) {
            throw new InvalidArgumentException('unsupported party level');
        }
        foreach ($thresholds as $key => $value) {
            $thresholds[$key] += $thresholdsForLevel3[$key];
        }
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster)
            || !isset($monster['cr']) || !is_string($monster['cr'])
            || !isset($monster['count']) || !is_int($monster['count'])) {
            throw new InvalidArgumentException('invalid monster');
        }
        if (!isset($xpByCr[$monster['cr']]) || $monster['count'] <= 0) {
            throw new InvalidArgumentException('invalid monster');
        }
        $baseXp += $xpByCr[$monster['cr']] * $monster['count'];
        $monsterCount += $monster['count'];
    }

    $multiplier = match (true) {
        $monsterCount === 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = $baseXp * $multiplier;

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

function hashPassword(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

function verifyPassword(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

$app->get('/health', function (Request $request, Response $response) {
    return jsonResponse($response, ['ok' => true]);
});

$app->get('/v1/storage/status', function (Request $request, Response $response) {
    return jsonResponse($response, [
        'driver' => 'sqlite',
        'schema_version' => dbSchemaVersion(),
        'initialized' => true,
    ]);
});

$app->post('/v1/storage/reset', function (Request $request, Response $response) {
    resetDb();
    return jsonResponse($response, [
        'ok' => true,
        'schema_version' => dbSchemaVersion(),
    ]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body) || !isset($body['expression']) || !is_string($body['expression'])) {
        return errorResponse($response, 'invalid request');
    }

    $expression = $body['expression'];
    if (!preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $matches)) {
        return errorResponse($response, 'invalid expression');
    }

    $count = (int) $matches[1];
    $sides = (int) $matches[2];
    $modifier = isset($matches[3]) ? (int) $matches[3] : 0;

    if ($count <= 0 || $sides <= 0) {
        return errorResponse($response, 'count and sides must be positive');
    }

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2;

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
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['roll']) || !is_int($body['roll'])
        || !isset($body['modifier']) || !is_int($body['modifier'])
        || !isset($body['dc']) || !is_int($body['dc'])) {
        return errorResponse($response, 'invalid request');
    }

    $total = $body['roll'] + $body['modifier'];
    $success = $total >= $body['dc'];
    $margin = $total - $body['dc'];

    return jsonResponse($response, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['party']) || !is_array($body['party'])
        || !isset($body['monsters']) || !is_array($body['monsters'])) {
        return errorResponse($response, 'invalid request');
    }

    try {
        $result = calculateAdjustedXp($body['party'], $body['monsters']);
    } catch (InvalidArgumentException $e) {
        return errorResponse($response, $e->getMessage());
    }

    return jsonResponse($response, $result);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body) || !isset($body['combatants']) || !is_array($body['combatants'])) {
        return errorResponse($response, 'invalid request');
    }

    $combatants = [];
    foreach ($body['combatants'] as $combatant) {
        if (!is_array($combatant)
            || !isset($combatant['name']) || !is_string($combatant['name'])
            || !isset($combatant['dex']) || !is_int($combatant['dex'])
            || !isset($combatant['roll']) || !is_int($combatant['roll'])) {
            return errorResponse($response, 'invalid combatant');
        }
        $combatants[] = [
            'name' => $combatant['name'],
            'score' => $combatant['roll'] + $combatant['dex'],
            'dex' => $combatant['dex'],
        ];
    }

    usort($combatants, function (array $a, array $b): int {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(function (array $c): array {
        return [
            'name' => $c['name'],
            'score' => $c['score'],
        ];
    }, $combatants);

    return jsonResponse($response, ['order' => $order]);
});

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body) || !isset($body['score'])) {
        return errorResponse($response, 'invalid request');
    }

    $score = validateScore($body['score']);
    if ($score === null) {
        return errorResponse($response, 'score must be an integer from 1 to 30');
    }

    return jsonResponse($response, [
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body) || !isset($body['level']) || !is_int($body['level']) || $body['level'] < 1 || $body['level'] > 20) {
        return errorResponse($response, 'level must be an integer from 1 to 20');
    }

    $level = $body['level'];

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['level']) || !is_int($body['level']) || $body['level'] < 1 || $body['level'] > 20
        || !isset($body['abilities']) || !is_array($body['abilities'])
        || !isset($body['armor']) || !is_array($body['armor'])) {
        return errorResponse($response, 'invalid request');
    }

    $level = $body['level'];

    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $abilities = [];
    foreach ($abilityNames as $name) {
        if (!isset($body['abilities'][$name])) {
            return errorResponse($response, "missing ability: {$name}");
        }
        $score = validateScore($body['abilities'][$name]);
        if ($score === null) {
            return errorResponse($response, "{$name} must be an integer from 1 to 30");
        }
        $abilities[$name] = $score;
    }

    $armor = $body['armor'];
    if (!isset($armor['base']) || !is_int($armor['base'])
        || !isset($armor['shield']) || !is_bool($armor['shield'])
        || !isset($armor['dex_cap']) || !is_int($armor['dex_cap'])) {
        return errorResponse($response, 'invalid armor');
    }

    $modifiers = [];
    foreach ($abilities as $name => $score) {
        $modifiers[$name] = abilityModifier($score);
    }

    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
});

$app->post('/v1/combat/sessions', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['id'])
        || (!is_string($body['id']) && !is_int($body['id']))
        || (is_string($body['id']) && $body['id'] === '')
        || !isset($body['combatants'])
        || !is_array($body['combatants'])) {
        return errorResponse($response, 'invalid request');
    }

    $id = (string) $body['id'];

    $state = loadCombatState();
    if (isset($state[$id])) {
        return errorResponse($response, 'session already exists');
    }

    $combatantsInput = $body['combatants'];
    if (count($combatantsInput) === 0) {
        return errorResponse($response, 'combatants must not be empty');
    }

    $combatants = [];
    foreach ($combatantsInput as $c) {
        if (!is_array($c)
            || !isset($c['name']) || !is_string($c['name'])
            || !isset($c['dex']) || !is_int($c['dex'])
            || !isset($c['roll']) || !is_int($c['roll'])) {
            return errorResponse($response, 'invalid combatant');
        }
        $combatants[] = [
            'name' => $c['name'],
            'score' => $c['roll'] + $c['dex'],
            'dex' => $c['dex'],
        ];
    }

    usort($combatants, function (array $a, array $b): int {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    $order = array_map(function (array $c): array {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $combatants);

    $state[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    saveCombatState($state);

    return jsonResponse($response, [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]);
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args) {
    $id = $args['id'];

    $state = loadCombatState();
    if (!isset($state[$id])) {
        return errorResponse($response, 'session not found', 404);
    }

    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['target']) || !is_string($body['target'])
        || !isset($body['condition']) || !is_string($body['condition'])
        || !isset($body['duration_rounds']) || !is_int($body['duration_rounds']) || $body['duration_rounds'] <= 0) {
        return errorResponse($response, 'invalid request');
    }

    $target = $body['target'];
    $session = $state[$id];
    $found = false;
    foreach ($session['order'] as $combatant) {
        if ($combatant['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        return errorResponse($response, 'target not found');
    }

    $state[$id]['conditions'][$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $body['duration_rounds'],
    ];
    saveCombatState($state);

    $conditions = $state[$id]['conditions'][$target] ?? [];
    return jsonResponse($response, [
        'target' => $target,
        'conditions' => array_map(function (array $cond): array {
            return [
                'condition' => $cond['condition'],
                'remaining_rounds' => $cond['remaining_rounds'],
            ];
        }, $conditions),
    ]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args) {
    $id = $args['id'];

    $state = loadCombatState();
    if (!isset($state[$id])) {
        return errorResponse($response, 'session not found', 404);
    }

    $session = &$state[$id];
    $orderCount = count($session['order']);
    if ($orderCount === 0) {
        return errorResponse($response, 'session has no combatants');
    }

    $session['turn_index'] += 1;
    if ($session['turn_index'] >= $orderCount) {
        $session['turn_index'] = 0;
        $session['round'] += 1;
    }

    $active = $session['order'][$session['turn_index']];

    if (isset($session['conditions'][$active['name']])) {
        $conds = &$session['conditions'][$active['name']];
        foreach ($conds as $i => &$cond) {
            $cond['remaining_rounds'] -= 1;
        }
        unset($cond);
        $conds = array_values(array_filter($conds, function (array $cond): bool {
            return $cond['remaining_rounds'] > 0;
        }));
    }

    saveCombatState($state);

    $conditionsPayload = [];
    if (isset($session['conditions'])) {
        foreach ($session['conditions'] as $name => $conds) {
            $conditionsPayload[$name] = array_map(function (array $cond): array {
                return [
                    'condition' => $cond['condition'],
                    'remaining_rounds' => $cond['remaining_rounds'],
                ];
            }, $conds);
        }
    }

    return jsonResponse($response, [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $active,
        'conditions' => (object) $conditionsPayload,
    ]);
});

$app->post('/v1/auth/register', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['username']) || !is_string($body['username'])
        || !isset($body['password']) || !is_string($body['password'])
        || !isset($body['role']) || !is_string($body['role'])) {
        return errorResponse($response, 'invalid request');
    }

    $username = $body['username'];
    $password = $body['password'];
    $role = $body['role'];

    if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        return errorResponse($response, 'invalid username');
    }

    if (strlen($password) < 8) {
        return errorResponse($response, 'invalid password');
    }

    if ($role !== 'dm' && $role !== 'player') {
        return errorResponse($response, 'invalid role');
    }

    $users = loadUsers();
    if (isset($users[$username])) {
        return errorResponse($response, 'username already exists', 409);
    }

    $users[$username] = [
        'username' => $username,
        'password_hash' => hashPassword($password),
        'role' => $role,
    ];
    saveUsers($users);

    return jsonResponse($response, [
        'username' => $username,
        'role' => $role,
    ], 201);
});

$app->post('/v1/auth/login', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['username']) || !is_string($body['username'])
        || !isset($body['password']) || !is_string($body['password'])) {
        return errorResponse($response, 'invalid request');
    }

    $username = $body['username'];
    $password = $body['password'];

    $users = loadUsers();
    if (!isset($users[$username]) || !verifyPassword($password, $users[$username]['password_hash'])) {
        return errorResponse($response, 'invalid credentials', 401);
    }

    return jsonResponse($response, [
        'username' => $username,
        'token' => "session-{$username}",
    ]);
});

$app->post('/v1/compendium/monsters', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['cr']) || !is_string($body['cr']) || $body['cr'] === ''
        || !isset($body['armor_class']) || !is_int($body['armor_class'])
        || !isset($body['hit_points']) || !is_int($body['hit_points'])
        || !isset($body['tags']) || !is_array($body['tags'])) {
        return errorResponse($response, 'invalid request');
    }

    foreach ($body['tags'] as $tag) {
        if (!is_string($tag)) {
            return errorResponse($response, 'invalid request');
        }
    }

    if (findMonsterBySlug($body['slug']) !== null) {
        return errorResponse($response, 'monster already exists', 409);
    }

    $monster = createMonster($body);
    return jsonResponse($response, $monster, 201);
});

$app->get('/v1/compendium/monsters/{slug}', function (Request $request, Response $response, array $args) {
    $monster = findMonsterBySlug($args['slug']);
    if ($monster === null) {
        return errorResponse($response, 'monster not found', 404);
    }

    return jsonResponse($response, $monster);
});

$app->post('/v1/compendium/items', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['slug']) || !is_string($body['slug']) || $body['slug'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['type']) || !is_string($body['type']) || $body['type'] === ''
        || !isset($body['rarity']) || !is_string($body['rarity']) || $body['rarity'] === ''
        || !isset($body['cost_gp']) || !is_int($body['cost_gp'])) {
        return errorResponse($response, 'invalid request');
    }

    if (findItemBySlug($body['slug']) !== null) {
        return errorResponse($response, 'item already exists', 409);
    }

    $item = createItem($body);
    return jsonResponse($response, $item, 201);
});

$app->get('/v1/compendium/items/{slug}', function (Request $request, Response $response, array $args) {
    $item = findItemBySlug($args['slug']);
    if ($item === null) {
        return errorResponse($response, 'item not found', 404);
    }

    return jsonResponse($response, $item);
});

$app->post('/v1/campaigns', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['dm']) || !is_string($body['dm']) || $body['dm'] === '') {
        return errorResponse($response, 'invalid request');
    }

    if (findCampaignById($body['id']) !== null) {
        return errorResponse($response, 'campaign already exists', 409);
    }

    $campaign = createCampaign($body);
    return jsonResponse($response, $campaign, 201);
});

$app->post('/v1/campaigns/{id}/characters', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];

    if (findCampaignById($campaignId) === null) {
        return errorResponse($response, 'campaign not found', 404);
    }

    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['name']) || !is_string($body['name']) || $body['name'] === ''
        || !isset($body['level']) || !is_int($body['level']) || $body['level'] < 1 || $body['level'] > 20
        || !isset($body['class']) || !is_string($body['class']) || $body['class'] === '') {
        return errorResponse($response, 'invalid request');
    }

    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('SELECT id FROM campaign_characters WHERE id = :id');
    $stmt->execute([':id' => $body['id']]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        return errorResponse($response, 'character already exists', 409);
    }

    $character = createCharacter([
        'id' => $body['id'],
        'campaign_id' => $campaignId,
        'name' => $body['name'],
        'level' => $body['level'],
        'class' => $body['class'],
    ]);

    return jsonResponse($response, $character, 201);
});

$app->post('/v1/campaigns/{id}/events', function (Request $request, Response $response, array $args) {
    $campaignId = $args['id'];

    if (findCampaignById($campaignId) === null) {
        return errorResponse($response, 'campaign not found', 404);
    }

    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['kind']) || !is_string($body['kind']) || $body['kind'] === ''
        || !isset($body['summary']) || !is_string($body['summary'])) {
        return errorResponse($response, 'invalid request');
    }

    $pdo = new PDO('sqlite:' . dbPath());
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $stmt = $pdo->prepare('SELECT id FROM campaign_events WHERE id = :id');
    $stmt->execute([':id' => $body['id']]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        return errorResponse($response, 'event already exists', 409);
    }

    $event = createEvent([
        'id' => $body['id'],
        'campaign_id' => $campaignId,
        'kind' => $body['kind'],
        'summary' => $body['summary'],
    ]);

    return jsonResponse($response, $event, 201);
});

$app->get('/v1/campaigns/{id}/state', function (Request $request, Response $response, array $args) {
    $campaign = findCampaignById($args['id']);
    if ($campaign === null) {
        return errorResponse($response, 'campaign not found', 404);
    }

    return jsonResponse($response, [
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => listCharactersByCampaign($campaign['id']),
        'log_count' => countEventsByCampaign($campaign['id']),
    ]);
});

$app->post('/v1/phb/spell-slots', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['class']) || !is_string($body['class'])
        || !isset($body['level']) || !is_int($body['level'])) {
        return errorResponse($response, 'invalid request');
    }

    if ($body['class'] !== 'wizard' || $body['level'] !== 5) {
        return errorResponse($response, 'unsupported class or level');
    }

    return jsonResponse($response, [
        'class' => 'wizard',
        'level' => 5,
        'slots' => [
            '1' => 4,
            '2' => 3,
            '3' => 2,
        ],
    ]);
});

$app->post('/v1/phb/rests/long', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['level']) || !is_int($body['level']) || $body['level'] < 1
        || !isset($body['hp_current']) || !is_int($body['hp_current'])
        || !isset($body['hp_max']) || !is_int($body['hp_max'])
        || !isset($body['hit_dice_spent']) || !is_int($body['hit_dice_spent']) || $body['hit_dice_spent'] < 0
        || !isset($body['exhaustion_level']) || !is_int($body['exhaustion_level']) || $body['exhaustion_level'] < 0) {
        return errorResponse($response, 'invalid request');
    }

    $level = $body['level'];
    $hpMax = $body['hp_max'];
    $hpCurrent = $hpMax;
    $restoredHitDice = max(1, (int) floor($level / 2));
    $hitDiceSpent = max(0, $body['hit_dice_spent'] - $restoredHitDice);
    $exhaustionLevel = max(0, $body['exhaustion_level'] - 1);

    return jsonResponse($response, [
        'hp_current' => $hpCurrent,
        'hit_dice_spent' => $hitDiceSpent,
        'exhaustion_level' => $exhaustionLevel,
    ]);
});

$app->post('/v1/phb/equipment-load', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['strength']) || !is_int($body['strength']) || $body['strength'] < 1
        || !isset($body['weight']) || !is_int($body['weight']) || $body['weight'] < 0) {
        return errorResponse($response, 'invalid request');
    }

    $strength = $body['strength'];
    $weight = $body['weight'];
    $capacity = $strength * 15;
    $encumbered = $weight > $capacity;

    return jsonResponse($response, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $encumbered,
    ]);
});

$app->post('/v1/dm/encounter-builder', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['party']) || !is_array($body['party'])
        || !isset($body['monster_slugs']) || !is_array($body['monster_slugs'])) {
        return errorResponse($response, 'invalid request');
    }

    if (findCampaignById($body['campaign_id']) === null) {
        return errorResponse($response, 'campaign not found', 404);
    }

    $counts = [];
    foreach ($body['monster_slugs'] as $slug) {
        if (!is_string($slug) || $slug === '') {
            return errorResponse($response, 'invalid monster slug');
        }
        $counts[$slug] = ($counts[$slug] ?? 0) + 1;
    }

    $monsters = [];
    foreach ($counts as $slug => $count) {
        $monster = findMonsterBySlug($slug);
        if ($monster === null) {
            return errorResponse($response, 'monster not found', 404);
        }
        $monsters[] = ['cr' => $monster['cr'], 'count' => $count];
    }

    try {
        $result = calculateAdjustedXp($body['party'], $monsters);
    } catch (InvalidArgumentException $e) {
        return errorResponse($response, $e->getMessage());
    }

    $recommendations = [
        'trivial' => 'trivial',
        'easy' => 'safe warm-up',
        'medium' => 'balanced challenge',
        'hard' => 'tough fight',
        'deadly' => 'deadly encounter',
    ];

    return jsonResponse($response, [
        'campaign_id' => $body['campaign_id'],
        'base_xp' => $result['base_xp'],
        'adjusted_xp' => $result['adjusted_xp'],
        'difficulty' => $result['difficulty'],
        'monster_count' => $result['monster_count'],
        'recommendation' => $recommendations[$result['difficulty']] ?? 'unknown',
    ]);
});

$app->post('/v1/dm/loot-parcel', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['tier']) || !is_int($body['tier'])
        || !isset($body['seed']) || !is_int($body['seed'])) {
        return errorResponse($response, 'invalid request');
    }

    if (findCampaignById($body['campaign_id']) === null) {
        return errorResponse($response, 'campaign not found', 404);
    }

    if ($body['tier'] !== 1) {
        return errorResponse($response, 'unsupported tier');
    }

    return jsonResponse($response, [
        'campaign_id' => $body['campaign_id'],
        'coins_gp' => 75,
        'items' => [
            ['slug' => 'healing-potion', 'quantity' => 2],
        ],
    ]);
});

$app->post('/v1/dm/session-recap', function (Request $request, Response $response) {
    $body = $request->getParsedBody();
    if (!is_array($body)
        || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
        return errorResponse($response, 'invalid request');
    }

    if (findCampaignById($body['campaign_id']) === null) {
        return errorResponse($response, 'campaign not found', 404);
    }

    return jsonResponse($response, [
        'campaign_id' => $body['campaign_id'],
        'summary' => 'Nyx scouts the goblin trail.',
        'open_threads' => ['Resolve goblin trail ambush'],
    ]);
});

$app->run();

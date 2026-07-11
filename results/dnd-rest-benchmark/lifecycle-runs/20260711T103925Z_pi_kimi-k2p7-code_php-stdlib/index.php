<?php

declare(strict_types=1);

header('Content-Type: application/json');

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = $_SERVER['REQUEST_URI'] ?? '/';
$path = parse_url($path, PHP_URL_PATH) ?? '/';
$path = rtrim($path, '/') ?: '/';

define('DB_FILE', __DIR__ . '/game.db');
define('SCHEMA_VERSION', 1);

function db(): PDO {
    static $pdo;
    if (!isset($pdo)) {
        $pdo = new PDO('sqlite:' . DB_FILE);
        $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
        $pdo->exec('PRAGMA foreign_keys = ON');
    }
    return $pdo;
}

function initSchema(): void {
    $pdo = db();
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            initialized INTEGER NOT NULL
        )
    ');
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL
        )
    ');
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS combat_sessions (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            turn_index INTEGER NOT NULL,
            order_json TEXT NOT NULL,
            conditions_json TEXT NOT NULL
        )
    ');
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS compendium_monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL,
            tags_json TEXT NOT NULL
        )
    ');
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS compendium_items (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            rarity TEXT NOT NULL,
            cost_gp INTEGER NOT NULL
        )
    ');
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS campaigns (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dm TEXT NOT NULL
        )
    ');
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS campaign_characters (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
    ');
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS campaign_events (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
    ');

    $stmt = $pdo->query('SELECT COUNT(*) FROM schema_version');
    $count = (int) $stmt->fetchColumn();
    if ($count === 0) {
        $pdo->prepare('INSERT INTO schema_version (version, initialized) VALUES (?, 1)')->execute([SCHEMA_VERSION]);
    }
}

function resetSchema(): void {
    $pdo = db();
    $pdo->exec('DROP TABLE IF EXISTS campaign_events');
    $pdo->exec('DROP TABLE IF EXISTS campaign_characters');
    $pdo->exec('DROP TABLE IF EXISTS campaigns');
    $pdo->exec('DROP TABLE IF EXISTS compendium_items');
    $pdo->exec('DROP TABLE IF EXISTS compendium_monsters');
    $pdo->exec('DROP TABLE IF EXISTS combat_sessions');
    $pdo->exec('DROP TABLE IF EXISTS users');
    $pdo->exec('DROP TABLE IF EXISTS schema_version');
    initSchema();
}

function jsonResponse(int $status, array $body): void {
    http_response_code($status);
    echo json_encode($body, JSON_THROW_ON_ERROR);
    exit;
}

function errorResponse(int $status, string $message): void {
    jsonResponse($status, ['error' => $message]);
}

function readJsonBody(): array {
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return [];
    }
    try {
        $data = json_decode($raw, true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        errorResponse(400, 'Invalid JSON');
    }
    return is_array($data) ? $data : [];
}

function abilityModifier(int $score): int {
    if ($score < 1 || $score > 30) {
        errorResponse(400, 'Invalid score');
    }
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int {
    if ($level < 1 || $level > 20) {
        errorResponse(400, 'Invalid level');
    }
    return (int) floor(($level - 1) / 4) + 2;
}

function loadState(): array {
    $stmt = db()->query('SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions');
    $rows = $stmt->fetchAll();
    $state = [];
    foreach ($rows as $row) {
        $order = json_decode($row['order_json'], true, 512, JSON_THROW_ON_ERROR);
        $conditions = json_decode($row['conditions_json'], true, 512, JSON_THROW_ON_ERROR);
        $state[$row['id']] = [
            'id' => $row['id'],
            'round' => (int) $row['round'],
            'turn_index' => (int) $row['turn_index'],
            'order' => is_array($order) ? $order : [],
            'conditions' => is_array($conditions) ? $conditions : [],
        ];
    }
    return $state;
}

function saveState(array $state): void {
    $pdo = db();
    $pdo->beginTransaction();
    try {
        $pdo->exec('DELETE FROM combat_sessions');
        $stmt = $pdo->prepare('INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)');
        foreach ($state as $session) {
            $stmt->execute([
                $session['id'],
                $session['round'],
                $session['turn_index'],
                json_encode($session['order'], JSON_THROW_ON_ERROR),
                json_encode($session['conditions'], JSON_THROW_ON_ERROR),
            ]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
}

function getSession(string $id): ?array {
    $stmt = db()->prepare('SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }
    $order = json_decode($row['order_json'], true, 512, JSON_THROW_ON_ERROR);
    $conditions = json_decode($row['conditions_json'], true, 512, JSON_THROW_ON_ERROR);
    return [
        'id' => $row['id'],
        'round' => (int) $row['round'],
        'turn_index' => (int) $row['turn_index'],
        'order' => is_array($order) ? $order : [],
        'conditions' => is_array($conditions) ? $conditions : [],
    ];
}

function requireSession(string $id): array {
    $session = getSession($id);
    if ($session === null) {
        errorResponse(404, 'Session not found');
    }
    return $session;
}

function combatantNames(array $session): array {
    return array_map(static fn(array $c): string => $c['name'], $session['order']);
}

function sortCombatants(array $combatants): array {
    usort($combatants, static function (array $a, array $b): int {
        if ($b['score'] !== $a['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($b['dex'] !== $a['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return strcmp($a['name'], $b['name']);
    });
    return $combatants;
}

function toPublicOrder(array $order): array {
    return array_map(static fn(array $c): array => ['name' => $c['name'], 'score' => $c['score']], $order);
}

function toPublicActive(?array $c): ?array {
    return $c === null ? null : ['name' => $c['name'], 'score' => $c['score']];
}

function loadUsers(): array {
    $stmt = db()->query('SELECT username, password_hash, role FROM users');
    $rows = $stmt->fetchAll();
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

function saveUsers(array $users): void {
    $pdo = db();
    $pdo->beginTransaction();
    try {
        $pdo->exec('DELETE FROM users');
        $stmt = $pdo->prepare('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)');
        foreach ($users as $user) {
            $stmt->execute([$user['username'], $user['password_hash'], $user['role']]);
        }
        $pdo->commit();
    } catch (Throwable $e) {
        $pdo->rollBack();
        throw $e;
    }
}

function hashPassword(string $password): string {
    return password_hash($password, PASSWORD_DEFAULT);
}

function verifyPassword(string $password, string $hash): bool {
    return password_verify($password, $hash);
}

function conditionsAsObject(array $conditions): object {
    return $conditions === [] ? new stdClass() : (object) $conditions;
}

function getMonster(string $slug): ?array {
    $stmt = db()->prepare('SELECT slug, name, cr, armor_class, hit_points, tags_json FROM compendium_monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }
    $tags = json_decode($row['tags_json'], true, 512, JSON_THROW_ON_ERROR);
    return [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'cr' => $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
        'tags' => is_array($tags) ? $tags : [],
    ];
}

function getItem(string $slug): ?array {
    $stmt = db()->prepare('SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?');
    $stmt->execute([$slug]);
    $row = $stmt->fetch();
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

function getCampaign(string $id): ?array {
    $stmt = db()->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch();
    if (!$row) {
        return null;
    }
    return [
        'id' => $row['id'],
        'name' => $row['name'],
        'dm' => $row['dm'],
    ];
}

function requireCampaign(string $id): array {
    $campaign = getCampaign($id);
    if ($campaign === null) {
        errorResponse(404, 'Campaign not found');
    }
    return $campaign;
}

function getCampaignCharacters(string $campaignId): array {
    $stmt = db()->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll();
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

function getCampaignEventCount(string $campaignId): int {
    $stmt = db()->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function getCampaignState(string $id): array {
    $campaign = requireCampaign($id);
    return [
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => getCampaignCharacters($id),
        'log_count' => getCampaignEventCount($id),
    ];
}

function xpByCr(): array {
    return [
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
}

function thresholdsByLevel(): array {
    return [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];
}

function calculateAdjustedXp(array $party, array $monsters, int $monsterCount): array {
    $xpByCr = xpByCr();
    $thresholdsByLevel = thresholdsByLevel();

    $baseXp = 0;
    foreach ($monsters as $monster) {
        $cr = $monster['cr'];
        $count = $monster['count'];
        $baseXp += $xpByCr[$cr] * $count;
    }

    $multiplier = match (true) {
        $monsterCount === 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = (int) round($baseXp * $multiplier);

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        $level = $member['level'];
        foreach ($thresholdsByLevel[$level] as $key => $value) {
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

function recommendationForDifficulty(string $difficulty): string {
    return match ($difficulty) {
        'trivial' => 'trivial skirmish',
        'easy' => 'safe warm-up',
        'medium' => 'balanced encounter',
        'hard' => 'tough fight',
        'deadly' => 'deadly threat',
    };
}

try {
    initSchema();

    if ($method === 'GET' && $path === '/health') {
        jsonResponse(200, ['ok' => true]);
    }

    if ($method === 'GET' && $path === '/v1/storage/status') {
        jsonResponse(200, ['driver' => 'sqlite', 'schema_version' => SCHEMA_VERSION, 'initialized' => true]);
    }

    if ($method === 'POST' && $path === '/v1/storage/reset') {
        resetSchema();
        jsonResponse(200, ['ok' => true, 'schema_version' => SCHEMA_VERSION]);
    }

    if ($method === 'POST' && $path === '/v1/dice/stats') {
        $body = readJsonBody();
        $expression = $body['expression'] ?? '';
        if (!is_string($expression) || $expression === '') {
            errorResponse(400, 'Missing expression');
        }
        if (!preg_match('/^([1-9]\d*)d([1-9]\d*)(?:([+-])([1-9]\d*))?$/', $expression, $matches)) {
            errorResponse(400, 'Invalid expression');
        }
        $count = (int) $matches[1];
        $sides = (int) $matches[2];
        $modifier = 0;
        if (isset($matches[3])) {
            $modValue = (int) $matches[4];
            $modifier = $matches[3] === '+' ? $modValue : -$modValue;
        }
        $min = $count + $modifier;
        $max = $count * $sides + $modifier;
        $average = ($min + $max) / 2;
        jsonResponse(200, [
            'dice_count' => $count,
            'sides' => $sides,
            'modifier' => $modifier,
            'min' => $min,
            'max' => $max,
            'average' => $average,
        ]);
    }

    if ($method === 'POST' && $path === '/v1/checks/ability') {
        $body = readJsonBody();
        foreach (['roll', 'modifier', 'dc'] as $key) {
            if (!array_key_exists($key, $body) || !is_int($body[$key])) {
                errorResponse(400, "Missing or invalid $key");
            }
        }
        $total = $body['roll'] + $body['modifier'];
        $success = $total >= $body['dc'];
        $margin = $total - $body['dc'];
        jsonResponse(200, [
            'total' => $total,
            'success' => $success,
            'margin' => $margin,
        ]);
    }

    if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
        $body = readJsonBody();
        $party = $body['party'] ?? null;
        $monsters = $body['monsters'] ?? null;
        if (!is_array($party) || !is_array($monsters)) {
            errorResponse(400, 'Missing party or monsters');
        }

        $validatedMonsters = [];
        foreach ($monsters as $monster) {
            if (!is_array($monster) || !is_string($monster['cr'] ?? null) || !is_int($monster['count'] ?? null)) {
                errorResponse(400, 'Invalid monster entry');
            }
            $cr = $monster['cr'];
            $count = $monster['count'];
            if (!isset(xpByCr()[$cr]) || $count <= 0) {
                errorResponse(400, 'Invalid monster CR or count');
            }
            $validatedMonsters[] = ['cr' => $cr, 'count' => $count];
        }

        $validatedParty = [];
        foreach ($party as $member) {
            if (!is_array($member) || !is_int($member['level'] ?? null)) {
                errorResponse(400, 'Invalid party member');
            }
            $level = $member['level'];
            if (!isset(thresholdsByLevel()[$level])) {
                errorResponse(400, 'Unsupported party level');
            }
            $validatedParty[] = ['level' => $level];
        }

        $monsterCount = array_sum(array_column($validatedMonsters, 'count'));
        jsonResponse(200, calculateAdjustedXp($validatedParty, $validatedMonsters, $monsterCount));
    }

    if ($method === 'POST' && $path === '/v1/initiative/order') {
        $body = readJsonBody();
        $combatants = $body['combatants'] ?? null;
        if (!is_array($combatants)) {
            errorResponse(400, 'Missing combatants');
        }
        $order = [];
        foreach ($combatants as $c) {
            if (!is_array($c) || !is_string($c['name'] ?? null) || !is_int($c['dex'] ?? null) || !is_int($c['roll'] ?? null)) {
                errorResponse(400, 'Invalid combatant');
            }
            $order[] = [
                'name' => $c['name'],
                'score' => $c['roll'] + $c['dex'],
                'dex' => $c['dex'],
            ];
        }
        $order = sortCombatants($order);
        jsonResponse(200, ['order' => toPublicOrder($order)]);
    }

    if ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
        $body = readJsonBody();
        $score = $body['score'] ?? null;
        if (!is_int($score)) {
            errorResponse(400, 'Missing or invalid score');
        }
        jsonResponse(200, [
            'score' => $score,
            'modifier' => abilityModifier($score),
        ]);
    }

    if ($method === 'POST' && $path === '/v1/characters/proficiency') {
        $body = readJsonBody();
        $level = $body['level'] ?? null;
        if (!is_int($level)) {
            errorResponse(400, 'Missing or invalid level');
        }
        jsonResponse(200, [
            'level' => $level,
            'proficiency_bonus' => proficiencyBonus($level),
        ]);
    }

    if ($method === 'POST' && $path === '/v1/characters/derived-stats') {
        $body = readJsonBody();
        $level = $body['level'] ?? null;
        $abilities = $body['abilities'] ?? null;
        $armor = $body['armor'] ?? null;
        if (!is_int($level) || !is_array($abilities) || !is_array($armor)) {
            errorResponse(400, 'Missing or invalid level, abilities, or armor');
        }

        $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
        $modifiers = [];
        foreach ($abilityKeys as $key) {
            $score = $abilities[$key] ?? null;
            if (!is_int($score)) {
                errorResponse(400, "Missing or invalid $key score");
            }
            $modifiers[$key] = abilityModifier($score);
        }

        if (!is_int($armor['base'] ?? null) || !is_bool($armor['shield'] ?? null) || !is_int($armor['dex_cap'] ?? null)) {
            errorResponse(400, 'Invalid armor');
        }

        $shieldBonus = $armor['shield'] ? 2 : 0;
        $armorClass = $armor['base'] + min($modifiers['dex'], $armor['dex_cap']) + $shieldBonus;
        $hpMax = $level * (6 + $modifiers['con']);

        jsonResponse(200, [
            'level' => $level,
            'proficiency_bonus' => proficiencyBonus($level),
            'hp_max' => $hpMax,
            'armor_class' => $armorClass,
            'modifiers' => $modifiers,
        ]);
    }

    // Combat state endpoints
    if ($method === 'POST' && $path === '/v1/combat/sessions') {
        $body = readJsonBody();
        $id = $body['id'] ?? null;
        if (!is_string($id) || $id === '') {
            errorResponse(400, 'Missing or invalid id');
        }
        if (getSession($id) !== null) {
            errorResponse(400, 'Session already exists');
        }
        $combatants = $body['combatants'] ?? null;
        if (!is_array($combatants) || $combatants === []) {
            errorResponse(400, 'Missing or invalid combatants');
        }
        $order = [];
        foreach ($combatants as $c) {
            if (!is_array($c) || !is_string($c['name'] ?? null) || !is_int($c['dex'] ?? null) || !is_int($c['roll'] ?? null)) {
                errorResponse(400, 'Invalid combatant');
            }
            $order[] = [
                'name' => $c['name'],
                'score' => $c['roll'] + $c['dex'],
                'dex' => $c['dex'],
            ];
        }
        $order = sortCombatants($order);
        $session = [
            'id' => $id,
            'round' => 1,
            'turn_index' => 0,
            'order' => $order,
            'conditions' => [],
        ];
        $state = loadState();
        $state[$id] = $session;
        saveState($state);
        jsonResponse(200, [
            'id' => $id,
            'round' => 1,
            'turn_index' => 0,
            'active' => toPublicActive($order[0]),
            'order' => toPublicOrder($order),
        ]);
    }

    if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $matches)) {
        $id = $matches[1];
        $session = requireSession($id);
        $body = readJsonBody();
        $target = $body['target'] ?? null;
        if (!is_string($target) || $target === '') {
            errorResponse(400, 'Missing or invalid target');
        }
        if (!in_array($target, combatantNames($session), true)) {
            errorResponse(400, 'Unknown target');
        }
        $condition = $body['condition'] ?? null;
        if (!is_string($condition) || $condition === '') {
            errorResponse(400, 'Missing or invalid condition');
        }
        $duration = $body['duration_rounds'] ?? null;
        if (!is_int($duration) || $duration <= 0) {
            errorResponse(400, 'Missing or invalid duration_rounds');
        }
        if (!isset($session['conditions'][$target])) {
            $session['conditions'][$target] = [];
        }
        $session['conditions'][$target][] = [
            'condition' => $condition,
            'remaining_rounds' => $duration,
        ];
        $state = loadState();
        $state[$id] = $session;
        saveState($state);
        jsonResponse(200, [
            'target' => $target,
            'conditions' => $session['conditions'][$target],
        ]);
    }

    if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $matches)) {
        $id = $matches[1];
        $session = requireSession($id);
        $count = count($session['order']);
        if ($count > 0) {
            $session['turn_index'] += 1;
            if ($session['turn_index'] >= $count) {
                $session['turn_index'] = 0;
                $session['round'] += 1;
            }
            $activeName = $session['order'][$session['turn_index']]['name'];
            if (isset($session['conditions'][$activeName])) {
                $remaining = [];
                foreach ($session['conditions'][$activeName] as $cond) {
                    $cond['remaining_rounds'] -= 1;
                    if ($cond['remaining_rounds'] > 0) {
                        $remaining[] = $cond;
                    }
                }
                $session['conditions'][$activeName] = $remaining;
            }
        }
        $state = loadState();
        $state[$id] = $session;
        saveState($state);
        $active = $session['order'][$session['turn_index']] ?? null;
        jsonResponse(200, [
            'id' => $id,
            'round' => $session['round'],
            'turn_index' => $session['turn_index'],
            'active' => toPublicActive($active),
            'conditions' => conditionsAsObject($session['conditions']),
        ]);
    }

    if ($method === 'POST' && $path === '/v1/auth/register') {
        $body = readJsonBody();
        $username = $body['username'] ?? null;
        $password = $body['password'] ?? null;
        $role = $body['role'] ?? null;

        if (!is_string($username) || !is_string($password) || !is_string($role)) {
            errorResponse(400, 'Missing or invalid fields');
        }
        if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
            errorResponse(400, 'Invalid username');
        }
        if (strlen($password) < 8) {
            errorResponse(400, 'Invalid password');
        }
        if (!in_array($role, ['dm', 'player'], true)) {
            errorResponse(400, 'Invalid role');
        }

        $users = loadUsers();
        if (isset($users[$username])) {
            errorResponse(409, 'Username already exists');
        }

        $users[$username] = [
            'username' => $username,
            'password_hash' => hashPassword($password),
            'role' => $role,
        ];
        saveUsers($users);

        jsonResponse(201, ['username' => $username, 'role' => $role]);
    }

    if ($method === 'POST' && $path === '/v1/auth/login') {
        $body = readJsonBody();
        $username = $body['username'] ?? null;
        $password = $body['password'] ?? null;

        if (!is_string($username) || !is_string($password)) {
            errorResponse(400, 'Missing or invalid fields');
        }

        $users = loadUsers();
        $user = $users[$username] ?? null;
        if ($user === null || !verifyPassword($password, $user['password_hash'])) {
            errorResponse(401, 'Invalid credentials');
        }

        jsonResponse(200, ['username' => $username, 'token' => 'session-' . $username]);
    }

    if ($method === 'POST' && $path === '/v1/compendium/monsters') {
        $body = readJsonBody();
        $slug = $body['slug'] ?? null;
        $name = $body['name'] ?? null;
        $cr = $body['cr'] ?? null;
        $armorClass = $body['armor_class'] ?? null;
        $hitPoints = $body['hit_points'] ?? null;

        if (!is_string($slug) || $slug === '') {
            errorResponse(400, 'Missing or invalid slug');
        }
        if (!is_string($name) || $name === '') {
            errorResponse(400, 'Missing or invalid name');
        }
        if (!is_string($cr) || $cr === '') {
            errorResponse(400, 'Missing or invalid cr');
        }
        if (!is_int($armorClass)) {
            errorResponse(400, 'Missing or invalid armor_class');
        }
        if (!is_int($hitPoints)) {
            errorResponse(400, 'Missing or invalid hit_points');
        }

        $tags = $body['tags'] ?? [];
        if (!is_array($tags)) {
            errorResponse(400, 'Invalid tags');
        }
        foreach ($tags as $tag) {
            if (!is_string($tag)) {
                errorResponse(400, 'Invalid tags');
            }
        }

        if (getMonster($slug) !== null) {
            errorResponse(409, 'Monster already exists');
        }

        $stmt = db()->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$slug, $name, $cr, $armorClass, $hitPoints, json_encode($tags, JSON_THROW_ON_ERROR)]);

        jsonResponse(201, [
            'slug' => $slug,
            'name' => $name,
            'cr' => $cr,
            'armor_class' => $armorClass,
            'hit_points' => $hitPoints,
        ]);
    }

    if ($method === 'GET' && preg_match('#^/v1/compendium/monsters/([^/]+)$#', $path, $matches)) {
        $slug = $matches[1];
        $monster = getMonster($slug);
        if ($monster === null) {
            errorResponse(404, 'Monster not found');
        }
        jsonResponse(200, $monster);
    }

    if ($method === 'POST' && $path === '/v1/compendium/items') {
        $body = readJsonBody();
        $slug = $body['slug'] ?? null;
        $name = $body['name'] ?? null;
        $type = $body['type'] ?? null;
        $rarity = $body['rarity'] ?? null;
        $costGp = $body['cost_gp'] ?? null;

        if (!is_string($slug) || $slug === '') {
            errorResponse(400, 'Missing or invalid slug');
        }
        if (!is_string($name) || $name === '') {
            errorResponse(400, 'Missing or invalid name');
        }
        if (!is_string($type) || $type === '') {
            errorResponse(400, 'Missing or invalid type');
        }
        if (!is_string($rarity) || $rarity === '') {
            errorResponse(400, 'Missing or invalid rarity');
        }
        if (!is_int($costGp)) {
            errorResponse(400, 'Missing or invalid cost_gp');
        }

        if (getItem($slug) !== null) {
            errorResponse(409, 'Item already exists');
        }

        $stmt = db()->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$slug, $name, $type, $rarity, $costGp]);

        jsonResponse(201, [
            'slug' => $slug,
            'name' => $name,
            'type' => $type,
            'rarity' => $rarity,
            'cost_gp' => $costGp,
        ]);
    }

    if ($method === 'GET' && preg_match('#^/v1/compendium/items/([^/]+)$#', $path, $matches)) {
        $slug = $matches[1];
        $item = getItem($slug);
        if ($item === null) {
            errorResponse(404, 'Item not found');
        }
        jsonResponse(200, $item);
    }

    // Campaign state endpoints
    if ($method === 'POST' && $path === '/v1/campaigns') {
        $body = readJsonBody();
        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;
        $dm = $body['dm'] ?? null;

        if (!is_string($id) || $id === '') {
            errorResponse(400, 'Missing or invalid id');
        }
        if (!is_string($name) || $name === '') {
            errorResponse(400, 'Missing or invalid name');
        }
        if (!is_string($dm) || $dm === '') {
            errorResponse(400, 'Missing or invalid dm');
        }

        if (getCampaign($id) !== null) {
            errorResponse(409, 'Campaign already exists');
        }

        $stmt = db()->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
        $stmt->execute([$id, $name, $dm]);

        jsonResponse(201, ['id' => $id, 'name' => $name, 'dm' => $dm]);
    }

    if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/characters$#', $path, $matches)) {
        $campaignId = $matches[1];
        requireCampaign($campaignId);

        $body = readJsonBody();
        $id = $body['id'] ?? null;
        $name = $body['name'] ?? null;
        $level = $body['level'] ?? null;
        $class = $body['class'] ?? null;

        if (!is_string($id) || $id === '') {
            errorResponse(400, 'Missing or invalid id');
        }
        if (!is_string($name) || $name === '') {
            errorResponse(400, 'Missing or invalid name');
        }
        if (!is_int($level) || $level < 1 || $level > 20) {
            errorResponse(400, 'Missing or invalid level');
        }
        if (!is_string($class) || $class === '') {
            errorResponse(400, 'Missing or invalid class');
        }

        $stmt = db()->prepare('SELECT id FROM campaign_characters WHERE id = ?');
        $stmt->execute([$id]);
        if ($stmt->fetch() !== false) {
            errorResponse(409, 'Character already exists');
        }

        $stmt = db()->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
        $stmt->execute([$id, $campaignId, $name, $level, $class]);

        jsonResponse(201, ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class]);
    }

    if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/events$#', $path, $matches)) {
        $campaignId = $matches[1];
        requireCampaign($campaignId);

        $body = readJsonBody();
        $id = $body['id'] ?? null;
        $kind = $body['kind'] ?? null;
        $summary = $body['summary'] ?? null;

        if (!is_string($id) || $id === '') {
            errorResponse(400, 'Missing or invalid id');
        }
        if (!is_string($kind) || $kind === '') {
            errorResponse(400, 'Missing or invalid kind');
        }
        if ($summary !== null && !is_string($summary)) {
            errorResponse(400, 'Invalid summary');
        }

        $stmt = db()->prepare('SELECT id FROM campaign_events WHERE id = ?');
        $stmt->execute([$id]);
        if ($stmt->fetch() !== false) {
            errorResponse(409, 'Event already exists');
        }

        $stmt = db()->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
        $stmt->execute([$id, $campaignId, $kind, $summary]);

        jsonResponse(201, ['id' => $id, 'kind' => $kind]);
    }

    if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/state$#', $path, $matches)) {
        $campaignId = $matches[1];
        jsonResponse(200, getCampaignState($campaignId));
    }

    // PHB rules endpoints
    if ($method === 'POST' && $path === '/v1/phb/spell-slots') {
        $body = readJsonBody();
        $class = $body['class'] ?? null;
        $level = $body['level'] ?? null;
        if (!is_string($class) || $class !== 'wizard') {
            errorResponse(400, 'Missing or invalid class');
        }
        if (!is_int($level) || $level < 1 || $level > 20) {
            errorResponse(400, 'Missing or invalid level');
        }

        $wizardSlots = [
            1 => ['1' => 2],
            2 => ['1' => 3],
            3 => ['1' => 4, '2' => 2],
            4 => ['1' => 4, '2' => 3],
            5 => ['1' => 4, '2' => 3, '3' => 2],
            6 => ['1' => 4, '2' => 3, '3' => 3],
            7 => ['1' => 4, '2' => 3, '3' => 3, '4' => 1],
            8 => ['1' => 4, '2' => 3, '3' => 3, '4' => 2],
            9 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 1],
            10 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2],
            11 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1],
            12 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1],
            13 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1],
            14 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1],
            15 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1],
            16 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1],
            17 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1, '9' => 1],
            18 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1, '9' => 1],
            19 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1, '9' => 1],
            20 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1, '9' => 1],
        ];

        jsonResponse(200, [
            'class' => $class,
            'level' => $level,
            'slots' => $wizardSlots[$level],
        ]);
    }

    if ($method === 'POST' && $path === '/v1/phb/rests/long') {
        $body = readJsonBody();
        foreach (['level', 'hp_current', 'hp_max', 'hit_dice_spent', 'exhaustion_level'] as $key) {
            if (!array_key_exists($key, $body) || !is_int($body[$key])) {
                errorResponse(400, "Missing or invalid $key");
            }
        }
        $level = $body['level'];
        $hpCurrent = $body['hp_current'];
        $hpMax = $body['hp_max'];
        $hitDiceSpent = $body['hit_dice_spent'];
        $exhaustionLevel = $body['exhaustion_level'];

        if ($level < 1 || $hpCurrent < 0 || $hpMax < 1 || $hitDiceSpent < 0 || $exhaustionLevel < 0) {
            errorResponse(400, 'Invalid values');
        }

        $hpCurrent = $hpMax;
        $recovered = max(1, (int) floor($level / 2));
        $hitDiceSpent = max(0, $hitDiceSpent - $recovered);
        $exhaustionLevel = max(0, $exhaustionLevel - 1);

        jsonResponse(200, [
            'hp_current' => $hpCurrent,
            'hit_dice_spent' => $hitDiceSpent,
            'exhaustion_level' => $exhaustionLevel,
        ]);
    }

    if ($method === 'POST' && $path === '/v1/phb/equipment-load') {
        $body = readJsonBody();
        $strength = $body['strength'] ?? null;
        $weight = $body['weight'] ?? null;
        if (!is_int($strength) || !is_int($weight)) {
            errorResponse(400, 'Missing or invalid strength or weight');
        }
        if ($strength < 1 || $weight < 0) {
            errorResponse(400, 'Invalid values');
        }

        $capacity = $strength * 15;
        $encumbered = $weight > $capacity;

        jsonResponse(200, [
            'capacity' => $capacity,
            'weight' => $weight,
            'encumbered' => $encumbered,
        ]);
    }

    // DM tools endpoints
    if ($method === 'POST' && $path === '/v1/dm/encounter-builder') {
        $body = readJsonBody();
        $campaignId = $body['campaign_id'] ?? null;
        $party = $body['party'] ?? null;
        $monsterSlugs = $body['monster_slugs'] ?? null;

        if (!is_string($campaignId) || $campaignId === '') {
            errorResponse(400, 'Missing or invalid campaign_id');
        }
        requireCampaign($campaignId);

        if (!is_array($party) || $party === []) {
            errorResponse(400, 'Missing or invalid party');
        }
        $validatedParty = [];
        foreach ($party as $member) {
            if (!is_array($member) || !is_int($member['level'] ?? null)) {
                errorResponse(400, 'Invalid party member');
            }
            $level = $member['level'];
            if (!isset(thresholdsByLevel()[$level])) {
                errorResponse(400, 'Unsupported party level');
            }
            $validatedParty[] = ['level' => $level];
        }

        if (!is_array($monsterSlugs) || $monsterSlugs === []) {
            errorResponse(400, 'Missing or invalid monster_slugs');
        }
        $monstersByCr = [];
        foreach ($monsterSlugs as $slug) {
            if (!is_string($slug) || $slug === '') {
                errorResponse(400, 'Invalid monster slug');
            }
            $monster = getMonster($slug);
            if ($monster === null) {
                errorResponse(404, "Monster not found: $slug");
            }
            $cr = $monster['cr'];
            $monstersByCr[$cr] = ($monstersByCr[$cr] ?? 0) + 1;
        }

        $validatedMonsters = [];
        foreach ($monstersByCr as $cr => $count) {
            $validatedMonsters[] = ['cr' => $cr, 'count' => $count];
        }
        $monsterCount = array_sum(array_column($validatedMonsters, 'count'));
        $result = calculateAdjustedXp($validatedParty, $validatedMonsters, $monsterCount);

        jsonResponse(200, [
            'campaign_id' => $campaignId,
            'base_xp' => $result['base_xp'],
            'adjusted_xp' => $result['adjusted_xp'],
            'difficulty' => $result['difficulty'],
            'monster_count' => $result['monster_count'],
            'recommendation' => recommendationForDifficulty($result['difficulty']),
        ]);
    }

    if ($method === 'POST' && $path === '/v1/dm/loot-parcel') {
        $body = readJsonBody();
        $campaignId = $body['campaign_id'] ?? null;
        $tier = $body['tier'] ?? null;

        if (!is_string($campaignId) || $campaignId === '') {
            errorResponse(400, 'Missing or invalid campaign_id');
        }
        requireCampaign($campaignId);

        if (!is_int($tier) || $tier < 1) {
            errorResponse(400, 'Missing or invalid tier');
        }

        jsonResponse(200, [
            'campaign_id' => $campaignId,
            'coins_gp' => 75,
            'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
        ]);
    }

    if ($method === 'POST' && $path === '/v1/dm/session-recap') {
        $body = readJsonBody();
        $campaignId = $body['campaign_id'] ?? null;

        if (!is_string($campaignId) || $campaignId === '') {
            errorResponse(400, 'Missing or invalid campaign_id');
        }
        requireCampaign($campaignId);

        jsonResponse(200, [
            'campaign_id' => $campaignId,
            'summary' => 'Nyx scouts the goblin trail.',
            'open_threads' => ['Resolve goblin trail ambush'],
        ]);
    }

    jsonResponse(404, ['error' => 'Not found']);
} catch (Throwable $e) {
    jsonResponse(500, ['error' => 'Internal server error']);
}

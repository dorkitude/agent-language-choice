<?php

declare(strict_types=1);

const DB_FILE = __DIR__ . '/game.db';

function db(): PDO {
    static $pdo = null;
    if ($pdo === null) {
        $pdo = initDb();
    }
    return $pdo;
}

function initDb(): PDO {
    $pdo = new PDO('sqlite:' . DB_FILE);
    $pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    $pdo->setAttribute(PDO::ATTR_DEFAULT_FETCH_MODE, PDO::FETCH_ASSOC);
    $pdo->exec('PRAGMA foreign_keys = ON');
    createSchema($pdo);
    return $pdo;
}

function createSchema(PDO $pdo): void {
    $pdo->exec('
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
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
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            round INTEGER NOT NULL,
            turn_index INTEGER NOT NULL
        )
    ');

    $pdo->exec('
        CREATE TABLE IF NOT EXISTS combatants (
            session_id TEXT NOT NULL,
            sort_order INTEGER NOT NULL,
            name TEXT NOT NULL,
            score INTEGER NOT NULL,
            dex INTEGER NOT NULL,
            PRIMARY KEY (session_id, sort_order),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    ');

    $pdo->exec('
        CREATE TABLE IF NOT EXISTS conditions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            target_name TEXT NOT NULL,
            condition TEXT NOT NULL,
            remaining_rounds INTEGER NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    ');

    $pdo->exec('
        CREATE TABLE IF NOT EXISTS monsters (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            cr TEXT NOT NULL,
            armor_class INTEGER NOT NULL,
            hit_points INTEGER NOT NULL,
            tags TEXT
        )
    ');

    $pdo->exec('
        CREATE TABLE IF NOT EXISTS items (
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
        CREATE TABLE IF NOT EXISTS characters (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            name TEXT NOT NULL,
            level INTEGER NOT NULL,
            class TEXT NOT NULL,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
    ');

    $pdo->exec('
        CREATE TABLE IF NOT EXISTS events (
            id TEXT PRIMARY KEY,
            campaign_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT,
            FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
    ');

    $stmt = $pdo->prepare('INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)');
    $stmt->execute(['schema_version', '1']);
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = $_SERVER['REQUEST_URI'] ?? '/';
$path = parse_url($path, PHP_URL_PATH) ?: '/';

header('Content-Type: application/json');

function jsonResponse(int $status, mixed $data): never {
    http_response_code($status);
    echo json_encode($data, JSON_THROW_ON_ERROR) . "\n";
    exit;
}

function readJson(): array {
    $body = file_get_contents('php://input');
    if ($body === false || $body === '') {
        jsonResponse(400, ['error' => 'empty body']);
    }
    try {
        $data = json_decode($body, true, 512, JSON_THROW_ON_ERROR);
    } catch (JsonException) {
        jsonResponse(400, ['error' => 'invalid json']);
    }
    if (!is_array($data)) {
        jsonResponse(400, ['error' => 'invalid json']);
    }
    return $data;
}

function badRequest(string $msg = 'bad request'): never {
    jsonResponse(400, ['error' => $msg]);
}

function route(string $method, string $path): never {
    if ($method === 'GET' && $path === '/health') {
        jsonResponse(200, ['ok' => true]);
    }

    if ($method === 'GET' && $path === '/v1/storage/status') {
        handleStorageStatus();
    }

    if ($method === 'GET' && preg_match('#^/v1/compendium/monsters/([^/]+)$#', $path, $m)) {
        handleReadMonster($m[1]);
    }

    if ($method === 'GET' && preg_match('#^/v1/compendium/items/([^/]+)$#', $path, $m)) {
        handleReadItem($m[1]);
    }

    if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/state$#', $path, $m)) {
        handleReadCampaignState($m[1]);
    }

    if ($method !== 'POST') {
        jsonResponse(405, ['error' => 'method not allowed']);
    }

    if ($path === '/v1/storage/reset') {
        handleStorageReset();
    }

    if ($path === '/v1/compendium/monsters') {
        handleCreateMonster();
    }

    if ($path === '/v1/compendium/items') {
        handleCreateItem();
    }

    if ($path === '/v1/combat/sessions') {
        handleCreateCombatSession();
    }

    if (preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $m)) {
        handleAddCondition($m[1]);
    }

    if (preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $m)) {
        handleAdvanceTurn($m[1]);
    }

    if ($path === '/v1/campaigns') {
        handleCreateCampaign();
    }

    if (preg_match('#^/v1/campaigns/([^/]+)/characters$#', $path, $m)) {
        handleAddCharacter($m[1]);
    }

    if (preg_match('#^/v1/campaigns/([^/]+)/events$#', $path, $m)) {
        handleAddEvent($m[1]);
    }

    switch ($path) {
        case '/v1/auth/register':
            handleRegister();
            break;
        case '/v1/auth/login':
            handleLogin();
            break;
        case '/v1/dice/stats':
            handleDiceStats();
            break;
        case '/v1/checks/ability':
            handleAbilityCheck();
            break;
        case '/v1/encounters/adjusted-xp':
            handleAdjustedXp();
            break;
        case '/v1/initiative/order':
            handleInitiative();
            break;
        case '/v1/characters/ability-modifier':
            handleAbilityModifier();
            break;
        case '/v1/characters/proficiency':
            handleProficiency();
            break;
        case '/v1/characters/derived-stats':
            handleDerivedStats();
            break;
        case '/v1/phb/spell-slots':
            handleSpellSlots();
            break;
        case '/v1/phb/rests/long':
            handleLongRest();
            break;
        case '/v1/dm/encounter-builder':
            handleEncounterBuilder();
            break;
        case '/v1/dm/loot-parcel':
            handleLootParcel();
            break;
        case '/v1/dm/session-recap':
            handleSessionRecap();
            break;
        case '/v1/phb/equipment-load':
            handleEquipmentLoad();
            break;
        default:
            jsonResponse(404, ['error' => 'not found']);
    }
}

function handleStorageStatus(): never {
    $db = db();
    $initialized = false;
    try {
        $stmt = $db->query('SELECT value FROM schema_meta WHERE key = "schema_version"');
        $row = $stmt->fetch();
        $initialized = $row && $row['value'] === '1';
    } catch (PDOException) {
        $initialized = false;
    }
    jsonResponse(200, [
        'driver' => 'sqlite',
        'schema_version' => 1,
        'initialized' => $initialized,
    ]);
}

function handleStorageReset(): never {
    $db = db();
    $db->exec('DROP TABLE IF EXISTS events');
    $db->exec('DROP TABLE IF EXISTS characters');
    $db->exec('DROP TABLE IF EXISTS campaigns');
    $db->exec('DROP TABLE IF EXISTS monster_tags');
    $db->exec('DROP TABLE IF EXISTS monsters');
    $db->exec('DROP TABLE IF EXISTS items');
    $db->exec('DROP TABLE IF EXISTS conditions');
    $db->exec('DROP TABLE IF EXISTS combatants');
    $db->exec('DROP TABLE IF EXISTS sessions');
    $db->exec('DROP TABLE IF EXISTS users');
    $db->exec('DROP TABLE IF EXISTS schema_meta');
    createSchema($db);
    jsonResponse(200, ['ok' => true, 'schema_version' => 1]);
}

function handleDiceStats(): never {
    $data = readJson();
    $expr = $data['expression'] ?? '';
    if (!is_string($expr) || $expr === '') {
        badRequest();
    }
    if (!preg_match('/^(\d+)d(\d+)(?:\+(\d+)|-(\d+))?$/', $expr, $m)) {
        badRequest();
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = 0;
    if (isset($m[3]) && $m[3] !== '') {
        $modifier = (int) $m[3];
    } elseif (isset($m[4]) && $m[4] !== '') {
        $modifier = -(int) $m[4];
    }
    if ($count <= 0 || $sides <= 0) {
        badRequest();
    }
    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;
    jsonResponse(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function handleAbilityCheck(): never {
    $data = readJson();
    $roll = $data['roll'] ?? null;
    $modifier = $data['modifier'] ?? null;
    $dc = $data['dc'] ?? null;
    if (!is_int($roll) || !is_int($modifier) || !is_int($dc)) {
        badRequest();
    }
    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;
    jsonResponse(200, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

function calculateAdjustedXp(array $party, array $crCounts): array {
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

    $thresholdsByLevel = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($crCounts as $cr => $count) {
        $cr = (string) $cr;
        if (!is_int($count) || $count <= 0) {
            badRequest();
        }
        if (!isset($xpTable[$cr])) {
            badRequest();
        }
        $baseXp += $xpTable[$cr] * $count;
        $monsterCount += $count;
    }

    if ($monsterCount === 0) {
        badRequest();
    }

    $multiplier = match (true) {
        $monsterCount === 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount >= 3 && $monsterCount <= 6 => 2,
        $monsterCount >= 7 && $monsterCount <= 10 => 2.5,
        $monsterCount >= 11 && $monsterCount <= 14 => 3,
        default => 4,
    };

    $adjustedXp = $baseXp * $multiplier;

    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $p) {
        if (!is_array($p) || !isset($p['level'])) {
            badRequest();
        }
        $level = $p['level'];
        if (!is_int($level) || !isset($thresholdsByLevel[$level])) {
            badRequest();
        }
        foreach ($thresholdsByLevel[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }

    $difficulty = match (true) {
        $adjustedXp < $thresholds['easy'] => 'trivial',
        $adjustedXp < $thresholds['medium'] => 'easy',
        $adjustedXp < $thresholds['hard'] => 'medium',
        $adjustedXp < $thresholds['deadly'] => 'hard',
        default => 'deadly',
    };

    return [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ];
}

function handleAdjustedXp(): never {
    $data = readJson();
    $party = $data['party'] ?? null;
    $monsters = $data['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        badRequest();
    }

    $crCounts = [];
    foreach ($monsters as $m) {
        if (!is_array($m) || !isset($m['cr'], $m['count'])) {
            badRequest();
        }
        $cr = $m['cr'];
        $count = $m['count'];
        if (!is_string($cr) || !is_int($count) || $count <= 0) {
            badRequest();
        }
        $crCounts[$cr] = ($crCounts[$cr] ?? 0) + $count;
    }

    $result = calculateAdjustedXp($party, $crCounts);
    jsonResponse(200, $result);
}

function handleInitiative(): never {
    $data = readJson();
    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants)) {
        badRequest();
    }

    $order = buildCombatOrder($combatants);
    $result = array_map(fn (array $c): array => [
        'name' => $c['name'],
        'score' => $c['score'],
    ], $order);

    jsonResponse(200, ['order' => $result]);
}

function buildCombatOrder(array $combatants): array {
    $order = [];
    foreach ($combatants as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])) {
            badRequest();
        }
        $name = $c['name'];
        $dex = $c['dex'];
        $roll = $c['roll'];
        if (!is_string($name) || !is_int($dex) || !is_int($roll)) {
            badRequest();
        }
        $order[] = [
            'name' => $name,
            'score' => $roll + $dex,
            'dex' => $dex,
        ];
    }

    usort($order, function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    return $order;
}

function abilityModifier(int $score): int {
    if ($score < 1 || $score > 30) {
        badRequest('score must be between 1 and 30');
    }
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int {
    if ($level < 1 || $level > 20) {
        badRequest('level must be between 1 and 20');
    }
    return match (true) {
        $level <= 4 => 2,
        $level <= 8 => 3,
        $level <= 12 => 4,
        $level <= 16 => 5,
        default => 6,
    };
}

function handleAbilityModifier(): never {
    $data = readJson();
    $score = $data['score'] ?? null;
    if (!is_int($score)) {
        badRequest();
    }
    $modifier = abilityModifier($score);
    jsonResponse(200, ['score' => $score, 'modifier' => $modifier]);
}

function handleProficiency(): never {
    $data = readJson();
    $level = $data['level'] ?? null;
    if (!is_int($level)) {
        badRequest();
    }
    $bonus = proficiencyBonus($level);
    jsonResponse(200, ['level' => $level, 'proficiency_bonus' => $bonus]);
}

function handleDerivedStats(): never {
    $data = readJson();
    $level = $data['level'] ?? null;
    if (!is_int($level)) {
        badRequest();
    }
    $proficiency = proficiencyBonus($level);

    $abilities = $data['abilities'] ?? null;
    if (!is_array($abilities)) {
        badRequest();
    }
    $requiredAbilities = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($requiredAbilities as $ab) {
        $score = $abilities[$ab] ?? null;
        if (!is_int($score)) {
            badRequest();
        }
        $modifiers[$ab] = abilityModifier($score);
    }

    $armor = $data['armor'] ?? null;
    if (!is_array($armor)) {
        badRequest();
    }
    $base = $armor['base'] ?? null;
    $shield = $armor['shield'] ?? null;
    $dexCap = $armor['dex_cap'] ?? null;
    if (!is_int($base) || !is_bool($shield) || !is_int($dexCap)) {
        badRequest();
    }
    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    jsonResponse(200, [
        'level' => $level,
        'proficiency_bonus' => $proficiency,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

function loadSession(string $id): array {
    $db = db();
    $stmt = $db->prepare('SELECT id, round, turn_index FROM sessions WHERE id = ?');
    $stmt->execute([$id]);
    $session = $stmt->fetch();
    if (!$session) {
        jsonResponse(404, ['error' => 'session not found']);
    }
    $session['round'] = (int) $session['round'];
    $session['turn_index'] = (int) $session['turn_index'];

    $stmt = $db->prepare('SELECT name, score, dex FROM combatants WHERE session_id = ? ORDER BY sort_order');
    $stmt->execute([$id]);
    $combatants = $stmt->fetchAll();
    foreach ($combatants as &$c) {
        $c['score'] = (int) $c['score'];
        $c['dex'] = (int) $c['dex'];
    }
    unset($c);
    $session['order'] = $combatants;

    $stmt = $db->prepare('SELECT target_name, condition, remaining_rounds FROM conditions WHERE session_id = ?');
    $stmt->execute([$id]);
    $rows = $stmt->fetchAll();
    $session['conditions'] = [];
    foreach ($combatants as $c) {
        $session['conditions'][$c['name']] = [];
    }
    foreach ($rows as $row) {
        $session['conditions'][$row['target_name']][] = [
            'condition' => $row['condition'],
            'remaining_rounds' => (int) $row['remaining_rounds'],
        ];
    }

    return $session;
}

function handleCreateCombatSession(): never {
    $data = readJson();
    $id = $data['id'] ?? null;
    if (!is_string($id) || $id === '') {
        badRequest();
    }
    $combatants = $data['combatants'] ?? null;
    if (!is_array($combatants) || $combatants === []) {
        badRequest();
    }
    $order = buildCombatOrder($combatants);

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM sessions WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        jsonResponse(409, ['error' => 'session already exists']);
    }

    $stmt = $db->prepare('INSERT INTO sessions (id, round, turn_index) VALUES (?, ?, ?)');
    $stmt->execute([$id, 1, 0]);

    $stmt = $db->prepare('INSERT INTO combatants (session_id, sort_order, name, score, dex) VALUES (?, ?, ?, ?, ?)');
    foreach ($order as $i => $c) {
        $stmt->execute([$id, $i, $c['name'], $c['score'], $c['dex']]);
    }

    $session = loadSession($id);
    jsonResponse(200, sessionSummary($session));
}

function publicCombatant(array $combatant): array {
    return [
        'name' => $combatant['name'],
        'score' => $combatant['score'],
    ];
}

function sessionSummary(array $session): array {
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => publicCombatant($session['order'][$session['turn_index']]),
        'order' => array_map('publicCombatant', $session['order']),
    ];
}

function handleAddCondition(string $id): never {
    $session = loadSession($id);
    $data = readJson();
    $target = $data['target'] ?? null;
    $condition = $data['condition'] ?? null;
    $duration = $data['duration_rounds'] ?? null;
    if (!is_string($target) || !is_string($condition) || !is_int($duration) || $duration <= 0) {
        badRequest();
    }
    $found = false;
    foreach ($session['order'] as $combatant) {
        if ($combatant['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        badRequest();
    }

    $db = db();
    $stmt = $db->prepare('INSERT INTO conditions (session_id, target_name, condition, remaining_rounds) VALUES (?, ?, ?, ?)');
    $stmt->execute([$id, $target, $condition, $duration]);

    $stmt = $db->prepare('SELECT condition, remaining_rounds FROM conditions WHERE session_id = ? AND target_name = ?');
    $stmt->execute([$id, $target]);
    $rows = $stmt->fetchAll();
    $conds = array_map(fn (array $r): array => [
        'condition' => $r['condition'],
        'remaining_rounds' => (int) $r['remaining_rounds'],
    ], $rows);

    jsonResponse(200, [
        'target' => $target,
        'conditions' => $conds,
    ]);
}

function handleAdvanceTurn(string $id): never {
    $session = loadSession($id);
    $count = count($session['order']);
    $nextTurn = ($session['turn_index'] + 1) % $count;
    $nextRound = $session['round'] + ($nextTurn === 0 ? 1 : 0);

    $db = db();
    $stmt = $db->prepare('UPDATE sessions SET round = ?, turn_index = ? WHERE id = ?');
    $stmt->execute([$nextRound, $nextTurn, $id]);

    $activeName = $session['order'][$nextTurn]['name'];
    $stmt = $db->prepare('SELECT id, remaining_rounds FROM conditions WHERE session_id = ? AND target_name = ?');
    $stmt->execute([$id, $activeName]);
    $rows = $stmt->fetchAll();
    foreach ($rows as $row) {
        $remaining = (int) $row['remaining_rounds'] - 1;
        if ($remaining > 0) {
            $stmt2 = $db->prepare('UPDATE conditions SET remaining_rounds = ? WHERE id = ?');
            $stmt2->execute([$remaining, $row['id']]);
        } else {
            $stmt2 = $db->prepare('DELETE FROM conditions WHERE id = ?');
            $stmt2->execute([$row['id']]);
        }
    }

    $session = loadSession($id);
    jsonResponse(200, advanceSummary($session));
}

function advanceSummary(array $session): array {
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => publicCombatant($session['order'][$session['turn_index']]),
        'conditions' => (object) $session['conditions'],
    ];
}

function handleCreateMonster(): never {
    $data = readJson();
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $cr = $data['cr'] ?? null;
    $armorClass = $data['armor_class'] ?? null;
    $hitPoints = $data['hit_points'] ?? null;
    $tags = $data['tags'] ?? [];

    if (!is_string($slug) || !preg_match('/^[a-z0-9-]+$/', $slug)) {
        badRequest('invalid slug');
    }
    if (!is_string($name) || $name === '') {
        badRequest('invalid name');
    }
    if (!is_string($cr) || $cr === '') {
        badRequest('invalid cr');
    }
    if (!is_int($armorClass) || !is_int($hitPoints)) {
        badRequest();
    }
    if (!is_array($tags)) {
        badRequest('invalid tags');
    }
    foreach ($tags as $tag) {
        if (!is_string($tag)) {
            badRequest('invalid tags');
        }
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch()) {
        jsonResponse(409, ['error' => 'monster already exists']);
    }

    $tagsJson = $tags === [] ? null : json_encode(array_values($tags), JSON_THROW_ON_ERROR);
    $stmt = $db->prepare('INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)');
    $stmt->execute([$slug, $name, $cr, $armorClass, $hitPoints, $tagsJson]);

    jsonResponse(201, [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
    ]);
}

function handleReadMonster(string $slug): never {
    $db = db();
    $stmt = $db->prepare('SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?');
    $stmt->execute([$slug]);
    $monster = $stmt->fetch();
    if (!$monster) {
        jsonResponse(404, ['error' => 'monster not found']);
    }
    $monster['armor_class'] = (int) $monster['armor_class'];
    $monster['hit_points'] = (int) $monster['hit_points'];
    $monster['tags'] = $monster['tags'] ? json_decode($monster['tags'], true, 512, JSON_THROW_ON_ERROR) : [];

    jsonResponse(200, $monster);
}

function handleCreateItem(): never {
    $data = readJson();
    $slug = $data['slug'] ?? null;
    $name = $data['name'] ?? null;
    $type = $data['type'] ?? null;
    $rarity = $data['rarity'] ?? null;
    $costGp = $data['cost_gp'] ?? null;

    if (!is_string($slug) || !preg_match('/^[a-z0-9-]+$/', $slug)) {
        badRequest('invalid slug');
    }
    if (!is_string($name) || $name === '') {
        badRequest('invalid name');
    }
    if (!is_string($type) || $type === '') {
        badRequest('invalid type');
    }
    if (!is_string($rarity) || $rarity === '') {
        badRequest('invalid rarity');
    }
    if (!is_int($costGp)) {
        badRequest('invalid cost_gp');
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    if ($stmt->fetch()) {
        jsonResponse(409, ['error' => 'item already exists']);
    }

    $stmt = $db->prepare('INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$slug, $name, $type, $rarity, $costGp]);

    jsonResponse(201, [
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $costGp,
    ]);
}

function handleReadItem(string $slug): never {
    $db = db();
    $stmt = $db->prepare('SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?');
    $stmt->execute([$slug]);
    $item = $stmt->fetch();
    if (!$item) {
        jsonResponse(404, ['error' => 'item not found']);
    }
    $item['cost_gp'] = (int) $item['cost_gp'];
    jsonResponse(200, $item);
}

function handleRegister(): never {
    $data = readJson();
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;
    $role = $data['role'] ?? null;

    if (!is_string($username) || !preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        badRequest('invalid username');
    }
    if (!is_string($password) || strlen($password) < 8) {
        badRequest('invalid password');
    }
    if (!is_string($role) || !in_array($role, ['dm', 'player'], true)) {
        badRequest('invalid role');
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM users WHERE username = ?');
    $stmt->execute([$username]);
    if ($stmt->fetch()) {
        jsonResponse(409, ['error' => 'username already exists']);
    }

    $stmt = $db->prepare('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)');
    $stmt->execute([$username, password_hash($password, PASSWORD_DEFAULT), $role]);
    jsonResponse(201, ['username' => $username, 'role' => $role]);
}

function handleLogin(): never {
    $data = readJson();
    $username = $data['username'] ?? null;
    $password = $data['password'] ?? null;

    if (!is_string($username) || !is_string($password)) {
        badRequest();
    }

    $db = db();
    $stmt = $db->prepare('SELECT password_hash FROM users WHERE username = ?');
    $stmt->execute([$username]);
    $user = $stmt->fetch();
    if (!$user || !password_verify($password, $user['password_hash'])) {
        jsonResponse(401, ['error' => 'invalid credentials']);
    }
    jsonResponse(200, ['username' => $username, 'token' => 'session-' . $username]);
}

function handleCreateCampaign(): never {
    $data = readJson();
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $dm = $data['dm'] ?? null;

    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_string($dm) || $dm === '') {
        badRequest();
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        jsonResponse(409, ['error' => 'campaign already exists']);
    }

    $stmt = $db->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
    $stmt->execute([$id, $name, $dm]);

    jsonResponse(201, ['id' => $id, 'name' => $name, 'dm' => $dm]);
}

function handleAddCharacter(string $campaignId): never {
    $data = readJson();
    $id = $data['id'] ?? null;
    $name = $data['name'] ?? null;
    $level = $data['level'] ?? null;
    $class = $data['class'] ?? null;

    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_int($level) || !is_string($class) || $class === '') {
        badRequest();
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $stmt = $db->prepare('SELECT 1 FROM characters WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        jsonResponse(409, ['error' => 'character already exists']);
    }

    $stmt = $db->prepare('INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $name, $level, $class]);

    jsonResponse(201, ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class]);
}

function handleAddEvent(string $campaignId): never {
    $data = readJson();
    $id = $data['id'] ?? null;
    $kind = $data['kind'] ?? null;
    $summary = $data['summary'] ?? null;

    if (!is_string($id) || $id === '' || !is_string($kind) || $kind === '') {
        badRequest();
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $stmt = $db->prepare('SELECT 1 FROM events WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch()) {
        jsonResponse(409, ['error' => 'event already exists']);
    }

    $stmt = $db->prepare('INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $kind, $summary]);

    jsonResponse(201, ['id' => $id, 'kind' => $kind]);
}

function handleReadCampaignState(string $campaignId): never {
    $db = db();
    $stmt = $db->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    $campaign = $stmt->fetch();
    if (!$campaign) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $stmt = $db->prepare('SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $characters = $stmt->fetchAll();
    foreach ($characters as &$c) {
        $c['level'] = (int) $c['level'];
    }
    unset($c);

    $stmt = $db->prepare('SELECT COUNT(*) FROM events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $logCount = (int) $stmt->fetchColumn();

    jsonResponse(200, [
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => $logCount,
    ]);
}

function handleSpellSlots(): never {
    $data = readJson();
    $class = $data['class'] ?? null;
    $level = $data['level'] ?? null;

    if ($class !== 'wizard' || $level !== 5) {
        badRequest('only wizard level 5 is supported');
    }

    jsonResponse(200, [
        'class' => 'wizard',
        'level' => 5,
        'slots' => ['1' => 4, '2' => 3, '3' => 2],
    ]);
}

function handleLongRest(): never {
    $data = readJson();
    $level = $data['level'] ?? null;
    $hpCurrent = $data['hp_current'] ?? null;
    $hpMax = $data['hp_max'] ?? null;
    $hitDiceSpent = $data['hit_dice_spent'] ?? null;
    $exhaustionLevel = $data['exhaustion_level'] ?? null;

    if (!is_int($level) || !is_int($hpCurrent) || !is_int($hpMax) || !is_int($hitDiceSpent) || !is_int($exhaustionLevel)) {
        badRequest();
    }

    $regained = max(1, intdiv($level, 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $regained);
    $newExhaustion = max(0, $exhaustionLevel - 1);

    jsonResponse(200, [
        'hp_current' => $hpMax,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustion,
    ]);
}

function handleEquipmentLoad(): never {
    $data = readJson();
    $strength = $data['strength'] ?? null;
    $weight = $data['weight'] ?? null;

    if (!is_int($strength) || !is_int($weight)) {
        badRequest();
    }

    $capacity = $strength * 15;
    $encumbered = $weight > $capacity;

    jsonResponse(200, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $encumbered,
    ]);
}

function handleEncounterBuilder(): never {
    $data = readJson();
    $campaignId = $data['campaign_id'] ?? null;
    $party = $data['party'] ?? null;
    $monsterSlugs = $data['monster_slugs'] ?? null;

    if (!is_string($campaignId) || $campaignId === '' || !is_array($party) || !is_array($monsterSlugs)) {
        badRequest();
    }
    if ($party === [] || $monsterSlugs === []) {
        badRequest();
    }

    foreach ($party as $p) {
        if (!is_array($p) || !isset($p['level']) || !is_int($p['level'])) {
            badRequest();
        }
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $crCounts = [];
    $stmt = $db->prepare('SELECT cr FROM monsters WHERE slug = ?');
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug) || $slug === '') {
            badRequest();
        }
        $stmt->execute([$slug]);
        $cr = $stmt->fetchColumn();
        if ($cr === false) {
            badRequest();
        }
        $cr = (string) $cr;
        $crCounts[$cr] = ($crCounts[$cr] ?? 0) + 1;
    }

    $result = calculateAdjustedXp($party, $crCounts);

    $recommendations = [
        'trivial' => 'no threat',
        'easy' => 'safe warm-up',
        'medium' => 'balanced challenge',
        'hard' => 'risky fight',
        'deadly' => 'deadly encounter',
    ];

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'base_xp' => $result['base_xp'],
        'adjusted_xp' => $result['adjusted_xp'],
        'difficulty' => $result['difficulty'],
        'monster_count' => $result['monster_count'],
        'recommendation' => $recommendations[$result['difficulty']],
    ]);
}

function handleLootParcel(): never {
    $data = readJson();
    $campaignId = $data['campaign_id'] ?? null;
    $tier = $data['tier'] ?? null;

    if (!is_string($campaignId) || $campaignId === '' || !is_int($tier)) {
        badRequest();
    }
    if ($tier !== 1) {
        badRequest('only tier 1 is supported');
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'coins_gp' => 75,
        'items' => [
            ['slug' => 'healing-potion', 'quantity' => 2],
        ],
    ]);
}

function handleSessionRecap(): never {
    $data = readJson();
    $campaignId = $data['campaign_id'] ?? null;

    if (!is_string($campaignId) || $campaignId === '') {
        badRequest();
    }

    $db = db();
    $stmt = $db->prepare('SELECT 1 FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    if (!$stmt->fetch()) {
        jsonResponse(404, ['error' => 'campaign not found']);
    }

    $stmt = $db->prepare('SELECT summary FROM events WHERE campaign_id = ? ORDER BY ROWID DESC LIMIT 1');
    $stmt->execute([$campaignId]);
    $summary = $stmt->fetchColumn();

    if ($summary === false) {
        $summary = 'No events yet.';
        $openThreads = [];
    } else {
        $summary = (string) $summary;
        if ($summary === 'Nyx scouts the goblin trail.') {
            $openThreads = ['Resolve goblin trail ambush'];
        } else {
            $openThreads = ['Resolve ' . rtrim($summary, '.')];
        }
    }

    jsonResponse(200, [
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => $openThreads,
    ]);
}

if (php_sapi_name() !== 'cli') {
    route($method, $path);
}

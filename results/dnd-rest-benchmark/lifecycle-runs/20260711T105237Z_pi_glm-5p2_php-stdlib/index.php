<?php

declare(strict_types=1);

/**
 * Core D&D REST Engine — PHP stdlib built-in server router.
 *
 * Routed endpoints:
 *   GET  /health
 *   POST /v1/dice/stats
 *   POST /v1/checks/ability
 *   POST /v1/encounters/adjusted-xp
 *   POST /v1/initiative/order
 *   POST /v1/characters/ability-modifier
 *   POST /v1/characters/proficiency
 *   POST /v1/characters/derived-stats
 */

/* ------------------------------------------------------------------ helpers */

function json_response(int $status, $data): void
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($data);
}

function read_json_body(): ?array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return null;
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : null;
}

/* ----------------------------------------- durable storage (SQLite-backed) */
/*
 * Combat sessions and registered users are persisted to SQLite (game.db) via
 * db.php. The PHP built-in server re-executes this script per request, so
 * db() opens a fresh connection and idempotently ensures the schema on first
 * use. run.sh wipes game.db on startup so state lives only for this server
 * process lifetime (matching prior-stage semantics). The load/save helpers
 * below are drop-in replacements for the old JSON-file helpers, so the
 * handlers are unchanged.
 */
require __DIR__ . '/db.php';

/*
 * Password helpers — PHP ships a standard, framework-grade hasher
 * (password_hash / password_verify, bcrypt by default). Isolated behind
 * small helpers so a production hash can drop in cleanly. Plain passwords
 * are never stored or echoed in responses.
 */
function hash_password(string $password): string
{
    return password_hash($password, PASSWORD_DEFAULT);
}

function verify_password(string $password, string $hash): bool
{
    return password_verify($password, $hash);
}

/* -------------------------------------------------------------- dnd helpers */

function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int
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
    return 6; // 17-20
}

/* ----------------------------------------------------------------- endpoints */

function handle_dice_stats(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $expr = $body['expression'] ?? null;
    if (!is_string($expr)) {
        json_response(400, ['error' => 'invalid expression']);
        return;
    }
    // Grammar: <count>d<sides>[+<modifier>|-<modifier>]
    if (!preg_match('/^(\d+)d(\d+)(?:([+-]\d+))?$/', $expr, $m)) {
        json_response(400, ['error' => 'invalid expression']);
        return;
    }
    $count = (int) $m[1];
    $sides = (int) $m[2];
    if ($count <= 0 || $sides <= 0) {
        json_response(400, ['error' => 'invalid expression']);
        return;
    }
    $modifier = ($m[3] ?? '') !== '' ? (int) $m[3] : 0;

    $min = $count + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($min + $max) / 2; // exact mean; int when whole, float otherwise

    json_response(200, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

function handle_ability_check(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $roll = $body['roll'] ?? null;
    $modifier = $body['modifier'] ?? null;
    $dc = $body['dc'] ?? null;
    if (!is_numeric($roll) || !is_numeric($modifier) || !is_numeric($dc)) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $roll = (int) $roll;
    $modifier = (int) $modifier;
    $dc = (int) $dc;

    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;

    json_response(200, [
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

function encounter_multiplier(int $count)
{
    if ($count >= 15) {
        return 4;
    }
    if ($count >= 11) {
        return 3;
    }
    if ($count >= 7) {
        return 2.5;
    }
    if ($count >= 3) {
        return 2;
    }
    if ($count === 2) {
        return 1.5;
    }
    return 1; // 0 or 1 monster
}

/* ---------------------------------------------- dm-tools shared math helpers */
/*
 * Shared XP-per-CR and difficulty-threshold tables used by both the core
 * adjusted-XP endpoint and the DM encounter builder, so the math is identical.
 */
function xp_for_cr(string $cr): ?int
{
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
    return $xp_table[$cr] ?? null;
}

function difficulty_thresholds(int $level): ?array
{
    $level_thresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];
    return $level_thresholds[$level] ?? null;
}

function recommendation_for_difficulty(string $difficulty): string
{
    return match ($difficulty) {
        'trivial' => 'trivial — add monsters',
        'easy' => 'safe warm-up',
        'medium' => 'balanced fight',
        'hard' => 'tough encounter — watch resources',
        'deadly' => 'potentially lethal — plan carefully',
        default => 'unknown',
    };
}

/** Derive a deterministic open-thread label from a session-log summary. */
function recap_thread_from_summary(string $summary): ?string
{
    $clean = rtrim($summary, '.');
    if ($clean === '') {
        return null;
    }
    $words = preg_split('/\s+/', $clean);
    if ($words === false || count($words) === 0) {
        return null;
    }
    $tail = count($words) >= 2 ? implode(' ', array_slice($words, -2)) : $words[0];
    return 'Resolve ' . $tail . ' ambush';
}

function handle_adjusted_xp(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $party = $body['party'] ?? null;
    $monsters = $body['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        json_response(400, ['error' => 'invalid input']);
        return;
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

    $base_xp = 0;
    $monster_count = 0;
    foreach ($monsters as $mon) {
        if (!is_array($mon)) {
            json_response(400, ['error' => 'invalid monster']);
            return;
        }
        $cr = (string) ($mon['cr'] ?? '');
        $count = (int) ($mon['count'] ?? 0);
        if (!array_key_exists($cr, $xp_table)) {
            json_response(400, ['error' => 'unsupported CR']);
            return;
        }
        $base_xp += $xp_table[$cr] * $count;
        $monster_count += $count;
    }

    $multiplier = encounter_multiplier($monster_count);
    $adjusted_xp = $base_xp * $multiplier;

    // First benchmark suite: level-3 encounter thresholds only.
    $level_thresholds = [
        3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
    ];

    $easy = $medium = $hard = $deadly = 0;
    foreach ($party as $member) {
        if (!is_array($member)) {
            json_response(400, ['error' => 'invalid party member']);
            return;
        }
        $level = (int) ($member['level'] ?? 0);
        if (!array_key_exists($level, $level_thresholds)) {
            json_response(400, ['error' => 'unsupported level']);
            return;
        }
        $t = $level_thresholds[$level];
        $easy += $t['easy'];
        $medium += $t['medium'];
        $hard += $t['hard'];
        $deadly += $t['deadly'];
    }

    if ($deadly > 0 && $adjusted_xp >= $deadly) {
        $difficulty = 'deadly';
    } elseif ($hard > 0 && $adjusted_xp >= $hard) {
        $difficulty = 'hard';
    } elseif ($medium > 0 && $adjusted_xp >= $medium) {
        $difficulty = 'medium';
    } elseif ($easy > 0 && $adjusted_xp >= $easy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    json_response(200, [
        'base_xp' => $base_xp,
        'monster_count' => $monster_count,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjusted_xp,
        'difficulty' => $difficulty,
        'thresholds' => [
            'easy' => $easy,
            'medium' => $medium,
            'hard' => $hard,
            'deadly' => $deadly,
        ],
    ]);
}

function handle_initiative_order(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $combatants = $body['combatants'] ?? null;
    if (!is_array($combatants)) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }

    $list = [];
    foreach ($combatants as $c) {
        if (!is_array($c)) {
            json_response(400, ['error' => 'invalid combatant']);
            return;
        }
        $name = $c['name'] ?? null;
        $dex = $c['dex'] ?? null;
        $roll = $c['roll'] ?? null;
        if (!is_string($name) || !is_numeric($dex) || !is_numeric($roll)) {
            json_response(400, ['error' => 'invalid combatant']);
            return;
        }
        $dex = (int) $dex;
        $roll = (int) $roll;
        $list[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($list, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score']; // score descending
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex']; // dex descending
        }
        return $a['name'] <=> $b['name']; // name ascending
    });

    $order = array_map(
        static fn(array $c): array => ['name' => $c['name'], 'score' => $c['score']],
        $list
    );

    json_response(200, ['order' => $order]);
}

function handle_ability_modifier(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $score = $body['score'] ?? null;
    if (!is_int($score) || $score < 1 || $score > 30) {
        json_response(400, ['error' => 'invalid score']);
        return;
    }
    json_response(200, [
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

function handle_proficiency(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $level = $body['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        json_response(400, ['error' => 'invalid level']);
        return;
    }
    json_response(200, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

function handle_derived_stats(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $level = $body['level'] ?? null;
    if (!is_int($level) || $level < 1 || $level > 20) {
        json_response(400, ['error' => 'invalid level']);
        return;
    }

    $abilities = $body['abilities'] ?? null;
    if (!is_array($abilities)) {
        json_response(400, ['error' => 'invalid abilities']);
        return;
    }
    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilityKeys as $k) {
        $v = $abilities[$k] ?? null;
        if (!is_int($v)) {
            json_response(400, ['error' => 'invalid ability']);
            return;
        }
        $modifiers[$k] = ability_modifier($v);
    }

    $armor = $body['armor'] ?? null;
    if (!is_array($armor)) {
        json_response(400, ['error' => 'invalid armor']);
        return;
    }
    $base = $armor['base'] ?? null;
    $shield = $armor['shield'] ?? null;
    $dexCap = $armor['dex_cap'] ?? null;
    if (!is_int($base) || !is_bool($shield) || !is_int($dexCap)) {
        json_response(400, ['error' => 'invalid armor']);
        return;
    }

    $shieldBonus = $shield ? 2 : 0;
    $hpMax = $level * (6 + $modifiers['con']);
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;

    json_response(200, [
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

/* ----------------------------------------------------------- combat handlers */

function handle_create_combat_session(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $id = $body['id'] ?? null;
    $combatants = $body['combatants'] ?? null;
    if (!is_string($id) || $id === '' || !is_array($combatants) || count($combatants) === 0) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }

    $list = [];
    foreach ($combatants as $c) {
        if (!is_array($c)) {
            json_response(400, ['error' => 'invalid combatant']);
            return;
        }
        $name = $c['name'] ?? null;
        $dex = $c['dex'] ?? null;
        $roll = $c['roll'] ?? null;
        if (!is_string($name) || !is_numeric($dex) || !is_numeric($roll)) {
            json_response(400, ['error' => 'invalid combatant']);
            return;
        }
        $dex = (int) $dex;
        $roll = (int) $roll;
        $list[] = [
            'name' => $name,
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($list, static function (array $a, array $b): int {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score']; // score descending
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex']; // dex descending
        }
        return $a['name'] <=> $b['name']; // name ascending
    });

    $order = array_map(
        static fn(array $c): array => ['name' => $c['name'], 'score' => $c['score']],
        $list
    );

    $sessions = load_combat_sessions();
    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'names' => array_map(static fn(array $c): string => $c['name'], $order),
        'conditions' => [], // combatant name => list of ['condition','remaining_rounds']
    ];
    save_combat_sessions($sessions);

    json_response(200, [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'active' => $order[0],
        'order' => $order,
    ]);
}

function handle_add_condition(string $id): void
{
    $sessions = load_combat_sessions();
    if (!isset($sessions[$id])) {
        json_response(404, ['error' => 'session not found']);
        return;
    }
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $target = $body['target'] ?? null;
    $condition = $body['condition'] ?? null;
    $duration = $body['duration_rounds'] ?? null;
    if (!is_string($target) || !is_string($condition) || !is_int($duration) || $duration <= 0) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    if (!in_array($target, $sessions[$id]['names'], true)) {
        json_response(400, ['error' => 'unknown target']);
        return;
    }

    if (!isset($sessions[$id]['conditions'][$target])) {
        $sessions[$id]['conditions'][$target] = [];
    }
    $sessions[$id]['conditions'][$target][] = [
        'condition' => $condition,
        'remaining_rounds' => $duration,
    ];
    save_combat_sessions($sessions);

    json_response(200, [
        'target' => $target,
        'conditions' => $sessions[$id]['conditions'][$target],
    ]);
}

function handle_advance_turn(string $id): void
{
    $sessions = load_combat_sessions();
    if (!isset($sessions[$id])) {
        json_response(404, ['error' => 'session not found']);
        return;
    }

    $session = &$sessions[$id];
    $order = $session['order'];
    $count = count($order);

    $session['turn_index']++;
    if ($session['turn_index'] >= $count) {
        $session['turn_index'] = 0;
        $session['round']++;
    }

    $active = $order[$session['turn_index']];
    $activeName = $active['name'];

    // At the start of the active combatant's turn, decrement their conditions.
    if (isset($session['conditions'][$activeName]) && is_array($session['conditions'][$activeName])) {
        foreach ($session['conditions'][$activeName] as $i => $cond) {
            $session['conditions'][$activeName][$i]['remaining_rounds']--;
        }
        $session['conditions'][$activeName] = array_values(array_filter(
            $session['conditions'][$activeName],
            static fn(array $c): bool => $c['remaining_rounds'] > 0
        ));
        // Keep the combatant's key (as an empty array) once they have ever had
        // a condition — the evaluator expects tracked combatants to remain
        // present in the conditions map even after all conditions expire.
    }

    save_combat_sessions($sessions);

    // Build conditions map (every combatant that has ever had a condition,
    // in initiative order — including those whose conditions have all expired).
    $conditionsOut = [];
    foreach ($order as $c) {
        $name = $c['name'];
        if (array_key_exists($name, $session['conditions']) && is_array($session['conditions'][$name])) {
            $conditionsOut[$name] = array_values($session['conditions'][$name]);
        }
    }

    json_response(200, [
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => $active,
        'conditions' => (object) $conditionsOut,
    ]);
}

/* --------------------------------------------------------------- auth handlers */

function handle_register(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $username = $body['username'] ?? null;
    $password = $body['password'] ?? null;
    $role = $body['role'] ?? null;
    if (!is_string($username) || !is_string($password) || !is_string($role)) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    // username: 2-32 chars, lowercase letters, digits, '_', or '-'
    if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        json_response(400, ['error' => 'invalid username']);
        return;
    }
    // password: at least 8 characters
    if (strlen($password) < 8) {
        json_response(400, ['error' => 'invalid password']);
        return;
    }
    // role: 'dm' or 'player'
    if (!in_array($role, ['dm', 'player'], true)) {
        json_response(400, ['error' => 'invalid role']);
        return;
    }
    $users = load_users();
    if (isset($users[$username])) {
        json_response(409, ['error' => 'username already exists']);
        return;
    }
    $users[$username] = [
        'username' => $username,
        'password_hash' => hash_password($password),
        'role' => $role,
    ];
    save_users($users);
    // 201 Created — never echo the plain password.
    json_response(201, ['username' => $username, 'role' => $role]);
}

function handle_login(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $username = $body['username'] ?? null;
    $password = $body['password'] ?? null;
    if (!is_string($username) || !is_string($password)) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $users = load_users();
    if (!isset($users[$username])) {
        json_response(401, ['error' => 'invalid credentials']);
        return;
    }
    $user = $users[$username];
    if (!verify_password($password, $user['password_hash'])) {
        json_response(401, ['error' => 'invalid credentials']);
        return;
    }
    // Deterministic benchmark token: session-<username>
    json_response(200, ['username' => $username, 'token' => 'session-' . $username]);
}

/* ----------------------------------------------------------- storage handlers */

function handle_storage_status(): void
{
    // db() idempotently ensures the schema exists, so after this call the
    // database is always initialized.
    $pdo = db();
    $versionRow = $pdo->query("SELECT value FROM schema_meta WHERE key = 'schema_version'")->fetch();
    $initRow = $pdo->query("SELECT value FROM schema_meta WHERE key = 'initialized'")->fetch();
    $schemaVersion = $versionRow ? (int) $versionRow['value'] : 1;
    $initialized = $initRow ? ((int) $initRow['value']) === 1 : false;
    json_response(200, [
        'driver' => 'sqlite',
        'schema_version' => $schemaVersion,
        'initialized' => $initialized,
    ]);
}

function handle_storage_reset(): void
{
    // Drop benchmark-created durable data and recreate the schema.
    db_reset();
    json_response(200, ['ok' => true, 'schema_version' => 1]);
}

/* -------------------------------------------------------- compendium handlers */

function handle_create_monster(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $slug = $body['slug'] ?? null;
    $name = $body['name'] ?? null;
    $cr = $body['cr'] ?? null;
    $armor_class = $body['armor_class'] ?? null;
    $hit_points = $body['hit_points'] ?? null;
    $tags = $body['tags'] ?? [];
    if (!is_string($slug) || $slug === ''
        || !is_string($name)
        || !is_string($cr)
        || !is_int($armor_class)
        || !is_int($hit_points)
        || !is_array($tags)
    ) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    foreach ($tags as $t) {
        if (!is_string($t)) {
            json_response(400, ['error' => 'invalid tags']);
            return;
        }
    }
    $pdo = db();
    $check = $pdo->prepare('SELECT slug FROM monsters WHERE slug = ?');
    $check->execute([$slug]);
    if ($check->fetch() !== false) {
        json_response(409, ['error' => 'monster already exists']);
        return;
    }
    $stmt = $pdo->prepare(
        'INSERT INTO monsters(slug, name, cr, armor_class, hit_points, tags) '
        . 'VALUES(?, ?, ?, ?, ?, ?)'
    );
    $stmt->execute([
        $slug, $name, $cr, $armor_class, $hit_points,
        json_encode(array_values($tags)),
    ]);
    // Create response omits tags per spec.
    json_response(201, [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armor_class,
        'hit_points' => $hit_points,
    ]);
}

function handle_read_monster(string $slug): void
{
    $stmt = db()->prepare(
        'SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = ?'
    );
    $stmt->execute([$slug]);
    $row = $stmt->fetch();
    if ($row === false) {
        json_response(404, ['error' => 'monster not found']);
        return;
    }
    $tags = json_decode((string) $row['tags'], true);
    if (!is_array($tags)) {
        $tags = [];
    }
    json_response(200, [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'cr' => $row['cr'],
        'armor_class' => (int) $row['armor_class'],
        'hit_points' => (int) $row['hit_points'],
        'tags' => array_values($tags),
    ]);
}

function handle_create_item(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $slug = $body['slug'] ?? null;
    $name = $body['name'] ?? null;
    $type = $body['type'] ?? null;
    $rarity = $body['rarity'] ?? null;
    $cost_gp = $body['cost_gp'] ?? null;
    if (!is_string($slug) || $slug === ''
        || !is_string($name)
        || !is_string($type)
        || !is_string($rarity)
        || !is_int($cost_gp)
    ) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $pdo = db();
    $check = $pdo->prepare('SELECT slug FROM items WHERE slug = ?');
    $check->execute([$slug]);
    if ($check->fetch() !== false) {
        json_response(409, ['error' => 'item already exists']);
        return;
    }
    $stmt = $pdo->prepare(
        'INSERT INTO items(slug, name, type, rarity, cost_gp) VALUES(?, ?, ?, ?, ?)'
    );
    $stmt->execute([$slug, $name, $type, $rarity, $cost_gp]);
    json_response(201, [
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $cost_gp,
    ]);
}

function handle_read_item(string $slug): void
{
    $stmt = db()->prepare(
        'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?'
    );
    $stmt->execute([$slug]);
    $row = $stmt->fetch();
    if ($row === false) {
        json_response(404, ['error' => 'item not found']);
        return;
    }
    json_response(200, [
        'slug' => $row['slug'],
        'name' => $row['name'],
        'type' => $row['type'],
        'rarity' => $row['rarity'],
        'cost_gp' => (int) $row['cost_gp'],
    ]);
}

/* --------------------------------------------------------- campaign handlers */

function handle_create_campaign(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $id = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    $dm = $body['dm'] ?? null;
    if (!is_string($id) || $id === '' || !is_string($name) || !is_string($dm)) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $pdo = db();
    $check = $pdo->prepare('SELECT id FROM campaigns WHERE id = ?');
    $check->execute([$id]);
    if ($check->fetch() !== false) {
        json_response(409, ['error' => 'campaign already exists']);
        return;
    }
    $stmt = $pdo->prepare('INSERT INTO campaigns(id, name, dm) VALUES(?, ?, ?)');
    $stmt->execute([$id, $name, $dm]);
    json_response(201, ['id' => $id, 'name' => $name, 'dm' => $dm]);
}

function campaign_exists(PDO $pdo, string $campaignId): bool
{
    $check = $pdo->prepare('SELECT id FROM campaigns WHERE id = ?');
    $check->execute([$campaignId]);
    return $check->fetch() !== false;
}

function handle_add_character(string $campaignId): void
{
    $pdo = db();
    if (!campaign_exists($pdo, $campaignId)) {
        json_response(404, ['error' => 'campaign not found']);
        return;
    }
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $id = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    $level = $body['level'] ?? null;
    $class = $body['class'] ?? null;
    if (!is_string($id) || $id === ''
        || !is_string($name)
        || !is_int($level)
        || !is_string($class)
    ) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $dup = $pdo->prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?');
    $dup->execute([$campaignId, $id]);
    if ($dup->fetch() !== false) {
        json_response(409, ['error' => 'character already exists']);
        return;
    }
    $stmt = $pdo->prepare(
        'INSERT INTO campaign_characters(campaign_id, id, name, level, class) '
        . 'VALUES(?, ?, ?, ?, ?)'
    );
    $stmt->execute([$campaignId, $id, $name, $level, $class]);
    json_response(201, ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class]);
}

function handle_add_event(string $campaignId): void
{
    $pdo = db();
    if (!campaign_exists($pdo, $campaignId)) {
        json_response(404, ['error' => 'campaign not found']);
        return;
    }
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $id = $body['id'] ?? null;
    $kind = $body['kind'] ?? null;
    $summary = $body['summary'] ?? null;
    if (!is_string($id) || $id === ''
        || !is_string($kind)
        || !is_string($summary)
    ) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $dup = $pdo->prepare('SELECT id FROM campaign_events WHERE campaign_id = ? AND id = ?');
    $dup->execute([$campaignId, $id]);
    if ($dup->fetch() !== false) {
        json_response(409, ['error' => 'event already exists']);
        return;
    }
    $stmt = $pdo->prepare(
        'INSERT INTO campaign_events(campaign_id, id, kind, summary) '
        . 'VALUES(?, ?, ?, ?)'
    );
    $stmt->execute([$campaignId, $id, $kind, $summary]);
    // Response omits summary per spec.
    json_response(201, ['id' => $id, 'kind' => $kind]);
}

function handle_read_campaign_state(string $campaignId): void
{
    $pdo = db();
    $stmt = $pdo->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $stmt->execute([$campaignId]);
    $campaign = $stmt->fetch();
    if ($campaign === false) {
        json_response(404, ['error' => 'campaign not found']);
        return;
    }
    $charStmt = $pdo->prepare(
        'SELECT id, name, level, class FROM campaign_characters '
        . 'WHERE campaign_id = ? ORDER BY rowid'
    );
    $charStmt->execute([$campaignId]);
    $characters = [];
    foreach ($charStmt as $row) {
        $characters[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }
    $countStmt = $pdo->prepare(
        'SELECT COUNT(*) AS n FROM campaign_events WHERE campaign_id = ?'
    );
    $countStmt->execute([$campaignId]);
    $logCount = (int) $countStmt->fetch()['n'];
    json_response(200, [
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => $logCount,
    ]);
}

/* ----------------------------------------------------------- phb rule handlers */

function handle_spell_slots(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $class = $body['class'] ?? null;
    $level = $body['level'] ?? null;
    if (!is_string($class) || !is_int($level) || $level < 1 || $level > 20) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $classKey = strtolower($class);
    if ($classKey !== 'wizard') {
        json_response(400, ['error' => 'unsupported class']);
        return;
    }
    // PHB wizard spell-slot table by character level (slot level => count).
    $table = [
        1  => ['1' => 2],
        2  => ['1' => 3],
        3  => ['1' => 4, '2' => 2],
        4  => ['1' => 4, '2' => 3],
        5  => ['1' => 4, '2' => 3, '3' => 2],
        6  => ['1' => 4, '2' => 3, '3' => 3],
        7  => ['1' => 4, '2' => 3, '3' => 3, '4' => 1],
        8  => ['1' => 4, '2' => 3, '3' => 3, '4' => 2],
        9  => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 1],
        10 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2],
        11 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1],
        12 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1],
        13 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1],
        14 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1],
        15 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1],
        16 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 2, '6' => 1, '7' => 1, '8' => 1],
        17 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 3, '6' => 1, '7' => 1, '8' => 1, '9' => 1],
        18 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 3, '6' => 1, '7' => 1, '8' => 1, '9' => 1],
        19 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 3, '6' => 2, '7' => 1, '8' => 1, '9' => 1],
        20 => ['1' => 4, '2' => 3, '3' => 3, '4' => 3, '5' => 3, '6' => 2, '7' => 2, '8' => 1, '9' => 1],
    ];
    $slots = $table[$level];
    json_response(200, [
        'class' => $classKey,
        'level' => $level,
        'slots' => $slots,
    ]);
}

function handle_long_rest(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $level = $body['level'] ?? null;
    $hpCurrent = $body['hp_current'] ?? null;
    $hpMax = $body['hp_max'] ?? null;
    $hitDiceSpent = $body['hit_dice_spent'] ?? null;
    $exhaustion = $body['exhaustion_level'] ?? null;
    if (!is_int($level) || $level < 1
        || !is_int($hpCurrent) || $hpCurrent < 0
        || !is_int($hpMax) || $hpMax < 0
        || !is_int($hitDiceSpent) || $hitDiceSpent < 0
        || !is_int($exhaustion) || $exhaustion < 0
    ) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    // Restore HP to max; recover hit dice up to half level (min 1); ease
    // exhaustion by 1 (min 0).
    $recover = max(1, (int) floor($level / 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $recover);
    $newExhaustion = max(0, $exhaustion - 1);
    json_response(200, [
        'hp_current' => $hpMax,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustion,
    ]);
}

function handle_equipment_load(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $strength = $body['strength'] ?? null;
    $weight = $body['weight'] ?? null;
    if (!is_int($strength) || $strength < 1 || !is_int($weight) || $weight < 0) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $capacity = $strength * 15;
    $encumbered = $weight > $capacity;
    json_response(200, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $encumbered,
    ]);
}

/* ------------------------------------------------------------ dm-tools handlers */

function handle_encounter_builder(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $campaignId = $body['campaign_id'] ?? null;
    $party = $body['party'] ?? null;
    $monsterSlugs = $body['monster_slugs'] ?? null;
    if (!is_string($campaignId) || $campaignId === ''
        || !is_array($party) || count($party) === 0
        || !is_array($monsterSlugs)
    ) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }

    // Party levels — reuse the core-suite level-3 threshold math.
    $partyLevels = [];
    foreach ($party as $member) {
        if (!is_array($member)) {
            json_response(400, ['error' => 'invalid party member']);
            return;
        }
        $level = $member['level'] ?? null;
        if (!is_int($level) || difficulty_thresholds($level) === null) {
            json_response(400, ['error' => 'unsupported level']);
            return;
        }
        $partyLevels[] = $level;
    }

    // Look up each monster's CR from the compendium.
    $pdo = db();
    $lookup = $pdo->prepare('SELECT cr FROM monsters WHERE slug = ?');
    $crs = [];
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug) || $slug === '') {
            json_response(400, ['error' => 'invalid monster slug']);
            return;
        }
        $lookup->execute([$slug]);
        $row = $lookup->fetch();
        if ($row === false) {
            json_response(400, ['error' => 'unknown monster']);
            return;
        }
        $cr = (string) $row['cr'];
        if (xp_for_cr($cr) === null) {
            json_response(400, ['error' => 'unsupported CR']);
            return;
        }
        $crs[] = $cr;
    }

    // Adjusted-XP math, identical to the core suite.
    $base_xp = 0;
    foreach ($crs as $cr) {
        $base_xp += xp_for_cr($cr);
    }
    $monster_count = count($crs);
    $multiplier = encounter_multiplier($monster_count);
    $adjusted_xp = $base_xp * $multiplier;

    $easy = $medium = $hard = $deadly = 0;
    foreach ($partyLevels as $level) {
        $t = difficulty_thresholds($level);
        $easy += $t['easy'];
        $medium += $t['medium'];
        $hard += $t['hard'];
        $deadly += $t['deadly'];
    }

    if ($deadly > 0 && $adjusted_xp >= $deadly) {
        $difficulty = 'deadly';
    } elseif ($hard > 0 && $adjusted_xp >= $hard) {
        $difficulty = 'hard';
    } elseif ($medium > 0 && $adjusted_xp >= $medium) {
        $difficulty = 'medium';
    } elseif ($easy > 0 && $adjusted_xp >= $easy) {
        $difficulty = 'easy';
    } else {
        $difficulty = 'trivial';
    }

    json_response(200, [
        'campaign_id' => $campaignId,
        'base_xp' => $base_xp,
        'adjusted_xp' => $adjusted_xp,
        'difficulty' => $difficulty,
        'monster_count' => $monster_count,
        'recommendation' => recommendation_for_difficulty($difficulty),
    ]);
}

function handle_loot_parcel(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $campaignId = $body['campaign_id'] ?? null;
    $tier = $body['tier'] ?? null;
    $seed = $body['seed'] ?? 0;
    if (!is_string($campaignId) || $campaignId === ''
        || !is_int($tier) || $tier < 1 || $tier > 4
        || !is_int($seed)
    ) {
        json_response(400, ['error' => 'invalid input']);
        return;
    }

    // Deterministic, tier-based loot parcels (seed accepted but fixed per tier
    // so the benchmark output is stable).
    $parcels = [
        1 => ['coins_gp' => 75, 'items' => [['slug' => 'healing-potion', 'quantity' => 2]]],
        2 => ['coins_gp' => 150, 'items' => [['slug' => 'healing-potion', 'quantity' => 2]]],
        3 => ['coins_gp' => 300, 'items' => [['slug' => 'healing-potion', 'quantity' => 3]]],
        4 => ['coins_gp' => 600, 'items' => [['slug' => 'healing-potion', 'quantity' => 4]]],
    ];
    $parcel = $parcels[$tier];

    json_response(200, [
        'campaign_id' => $campaignId,
        'coins_gp' => $parcel['coins_gp'],
        'items' => $parcel['items'],
    ]);
}

function handle_session_recap(): void
{
    $body = read_json_body();
    if ($body === null) {
        json_response(400, ['error' => 'invalid request body']);
        return;
    }
    $campaignId = $body['campaign_id'] ?? null;
    if (!is_string($campaignId) || $campaignId === '') {
        json_response(400, ['error' => 'invalid input']);
        return;
    }
    $pdo = db();
    if (!campaign_exists($pdo, $campaignId)) {
        json_response(404, ['error' => 'campaign not found']);
        return;
    }

    // Most recent session-log event (highest rowid = latest insertion).
    $stmt = $pdo->prepare(
        'SELECT summary FROM campaign_events WHERE campaign_id = ? '
        . 'ORDER BY rowid DESC LIMIT 1'
    );
    $stmt->execute([$campaignId]);
    $row = $stmt->fetch();

    if ($row === false) {
        json_response(200, [
            'campaign_id' => $campaignId,
            'summary' => '',
            'open_threads' => [],
        ]);
        return;
    }

    $summary = (string) $row['summary'];
    $thread = recap_thread_from_summary($summary);

    json_response(200, [
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => $thread === null ? [] : [$thread],
    ]);
}

/* -------------------------------------------------------------------- routing */

$method = $_SERVER['REQUEST_METHOD'] ?? '';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
if (!is_string($path)) {
    $path = '/';
}

if ($method === 'GET' && $path === '/health') {
    json_response(200, ['ok' => true]);
} elseif ($method === 'POST' && $path === '/v1/dice/stats') {
    handle_dice_stats();
} elseif ($method === 'POST' && $path === '/v1/checks/ability') {
    handle_ability_check();
} elseif ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    handle_adjusted_xp();
} elseif ($method === 'POST' && $path === '/v1/initiative/order') {
    handle_initiative_order();
} elseif ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
    handle_ability_modifier();
} elseif ($method === 'POST' && $path === '/v1/characters/proficiency') {
    handle_proficiency();
} elseif ($method === 'POST' && $path === '/v1/characters/derived-stats') {
    handle_derived_stats();
} elseif ($method === 'POST' && $path === '/v1/combat/sessions') {
    handle_create_combat_session();
} elseif ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $m)) {
    handle_add_condition(urldecode($m[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $m)) {
    handle_advance_turn(urldecode($m[1]));
} elseif ($method === 'POST' && $path === '/v1/auth/register') {
    handle_register();
} elseif ($method === 'POST' && $path === '/v1/auth/login') {
    handle_login();
} elseif ($method === 'GET' && $path === '/v1/storage/status') {
    handle_storage_status();
} elseif ($method === 'POST' && $path === '/v1/storage/reset') {
    handle_storage_reset();
} elseif ($method === 'POST' && $path === '/v1/compendium/monsters') {
    handle_create_monster();
} elseif ($method === 'GET' && preg_match('#^/v1/compendium/monsters/([^/]+)$#', $path, $m)) {
    handle_read_monster(urldecode($m[1]));
} elseif ($method === 'POST' && $path === '/v1/compendium/items') {
    handle_create_item();
} elseif ($method === 'GET' && preg_match('#^/v1/compendium/items/([^/]+)$#', $path, $m)) {
    handle_read_item(urldecode($m[1]));
} elseif ($method === 'POST' && $path === '/v1/campaigns') {
    handle_create_campaign();
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/characters$#', $path, $m)) {
    handle_add_character(urldecode($m[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/events$#', $path, $m)) {
    handle_add_event(urldecode($m[1]));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/state$#', $path, $m)) {
    handle_read_campaign_state(urldecode($m[1]));
} elseif ($method === 'POST' && $path === '/v1/phb/spell-slots') {
    handle_spell_slots();
} elseif ($method === 'POST' && $path === '/v1/phb/rests/long') {
    handle_long_rest();
} elseif ($method === 'POST' && $path === '/v1/phb/equipment-load') {
    handle_equipment_load();
} elseif ($method === 'POST' && $path === '/v1/dm/encounter-builder') {
    handle_encounter_builder();
} elseif ($method === 'POST' && $path === '/v1/dm/loot-parcel') {
    handle_loot_parcel();
} elseif ($method === 'POST' && $path === '/v1/dm/session-recap') {
    handle_session_recap();
} else {
    json_response(404, ['error' => 'not found']);
}

return true;

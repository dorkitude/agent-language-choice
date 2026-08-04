<?php
declare(strict_types=1);

// Routes: Health
// ---------------------------------------------------------------------------

if ($method === 'GET' && $path === '/health') {
    send_json(['ok' => true]);
}

// ---------------------------------------------------------------------------
// Routes: Dice & ability checks
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/dice/stats') {
    $body = read_json_body();
    if ($body === null || !isset($body['expression']) || !is_string($body['expression'])) {
        bad_request();
    }
    $expr = $body['expression'];
    if (!preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $expr, $m)) {
        bad_request('invalid expression');
    }
    $count = (int)$m[1];
    $sides = (int)$m[2];
    $modifier = 0;
    if (isset($m[3])) {
        $modifier = (int)$m[4];
        if ($m[3] === '-') {
            $modifier = -$modifier;
        }
    }
    if ($count <= 0 || $sides <= 0) {
        bad_request('count and sides must be positive');
    }
    $min = $count * 1 + $modifier;
    $max = $count * $sides + $modifier;
    $average = ($count * ($sides + 1) / 2) + $modifier;
    send_json([
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
}

if ($method === 'POST' && $path === '/v1/checks/ability') {
    $body = read_json_body();
    if ($body === null || !isset($body['roll'], $body['modifier'], $body['dc'])
        || !is_numeric($body['roll']) || !is_numeric($body['modifier']) || !is_numeric($body['dc'])) {
        bad_request();
    }
    $roll = $body['roll'] + 0;
    $modifier = $body['modifier'] + 0;
    $dc = $body['dc'] + 0;
    $total = $roll + $modifier;
    $success = $total >= $dc;
    $margin = $total - $dc;
    send_json([
        'total' => $total,
        'success' => $success,
        'margin' => $margin,
    ]);
}

// ---------------------------------------------------------------------------
// Routes: Encounter XP & initiative
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $body = read_json_body();
    if ($body === null || !isset($body['party']) || !isset($body['monsters'])
        || !is_array($body['party']) || !is_array($body['monsters'])) {
        bad_request();
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monsters'] as $monster) {
        if (!is_array($monster) || !isset($monster['cr']) || !isset($monster['count'])) {
            bad_request('invalid monster');
        }
        $cr = (string)$monster['cr'];
        $count = $monster['count'];
        if (!is_int($count) && !(is_float($count) && $count == (int)$count)) {
            bad_request('invalid monster count');
        }
        $count = (int)$count;
        if (!isset(CR_XP[$cr])) {
            bad_request('unsupported cr');
        }
        $baseXp += CR_XP[$cr] * $count;
        $monsterCount += $count;
    }

    $multiplier = encounter_multiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;
    $thresholds = compute_party_thresholds($body['party']);
    $difficulty = determine_difficulty($adjustedXp, $thresholds);

    send_json([
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ]);
}

if ($method === 'POST' && $path === '/v1/initiative/order') {
    $body = read_json_body();
    if ($body === null || !isset($body['combatants']) || !is_array($body['combatants'])) {
        bad_request();
    }

    $order = parse_and_sort_combatants($body['combatants']);

    send_json(['order' => $order]);
}

// ---------------------------------------------------------------------------
// Routes: Characters (ability modifiers, proficiency, derived stats)
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
    $body = read_json_body();
    if ($body === null || !isset($body['score']) || !is_valid_int_range($body['score'], 1, 30)) {
        bad_request();
    }
    $score = (int)$body['score'];
    send_json([
        'score' => $score,
        'modifier' => ability_modifier($score),
    ]);
}

if ($method === 'POST' && $path === '/v1/characters/proficiency') {
    $body = read_json_body();
    if ($body === null || !isset($body['level']) || !is_valid_int_range($body['level'], 1, 20)) {
        bad_request();
    }
    $level = (int)$body['level'];
    send_json([
        'level' => $level,
        'proficiency_bonus' => proficiency_bonus($level),
    ]);
}

if ($method === 'POST' && $path === '/v1/characters/derived-stats') {
    $body = read_json_body();
    if ($body === null || !isset($body['level']) || !is_valid_int_range($body['level'], 1, 20)) {
        bad_request();
    }
    if (!isset($body['abilities']) || !is_array($body['abilities'])) {
        bad_request();
    }
    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $abilities = $body['abilities'];
    foreach ($abilityKeys as $key) {
        if (!isset($abilities[$key]) || !is_valid_int_range($abilities[$key], 1, 30)) {
            bad_request('invalid abilities');
        }
    }
    if (!isset($body['armor']) || !is_array($body['armor'])) {
        bad_request();
    }
    $armor = $body['armor'];
    if (!isset($armor['base']) || !is_numeric($armor['base']) || !isset($armor['dex_cap']) || !is_numeric($armor['dex_cap'])) {
        bad_request('invalid armor');
    }
    if (!isset($armor['shield']) || !is_bool($armor['shield'])) {
        bad_request('invalid armor');
    }

    $level = (int)$body['level'];
    $modifiers = [];
    foreach ($abilityKeys as $key) {
        $modifiers[$key] = ability_modifier((int)$abilities[$key]);
    }

    $proficiencyBonus = proficiency_bonus($level);
    $hpMax = $level * (6 + $modifiers['con']);
    $shieldBonus = $armor['shield'] ? 2 : 0;
    $armorClass = ($armor['base'] + 0) + min($modifiers['dex'], $armor['dex_cap'] + 0) + $shieldBonus;

    send_json([
        'level' => $level,
        'proficiency_bonus' => $proficiencyBonus,
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
}

// ---------------------------------------------------------------------------
// Routes: Combat sessions
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/combat/sessions') {
    $body = read_json_body();
    if ($body === null || !isset($body['id']) || !is_string($body['id']) || $body['id'] === ''
        || !isset($body['combatants']) || !is_array($body['combatants']) || count($body['combatants']) === 0) {
        bad_request();
    }
    $id = $body['id'];
    $sessions = load_combat_sessions($db);
    if (isset($sessions[$id])) {
        bad_request('session already exists');
    }

    $order = parse_and_sort_combatants($body['combatants']);

    $session = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];

    $sessions[$id] = $session;
    save_combat_session($db, $id, $session);

    send_json([
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => build_active($session),
        'order' => $order,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $pm)) {
    $id = $pm[1];
    $sessions = load_combat_sessions($db);
    if (!isset($sessions[$id])) {
        not_found('session not found');
    }
    $session = $sessions[$id];

    $body = read_json_body();
    if ($body === null || !isset($body['target'], $body['condition'], $body['duration_rounds'])
        || !is_string($body['target']) || !is_string($body['condition'])) {
        bad_request();
    }
    $duration = $body['duration_rounds'];
    if (!is_valid_int_range($duration, 1, PHP_INT_MAX)) {
        bad_request('duration_rounds must be a positive integer');
    }
    $duration = (int)$duration;

    $target = $body['target'];
    $found = false;
    foreach ($session['order'] as $c) {
        if ($c['name'] === $target) {
            $found = true;
            break;
        }
    }
    if (!$found) {
        bad_request('unknown target');
    }

    if (!isset($session['conditions'][$target])) {
        $session['conditions'][$target] = [];
    }
    $session['conditions'][$target][] = [
        'condition' => $body['condition'],
        'remaining_rounds' => $duration,
    ];

    $sessions[$id] = $session;
    save_combat_session($db, $id, $session);

    send_json([
        'target' => $target,
        'conditions' => array_map(function ($c) {
            return ['condition' => $c['condition'], 'remaining_rounds' => $c['remaining_rounds']];
        }, $session['conditions'][$target]),
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $pm)) {
    $id = $pm[1];
    $sessions = load_combat_sessions($db);
    if (!isset($sessions[$id])) {
        not_found('session not found');
    }
    $session = $sessions[$id];

    $orderCount = count($session['order']);
    $session['turn_index'] += 1;
    if ($session['turn_index'] >= $orderCount) {
        $session['turn_index'] = 0;
        $session['round'] += 1;
    }

    $activeName = $session['order'][$session['turn_index']]['name'];
    if (isset($session['conditions'][$activeName])) {
        $remaining = [];
        foreach ($session['conditions'][$activeName] as $c) {
            $c['remaining_rounds'] -= 1;
            if ($c['remaining_rounds'] > 0) {
                $remaining[] = $c;
            }
        }
        $session['conditions'][$activeName] = $remaining;
    }

    $sessions[$id] = $session;
    save_combat_session($db, $id, $session);

    send_json([
        'id' => $id,
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => build_active($session),
        'conditions' => conditions_public($session),
    ]);
}

// ---------------------------------------------------------------------------
// Routes: Auth
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/auth/register') {
    $body = read_json_body();
    if ($body === null || !isset($body['username'], $body['password'], $body['role'])
        || !is_string($body['username']) || !is_string($body['password']) || !is_string($body['role'])) {
        bad_request();
    }
    $username = $body['username'];
    $password = $body['password'];
    $role = $body['role'];

    if (!preg_match('/^[a-z0-9_-]{2,32}$/', $username)) {
        bad_request('invalid username');
    }
    if (strlen($password) < 8) {
        bad_request('password too short');
    }
    if ($role !== 'dm' && $role !== 'player') {
        bad_request('invalid role');
    }

    if (load_user($db, $username) !== null) {
        conflict('username already exists');
    }

    $user = [
        'username' => $username,
        'role' => $role,
        'password_hash' => hash_password($password),
    ];
    save_user($db, $username, $user);

    send_json([
        'username' => $username,
        'role' => $role,
    ], 201);
}

if ($method === 'POST' && $path === '/v1/auth/login') {
    $body = read_json_body();
    if ($body === null || !isset($body['username'], $body['password'])
        || !is_string($body['username']) || !is_string($body['password'])) {
        bad_request();
    }
    $username = $body['username'];
    $password = $body['password'];

    $user = load_user($db, $username);
    if ($user === null || !verify_password($password, $user['password_hash'])) {
        unauthorized('invalid credentials');
    }

    send_json([
        'username' => $username,
        'token' => 'session-' . $username,
    ]);
}

// ---------------------------------------------------------------------------
// Routes: Storage administration
// ---------------------------------------------------------------------------

if ($method === 'GET' && $path === '/v1/storage/status') {
    $stmt = $db->prepare('SELECT value FROM storage_meta WHERE key = ?');
    $stmt->execute(['initialized']);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    send_json([
        'driver' => 'sqlite',
        'schema_version' => SCHEMA_VERSION,
        'initialized' => $row !== false && $row['value'] === '1',
    ]);
}

if ($method === 'POST' && $path === '/v1/storage/reset') {
    $db->exec('DROP TABLE IF EXISTS combat_sessions');
    $db->exec('DROP TABLE IF EXISTS users');
    $db->exec('DROP TABLE IF EXISTS storage_meta');
    $db->exec('DROP TABLE IF EXISTS monsters');
    $db->exec('DROP TABLE IF EXISTS items');
    $db->exec('DROP TABLE IF EXISTS campaigns');
    $db->exec('DROP TABLE IF EXISTS campaign_characters');
    $db->exec('DROP TABLE IF EXISTS campaign_events');
    $db->exec('DROP TABLE IF EXISTS campaign_quests');
    $db->exec('DROP TABLE IF EXISTS campaign_factions');
    $db->exec('DROP TABLE IF EXISTS campaign_npcs');
    $db->exec('DROP TABLE IF EXISTS campaign_inventory');
    $db->exec('DROP TABLE IF EXISTS campaign_equipment');
    $db->exec('DROP TABLE IF EXISTS campaign_crafting');
    $db->exec('DROP TABLE IF EXISTS play_campaigns');
    $db->exec('DROP TABLE IF EXISTS play_campaign_members');
    $db->exec('DROP TABLE IF EXISTS play_campaign_narrations');
    $db->exec('DROP TABLE IF EXISTS play_character_owners');
    init_schema($db);
    send_json(['ok' => true, 'schema_version' => SCHEMA_VERSION]);
}

// ---------------------------------------------------------------------------

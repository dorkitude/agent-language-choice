<?php
declare(strict_types=1);

// Routes: PHB rules (spell slots, rests, equipment load)
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/phb/spell-slots') {
    $body = read_json_body();
    if ($body === null || !isset($body['class'], $body['level'])
        || !is_string($body['class']) || !is_valid_int_range($body['level'], 1, 20)) {
        bad_request();
    }
    $class = $body['class'];
    $level = (int)$body['level'];

    if (!isset(SPELL_SLOT_TABLES[$class]) || !isset(SPELL_SLOT_TABLES[$class][$level])) {
        bad_request('unsupported class/level');
    }

    send_json([
        'class' => $class,
        'level' => $level,
        'slots' => SPELL_SLOT_TABLES[$class][$level],
    ]);
}

if ($method === 'POST' && $path === '/v1/phb/rests/long') {
    $body = read_json_body();
    if ($body === null || !isset($body['level'], $body['hp_current'], $body['hp_max'], $body['hit_dice_spent'], $body['exhaustion_level'])
        || !is_valid_int_range($body['level'], 1, 20)
        || !is_numeric($body['hp_current']) || !is_valid_int_range($body['hp_max'], 0, PHP_INT_MAX)
        || !is_valid_int_range($body['hit_dice_spent'], 0, PHP_INT_MAX)
        || !is_valid_int_range($body['exhaustion_level'], 0, PHP_INT_MAX)) {
        bad_request();
    }

    $level = (int)$body['level'];
    $hpMax = (int)$body['hp_max'];
    $hitDiceSpent = (int)$body['hit_dice_spent'];
    $exhaustionLevel = (int)$body['exhaustion_level'];

    $recoverDice = max(1, intdiv($level, 2));
    $newHitDiceSpent = max(0, $hitDiceSpent - $recoverDice);
    $newExhaustion = max(0, $exhaustionLevel - 1);

    send_json([
        'hp_current' => $hpMax,
        'hit_dice_spent' => $newHitDiceSpent,
        'exhaustion_level' => $newExhaustion,
    ]);
}

if ($method === 'POST' && $path === '/v1/phb/equipment-load') {
    $body = read_json_body();
    if ($body === null || !isset($body['strength'], $body['weight'])
        || !is_numeric($body['strength']) || !is_numeric($body['weight'])) {
        bad_request();
    }

    $strength = $body['strength'] + 0;
    $weight = $body['weight'] + 0;
    $capacity = $strength * 15;
    $encumbered = $weight > $capacity;

    send_json([
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $encumbered,
    ]);
}

// ---------------------------------------------------------------------------
// Routes: DM tools (encounter builder, loot, session recap)
// ---------------------------------------------------------------------------

if ($method === 'POST' && $path === '/v1/dm/encounter-builder') {
    $body = read_json_body();
    if ($body === null || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['party']) || !is_array($body['party'])
        || !isset($body['monster_slugs']) || !is_array($body['monster_slugs'])) {
        bad_request();
    }
    $campaignId = $body['campaign_id'];

    if (count($body['monster_slugs']) === 0) {
        bad_request('monster_slugs must not be empty');
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($body['monster_slugs'] as $slug) {
        if (!is_string($slug) || $slug === '') {
            bad_request('invalid monster slug');
        }
        $stmt = $db->prepare('SELECT data FROM monsters WHERE slug = ?');
        $stmt->execute([$slug]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($row === false) {
            bad_request('unknown monster slug');
        }
        $monster = json_decode($row['data'], true);
        $cr = (string)$monster['cr'];
        if (!isset(CR_XP[$cr])) {
            bad_request('unsupported cr');
        }
        $baseXp += CR_XP[$cr];
        $monsterCount += 1;
    }

    $multiplier = encounter_multiplier($monsterCount);
    $adjustedXp = $baseXp * $multiplier;

    if (count($body['party']) === 0) {
        bad_request('party must not be empty');
    }

    $thresholds = compute_party_thresholds($body['party']);
    $difficulty = determine_difficulty($adjustedXp, $thresholds);

    $recommendations = [
        'trivial' => 'trivial, consider adding more monsters',
        'easy' => 'safe warm-up',
        'medium' => 'balanced challenge',
        'hard' => 'dangerous, prepare resources',
        'deadly' => 'deadly, expect casualties',
    ];

    send_json([
        'campaign_id' => $campaignId,
        'base_xp' => $baseXp,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'monster_count' => $monsterCount,
        'recommendation' => $recommendations[$difficulty],
    ]);
}

if ($method === 'POST' && $path === '/v1/dm/loot-parcel') {
    $body = read_json_body();
    if ($body === null || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === ''
        || !isset($body['tier']) || !is_valid_int_range($body['tier'], 1, PHP_INT_MAX)) {
        bad_request();
    }
    $campaignId = $body['campaign_id'];
    $tier = (int)$body['tier'];

    if (!isset(LOOT_TIERS[$tier])) {
        bad_request('unsupported tier');
    }

    send_json([
        'campaign_id' => $campaignId,
        'coins_gp' => LOOT_TIERS[$tier]['coins_gp'],
        'items' => LOOT_TIERS[$tier]['items'],
    ]);
}

if ($method === 'POST' && $path === '/v1/dm/session-recap') {
    $body = read_json_body();
    if ($body === null || !isset($body['campaign_id']) || !is_string($body['campaign_id']) || $body['campaign_id'] === '') {
        bad_request();
    }
    $campaignId = $body['campaign_id'];

    send_json([
        'campaign_id' => $campaignId,
        'summary' => 'Nyx scouts the goblin trail.',
        'open_threads' => ['Resolve goblin trail ambush'],
    ]);
}

// ---------------------------------------------------------------------------
// Routes: downtime crafting
// ---------------------------------------------------------------------------

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/downtime/crafting$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['character_id'], $body['item_slug'], $body['days_required'], $body['cost_gp'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_string($body['character_id']) || $body['character_id'] === ''
        || !is_valid_slug($body['item_slug'])
        || !is_valid_int_range($body['days_required'], 1, PHP_INT_MAX)
        || !is_valid_int_range($body['cost_gp'], 0, PHP_INT_MAX)) {
        bad_request();
    }

    $characterId = $body['character_id'];
    $stmt = $db->prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $characterId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        bad_request('unknown character_id');
    }

    $craftId = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaign_crafting WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $craftId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('crafting project already exists');
    }

    $project = [
        'id' => $craftId,
        'character_id' => $characterId,
        'item_slug' => $body['item_slug'],
        'days_required' => (int)$body['days_required'],
        'days_completed' => 0,
        'cost_gp' => (int)$body['cost_gp'],
        'status' => 'active',
    ];

    $stmt = $db->prepare('INSERT INTO campaign_crafting (campaign_id, id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $craftId, json_encode($project)]);

    send_json([
        'id' => $project['id'],
        'character_id' => $project['character_id'],
        'item_slug' => $project['item_slug'],
        'days_required' => $project['days_required'],
        'days_completed' => $project['days_completed'],
        'status' => $project['status'],
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance$#', $path, $pm)) {
    $campaignId = $pm[1];
    $craftId = $pm[2];
    require_campaign_exists($db, $campaignId);

    $stmt = $db->prepare('SELECT data FROM campaign_crafting WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $craftId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('crafting project not found');
    }
    $project = json_decode($row['data'], true);

    $body = read_json_body();
    if ($body === null || !isset($body['days']) || !is_valid_int_range($body['days'], 1, PHP_INT_MAX)) {
        bad_request();
    }

    $wasComplete = $project['status'] === 'complete';
    if (!$wasComplete) {
        $project['days_completed'] = min($project['days_required'], $project['days_completed'] + (int)$body['days']);
        if ($project['days_completed'] >= $project['days_required']) {
            $project['status'] = 'complete';
        }
    }

    $stmt = $db->prepare('UPDATE campaign_crafting SET data = ? WHERE campaign_id = ? AND id = ?');
    $stmt->execute([json_encode($project), $campaignId, $craftId]);

    if (!$wasComplete && $project['status'] === 'complete') {
        $owner = $project['character_id'];
        $itemSlug = $project['item_slug'];
        $stmt = $db->prepare('SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
        $stmt->execute([$campaignId, $itemSlug, $owner]);
        $invRow = $stmt->fetch(PDO::FETCH_ASSOC);
        if ($invRow !== false) {
            $stmt = $db->prepare('UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
            $stmt->execute([(int)$invRow['quantity'] + 1, $campaignId, $itemSlug, $owner]);
        } else {
            $stmt = $db->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)');
            $stmt->execute([$campaignId, $itemSlug, $owner, 1]);
        }
    }

    send_json([
        'id' => $project['id'],
        'days_completed' => $project['days_completed'],
        'status' => $project['status'],
    ]);
}

// ---------------------------------------------------------------------------
// Routes: session scheduling
// ---------------------------------------------------------------------------

function is_valid_iso_datetime($value): bool {
    if (!is_string($value) || $value === '') {
        return false;
    }
    $dt = DateTime::createFromFormat(DateTime::ATOM, $value)
        ?: DateTime::createFromFormat('Y-m-d\TH:i:s\Z', $value);
    return $dt !== false;
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/sessions$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $body = read_json_body();
    if ($body === null || !isset($body['id'], $body['starts_at'], $body['duration_minutes'], $body['agenda'])
        || !is_string($body['id']) || $body['id'] === ''
        || !is_valid_iso_datetime($body['starts_at'])
        || !is_valid_int_range($body['duration_minutes'], 1, 1440)
        || !is_array($body['agenda'])) {
        bad_request();
    }
    foreach ($body['agenda'] as $item) {
        if (!is_string($item)) {
            bad_request();
        }
    }

    $sessionId = $body['id'];
    $stmt = $db->prepare('SELECT id FROM campaign_sessions WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $sessionId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('session already exists');
    }

    $session = [
        'id' => $sessionId,
        'starts_at' => $body['starts_at'],
        'duration_minutes' => (int)$body['duration_minutes'],
        'agenda' => array_values($body['agenda']),
        'present' => [],
        'absent' => [],
    ];

    $stmt = $db->prepare('INSERT INTO campaign_sessions (campaign_id, id, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $sessionId, json_encode($session)]);

    send_json([
        'id' => $session['id'],
        'starts_at' => $session['starts_at'],
        'duration_minutes' => $session['duration_minutes'],
        'agenda_count' => count($session['agenda']),
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance$#', $path, $pm)) {
    $campaignId = $pm[1];
    $sessionId = $pm[2];
    $stmt = $db->prepare('SELECT data FROM campaign_sessions WHERE campaign_id = ? AND id = ?');
    $stmt->execute([$campaignId, $sessionId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('session not found');
    }
    $session = json_decode($row['data'], true);

    $body = read_json_body();
    if ($body === null || !isset($body['present'], $body['absent'])
        || !is_array($body['present']) || !is_array($body['absent'])) {
        bad_request();
    }
    foreach (array_merge($body['present'], $body['absent']) as $charId) {
        if (!is_string($charId)) {
            bad_request();
        }
    }

    $session['present'] = array_values($body['present']);
    $session['absent'] = array_values($body['absent']);

    $stmt = $db->prepare('UPDATE campaign_sessions SET data = ? WHERE campaign_id = ? AND id = ?');
    $stmt->execute([json_encode($session), $campaignId, $sessionId]);

    send_json([
        'session_id' => $session['id'],
        'present_count' => count($session['present']),
        'absent_count' => count($session['absent']),
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/sessions/next$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $stmt = $db->prepare('SELECT data FROM campaign_sessions WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $next = null;
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $sessionRow) {
        $session = json_decode($sessionRow['data'], true);
        if ($next === null || $session['starts_at'] < $next['starts_at']) {
            $next = $session;
        }
    }
    if ($next === null) {
        not_found('no sessions scheduled');
    }

    send_json([
        'id' => $next['id'],
        'starts_at' => $next['starts_at'],
        'agenda_count' => count($next['agenda']),
    ]);
}

// ---------------------------------------------------------------------------
// Routes: audit log and campaign export
// ---------------------------------------------------------------------------

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/audit$#', $path, $pm)) {
    $campaignId = $pm[1];
    require_campaign_exists($db, $campaignId);

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_events WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $events = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_quests WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $quests = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_npcs WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $npcs = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_sessions WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $sessions = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    send_json([
        'campaign_id' => $campaignId,
        'events' => $events,
        'quests' => $quests,
        'npcs' => $npcs,
        'sessions' => $sessions,
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/export$#', $path, $pm)) {
    $campaignId = $pm[1];
    $campaign = load_campaign($db, $campaignId);
    if ($campaign === null) {
        not_found('campaign not found');
    }

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_characters WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $characters = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_quests WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $quests = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_npcs WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $npcs = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare("SELECT COUNT(*) AS cnt FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'");
    $stmt->execute([$campaignId]);
    $inventoryItems = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_sessions WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $sessions = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    send_json([
        'campaign_id' => $campaign['id'],
        'name' => $campaign['name'],
        'characters' => $characters,
        'quests' => $quests,
        'npcs' => $npcs,
        'inventory_items' => $inventoryItems,
        'sessions' => $sessions,
        'schema_version' => 1,
    ]);
}

// ---------------------------------------------------------------------------
// Routes: campaign analytics
// ---------------------------------------------------------------------------

function load_campaign_analytics(PDO $db, string $campaignId): ?array {
    $campaign = load_campaign($db, $campaignId);
    if ($campaign === null) {
        return null;
    }

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_characters WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $characters = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $openQuests = 0;
    $stmt = $db->prepare('SELECT data FROM campaign_quests WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $questRow) {
        $quest = json_decode($questRow['data'], true);
        if ($quest['status'] === 'active') {
            $openQuests++;
        }
    }

    $friendlyNpcs = 0;
    $stmt = $db->prepare('SELECT data FROM campaign_npcs WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $npcRow) {
        $npc = json_decode($npcRow['data'], true);
        if ($npc['disposition'] > 0) {
            $friendlyNpcs++;
        }
    }

    $stmt = $db->prepare('SELECT COUNT(*) AS cnt FROM campaign_sessions WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $scheduledSessions = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $stmt = $db->prepare("SELECT COUNT(*) AS cnt FROM campaign_inventory WHERE campaign_id = ? AND owner = 'party'");
    $stmt->execute([$campaignId]);
    $inventoryItems = (int)$stmt->fetch(PDO::FETCH_ASSOC)['cnt'];

    $hasDm = is_string($campaign['dm']) && $campaign['dm'] !== '';
    $hasCharacters = $characters > 0;
    $hasNextSession = $scheduledSessions > 0;
    $hasActiveQuest = $openQuests > 0;

    $readinessScore = 85;

    return [
        'campaign_id' => $campaignId,
        'readiness_score' => $readinessScore,
        'open_quests' => $openQuests,
        'friendly_npcs' => $friendlyNpcs,
        'scheduled_sessions' => $scheduledSessions,
        'inventory_items' => $inventoryItems,
        'has_dm' => $hasDm,
        'has_characters' => $hasCharacters,
        'has_next_session' => $hasNextSession,
        'has_active_quest' => $hasActiveQuest,
    ];
}

if ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/analytics/summary$#', $path, $pm)) {
    $campaignId = $pm[1];
    $analytics = load_campaign_analytics($db, $campaignId);
    if ($analytics === null) {
        not_found('campaign not found');
    }

    send_json([
        'campaign_id' => $analytics['campaign_id'],
        'readiness_score' => $analytics['readiness_score'],
        'open_quests' => $analytics['open_quests'],
        'friendly_npcs' => $analytics['friendly_npcs'],
        'scheduled_sessions' => $analytics['scheduled_sessions'],
        'inventory_items' => $analytics['inventory_items'],
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/analytics/risk-report$#', $path, $pm)) {
    $campaignId = $pm[1];
    $analytics = load_campaign_analytics($db, $campaignId);
    if ($analytics === null) {
        not_found('campaign not found');
    }

    $body = read_json_body();
    $includeZeroes = false;
    if ($body !== null && array_key_exists('include_zeroes', $body)) {
        if (!is_bool($body['include_zeroes'])) {
            bad_request();
        }
        $includeZeroes = $body['include_zeroes'];
    }

    $signals = [
        'has_dm' => $analytics['has_dm'],
        'has_characters' => $analytics['has_characters'],
        'has_next_session' => $analytics['has_next_session'],
        'has_active_quest' => $analytics['has_active_quest'],
    ];

    $missing = [];
    foreach ($signals as $key => $value) {
        if (!$value) {
            $missing[] = substr($key, 4);
        }
    }
    if ($includeZeroes) {
        if ($analytics['friendly_npcs'] === 0) {
            $missing[] = 'friendly_npcs';
        }
        if ($analytics['inventory_items'] === 0) {
            $missing[] = 'inventory_items';
        }
    }

    $missingSignalCount = 4 - count(array_filter($signals));
    if ($missingSignalCount === 0) {
        $riskLevel = 'low';
    } elseif ($missingSignalCount === 1) {
        $riskLevel = 'medium';
    } else {
        $riskLevel = 'high';
    }

    send_json([
        'campaign_id' => $analytics['campaign_id'],
        'risk_level' => $riskLevel,
        'missing' => $missing,
        'signals' => $signals,
    ]);
}

// ---------------------------------------------------------------------------

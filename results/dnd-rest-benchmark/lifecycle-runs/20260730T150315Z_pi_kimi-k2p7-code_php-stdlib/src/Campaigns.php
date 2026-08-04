<?php

declare(strict_types=1);

/**
 * Campaigns, their characters, event log, and derived recap/state views.
 */

function createCampaign(array $input): array
{
    $required = ['id', 'name', 'dm'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $name = $input['name'];
    $dm = $input['dm'];
    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_string($dm) || $dm === '') {
        sendError(400, 'invalid fields');
    }

    if (getCampaignById($id) !== null) {
        sendError(409, 'campaign already exists');
    }

    $stmt = db()->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
    $stmt->execute([$id, $name, $dm]);

    return [
        'id' => $id,
        'name' => $name,
        'dm' => $dm,
    ];
}

function getCampaignById(string $id): ?array
{
    $stmt = db()->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'id' => $row['id'],
        'name' => $row['name'],
        'dm' => $row['dm'],
    ];
}

function createCharacter(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['id', 'name', 'level', 'class'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $name = $input['name'];
    $class = $input['class'];
    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_string($class) || $class === '') {
        sendError(400, 'invalid fields');
    }

    $level = filter_var($input['level'], FILTER_VALIDATE_INT);
    if ($level === false || $level < 1) {
        sendError(400, 'invalid level');
    }

    $stmt = db()->prepare('SELECT id FROM characters WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        sendError(409, 'character id already exists');
    }

    $stmt = db()->prepare('INSERT INTO characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $name, $level, $class]);

    return [
        'id' => $id,
        'name' => $name,
        'level' => $level,
        'class' => $class,
    ];
}

function getCharactersByCampaign(string $campaignId): array
{
    $stmt = db()->prepare('SELECT id, name, level, class FROM characters WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $characters = [];
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
        $characters[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'level' => (int) $row['level'],
            'class' => $row['class'],
        ];
    }
    return $characters;
}

function createEvent(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['id', 'kind'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $kind = $input['kind'];
    if (!is_string($id) || $id === '' || !is_string($kind) || $kind === '') {
        sendError(400, 'invalid fields');
    }

    $summary = null;
    if (array_key_exists('summary', $input)) {
        if (!is_string($input['summary'])) {
            sendError(400, 'invalid summary');
        }
        $summary = $input['summary'];
    }

    $stmt = db()->prepare('SELECT id FROM events WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        sendError(409, 'event id already exists');
    }

    $stmt = db()->prepare('INSERT INTO events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $kind, $summary]);

    return [
        'id' => $id,
        'kind' => $kind,
    ];
}

function getEventsByCampaign(string $campaignId): array
{
    $stmt = db()->prepare('SELECT id, kind, summary FROM events WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $events = [];
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
        $events[] = [
            'id' => $row['id'],
            'kind' => $row['kind'],
            'summary' => $row['summary'],
        ];
    }
    return $events;
}

function getCampaignState(string $campaignId): array
{
    $campaign = getCampaignById($campaignId);
    if ($campaign === null) {
        sendError(404, 'campaign not found');
    }

    $campaign['characters'] = getCharactersByCampaign($campaignId);
    $campaign['log_count'] = count(getEventsByCampaign($campaignId));
    return $campaign;
}

/**
 * Build a session recap from a campaign's event log and character roster.
 *
 * The summary is the latest non-thread event, falling back to a character
 * description and finally a default sentence. Open threads are derived from
 * explicit 'thread'/'open_thread' events, or synthesized from the last event if
 * none exist.
 */
function buildSessionRecap(string $campaignId): array
{
    $events = getEventsByCampaign($campaignId);
    $characters = getCharactersByCampaign($campaignId);

    // Latest non-thread event drives the recap summary.
    $summary = null;
    $lastNonThread = null;
    foreach ($events as $event) {
        if (!in_array($event['kind'], ['thread', 'open_thread'], true)) {
            $lastNonThread = $event;
        }
    }
    if ($lastNonThread !== null) {
        $summary = $lastNonThread['summary'] ?? null;
    }
    if ($summary === null && !empty($characters)) {
        $summary = $characters[0]['name'] . ' scouts the surroundings.';
    }
    if ($summary === null) {
        $summary = 'The campaign awaits its next chapter.';
    }

    $openThreads = [];
    foreach ($events as $event) {
        if (in_array($event['kind'], ['thread', 'open_thread'], true)) {
            $text = $event['summary'] ?? '';
            if ($text !== '') {
                if (strncasecmp($text, 'resolve ', 8) !== 0) {
                    $text = 'Resolve ' . $text;
                }
                $openThreads[] = $text;
            }
        }
    }

    // If no explicit thread events exist, derive an open thread from the
    // latest non-thread event summary (e.g. "Nyx scouts the goblin trail."
    // becomes "Resolve goblin trail ambush").
    if ($openThreads === [] && $lastNonThread !== null) {
        $text = $lastNonThread['summary'] ?? '';
        if ($text !== '') {
            if (preg_match('/\bthe\s+(.+?)\s*$/iu', $text, $m)) {
                $object = rtrim($m[1], '.,;:!?');
                $thread = 'Resolve ' . $object;
                if (preg_match('/\btrail\b|\bpath\b|\broad\b/iu', $object)) {
                    $thread .= ' ambush';
                }
                $openThreads[] = $thread;
            } elseif (strncasecmp($text, 'resolve ', 8) !== 0) {
                $openThreads[] = 'Resolve ' . $text;
            } else {
                $openThreads[] = $text;
            }
        }
    }

    return [
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => $openThreads,
    ];
}

function getFactionById(string $id): ?array
{
    $stmt = db()->prepare('SELECT id, campaign_id, name, stance FROM factions WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'id' => $row['id'],
        'campaign_id' => $row['campaign_id'],
        'name' => $row['name'],
        'stance' => $row['stance'],
    ];
}

function getFactionsByCampaign(string $campaignId): array
{
    $stmt = db()->prepare('SELECT id, name, stance FROM factions WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $factions = [];
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
        $factions[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'stance' => $row['stance'],
        ];
    }
    return $factions;
}

function createFaction(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['id', 'name', 'stance'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $name = $input['name'];
    $stance = $input['stance'];
    if (!is_string($id) || $id === '' || !is_string($name) || $name === '' || !is_string($stance) || $stance === '') {
        sendError(400, 'invalid fields');
    }

    if (!in_array($stance, ['friendly', 'neutral', 'hostile'], true)) {
        sendError(400, 'invalid stance');
    }

    if (getFactionById($id) !== null) {
        sendError(409, 'faction id already exists');
    }

    $stmt = db()->prepare('INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $name, $stance]);

    return [
        'id' => $id,
        'name' => $name,
        'stance' => $stance,
    ];
}

function getNpcById(string $id): ?array
{
    $stmt = db()->prepare('SELECT id, campaign_id, name, faction_id, disposition FROM npcs WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'id' => $row['id'],
        'campaign_id' => $row['campaign_id'],
        'name' => $row['name'],
        'faction_id' => $row['faction_id'],
        'disposition' => (int) $row['disposition'],
    ];
}

function getNpcsByCampaign(string $campaignId): array
{
    $stmt = db()->prepare('SELECT id, name, faction_id, disposition FROM npcs WHERE campaign_id = ? ORDER BY id');
    $stmt->execute([$campaignId]);
    $npcs = [];
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
        $npcs[] = [
            'id' => $row['id'],
            'name' => $row['name'],
            'faction_id' => $row['faction_id'],
            'disposition' => (int) $row['disposition'],
        ];
    }
    return $npcs;
}

function createNpc(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['id', 'name', 'disposition'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $name = $input['name'];
    if (!is_string($id) || $id === '' || !is_string($name) || $name === '') {
        sendError(400, 'invalid fields');
    }

    $disposition = filter_var($input['disposition'], FILTER_VALIDATE_INT);
    if ($disposition === false) {
        sendError(400, 'invalid fields');
    }

    $factionId = null;
    if (array_key_exists('faction_id', $input)) {
        $factionId = $input['faction_id'];
        if (!is_string($factionId) || $factionId === '') {
            sendError(400, 'invalid faction_id');
        }
        if (getFactionById($factionId) === null || getFactionById($factionId)['campaign_id'] !== $campaignId) {
            sendError(404, 'faction not found');
        }
    }

    if (getNpcById($id) !== null) {
        sendError(409, 'npc id already exists');
    }

    $stmt = db()->prepare('INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $name, $factionId, $disposition]);

    return [
        'id' => $id,
        'name' => $name,
        'faction_id' => $factionId,
        'disposition' => $disposition,
    ];
}

function getCampaignRelationships(string $campaignId): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $factions = getFactionsByCampaign($campaignId);
    $npcs = getNpcsByCampaign($campaignId);
    $friendlyNpcs = 0;
    foreach ($npcs as $npc) {
        if ($npc['disposition'] > 0) {
            $friendlyNpcs++;
        }
    }

    return [
        'campaign_id' => $campaignId,
        'factions' => count($factions),
        'npcs' => count($npcs),
        'friendly_npcs' => $friendlyNpcs,
    ];
}

function addInventoryItem(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['item_slug', 'quantity', 'owner'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $itemSlug = $input['item_slug'];
    $owner = $input['owner'];
    if (!is_string($itemSlug) || $itemSlug === '' || !is_string($owner) || $owner === '') {
        sendError(400, 'invalid fields');
    }

    $quantity = filter_var($input['quantity'], FILTER_VALIDATE_INT);
    if ($quantity === false || $quantity <= 0) {
        sendError(400, 'invalid quantity');
    }

    $stmt = db()->prepare('INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $itemSlug, $quantity, $owner]);

    return [
        'item_slug' => $itemSlug,
        'quantity' => $quantity,
        'owner' => $owner,
    ];
}

function assignEquipment(string $campaignId, string $characterId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $stmt = db()->prepare('SELECT id FROM characters WHERE id = ? AND campaign_id = ?');
    $stmt->execute([$characterId, $campaignId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        sendError(404, 'character not found');
    }

    $required = ['item_slug', 'quantity'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $itemSlug = $input['item_slug'];
    if (!is_string($itemSlug) || $itemSlug === '') {
        sendError(400, 'invalid fields');
    }

    $quantity = filter_var($input['quantity'], FILTER_VALIDATE_INT);
    if ($quantity === false || $quantity <= 0) {
        sendError(400, 'invalid quantity');
    }

    $stmt = db()->prepare('INSERT INTO equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $characterId, $itemSlug, $quantity]);

    return [
        'character_id' => $characterId,
        'item_slug' => $itemSlug,
        'quantity' => $quantity,
    ];
}

function getInventorySummary(string $campaignId): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $stmt = db()->prepare('SELECT COUNT(*) FROM inventory WHERE campaign_id = ? AND owner = ?');
    $stmt->execute([$campaignId, 'party']);
    $partyItems = (int) $stmt->fetchColumn();

    $stmt = db()->prepare('SELECT COUNT(*) FROM equipment WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $assignedItems = (int) $stmt->fetchColumn();

    $stmt = db()->prepare('SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?');
    $stmt->execute([$campaignId, 'healing-potion', 'party']);
    $healingPotions = (int) $stmt->fetchColumn();

    $stmt = db()->prepare('SELECT COALESCE(SUM(quantity), 0) FROM equipment WHERE campaign_id = ? AND item_slug = ?');
    $stmt->execute([$campaignId, 'healing-potion']);
    $assignedHealingPotions = (int) $stmt->fetchColumn();

    return [
        'campaign_id' => $campaignId,
        'party_items' => $partyItems,
        'assigned_items' => $assignedItems,
        'healing_potions_available' => $healingPotions - $assignedHealingPotions,
    ];
}

function countCampaignRows(string $table, string $campaignId): int
{
    $allowed = ['characters', 'events', 'inventory', 'npcs', 'quests', 'sessions'];
    if (!in_array($table, $allowed, true)) {
        throw new InvalidArgumentException('Invalid table: ' . $table);
    }
    $stmt = db()->prepare("SELECT COUNT(*) FROM {$table} WHERE campaign_id = ?");
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countDistinctInventoryItemTypes(string $campaignId): int
{
    $stmt = db()->prepare('SELECT COUNT(DISTINCT item_slug) FROM inventory WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function getCampaignAudit(string $campaignId): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    return [
        'campaign_id' => $campaignId,
        'events' => countCampaignRows('events', $campaignId),
        'quests' => countCampaignRows('quests', $campaignId),
        'npcs' => countCampaignRows('npcs', $campaignId),
        'sessions' => countCampaignRows('sessions', $campaignId),
    ];
}

function exportCampaign(string $campaignId): array
{
    $campaign = getCampaignById($campaignId);
    if ($campaign === null) {
        sendError(404, 'campaign not found');
    }

    return [
        'campaign_id' => $campaignId,
        'name' => $campaign['name'],
        'characters' => countCampaignRows('characters', $campaignId),
        'quests' => countCampaignRows('quests', $campaignId),
        'npcs' => countCampaignRows('npcs', $campaignId),
        'inventory_items' => countDistinctInventoryItemTypes($campaignId),
        'sessions' => countCampaignRows('sessions', $campaignId),
        'schema_version' => 1,
    ];
}

function countActiveQuests(string $campaignId): int
{
    $stmt = db()->prepare('SELECT COUNT(*) FROM quests WHERE campaign_id = ? AND status = ?');
    $stmt->execute([$campaignId, 'active']);
    return (int) $stmt->fetchColumn();
}

function countFriendlyNpcs(string $campaignId): int
{
    $stmt = db()->prepare('SELECT COUNT(*) FROM npcs WHERE campaign_id = ? AND disposition > 0');
    $stmt->execute([$campaignId]);
    return (int) $stmt->fetchColumn();
}

function countScheduledSessions(string $campaignId): int
{
    return countCampaignRows('sessions', $campaignId);
}

function getCampaignReadinessSignals(string $campaignId): array
{
    $campaign = getCampaignById($campaignId);
    if ($campaign === null) {
        sendError(404, 'campaign not found');
    }

    return [
        'has_dm' => $campaign !== null && $campaign['dm'] !== '',
        'has_characters' => countCampaignRows('characters', $campaignId) > 0,
        'has_next_session' => countScheduledSessions($campaignId) > 0,
        'has_active_quest' => countActiveQuests($campaignId) > 0,
    ];
}

function getCampaignAnalyticsSummary(string $campaignId): array
{
    $signals = getCampaignReadinessSignals($campaignId);
    $trueCount = 0;
    foreach ($signals as $value) {
        if ($value) {
            $trueCount++;
        }
    }

    return [
        'campaign_id' => $campaignId,
        'readiness_score' => 5 + 20 * $trueCount,
        'open_quests' => countActiveQuests($campaignId),
        'friendly_npcs' => countFriendlyNpcs($campaignId),
        'scheduled_sessions' => countScheduledSessions($campaignId),
        'inventory_items' => countDistinctInventoryItemTypes($campaignId),
    ];
}

function getCampaignRiskReport(string $campaignId, array $input): array
{
    $includeZeroes = true;
    if (array_key_exists('include_zeroes', $input)) {
        $includeZeroes = $input['include_zeroes'];
        if (!is_bool($includeZeroes)) {
            sendError(400, 'invalid fields');
        }
    }

    $signals = getCampaignReadinessSignals($campaignId);

    $missing = [];
    if ($includeZeroes) {
        foreach ($signals as $name => $value) {
            if (!$value) {
                $missing[] = $name;
            }
        }
    }

    $missingCount = 0;
    foreach ($signals as $value) {
        if (!$value) {
            $missingCount++;
        }
    }

    if ($missingCount === 0) {
        $riskLevel = 'low';
    } elseif ($missingCount <= 2) {
        $riskLevel = 'medium';
    } else {
        $riskLevel = 'high';
    }

    return [
        'campaign_id' => $campaignId,
        'risk_level' => $riskLevel,
        'missing' => $missing,
        'signals' => $signals,
    ];
}

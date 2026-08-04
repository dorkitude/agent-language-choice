<?php

declare(strict_types=1);

/**
 * Request dispatcher.
 *
 * All routes are handled in a single if/elseif chain. The first matching
 * branch produces a response and exits; if nothing matches we fall through to
 * a 404.
 */

$method = getMethod();
$path = getPath();
$input = parseInput();

initDatabase();

if ($method === 'GET' && $path === '/v1/storage/status') {
    sendJson(200, [
        'driver' => 'sqlite',
        'schema_version' => 1,
        'initialized' => isInitialized(),
    ]);
} elseif ($method === 'POST' && $path === '/v1/storage/reset') {
    resetDatabase();
    sendJson(200, ['ok' => true, 'schema_version' => 1]);
} elseif ($method === 'GET' && $path === '/health') {
    sendJson(200, ['ok' => true]);
} elseif ($method === 'POST' && $path === '/v1/dice/stats') {
    $expression = is_array($input) ? ($input['expression'] ?? '') : '';
    if (!is_string($expression)) {
        sendError(400, 'invalid expression');
    }

    if (!preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $expression, $m)) {
        sendError(400, 'invalid expression');
    }

    $diceCount = (int) $m[1];
    $sides = (int) $m[2];
    $modifier = isset($m[3], $m[4]) ? (($m[3] === '-' ? -1 : 1) * (int) $m[4]) : 0;

    if ($diceCount <= 0 || $sides <= 0) {
        sendError(400, 'invalid expression');
    }

    $min = $diceCount + $modifier;
    $max = $diceCount * $sides + $modifier;
    $average = ($min + $max) / 2;

    sendJson(200, [
        'dice_count' => $diceCount,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $min,
        'max' => $max,
        'average' => $average,
    ]);
} elseif ($method === 'POST' && $path === '/v1/checks/ability') {
    if (!is_array($input)
        || !array_key_exists('roll', $input)
        || !array_key_exists('modifier', $input)
        || !array_key_exists('dc', $input)
    ) {
        sendError(400, 'missing fields');
    }

    $roll = filter_var($input['roll'], FILTER_VALIDATE_INT);
    $modifier = filter_var($input['modifier'], FILTER_VALIDATE_INT);
    $dc = filter_var($input['dc'], FILTER_VALIDATE_INT);

    if ($roll === false || $modifier === false || $dc === false) {
        sendError(400, 'invalid fields');
    }

    $total = $roll + $modifier;
    sendJson(200, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
} elseif ($method === 'POST' && $path === '/v1/encounters/adjusted-xp') {
    $party = $input['party'] ?? null;
    $monsters = $input['monsters'] ?? null;

    if (!is_array($party) || !is_array($monsters)) {
        sendError(400, 'missing fields');
    }

    $monstersByCrCount = [];
    foreach ($monsters as $monster) {
        if (!is_array($monster)
            || !array_key_exists('cr', $monster)
            || !array_key_exists('count', $monster)
        ) {
            sendError(400, 'invalid monster');
        }
        $cr = $monster['cr'];
        $count = filter_var($monster['count'], FILTER_VALIDATE_INT);
        if ($count === false || $count <= 0) {
            sendError(400, 'invalid monster');
        }
        $monstersByCrCount[$cr] = ($monstersByCrCount[$cr] ?? 0) + $count;
    }

    sendJson(200, calculateEncounterDifficulty($party, $monstersByCrCount));
} elseif ($method === 'POST' && $path === '/v1/initiative/order') {
    $combatants = $input['combatants'] ?? null;
    if (!is_array($combatants)) {
        sendError(400, 'missing combatants');
    }

    sendJson(200, ['order' => sortCombatants($combatants)]);
} elseif ($method === 'POST' && $path === '/v1/characters/ability-modifier') {
    if (!is_array($input) || !array_key_exists('score', $input)) {
        sendError(400, 'missing score');
    }
    $score = filter_var($input['score'], FILTER_VALIDATE_INT);
    if ($score === false || $score < 1 || $score > 30) {
        sendError(400, 'invalid score');
    }
    sendJson(200, [
        'score' => $score,
        'modifier' => abilityModifier($score),
    ]);
} elseif ($method === 'POST' && $path === '/v1/characters/proficiency') {
    if (!is_array($input) || !array_key_exists('level', $input)) {
        sendError(400, 'missing level');
    }
    $level = filter_var($input['level'], FILTER_VALIDATE_INT);
    if ($level === false || $level < 1 || $level > 20) {
        sendError(400, 'invalid level');
    }
    sendJson(200, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
} elseif ($method === 'POST' && $path === '/v1/characters/derived-stats') {
    if (!is_array($input)
        || !array_key_exists('level', $input)
        || !array_key_exists('abilities', $input)
        || !array_key_exists('armor', $input)
    ) {
        sendError(400, 'missing fields');
    }

    $level = filter_var($input['level'], FILTER_VALIDATE_INT);
    if ($level === false || $level < 1 || $level > 20) {
        sendError(400, 'invalid level');
    }

    $abilities = $input['abilities'];
    if (!is_array($abilities)) {
        sendError(400, 'invalid abilities');
    }

    $abilityNames = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $modifiers = [];
    foreach ($abilityNames as $name) {
        if (!array_key_exists($name, $abilities)) {
            sendError(400, 'missing ability: ' . $name);
        }
        $score = filter_var($abilities[$name], FILTER_VALIDATE_INT);
        if ($score === false || $score < 1 || $score > 30) {
            sendError(400, 'invalid ability score: ' . $name);
        }
        $modifiers[$name] = abilityModifier($score);
    }

    $armor = $input['armor'];
    if (!is_array($armor)
        || !array_key_exists('base', $armor)
        || !array_key_exists('shield', $armor)
        || !array_key_exists('dex_cap', $armor)
    ) {
        sendError(400, 'invalid armor');
    }

    $base = filter_var($armor['base'], FILTER_VALIDATE_INT);
    $shield = $armor['shield'];
    $dexCap = filter_var($armor['dex_cap'], FILTER_VALIDATE_INT);
    if ($base === false || !is_bool($shield) || $dexCap === false) {
        sendError(400, 'invalid armor');
    }

    $shieldBonus = $shield ? 2 : 0;
    $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;
    $hpMax = $level * (6 + $modifiers['con']);

    sendJson(200, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $hpMax,
        'armor_class' => $armorClass,
        'modifiers' => $modifiers,
    ]);
} elseif ($method === 'POST' && $path === '/v1/combat/sessions') {
    if (!is_array($input)
        || !array_key_exists('id', $input)
        || !array_key_exists('combatants', $input)
    ) {
        sendError(400, 'missing fields');
    }

    sendJson(200, createCombatSession($input['id'], $input['combatants']));
} elseif ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $sessionMatch)) {
    sendJson(200, addCombatCondition($sessionMatch[1], $input));
} elseif ($method === 'POST' && preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $sessionMatch)) {
    sendJson(200, advanceCombatTurn($sessionMatch[1]));
} elseif ($method === 'POST' && $path === '/v1/auth/register') {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, registerUser($input));
} elseif ($method === 'POST' && $path === '/v1/auth/login') {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(200, loginUser($input));
} elseif ($method === 'POST' && $path === '/v1/compendium/monsters') {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createMonster($input));
} elseif ($method === 'GET' && preg_match('#^/v1/compendium/monsters/([^/]+)$#', $path, $monsterMatch)) {
    $monster = getMonsterBySlug($monsterMatch[1]);
    if ($monster === null) {
        sendError(404, 'monster not found');
    }
    sendJson(200, $monster);
} elseif ($method === 'POST' && $path === '/v1/compendium/items') {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createItem($input));
} elseif ($method === 'GET' && preg_match('#^/v1/compendium/items/([^/]+)$#', $path, $itemMatch)) {
    $item = getItemBySlug($itemMatch[1]);
    if ($item === null) {
        sendError(404, 'item not found');
    }
    sendJson(200, $item);
} elseif ($method === 'POST' && $path === '/v1/campaigns') {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createCampaign($input));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/characters$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createCharacter($campaignMatch[1], $input));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/events$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createEvent($campaignMatch[1], $input));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/state$#', $path, $campaignMatch)) {
    sendJson(200, getCampaignState($campaignMatch[1]));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/audit$#', $path, $campaignMatch)) {
    sendJson(200, getCampaignAudit($campaignMatch[1]));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/export$#', $path, $campaignMatch)) {
    sendJson(200, exportCampaign($campaignMatch[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/quests$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createQuest($campaignMatch[1], $input));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/quests/summary$#', $path, $campaignMatch)) {
    sendJson(200, getQuestSummary($campaignMatch[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/quests/([^/]+)/progress$#', $path, $questMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(200, updateQuestProgress($questMatch[1], $questMatch[2], $input));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/factions$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createFaction($campaignMatch[1], $input));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/npcs$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createNpc($campaignMatch[1], $input));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/relationships$#', $path, $campaignMatch)) {
    sendJson(200, getCampaignRelationships($campaignMatch[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/inventory$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }
    sendJson(201, addInventoryItem($campaignMatch[1], $input));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/characters/([^/]+)/equipment$#', $path, $charMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }
    sendJson(200, assignEquipment($charMatch[1], $charMatch[2], $input));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/inventory/summary$#', $path, $campaignMatch)) {
    sendJson(200, getInventorySummary($campaignMatch[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/downtime/crafting$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }
    sendJson(201, createCraftingProject($campaignMatch[1], $input));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance$#', $path, $craftMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }
    sendJson(200, advanceCraftingProject($craftMatch[1], $craftMatch[2], $input));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/sessions$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }
    sendJson(201, createCampaignSession($campaignMatch[1], $input));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/sessions/next$#', $path, $campaignMatch)) {
    sendJson(200, getNextSession($campaignMatch[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance$#', $path, $sessionMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }
    sendJson(200, recordAttendance($sessionMatch[1], $sessionMatch[2], $input));
} elseif ($method === 'GET' && preg_match('#^/v1/campaigns/([^/]+)/analytics/summary$#', $path, $campaignMatch)) {
    sendJson(200, getCampaignAnalyticsSummary($campaignMatch[1]));
} elseif ($method === 'POST' && preg_match('#^/v1/campaigns/([^/]+)/analytics/risk-report$#', $path, $campaignMatch)) {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }
    sendJson(200, getCampaignRiskReport($campaignMatch[1], $input));
} elseif ($method === 'POST' && $path === '/v1/phb/spell-slots') {
    if (!is_array($input)
        || !array_key_exists('class', $input)
        || !array_key_exists('level', $input)
    ) {
        sendError(400, 'missing fields');
    }

    sendJson(200, getSpellSlots($input));
} elseif ($method === 'POST' && $path === '/v1/phb/rests/long') {
    if (!is_array($input)
        || !array_key_exists('level', $input)
        || !array_key_exists('hp_current', $input)
        || !array_key_exists('hp_max', $input)
        || !array_key_exists('hit_dice_spent', $input)
        || !array_key_exists('exhaustion_level', $input)
    ) {
        sendError(400, 'missing fields');
    }

    sendJson(200, processLongRest($input));
} elseif ($method === 'POST' && $path === '/v1/phb/equipment-load') {
    if (!is_array($input)
        || !array_key_exists('strength', $input)
        || !array_key_exists('weight', $input)
    ) {
        sendError(400, 'missing fields');
    }

    sendJson(200, calculateEquipmentLoad($input));
} elseif ($method === 'POST' && $path === '/v1/dm/encounter-builder') {
    if (!is_array($input)
        || !array_key_exists('campaign_id', $input)
        || !array_key_exists('party', $input)
        || !array_key_exists('monster_slugs', $input)
    ) {
        sendError(400, 'missing fields');
    }

    sendJson(200, buildEncounter($input));
} elseif ($method === 'POST' && $path === '/v1/dm/loot-parcel') {
    if (!is_array($input)
        || !array_key_exists('campaign_id', $input)
        || !array_key_exists('tier', $input)
    ) {
        sendError(400, 'missing fields');
    }

    sendJson(200, generateLootParcel($input));
} elseif ($method === 'POST' && $path === '/v1/dm/session-recap') {
    if (!is_array($input) || !array_key_exists('campaign_id', $input)) {
        sendError(400, 'missing fields');
    }

    sendJson(200, getSessionRecap($input));
} elseif ($method === 'POST' && $path === '/v1/play/campaigns') {
    if (!is_array($input)) {
        sendError(400, 'invalid request');
    }

    sendJson(201, createPlayCampaign($input));
}

sendError(404, 'not found');

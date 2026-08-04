<?php

declare(strict_types=1);

/**
 * DM-facing tools: encounter balancing, loot parcels, and session recaps.
 */

function buildEncounter(array $input): array
{
    if (!array_key_exists('campaign_id', $input)
        || !array_key_exists('party', $input)
        || !array_key_exists('monster_slugs', $input)
    ) {
        sendError(400, 'missing fields');
    }

    $campaignId = $input['campaign_id'];
    $party = $input['party'];
    $monsterSlugs = $input['monster_slugs'];

    if (!is_string($campaignId) || $campaignId === '' || !is_array($party) || !is_array($monsterSlugs)) {
        sendError(400, 'invalid fields');
    }

    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $monstersByCrCount = [];
    foreach ($monsterSlugs as $slug) {
        if (!is_string($slug) || $slug === '') {
            sendError(400, 'invalid monster slug');
        }
        $monster = getMonsterBySlug($slug);
        if ($monster === null) {
            sendError(404, 'monster not found');
        }
        $cr = $monster['cr'];
        $monstersByCrCount[$cr] = ($monstersByCrCount[$cr] ?? 0) + 1;
    }

    $result = calculateEncounterDifficulty($party, $monstersByCrCount);

    return [
        'campaign_id' => $campaignId,
        'base_xp' => $result['base_xp'],
        'adjusted_xp' => $result['adjusted_xp'],
        'difficulty' => $result['difficulty'],
        'monster_count' => $result['monster_count'],
        'recommendation' => recommendationForDifficulty($result['difficulty']),
    ];
}

function generateLootParcel(array $input): array
{
    if (!array_key_exists('campaign_id', $input) || !array_key_exists('tier', $input)) {
        sendError(400, 'missing fields');
    }

    $campaignId = $input['campaign_id'];
    $tier = filter_var($input['tier'], FILTER_VALIDATE_INT);

    if (!is_string($campaignId) || $campaignId === '' || $tier === false) {
        sendError(400, 'invalid fields');
    }

    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    if ($tier !== 1) {
        sendError(400, 'unsupported tier');
    }

    return [
        'campaign_id' => $campaignId,
        'coins_gp' => 75,
        'items' => [
            ['slug' => 'healing-potion', 'quantity' => 2],
        ],
    ];
}

function getSessionRecap(array $input): array
{
    if (!array_key_exists('campaign_id', $input)) {
        sendError(400, 'missing fields');
    }

    $campaignId = $input['campaign_id'];
    if (!is_string($campaignId) || $campaignId === '') {
        sendError(400, 'invalid fields');
    }

    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    return buildSessionRecap($campaignId);
}

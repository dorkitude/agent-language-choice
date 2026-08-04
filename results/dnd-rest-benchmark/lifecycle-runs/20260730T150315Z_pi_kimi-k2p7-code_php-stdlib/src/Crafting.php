<?php

declare(strict_types=1);

/**
 * Downtime crafting projects for campaigns.
 */

function createCraftingProject(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['id', 'character_id', 'item_slug', 'days_required', 'cost_gp'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $characterId = $input['character_id'];
    $itemSlug = $input['item_slug'];
    if (!is_string($id) || $id === '' || !is_string($characterId) || $characterId === '' || !is_string($itemSlug) || $itemSlug === '') {
        sendError(400, 'invalid fields');
    }

    $daysRequired = filter_var($input['days_required'], FILTER_VALIDATE_INT);
    $costGp = filter_var($input['cost_gp'], FILTER_VALIDATE_INT);
    if ($daysRequired === false || $daysRequired <= 0 || $costGp === false || $costGp < 0) {
        sendError(400, 'invalid fields');
    }

    $stmt = db()->prepare('SELECT id FROM characters WHERE id = ? AND campaign_id = ?');
    $stmt->execute([$characterId, $campaignId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        sendError(404, 'character not found');
    }

    $stmt = db()->prepare('SELECT id FROM crafting_projects WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        sendError(409, 'crafting project id already exists');
    }

    $status = 'active';
    $daysCompleted = 0;

    $stmt = db()->prepare('INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, status, cost_gp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $characterId, $itemSlug, $daysRequired, $daysCompleted, $status, $costGp]);

    return [
        'id' => $id,
        'character_id' => $characterId,
        'item_slug' => $itemSlug,
        'days_required' => $daysRequired,
        'days_completed' => $daysCompleted,
        'status' => $status,
    ];
}

function advanceCraftingProject(string $campaignId, string $projectId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    if (!array_key_exists('days', $input)) {
        sendError(400, 'missing fields');
    }

    $days = filter_var($input['days'], FILTER_VALIDATE_INT);
    if ($days === false || $days <= 0) {
        sendError(400, 'invalid days');
    }

    $stmt = db()->prepare('SELECT id, character_id, item_slug, days_required, days_completed, status FROM crafting_projects WHERE id = ? AND campaign_id = ?');
    $stmt->execute([$projectId, $campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        sendError(404, 'crafting project not found');
    }

    $daysRequired = (int) $row['days_required'];
    $daysCompleted = (int) $row['days_completed'];
    $status = $row['status'];
    $itemSlug = $row['item_slug'];

    if ($status === 'complete') {
        sendError(400, 'project already complete');
    }

    $newDaysCompleted = min($daysRequired, $daysCompleted + $days);
    $newStatus = $newDaysCompleted >= $daysRequired ? 'complete' : 'active';

    $stmt = db()->prepare('UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?');
    $stmt->execute([$newDaysCompleted, $newStatus, $projectId]);

    if ($newStatus === 'complete') {
        $stmt = db()->prepare('INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $itemSlug, 1, 'party']);
    }

    return [
        'id' => $projectId,
        'days_completed' => $newDaysCompleted,
        'status' => $newStatus,
    ];
}

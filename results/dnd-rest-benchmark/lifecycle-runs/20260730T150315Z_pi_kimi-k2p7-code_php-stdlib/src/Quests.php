<?php

declare(strict_types=1);

/**
 * Campaign quest tracking.
 */

function createQuest(string $campaignId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $required = ['id', 'title', 'status', 'milestones'];
    foreach ($required as $key) {
        if (!array_key_exists($key, $input)) {
            sendError(400, 'missing fields');
        }
    }

    $id = $input['id'];
    $title = $input['title'];
    $status = $input['status'];
    $milestones = $input['milestones'];

    if (!is_string($id) || $id === '' || !is_string($title) || $title === '') {
        sendError(400, 'invalid fields');
    }

    if (!is_string($status) || !in_array($status, ['active', 'completed', 'blocked'], true)) {
        sendError(400, 'invalid status');
    }

    if (!is_array($milestones) || $milestones === []) {
        sendError(400, 'invalid milestones');
    }

    foreach ($milestones as $milestone) {
        if (!is_string($milestone) || $milestone === '') {
            sendError(400, 'invalid milestone');
        }
    }

    $stmt = db()->prepare('SELECT id FROM quests WHERE id = ?');
    $stmt->execute([$id]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        sendError(409, 'quest id already exists');
    }

    $milestones = array_values(array_unique($milestones));
    $milestonesJson = json_encode($milestones, JSON_UNESCAPED_SLASHES);
    $completedJson = json_encode([], JSON_UNESCAPED_SLASHES);

    $stmt = db()->prepare('INSERT INTO quests (id, campaign_id, title, status, milestones_json, completed_milestones_json) VALUES (?, ?, ?, ?, ?, ?)');
    $stmt->execute([$id, $campaignId, $title, $status, $milestonesJson, $completedJson]);

    return [
        'id' => $id,
        'title' => $title,
        'status' => $status,
        'milestones_total' => count($milestones),
        'milestones_done' => 0,
    ];
}

function updateQuestProgress(string $campaignId, string $questId, array $input): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    if (!array_key_exists('completed', $input)) {
        sendError(400, 'missing fields');
    }

    $completed = $input['completed'];
    if (!is_array($completed)) {
        sendError(400, 'invalid fields');
    }

    foreach ($completed as $milestone) {
        if (!is_string($milestone) || $milestone === '') {
            sendError(400, 'invalid milestone');
        }
    }

    $stmt = db()->prepare('SELECT id, title, status, milestones_json, completed_milestones_json FROM quests WHERE id = ? AND campaign_id = ?');
    $stmt->execute([$questId, $campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        sendError(404, 'quest not found');
    }

    $milestones = json_decode($row['milestones_json'], true);
    $existingCompleted = json_decode($row['completed_milestones_json'], true);

    foreach ($completed as $milestone) {
        if (!in_array($milestone, $milestones, true)) {
            sendError(400, 'invalid milestone');
        }
    }

    $newCompleted = array_values(array_unique(array_merge($existingCompleted, $completed)));
    $milestonesDone = count($newCompleted);
    $milestonesTotal = count($milestones);

    $newStatus = $row['status'];
    if ($milestonesDone === $milestonesTotal) {
        $newStatus = 'completed';
    }

    $stmt = db()->prepare('UPDATE quests SET status = ?, completed_milestones_json = ? WHERE id = ?');
    $stmt->execute([$newStatus, json_encode($newCompleted, JSON_UNESCAPED_SLASHES), $questId]);

    return [
        'id' => $questId,
        'status' => $newStatus,
        'milestones_total' => $milestonesTotal,
        'milestones_done' => $milestonesDone,
    ];
}

function getQuestSummary(string $campaignId): array
{
    if (getCampaignById($campaignId) === null) {
        sendError(404, 'campaign not found');
    }

    $stmt = db()->prepare('SELECT status FROM quests WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $active = 0;
    $completed = 0;
    $blocked = 0;
    while ($row = $stmt->fetch(PDO::FETCH_ASSOC)) {
        if ($row['status'] === 'active') {
            $active++;
        } elseif ($row['status'] === 'completed') {
            $completed++;
        } elseif ($row['status'] === 'blocked') {
            $blocked++;
        }
    }

    return [
        'campaign_id' => $campaignId,
        'active' => $active,
        'completed' => $completed,
        'blocked' => $blocked,
    ];
}

<?php

declare(strict_types=1);

/**
 * Protected play-surface campaigns.
 */

function getPlayCampaignById(string $id): ?array
{
    $stmt = db()->prepare('SELECT id, name, owner, status, max_players FROM play_campaigns WHERE id = ?');
    $stmt->execute([$id]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return null;
    }
    return [
        'id' => $row['id'],
        'name' => $row['name'],
        'owner' => $row['owner'],
        'status' => $row['status'],
        'max_players' => (int) $row['max_players'],
    ];
}

function createPlayCampaign(array $input): array
{
    $required = ['id', 'name', 'max_players'];
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

    $maxPlayers = filter_var($input['max_players'], FILTER_VALIDATE_INT);
    if ($maxPlayers === false || $maxPlayers <= 0) {
        sendError(400, 'invalid max_players');
    }

    $actor = getAuthenticatedUser();
    if ($actor === null) {
        sendError(401, 'invalid credentials');
    }
    if ($actor['role'] !== 'dm') {
        sendError(403, 'forbidden');
    }

    if (getPlayCampaignById($id) !== null) {
        sendError(409, 'campaign already exists');
    }

    $stmt = db()->prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)');
    $stmt->execute([$id, $name, $actor['username'], 'lobby', $maxPlayers]);

    return [
        'id' => $id,
        'name' => $name,
        'owner' => $actor['username'],
        'status' => 'lobby',
        'max_players' => $maxPlayers,
    ];
}

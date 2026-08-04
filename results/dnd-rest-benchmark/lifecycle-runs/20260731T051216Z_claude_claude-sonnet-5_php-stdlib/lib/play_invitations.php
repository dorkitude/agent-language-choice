<?php
declare(strict_types=1);

// Routes: Play campaign invitations
// ---------------------------------------------------------------------------

function next_invitation_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) AS max_seq FROM play_campaign_invitations WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

function is_campaign_member(PDO $db, string $campaignId, string $username): bool {
    $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $username]);
    return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/invitations$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the dm owner may invite players');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['invitation_id'], $body['username'], $body['character_id'])
        || !is_string($body['invitation_id']) || $body['invitation_id'] === ''
        || !is_string($body['username']) || $body['username'] === ''
        || !is_string($body['character_id']) || $body['character_id'] === '') {
        bad_request();
    }

    $invitationId = $body['invitation_id'];
    $targetUsername = $body['username'];
    $characterId = $body['character_id'];

    $targetUser = load_user($db, $targetUsername);
    if ($targetUser === null || ($targetUser['role'] ?? null) !== 'player') {
        bad_request('unknown or non-player target user');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?');
    $stmt->execute([$campaignId, $invitationId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('invitation id already exists');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_invitations WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    foreach ($stmt->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $existing = json_decode($row['data'], true);
        if ($existing['username'] === $targetUsername && $existing['status'] === 'pending') {
            conflict('an active invitation already exists for this user');
        }
    }

    $invitation = [
        'invitation_id' => $invitationId,
        'username' => $targetUsername,
        'character_id' => $characterId,
        'status' => 'pending',
    ];

    $seq = next_invitation_sequence($db, $campaignId);
    $stmt = $db->prepare('INSERT INTO play_campaign_invitations (campaign_id, invitation_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $invitationId, $seq, json_encode($invitation)]);

    send_json($invitation, 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/invitations/([^/]+)/accept$#', $path, $pm)) {
    $campaignId = $pm[1];
    $invitationId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $stmt = $db->prepare('SELECT data FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?');
    $stmt->execute([$campaignId, $invitationId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('invitation not found');
    }
    $invitation = json_decode($row['data'], true);

    if ($actor['username'] !== $invitation['username']) {
        forbidden('only the invited user may accept this invitation');
    }

    if ($invitation['status'] !== 'pending') {
        conflict('invitation is not pending');
    }

    $invitation['status'] = 'accepted';
    $stmt = $db->prepare('UPDATE play_campaign_invitations SET data = ? WHERE campaign_id = ? AND invitation_id = ?');
    $stmt->execute([json_encode($invitation), $campaignId, $invitationId]);

    if (!is_campaign_member($db, $campaignId, $actor['username'])) {
        $membership = [
            'username' => $actor['username'],
            'character_id' => $invitation['character_id'],
            'name' => $actor['username'],
            'class' => '',
            'gold' => 10,
        ];
        $stmt = $db->prepare('INSERT INTO play_campaign_members (campaign_id, username, character_id, data) VALUES (?, ?, ?, ?)');
        $stmt->execute([$campaignId, $actor['username'], $invitation['character_id'], json_encode($membership)]);
    }

    send_json($invitation);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/invitations$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];

    $stmt = $db->prepare('SELECT data FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    $invitations = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);

    if (!$isOwner) {
        $invitations = array_values(array_filter($invitations, function ($invitation) use ($actor) {
            return $invitation['username'] === $actor['username'];
        }));
    }

    send_json(['invitations' => array_values($invitations)]);
}

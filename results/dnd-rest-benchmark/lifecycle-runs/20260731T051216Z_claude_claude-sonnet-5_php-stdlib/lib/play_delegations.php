<?php
declare(strict_types=1);

// Routes: Play campaign GM delegation
// ---------------------------------------------------------------------------

function next_delegation_audit_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) AS max_seq FROM play_campaign_delegation_audit WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

function append_delegation_audit(PDO $db, string $campaignId, string $username, string $action, array $powers): void {
    $entry = [
        'username' => $username,
        'action' => $action,
        'powers' => $powers,
    ];
    $seq = next_delegation_audit_sequence($db, $campaignId);
    $stmt = $db->prepare('INSERT INTO play_campaign_delegation_audit (campaign_id, seq, data) VALUES (?, ?, ?)');
    $stmt->execute([$campaignId, $seq, json_encode($entry)]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/delegations$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign owner may grant delegation');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['username'], $body['powers'])
        || !is_string($body['username']) || $body['username'] === ''
        || !is_array($body['powers']) || count($body['powers']) === 0) {
        bad_request();
    }

    $targetUsername = $body['username'];
    $powers = $body['powers'];

    if (count($powers) !== count(array_unique($powers))) {
        bad_request('duplicate powers');
    }
    foreach ($powers as $power) {
        if (!is_string($power) || !in_array($power, VALID_DELEGATION_POWERS, true)) {
            bad_request('invalid power');
        }
    }

    if (!is_campaign_member($db, $campaignId, $targetUsername)) {
        bad_request('unknown or non-member target user');
    }

    $existing = load_delegation($db, $campaignId, $targetUsername);
    if ($existing !== null && $existing['active'] === true) {
        conflict('an active delegate already exists for this user');
    }

    $delegation = [
        'username' => $targetUsername,
        'powers' => array_values($powers),
        'active' => true,
    ];

    if ($existing === null) {
        $stmt = $db->prepare('INSERT INTO play_campaign_delegations (campaign_id, username, data) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $targetUsername, json_encode($delegation)]);
    } else {
        $stmt = $db->prepare('UPDATE play_campaign_delegations SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($delegation), $campaignId, $targetUsername]);
    }

    append_delegation_audit($db, $campaignId, $targetUsername, 'granted', array_values($powers));

    send_json($delegation, 201);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/delegations/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $targetUsername = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign owner may revoke delegation');
    }

    $existing = load_delegation($db, $campaignId, $targetUsername);
    if ($existing === null) {
        not_found('delegation not found');
    }

    $delegation = $existing;
    $delegation['active'] = false;

    $stmt = $db->prepare('UPDATE play_campaign_delegations SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($delegation), $campaignId, $targetUsername]);

    append_delegation_audit($db, $campaignId, $targetUsername, 'revoked', $delegation['powers']);

    send_json($delegation);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/delegations/audit$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign owner may read delegation audit');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    $entries = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);

    send_json(['entries' => array_values($entries)]);
}

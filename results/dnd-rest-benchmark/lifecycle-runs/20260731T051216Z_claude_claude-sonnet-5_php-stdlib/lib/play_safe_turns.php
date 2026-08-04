<?php
declare(strict_types=1);

// Routes: Play campaign concurrent-safe turn submission
// ---------------------------------------------------------------------------

// Returns the current safe-turn counter for a campaign, creating the row
// (starting at turn 1) if this is the first submission/read for it.
function get_or_init_safe_turn_state(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row !== false) {
        return (int)$row['current_turn'];
    }
    $stmt = $db->prepare('INSERT OR IGNORE INTO play_campaign_safe_turns (campaign_id, current_turn) VALUES (?, 1)');
    $stmt->execute([$campaignId]);
    return 1;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/safe-turns$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner && !is_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('must be a campaign member to submit safe turns');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['submission_id'], $body['expected_turn'], $body['action'])
        || !is_string($body['submission_id']) || trim($body['submission_id']) === ''
        || !is_string($body['action']) || trim($body['action']) === ''
        || !is_valid_int_range($body['expected_turn'], 1, PHP_INT_MAX)) {
        bad_request('submission_id, action, and a positive integer expected_turn are required');
    }
    $submissionId = $body['submission_id'];
    $action = $body['action'];
    $expectedTurn = (int)$body['expected_turn'];

    $db->beginTransaction();
    try {
        $currentTurn = get_or_init_safe_turn_state($db, $campaignId);

        $stmt = $db->prepare('SELECT 1 FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? AND submission_id = ?');
        $stmt->execute([$campaignId, $submissionId]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
            $db->commit();
            conflict('submission_id already used in this campaign');
        }

        if ($expectedTurn !== $currentTurn) {
            $db->commit();
            send_json(['current_turn' => $currentTurn], 409);
        }

        $acceptedTurn = $currentTurn;
        $nextTurn = $currentTurn + 1;

        $stmt = $db->prepare('SELECT COALESCE(MAX(sequence), 0) AS max_seq FROM play_campaign_safe_turn_submissions WHERE campaign_id = ?');
        $stmt->execute([$campaignId]);
        $sequence = (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;

        $stmt = $db->prepare('INSERT INTO play_campaign_safe_turn_submissions (campaign_id, sequence, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?, ?)');
        $stmt->execute([$campaignId, $sequence, $submissionId, $action, $acceptedTurn, $nextTurn]);

        $stmt = $db->prepare('UPDATE play_campaign_safe_turns SET current_turn = ? WHERE campaign_id = ?');
        $stmt->execute([$nextTurn, $campaignId]);

        $db->commit();
    } catch (Throwable $e) {
        if ($db->inTransaction()) {
            $db->rollBack();
        }
        throw $e;
    }

    send_json([
        'submission_id' => $submissionId,
        'action' => $action,
        'accepted_turn' => $acceptedTurn,
        'next_turn' => $nextTurn,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/safe-turns$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isOwner = $actor['username'] === $campaign['owner'];
    if (!$isOwner && !is_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('must be a campaign member to read safe turns');
    }

    $currentTurn = get_or_init_safe_turn_state($db, $campaignId);

    $stmt = $db->prepare('SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? ORDER BY sequence ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $accepted = array_map(function (array $row): array {
        return [
            'submission_id' => $row['submission_id'],
            'action' => $row['action'],
            'accepted_turn' => (int)$row['accepted_turn'],
            'next_turn' => (int)$row['next_turn'],
        ];
    }, $rows);

    send_json([
        'current_turn' => $currentTurn,
        'accepted' => $accepted,
    ]);
}

<?php
declare(strict_types=1);

// Routes: campaign-scoped transactional currency transfers. Unlike the
// simpler currency/transfers endpoint, a failed (simulated or otherwise)
// compound mutation here must leave no partial debit, credit, or transfer
// record behind.

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/transactional-transfers$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $actor['username']]);
    $isMember = $stmt->fetch(PDO::FETCH_ASSOC) !== false;
    if (!$isMember && $actor['username'] !== $campaign['owner']) {
        forbidden('only a campaign member may create a transfer');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['from_character_id']) || !is_string($body['from_character_id']) || $body['from_character_id'] === ''
        || !isset($body['to_character_id']) || !is_string($body['to_character_id']) || $body['to_character_id'] === ''
        || !isset($body['amount']) || !is_valid_int_range($body['amount'], PHP_INT_MIN, PHP_INT_MAX)) {
        bad_request();
    }
    $fromCharId = $body['from_character_id'];
    $toCharId = $body['to_character_id'];
    $amount = (int)$body['amount'];
    $simulateFailure = isset($body['simulate_failure']) && $body['simulate_failure'] === true;

    if ($fromCharId === $toCharId || $amount <= 0) {
        bad_request();
    }

    $fromFound = find_play_character($db, $campaignId, $fromCharId);
    if ($fromFound === null) {
        bad_request('source character not found in this campaign');
    }
    [$fromUsername, $fromMember] = $fromFound;

    $toFound = find_play_character($db, $campaignId, $toCharId);
    if ($toFound === null) {
        bad_request('destination character not found in this campaign');
    }
    [$toUsername, $toMember] = $toFound;

    $owner = play_character_owner($db, $campaignId, $fromCharId, $fromUsername);
    if ($actor['username'] !== $owner) {
        forbidden('only the owner of the source character may create this transfer');
    }

    $fromGold = (int)($fromMember['gold'] ?? 10);
    $toGold = (int)($toMember['gold'] ?? 10);

    if ($fromGold < $amount) {
        conflict('insufficient gold');
    }

    $fromGoldAfter = $fromGold - $amount;
    $toGoldAfter = $toGold + $amount;

    if ($simulateFailure) {
        send_json(['error' => 'simulated failure'], 500);
    }

    $stmt = $db->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 AS next_seq FROM play_transactional_transfers WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $sequence = (int)$stmt->fetch(PDO::FETCH_ASSOC)['next_seq'];

    $db->beginTransaction();
    try {
        $fromMember['gold'] = $fromGoldAfter;
        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($fromMember), $campaignId, $fromUsername]);

        $toMember['gold'] = $toGoldAfter;
        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($toMember), $campaignId, $toUsername]);

        $transfer = [
            'from_character_id' => $fromCharId,
            'to_character_id' => $toCharId,
            'amount' => $amount,
            'from_gold' => $fromGoldAfter,
            'to_gold' => $toGoldAfter,
            'sequence' => $sequence,
        ];
        $stmt = $db->prepare('INSERT INTO play_transactional_transfers (campaign_id, sequence, data) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $sequence, json_encode($transfer)]);

        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }

    send_json($transfer, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/transactional-transfers$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view transactional transfers');
        }
    }

    $stmt = $db->prepare('SELECT data FROM play_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);
    $transfers = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);

    send_json(['transfers' => array_values($transfers)], 200);
}

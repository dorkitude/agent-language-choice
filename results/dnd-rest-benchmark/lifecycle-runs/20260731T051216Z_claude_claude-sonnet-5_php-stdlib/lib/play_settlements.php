<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped DM-managed settlements with services,
// availability, and player discovery)
// ---------------------------------------------------------------------------

function require_play_settlement(PDO $db, string $campaignId, string $settlementId): array {
    $stmt = $db->prepare('SELECT data FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
    $stmt->execute([$campaignId, $settlementId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('settlement not found');
    }
    return json_decode($row['data'], true);
}

function validate_settlement_payload($body): ?array {
    if ($body === null
        || !isset($body['name'], $body['services'], $body['availability'])
        || !is_string($body['name']) || $body['name'] === ''
        || !is_array($body['services'])
        || !is_string($body['availability'])) {
        return null;
    }

    if (!in_array($body['availability'], ['open', 'limited', 'closed'], true)) {
        return null;
    }

    if (count($body['services']) === 0) {
        return null;
    }

    $services = [];
    foreach ($body['services'] as $service) {
        if (!is_string($service)) {
            return null;
        }
        $trimmed = trim($service);
        if ($trimmed === '') {
            return null;
        }
        if (in_array($trimmed, $services, true)) {
            return null;
        }
        $services[] = $trimmed;
    }

    return [
        'name' => $body['name'],
        'services' => $services,
        'availability' => $body['availability'],
    ];
}

function settlement_for_actor(array $settlement, bool $isDm, ?string $ownCharacterId): array {
    if ($isDm) {
        return $settlement;
    }

    $discovered = ($ownCharacterId !== null && in_array($ownCharacterId, $settlement['discovered_by'], true))
        ? [$ownCharacterId]
        : [];

    return [
        'settlement_id' => $settlement['settlement_id'],
        'name' => $settlement['name'],
        'services' => $settlement['services'],
        'availability' => $settlement['availability'],
        'discovered_by' => $discovered,
    ];
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create settlements');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['settlement_id']) || !is_string($body['settlement_id']) || $body['settlement_id'] === '') {
        bad_request();
    }
    $settlementId = $body['settlement_id'];

    $validated = validate_settlement_payload($body);
    if ($validated === null) {
        bad_request();
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
    $stmt->execute([$campaignId, $settlementId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('settlement id already exists in this campaign');
    }

    $settlement = [
        'settlement_id' => $settlementId,
        'name' => $validated['name'],
        'services' => $validated['services'],
        'availability' => $validated['availability'],
        'discovered_by' => [],
    ];

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_settlements WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_settlements (campaign_id, settlement_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $settlementId, $seq, json_encode($settlement)]);

    send_json($settlement, 201);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $settlementId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may update settlements');
    }

    $existing = require_play_settlement($db, $campaignId, $settlementId);

    $body = read_json_body();
    $validated = validate_settlement_payload($body);
    if ($validated === null) {
        bad_request();
    }

    $settlement = [
        'settlement_id' => $settlementId,
        'name' => $validated['name'],
        'services' => $validated['services'],
        'availability' => $validated['availability'],
        'discovered_by' => $existing['discovered_by'],
    ];

    $stmt = $db->prepare('UPDATE play_campaign_settlements SET data = ? WHERE campaign_id = ? AND settlement_id = ?');
    $stmt->execute([json_encode($settlement), $campaignId, $settlementId]);

    send_json($settlement, 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/discover$#', $path, $pm)) {
    $campaignId = $pm[1];
    $settlementId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] === $campaign['owner'] || !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only a joined campaign player may discover settlements');
    }

    $settlement = require_play_settlement($db, $campaignId, $settlementId);

    $stmt = $db->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $actor['username']]);
    $ownCharacterId = $stmt->fetchColumn();

    $alreadyDiscovered = in_array($ownCharacterId, $settlement['discovered_by'], true);
    if (!$alreadyDiscovered) {
        $settlement['discovered_by'][] = $ownCharacterId;
        $stmt = $db->prepare('UPDATE play_campaign_settlements SET data = ? WHERE campaign_id = ? AND settlement_id = ?');
        $stmt->execute([json_encode($settlement), $campaignId, $settlementId]);
    }

    $response = settlement_for_actor($settlement, false, $ownCharacterId);
    send_json($response, $alreadyDiscovered ? 200 : 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/settlements$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isDm = $actor['username'] === $campaign['owner'];
    if (!$isDm && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view settlements');
    }

    $ownCharacterId = null;
    if (!$isDm) {
        $stmt = $db->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        $ownCharacterId = $stmt->fetchColumn();
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_COLUMN);
    $settlements = array_map(fn($row) => json_decode($row, true), $rows);

    if (!$isDm) {
        $settlements = array_values(array_filter($settlements, function ($settlement) use ($ownCharacterId) {
            return in_array($ownCharacterId, $settlement['discovered_by'], true);
        }));
        $settlements = array_map(fn($settlement) => settlement_for_actor($settlement, false, $ownCharacterId), $settlements);
    }

    send_json(['settlements' => $settlements], 200);
}

<?php
declare(strict_types=1);

// Routes: Play (campaign-scoped DM clues revealed to a character, the party, or nobody)
// ---------------------------------------------------------------------------

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/clues$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the campaign dm may create clues');
    }

    $body = read_json_body();
    if ($body === null
        || !isset($body['clue_id'], $body['text'], $body['audience'])
        || !is_string($body['clue_id']) || $body['clue_id'] === ''
        || !is_string($body['text']) || $body['text'] === ''
        || !is_string($body['audience'])) {
        bad_request();
    }
    $clueId = $body['clue_id'];
    $text = $body['text'];
    $audience = $body['audience'];

    if (!in_array($audience, ['character', 'party', 'hidden'], true)) {
        bad_request('invalid audience');
    }

    if ($audience === 'character') {
        if (!isset($body['character_id']) || !is_string($body['character_id']) || $body['character_id'] === '') {
            bad_request('character_id is required for character audience');
        }
        $characterId = $body['character_id'];
        if (find_play_character($db, $campaignId, $characterId) === null) {
            bad_request('character_id must name a campaign member character');
        }
    } else {
        if (isset($body['character_id'])) {
            bad_request('character_id must be omitted for this audience');
        }
        $characterId = null;
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_clues WHERE campaign_id = ? AND clue_id = ?');
    $stmt->execute([$campaignId, $clueId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('clue id already exists in this campaign');
    }

    $clue = [
        'clue_id' => $clueId,
        'text' => $text,
        'audience' => $audience,
    ];
    if ($audience === 'character') {
        $clue['character_id'] = $characterId;
    }

    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) + 1 FROM play_campaign_clues WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $seq = (int)$stmt->fetchColumn();

    $stmt = $db->prepare('INSERT INTO play_campaign_clues (campaign_id, clue_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $clueId, $seq, json_encode($clue)]);

    send_json($clue, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/clues$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $isDm = $actor['username'] === $campaign['owner'];
    if (!$isDm && !is_play_campaign_member($db, $campaignId, $actor['username'])) {
        forbidden('only the owner or a party member may view clues');
    }

    $stmt = $db->prepare('SELECT data FROM play_campaign_clues WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_COLUMN);
    $clues = array_map(fn($row) => json_decode($row, true), $rows);

    if (!$isDm) {
        $stmt = $db->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        $ownCharacterId = $stmt->fetchColumn();

        $clues = array_values(array_filter($clues, function ($clue) use ($ownCharacterId) {
            if ($clue['audience'] === 'party') {
                return true;
            }
            if ($clue['audience'] === 'character') {
                return $clue['character_id'] === $ownCharacterId;
            }
            return false;
        }));
    }

    send_json(['clues' => $clues], 200);
}

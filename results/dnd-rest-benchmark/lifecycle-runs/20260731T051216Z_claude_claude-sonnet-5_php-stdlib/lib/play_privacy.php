<?php
declare(strict_types=1);

// Routes: campaign-scoped privacy controls -- role-filtered notes,
// character-to-character whispers, and basic character sheets.
// ---------------------------------------------------------------------------

function play_campaign_is_member(PDO $db, string $campaignId, string $username): bool {
    $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $username]);
    return $stmt->fetch(PDO::FETCH_ASSOC) !== false;
}

// Enforces the baseline visibility rule shared by every privacy-controls
// route: the actor must be the campaign DM or a campaign member. Returns
// whether the actor is the DM; sends 403 and exits otherwise.
function require_campaign_access(PDO $db, array $campaign, array $actor): bool {
    $isDm = $actor['username'] === $campaign['owner'];
    if (!$isDm && !play_campaign_is_member($db, $campaign['id'], $actor['username'])) {
        forbidden('only the dm or a campaign member may access this campaign');
    }
    return $isDm;
}

function next_note_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) AS max_seq FROM play_campaign_notes WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

function next_whisper_sequence(PDO $db, string $campaignId): int {
    $stmt = $db->prepare('SELECT COALESCE(MAX(seq), 0) AS max_seq FROM play_campaign_whispers WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    return (int)$stmt->fetch(PDO::FETCH_ASSOC)['max_seq'] + 1;
}

function is_valid_visibility($value): bool {
    return is_string($value) && in_array($value, ['private', 'party'], true);
}

// ---------------------------------------------------------------------------
// Notes
// ---------------------------------------------------------------------------

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/notes$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if (!play_campaign_is_member($db, $campaignId, $actor['username'])) {
        forbidden('only a campaign member may create notes');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['note_id'], $body['text'], $body['visibility'])
        || !is_string($body['note_id']) || $body['note_id'] === ''
        || !is_string($body['text']) || $body['text'] === ''
        || !is_valid_visibility($body['visibility'])) {
        bad_request();
    }
    $noteId = $body['note_id'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
    $stmt->execute([$campaignId, $noteId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('note id already exists');
    }

    $note = [
        'note_id' => $noteId,
        'text' => $body['text'],
        'visibility' => $body['visibility'],
        'owner' => $actor['username'],
    ];

    $seq = next_note_sequence($db, $campaignId);
    $stmt = $db->prepare('INSERT INTO play_campaign_notes (campaign_id, note_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $noteId, $seq, json_encode($note)]);

    send_json($note, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/notes$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    $isDm = require_campaign_access($db, $campaign, $actor);

    $stmt = $db->prepare('SELECT data FROM play_campaign_notes WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $notes = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);

    if (!$isDm) {
        $notes = array_values(array_filter($notes, function ($note) use ($actor) {
            if ($note['visibility'] === 'party') {
                return true;
            }
            return $note['owner'] === $actor['username'];
        }));
    }

    send_json(['notes' => array_values($notes)]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/notes/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $noteId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    $isDm = require_campaign_access($db, $campaign, $actor);

    $stmt = $db->prepare('SELECT data FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
    $stmt->execute([$campaignId, $noteId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('note not found');
    }
    $note = json_decode($row['data'], true);

    if (!$isDm && $note['visibility'] === 'private' && $note['owner'] !== $actor['username']) {
        forbidden('this note is private to its owner');
    }

    send_json($note);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/notes/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $noteId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    require_campaign_access($db, $campaign, $actor);

    $stmt = $db->prepare('SELECT data FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
    $stmt->execute([$campaignId, $noteId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        not_found('note not found');
    }
    $note = json_decode($row['data'], true);

    if ($note['owner'] !== $actor['username']) {
        forbidden('only the note owner may update this note');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['text'], $body['visibility'])
        || !is_string($body['text']) || $body['text'] === ''
        || !is_valid_visibility($body['visibility'])) {
        bad_request();
    }

    $note['text'] = $body['text'];
    $note['visibility'] = $body['visibility'];

    $stmt = $db->prepare('UPDATE play_campaign_notes SET data = ? WHERE campaign_id = ? AND note_id = ?');
    $stmt->execute([json_encode($note), $campaignId, $noteId]);

    send_json($note);
}

// ---------------------------------------------------------------------------
// Whispers
// ---------------------------------------------------------------------------

// Finds the character_id currently owned by a username, or null if the
// actor is not a player with an owned character in this campaign.
function play_actor_owned_character(PDO $db, string $campaignId, string $username): ?string {
    $stmt = $db->prepare('SELECT username, character_id FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
    $stmt->execute([$campaignId]);
    $members = $stmt->fetchAll(PDO::FETCH_ASSOC);
    foreach ($members as $member) {
        $owner = play_character_owner($db, $campaignId, $member['character_id'], $member['username']);
        if ($owner === $username) {
            return $member['character_id'];
        }
    }
    return null;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/whispers$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if (!play_campaign_is_member($db, $campaignId, $actor['username'])) {
        forbidden('only a campaign player may send whispers');
    }

    $fromCharacterId = play_actor_owned_character($db, $campaignId, $actor['username']);
    if ($fromCharacterId === null) {
        forbidden('only a campaign player with an owned character may send whispers');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['whisper_id'], $body['to_character_id'], $body['text'])
        || !is_string($body['whisper_id']) || $body['whisper_id'] === ''
        || !is_string($body['to_character_id']) || $body['to_character_id'] === ''
        || !is_string($body['text']) || $body['text'] === '') {
        bad_request();
    }
    $whisperId = $body['whisper_id'];
    $toCharacterId = $body['to_character_id'];

    if (find_play_character($db, $campaignId, $toCharacterId) === null) {
        bad_request('to_character_id must belong to a current campaign member');
    }

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_whispers WHERE campaign_id = ? AND whisper_id = ?');
    $stmt->execute([$campaignId, $whisperId]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) !== false) {
        conflict('whisper id already exists');
    }

    $whisper = [
        'whisper_id' => $whisperId,
        'from_character_id' => $fromCharacterId,
        'to_character_id' => $toCharacterId,
        'text' => $body['text'],
    ];

    $seq = next_whisper_sequence($db, $campaignId);
    $stmt = $db->prepare('INSERT INTO play_campaign_whispers (campaign_id, whisper_id, seq, data) VALUES (?, ?, ?, ?)');
    $stmt->execute([$campaignId, $whisperId, $seq, json_encode($whisper)]);

    send_json($whisper, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/whispers$#', $path, $pm)) {
    $campaignId = $pm[1];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);
    $isDm = require_campaign_access($db, $campaign, $actor);

    $stmt = $db->prepare('SELECT data FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY seq ASC');
    $stmt->execute([$campaignId]);
    $rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

    $whispers = array_map(function ($r) {
        return json_decode($r['data'], true);
    }, $rows);

    if (!$isDm) {
        $ownedCharacterId = play_actor_owned_character($db, $campaignId, $actor['username']);
        $whispers = array_values(array_filter($whispers, function ($whisper) use ($ownedCharacterId) {
            return $ownedCharacterId !== null
                && ($whisper['from_character_id'] === $ownedCharacterId || $whisper['to_character_id'] === $ownedCharacterId);
        }));
    }

    send_json(['whispers' => array_values($whispers)]);
}

// ---------------------------------------------------------------------------
// Character sheets
// ---------------------------------------------------------------------------

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/sheet$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $isDm = $actor['username'] === $campaign['owner'];
    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);

    if (!$isDm && $actor['username'] !== $owner) {
        forbidden('only the character owner or the dm may view this sheet');
    }

    send_json([
        'character_id' => $charId,
        'owner' => $owner,
        'name' => $member['name'],
        'class' => $member['class'],
        'level' => 1,
        'proficiency_bonus' => 2,
        'hp_max' => 10,
        'armor_class' => 10,
    ]);
}

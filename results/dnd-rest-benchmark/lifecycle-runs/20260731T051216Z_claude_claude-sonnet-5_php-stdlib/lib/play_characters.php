<?php
declare(strict_types=1);

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/damage$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        forbidden('only the owner may apply damage');
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$username, $member] = $found;

    $body = read_json_body();
    if ($body === null || !isset($body['amount']) || !is_valid_int_range($body['amount'], 0, PHP_INT_MAX)) {
        bad_request();
    }
    $amount = (int)$body['amount'];

    $hpMax = (int)($member['hp_max'] ?? 20);
    $hpBefore = (int)($member['hp_current'] ?? $hpMax);
    $hpCurrent = max(0, min($hpMax, $hpBefore - $amount));
    $member['hp_max'] = $hpMax;
    $member['hp_current'] = $hpCurrent;

    if ($hpCurrent === 0) {
        if (($member['status'] ?? 'alive') === 'alive') {
            $member['status'] = 'unconscious';
            $member['death_saves'] = ['successes' => 0, 'failures' => 0];
        }
    } else {
        $member['status'] = 'alive';
        unset($member['death_saves']);
    }

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $username]);

    send_json([
        'character_id' => $charId,
        'target' => $charId,
        'hp_current' => $hpCurrent,
        'hp_max' => $hpMax,
        'hp_before' => $hpBefore,
        'hp_after' => $hpCurrent,
        'damage' => $amount,
        'status' => $member['status'],
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/death-saves$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$username, $member] = $found;

    if ($actor['username'] !== $username) {
        forbidden("only the character's owner may roll a death save");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['outcome']) || !is_string($body['outcome'])
        || !in_array($body['outcome'], ['success', 'failure'], true)) {
        bad_request();
    }
    $outcome = $body['outcome'];

    $status = $member['status'] ?? 'alive';
    if ($status !== 'unconscious') {
        conflict('character is not making death saves');
    }

    $deathSaves = $member['death_saves'] ?? ['successes' => 0, 'failures' => 0];
    if ($outcome === 'success') {
        $deathSaves['successes']++;
    } else {
        $deathSaves['failures']++;
    }

    if ($deathSaves['successes'] >= 3) {
        $status = 'stable';
    } elseif ($deathSaves['failures'] >= 3) {
        $status = 'dead';
    }

    $member['death_saves'] = $deathSaves;
    $member['status'] = $status;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $username]);

    send_json([
        'character_id' => $charId,
        'successes' => $deathSaves['successes'],
        'failures' => $deathSaves['failures'],
        'status' => $status,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/status$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view character status');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    $hpMax = (int)($member['hp_max'] ?? 20);
    $hpCurrent = (int)($member['hp_current'] ?? $hpMax);

    send_json([
        'character_id' => $charId,
        'hp_current' => $hpCurrent,
        'hp_max' => $hpMax,
        'status' => $member['status'] ?? 'alive',
    ], 200);
}

// Returns the current owner username for a campaign character, defaulting to
// the username that created the membership row if no explicit claim/transfer
// has happened yet.
function play_character_owner(PDO $db, string $campaignId, string $charId, string $defaultOwner): string {
    $stmt = $db->prepare('SELECT owner FROM play_character_owners WHERE campaign_id = ? AND character_id = ?');
    $stmt->execute([$campaignId, $charId]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    if ($row === false) {
        return $defaultOwner;
    }
    return $row['owner'];
}

function set_play_character_owner(PDO $db, string $campaignId, string $charId, string $owner): void {
    $stmt = $db->prepare('INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?)
        ON CONFLICT(campaign_id, character_id) DO UPDATE SET owner = excluded.owner');
    $stmt->execute([$campaignId, $charId, $owner]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/owner$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view character ownership');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, ] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);

    send_json([
        'character_id' => $charId,
        'owner' => $owner,
    ]);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/claim$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $actor['username']]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        forbidden('only a campaign member may claim a character');
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, ] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($owner !== $actor['username']) {
        conflict('character is already owned by another player');
    }

    set_play_character_owner($db, $campaignId, $charId, $actor['username']);

    send_json([
        'character_id' => $charId,
        'owner' => $actor['username'],
    ], 201);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/transfer$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, ] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden('only the owner may transfer this character');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['new_owner']) || !is_string($body['new_owner']) || $body['new_owner'] === '') {
        bad_request();
    }
    $newOwner = $body['new_owner'];

    $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $stmt->execute([$campaignId, $newOwner]);
    if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
        bad_request('new owner must be a campaign member');
    }

    set_play_character_owner($db, $campaignId, $charId, $newOwner);

    send_json([
        'character_id' => $charId,
        'owner' => $newOwner,
    ]);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view character currency');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    send_json([
        'character_id' => $charId,
        'gold' => (int)($member['gold'] ?? 10),
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency/transfers$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$fromUsername, $fromMember] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $fromUsername);
    if ($actor['username'] !== $owner) {
        forbidden('only the source character owner may transfer gold');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['to_character_id']) || !is_string($body['to_character_id'])
        || $body['to_character_id'] === '' || !isset($body['gold']) || !is_valid_int_range($body['gold'], PHP_INT_MIN, PHP_INT_MAX)) {
        bad_request();
    }
    $toCharId = $body['to_character_id'];
    $amount = (int)$body['gold'];

    if ($toCharId === $charId || $amount <= 0) {
        bad_request();
    }

    $toFound = find_play_character($db, $campaignId, $toCharId);
    if ($toFound === null) {
        bad_request('destination character not found in this campaign');
    }
    [$toUsername, $toMember] = $toFound;

    $fromGold = (int)($fromMember['gold'] ?? 10);
    $toGold = (int)($toMember['gold'] ?? 10);

    if ($fromGold < $amount) {
        conflict('insufficient gold');
    }

    $fromGoldAfter = $fromGold - $amount;
    $toGoldAfter = $toGold + $amount;

    $stmt = $db->prepare('SELECT COALESCE(MAX(transfer_id), 0) + 1 AS next_id FROM play_character_transfers WHERE campaign_id = ?');
    $stmt->execute([$campaignId]);
    $transferId = (int)$stmt->fetch(PDO::FETCH_ASSOC)['next_id'];

    $db->beginTransaction();
    try {
        $fromMember['gold'] = $fromGoldAfter;
        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($fromMember), $campaignId, $fromUsername]);

        $toMember['gold'] = $toGoldAfter;
        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($toMember), $campaignId, $toUsername]);

        $transfer = [
            'transfer_id' => $transferId,
            'from_character_id' => $charId,
            'to_character_id' => $toCharId,
            'gold' => $amount,
            'from_gold' => $fromGoldAfter,
            'to_gold' => $toGoldAfter,
        ];
        $stmt = $db->prepare('INSERT INTO play_character_transfers (campaign_id, transfer_id, data) VALUES (?, ?, ?)');
        $stmt->execute([$campaignId, $transferId, json_encode($transfer)]);

        $db->commit();
    } catch (Throwable $e) {
        $db->rollBack();
        throw $e;
    }

    send_json($transfer, 201);
}

const VALID_CHARACTER_RACES = [
    'human', 'elf', 'dwarf', 'halfling', 'dragonborn', 'gnome', 'half-elf', 'half-orc', 'tiefling',
];

const VALID_CHARACTER_CLASSES = [
    'barbarian', 'bard', 'cleric', 'druid', 'fighter', 'monk',
    'paladin', 'ranger', 'rogue', 'sorcerer', 'warlock', 'wizard',
];

const VALID_CHARACTER_BACKGROUNDS = [
    'acolyte', 'charlatan', 'criminal', 'entertainer', 'folk hero', 'guild artisan',
    'hermit', 'noble', 'outlander', 'sage', 'sailor', 'soldier', 'urchin',
];

const VALID_SKILLS = [
    'acrobatics', 'animal-handling', 'arcana', 'athletics', 'deception', 'history',
    'insight', 'intimidation', 'investigation', 'medicine', 'nature', 'perception',
    'performance', 'persuasion', 'religion', 'sleight-of-hand', 'stealth', 'survival',
];

const VALID_ABILITIES = ['str', 'dex', 'con', 'int', 'wis', 'cha'];

const CLASS_HIT_DICE = [
    'barbarian' => 12,
    'fighter' => 10,
    'paladin' => 10,
    'ranger' => 10,
    'bard' => 8,
    'cleric' => 8,
    'druid' => 8,
    'monk' => 8,
    'rogue' => 8,
    'warlock' => 8,
    'sorcerer' => 6,
    'wizard' => 6,
];

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/build$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may build this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['race'], $body['class'], $body['background'], $body['abilities'])
        || !is_string($body['race']) || !is_string($body['class']) || !is_string($body['background'])
        || !is_array($body['abilities'])) {
        bad_request();
    }

    $race = $body['race'];
    $class = $body['class'];
    $background = $body['background'];

    if (!in_array($race, VALID_CHARACTER_RACES, true)) {
        bad_request('invalid race');
    }
    if (!in_array($class, VALID_CHARACTER_CLASSES, true)) {
        bad_request('invalid class');
    }
    if (!in_array($background, VALID_CHARACTER_BACKGROUNDS, true)) {
        bad_request('invalid background');
    }

    $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
    $abilities = $body['abilities'];
    foreach ($abilityKeys as $key) {
        if (!isset($abilities[$key]) || !is_valid_int_range($abilities[$key], 1, 30)) {
            bad_request('invalid abilities');
        }
    }

    $level = 1;
    $conModifier = ability_modifier((int)$abilities['con']);
    $hitDie = CLASS_HIT_DICE[$class];
    $hpMax = $hitDie + $conModifier;
    $proficiencyBonus = proficiency_bonus($level);

    $member['race'] = $race;
    $member['class'] = $class;
    $member['background'] = $background;
    $member['abilities'] = [
        'str' => (int)$abilities['str'],
        'dex' => (int)$abilities['dex'],
        'con' => (int)$abilities['con'],
        'int' => (int)$abilities['int'],
        'wis' => (int)$abilities['wis'],
        'cha' => (int)$abilities['cha'],
    ];
    $member['level'] = $level;
    $member['hp_max'] = $hpMax;
    $member['hp_current'] = $hpMax;
    $member['proficiency_bonus'] = $proficiencyBonus;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'race' => $race,
        'class' => $class,
        'background' => $background,
        'level' => $level,
        'hp_max' => $hpMax,
        'proficiency_bonus' => $proficiencyBonus,
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/level-up$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may level up this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['level']) || !is_valid_int_range($body['level'], 1, 20)) {
        bad_request();
    }

    $newLevel = (int)$body['level'];
    $currentLevel = (int)($member['level'] ?? 1);
    if ($newLevel !== $currentLevel + 1) {
        bad_request('level must be exactly one higher than the current level');
    }

    $class = $member['class'] ?? null;
    if (!is_string($class) || !isset(CLASS_HIT_DICE[$class])) {
        bad_request('character has no class assigned');
    }

    $abilities = $member['abilities'] ?? [];
    $conModifier = ability_modifier((int)($abilities['con'] ?? 10));
    $hitDie = CLASS_HIT_DICE[$class];
    $hpGain = intdiv($hitDie, 2) + 1 + $conModifier;

    $hpMax = (int)($member['hp_max'] ?? ($hitDie + $conModifier));
    $hpCurrent = (int)($member['hp_current'] ?? $hpMax);

    $newHpMax = $hpMax + $hpGain;
    $newHpCurrent = min($newHpMax, $hpCurrent + $hpGain);

    $proficiencyBonus = proficiency_bonus($newLevel);

    $member['level'] = $newLevel;
    $member['hp_max'] = $newHpMax;
    $member['hp_current'] = $newHpCurrent;
    $member['proficiency_bonus'] = $proficiencyBonus;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'level' => $newLevel,
        'hp_max' => $newHpMax,
        'hit_dice' => sprintf('1d%d', $hitDie),
        'proficiency_bonus' => $proficiencyBonus,
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/skill-check$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may make this skill check");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['skill'], $body['ability'], $body['proficient'], $body['roll'])
        || !is_string($body['skill']) || !is_string($body['ability'])
        || !is_bool($body['proficient']) || !is_numeric($body['roll'])) {
        bad_request();
    }

    $skill = $body['skill'];
    $ability = $body['ability'];
    if (!in_array($skill, VALID_SKILLS, true)) {
        bad_request('unsupported skill');
    }
    if (!in_array($ability, VALID_ABILITIES, true)) {
        bad_request('unsupported ability');
    }

    $proficient = $body['proficient'];
    $roll = (int)$body['roll'];

    $abilities = $member['abilities'] ?? [];
    $score = (int)($abilities[$ability] ?? 10);
    $abilityModifier = ability_modifier($score);
    $level = (int)($member['level'] ?? 1);
    $proficiencyBonus = proficiency_bonus($level);

    $modifier = $abilityModifier + ($proficient ? $proficiencyBonus : 0);
    $total = $roll + $modifier;

    send_json([
        'character_id' => $charId,
        'skill' => $skill,
        'ability' => $ability,
        'modifier' => $modifier,
        'total' => $total,
    ], 200);
}

const SPELL_COMPENDIUM = [
    'fire-bolt' => ['name' => 'Fire Bolt', 'level' => 0, 'classes' => ['sorcerer', 'wizard']],
    'sacred-flame' => ['name' => 'Sacred Flame', 'level' => 0, 'classes' => ['cleric']],
    'eldritch-blast' => ['name' => 'Eldritch Blast', 'level' => 0, 'classes' => ['warlock']],
    'druidcraft' => ['name' => 'Druidcraft', 'level' => 0, 'classes' => ['druid']],
    'vicious-mockery' => ['name' => 'Vicious Mockery', 'level' => 0, 'classes' => ['bard']],
    'magic-missile' => ['name' => 'Magic Missile', 'level' => 1, 'classes' => ['sorcerer', 'wizard']],
    'shield' => ['name' => 'Shield', 'level' => 1, 'classes' => ['sorcerer', 'wizard']],
    'cure-wounds' => ['name' => 'Cure Wounds', 'level' => 1, 'classes' => ['bard', 'cleric', 'druid', 'paladin', 'ranger']],
    'bless' => ['name' => 'Bless', 'level' => 1, 'classes' => ['cleric', 'paladin']],
    'hunters-mark' => ['name' => "Hunter's Mark", 'level' => 1, 'classes' => ['ranger']],
];

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may add spells to this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['spell_id'], $body['name'], $body['level'])
        || !is_string($body['spell_id']) || !is_string($body['name'])
        || !is_valid_int_range($body['level'], 0, 9)) {
        bad_request();
    }
    $spellId = $body['spell_id'];
    $name = $body['name'];
    $level = (int)$body['level'];

    $class = $member['class'] ?? null;
    $spellEntry = SPELL_COMPENDIUM[$spellId] ?? null;
    if ($spellEntry === null || !is_string($class) || !in_array($class, $spellEntry['classes'], true)) {
        bad_request('invalid class/spell combination');
    }

    $spells = $member['spells'] ?? [];
    foreach ($spells as $s) {
        if ($s['spell_id'] === $spellId) {
            conflict('character already knows this spell');
        }
    }

    $spells[] = ['spell_id' => $spellId, 'name' => $name, 'level' => $level];
    $member['spells'] = $spells;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'spell_id' => $spellId,
        'name' => $name,
        'level' => $level,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this spellbook');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    $spells = array_map(function ($s) {
        return ['spell_id' => $s['spell_id'], 'name' => $s['name'], 'level' => $s['level']];
    }, $member['spells'] ?? []);

    send_json(['spells' => $spells], 200);
}

// Classes that prepare spells from a known list (as opposed to non-casters
// like rogue/fighter). Derived from the classes referenced in the spell
// compendium above.
const SPELLCASTING_CLASSES = ['sorcerer', 'wizard', 'cleric', 'warlock', 'druid', 'bard', 'paladin', 'ranger'];

// Maximum number of spells a spellcasting class can have prepared at a given
// character level; non-spellcasting classes may prepare none. At level 1 a
// wizard may prepare at most one spell.
function max_prepared_spells(?string $class, int $level): int {
    if (!is_string($class) || !in_array($class, SPELLCASTING_CLASSES, true)) {
        return 0;
    }
    return max(1, $level);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may prepare spells for this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['spell_ids']) || !is_array($body['spell_ids'])) {
        bad_request();
    }
    $spellIds = $body['spell_ids'];
    foreach ($spellIds as $sid) {
        if (!is_string($sid)) {
            bad_request();
        }
    }

    $class = $member['class'] ?? null;
    $level = (int)($member['level'] ?? 1);
    $maxPrepared = max_prepared_spells(is_string($class) ? $class : null, $level);

    if ($maxPrepared === 0) {
        bad_request('this class cannot prepare spells');
    }

    $knownSpellIds = array_map(function ($s) {
        return $s['spell_id'];
    }, $member['spells'] ?? []);

    foreach ($spellIds as $sid) {
        if (!isset(SPELL_COMPENDIUM[$sid])) {
            bad_request('unknown spell');
        }
        if (!in_array($sid, $knownSpellIds, true)) {
            bad_request('character does not know this spell');
        }
    }

    if (count($spellIds) > $maxPrepared) {
        bad_request('prepared spell list exceeds the maximum allowed');
    }

    $member['prepared_spells'] = array_values($spellIds);

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'prepared_spells' => array_values($spellIds),
        'max_prepared' => $maxPrepared,
    ], 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view prepared spells');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    $class = $member['class'] ?? null;
    $level = (int)($member['level'] ?? 1);
    $maxPrepared = max_prepared_spells(is_string($class) ? $class : null, $level);
    $prepared = $member['prepared_spells'] ?? [];

    send_json([
        'character_id' => $charId,
        'prepared_spells' => array_values($prepared),
        'max_prepared' => $maxPrepared,
    ], 200);
}

// Number of spell slots of a given spell level available to a spellcasting
// class at a given character level. Cantrips (level 0) draw on no slot and
// may always be cast. Non-casters, and spell levels above the character's
// current level, have no slots. At level 1 a wizard has exactly one
// first-level slot.
function spell_slots_for_level(string $class, int $charLevel, int $spellLevel): int {
    if (!in_array($class, SPELLCASTING_CLASSES, true)) {
        return 0;
    }
    if ($spellLevel === 0) {
        return PHP_INT_MAX;
    }
    if ($spellLevel > $charLevel) {
        return 0;
    }
    return 1;
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may cast spells with this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['spell_id'], $body['target'])
        || !is_string($body['spell_id']) || !is_string($body['target'])) {
        bad_request();
    }
    $spellId = $body['spell_id'];
    $target = $body['target'];

    $class = $member['class'] ?? null;
    if (!is_string($class) || !in_array($class, SPELLCASTING_CLASSES, true)) {
        bad_request('character is not a spellcaster');
    }

    $spellEntry = SPELL_COMPENDIUM[$spellId] ?? null;
    $prepared = $member['prepared_spells'] ?? [];
    if ($spellEntry === null || !in_array($spellId, $prepared, true)) {
        bad_request('spell is not currently prepared');
    }

    $spellLevel = (int)$spellEntry['level'];
    $charLevel = (int)($member['level'] ?? 1);
    $totalSlots = spell_slots_for_level($class, $charLevel, $spellLevel);

    $casts = $member['casts'] ?? [];
    $usedSlots = 0;
    foreach ($casts as $c) {
        if ((int)($c['slot_level'] ?? -1) === $spellLevel) {
            $usedSlots++;
        }
    }

    if ($usedSlots >= $totalSlots) {
        conflict('no remaining spell slots of this level');
    }

    $sequence = count($casts) + 1;
    $cast = [
        'character_id' => $charId,
        'spell_id' => $spellId,
        'target' => $target,
        'slot_level' => $spellLevel,
        'slots_remaining' => $totalSlots - $usedSlots - 1,
        'sequence' => $sequence,
    ];
    $casts[] = $cast;
    $member['casts'] = $casts;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json($cast, 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this cast history');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    send_json(['casts' => array_values($member['casts'] ?? [])], 200);
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may set concentration for this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['spell_id'], $body['target'], $body['duration_turns'])
        || !is_string($body['spell_id']) || !is_string($body['target']) || !is_int($body['duration_turns'])) {
        bad_request();
    }
    $spellId = $body['spell_id'];
    $target = $body['target'];
    $durationTurns = $body['duration_turns'];

    $class = $member['class'] ?? null;
    if (!is_string($class) || !in_array($class, SPELLCASTING_CLASSES, true)) {
        bad_request('character is not a spellcaster');
    }

    $knownSpellIds = array_map(function ($s) {
        return $s['spell_id'];
    }, $member['spells'] ?? []);
    if (!isset(SPELL_COMPENDIUM[$spellId]) || !in_array($spellId, $knownSpellIds, true)) {
        bad_request('unknown spell');
    }

    $prepared = $member['prepared_spells'] ?? [];
    if (!in_array($spellId, $prepared, true)) {
        bad_request('spell is not currently prepared');
    }

    if ($durationTurns < 1) {
        bad_request('duration_turns must be positive');
    }

    $concentration = [
        'spell_id' => $spellId,
        'target' => $target,
        'remaining_turns' => $durationTurns,
    ];
    $member['concentration'] = $concentration;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'concentration' => $concentration,
    ], 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view concentration');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    send_json([
        'character_id' => $charId,
        'concentration' => $member['concentration'] ?? null,
    ], 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration/advance-turn$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may advance concentration');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $concentration = $member['concentration'] ?? null;
    if ($concentration !== null) {
        $concentration['remaining_turns'] = (int)$concentration['remaining_turns'] - 1;
        if ($concentration['remaining_turns'] <= 0) {
            $concentration = null;
        }
        $member['concentration'] = $concentration;

        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);
    }

    send_json([
        'character_id' => $charId,
        'concentration' => $concentration,
    ], 200);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may clear concentration for this character");
    }

    $member['concentration'] = null;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'concentration' => null,
    ], 200);
}

const VALID_INVENTORY_ITEM_IDS = [
    'healing-potion', 'torch',
    'leather-armor', 'ring-of-protection', 'amulet-of-health',
];

const EQUIPMENT_SLOT_ITEMS = [
    'armor' => ['leather-armor'],
    'accessory' => ['ring-of-protection', 'amulet-of-health'],
];

const ATTUNABLE_ITEM_IDS = ['ring-of-protection', 'amulet-of-health'];

const MAX_ATTUNEMENTS = 1;

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may add items to this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['item_id'], $body['quantity'])
        || !is_string($body['item_id']) || !is_valid_int_range($body['quantity'], 1, PHP_INT_MAX)) {
        bad_request();
    }
    $itemId = $body['item_id'];
    $quantity = (int)$body['quantity'];

    if (!in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
        bad_request('invalid item id');
    }

    $items = $member['inventory_items'] ?? [];
    $totalQuantity = $quantity;
    if (isset($items[$itemId])) {
        $totalQuantity = (int)$items[$itemId] + $quantity;
    }
    $items[$itemId] = $totalQuantity;
    $member['inventory_items'] = $items;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'item_id' => $itemId,
        'quantity' => $quantity,
        'total_quantity' => $totalQuantity,
    ], 201);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this inventory');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    $items = $member['inventory_items'] ?? [];
    ksort($items);
    $itemList = [];
    foreach ($items as $itemId => $qty) {
        $itemList[] = ['item_id' => $itemId, 'quantity' => $qty];
    }

    send_json([
        'character_id' => $charId,
        'items' => $itemList,
    ], 200);
}

if ($method === 'DELETE' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $itemId = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may remove items from this character");
    }

    $body = read_json_body();
    if ($body === null || !isset($body['quantity']) || !is_valid_int_range($body['quantity'], 1, PHP_INT_MAX)) {
        bad_request();
    }
    $quantity = (int)$body['quantity'];

    if (!in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
        bad_request('invalid item id');
    }

    $items = $member['inventory_items'] ?? [];
    $held = (int)($items[$itemId] ?? 0);
    if ($quantity > $held) {
        conflict('cannot remove more than the held quantity');
    }

    $totalQuantity = $held - $quantity;
    if ($totalQuantity > 0) {
        $items[$itemId] = $totalQuantity;
    } else {
        unset($items[$itemId]);
    }
    $member['inventory_items'] = $items;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'item_id' => $itemId,
        'quantity' => $quantity,
        'total_quantity' => $totalQuantity,
    ], 200);
}

const CONSUMABLE_ITEM_IDS = ['healing-potion'];

const CONSUMABLE_EFFECTS = [
    'healing-potion' => ['type' => 'healing', 'hp_restored' => 5],
];

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)/consume$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $itemId = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may consume items for this character");
    }

    if (!in_array($itemId, VALID_INVENTORY_ITEM_IDS, true) || !in_array($itemId, CONSUMABLE_ITEM_IDS, true)) {
        bad_request('item is not consumable');
    }

    $items = $member['inventory_items'] ?? [];
    $held = (int)($items[$itemId] ?? 0);
    if ($held <= 0) {
        conflict('no held quantity of this item');
    }

    $totalQuantity = $held - 1;
    if ($totalQuantity > 0) {
        $items[$itemId] = $totalQuantity;
    } else {
        unset($items[$itemId]);
    }
    $member['inventory_items'] = $items;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'item_id' => $itemId,
        'quantity_consumed' => 1,
        'total_quantity' => $totalQuantity,
        'effect' => CONSUMABLE_EFFECTS[$itemId],
    ], 200);
}

// Returns the equipment response shape for a given slot, resolving equipped
// item id and attunement flag from the member's stored equipment state.
function build_equipment_response(string $charId, string $slot, array $member): array {
    $equipment = $member['equipment'] ?? [];
    $itemId = $equipment[$slot] ?? '';
    $attunedSlots = $member['attuned_slots'] ?? [];
    return [
        'character_id' => $charId,
        'slot' => $slot,
        'item_id' => $itemId,
        'attuned' => (bool)($attunedSlots[$slot] ?? false),
    ];
}

if ($method === 'PUT' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $slot = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may equip items for this character");
    }

    if (!array_key_exists($slot, EQUIPMENT_SLOT_ITEMS)) {
        bad_request('invalid slot');
    }

    $body = read_json_body();
    if ($body === null || !isset($body['item_id']) || !is_string($body['item_id'])) {
        bad_request();
    }
    $itemId = $body['item_id'];

    if (!in_array($itemId, VALID_INVENTORY_ITEM_IDS, true)) {
        bad_request('invalid item id');
    }

    $items = $member['inventory_items'] ?? [];
    if ((int)($items[$itemId] ?? 0) <= 0) {
        bad_request('item is not held in inventory');
    }

    if (!in_array($itemId, EQUIPMENT_SLOT_ITEMS[$slot], true)) {
        bad_request('item does not match this slot');
    }

    $equipment = $member['equipment'] ?? [];
    $equipment[$slot] = $itemId;
    $member['equipment'] = $equipment;

    $attunedSlots = $member['attuned_slots'] ?? [];
    unset($attunedSlots[$slot]);
    $member['attuned_slots'] = $attunedSlots;

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json(build_equipment_response($charId, $slot, $member), 200);
}

if ($method === 'GET' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $slot = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    if ($actor['username'] !== $campaign['owner']) {
        $stmt = $db->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $actor['username']]);
        if ($stmt->fetch(PDO::FETCH_ASSOC) === false) {
            forbidden('only the owner or a party member may view this equipment');
        }
    }

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [, $member] = $found;

    if (!array_key_exists($slot, EQUIPMENT_SLOT_ITEMS)) {
        bad_request('invalid slot');
    }

    send_json(build_equipment_response($charId, $slot, $member), 200);
}

if ($method === 'POST' && preg_match('#^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune$#', $path, $pm)) {
    $campaignId = $pm[1];
    $charId = $pm[2];
    $slot = $pm[3];
    $actor = require_actor($db);

    $campaign = require_play_campaign($db, $campaignId);

    $found = find_play_character($db, $campaignId, $charId);
    if ($found === null) {
        not_found('character not found');
    }
    [$creatorUsername, $member] = $found;

    $owner = play_character_owner($db, $campaignId, $charId, $creatorUsername);
    if ($actor['username'] !== $owner) {
        forbidden("only the character's owner may attune items for this character");
    }

    if (!array_key_exists($slot, EQUIPMENT_SLOT_ITEMS)) {
        bad_request('invalid slot');
    }

    $equipment = $member['equipment'] ?? [];
    $itemId = $equipment[$slot] ?? '';
    if ($itemId === '' || !in_array($itemId, ATTUNABLE_ITEM_IDS, true)) {
        bad_request('slot does not contain an attunable item');
    }

    $attunedSlots = $member['attuned_slots'] ?? [];
    $attunementCount = count(array_filter($attunedSlots));

    if ($attunementCount >= MAX_ATTUNEMENTS) {
        conflict('maximum attunements reached');
    }

    $attunedSlots[$slot] = true;
    $member['attuned_slots'] = $attunedSlots;
    $attunementCount = count(array_filter($attunedSlots));

    $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
    $stmt->execute([json_encode($member), $campaignId, $creatorUsername]);

    send_json([
        'character_id' => $charId,
        'slot' => $slot,
        'item_id' => $itemId,
        'attuned' => true,
        'attunement_count' => $attunementCount,
        'max_attunements' => MAX_ATTUNEMENTS,
    ], 200);
}

// Builds the deterministic initiative order for an encounter's combatants and
// monsters combined: highest initiative first, ties broken by name so the
// order is stable regardless of insertion order.
function build_encounter_turn_order(array $encounter): array {
    $order = [];
    foreach ($encounter['combatants'] ?? [] as $c) {
        $order[] = [
            'name' => $c['name'],
            'kind' => 'player',
            'initiative' => $c['initiative'],
            'member' => $c['member'],
            'target' => $c['member'],
        ];
    }
    foreach ($encounter['monsters'] ?? [] as $monsterId => $m) {
        $order[] = [
            'name' => $m['name'],
            'kind' => 'monster',
            'initiative' => $m['initiative'],
            'target' => $monsterId,
        ];
    }
    usort($order, function ($a, $b) {
        if ($a['initiative'] !== $b['initiative']) {
            return $b['initiative'] <=> $a['initiative'];
        }
        return $a['name'] <=> $b['name'];
    });

    $override = $encounter['turn_order'] ?? null;
    if (is_array($override) && count($override) > 0) {
        $byTarget = [];
        foreach ($order as $entry) {
            $byTarget[$entry['target']] = $entry;
        }
        $reordered = [];
        foreach ($override as $target) {
            if (isset($byTarget[$target])) {
                $reordered[] = $byTarget[$target];
                unset($byTarget[$target]);
            }
        }
        foreach ($order as $entry) {
            if (isset($byTarget[$entry['target']])) {
                $reordered[] = $entry;
            }
        }
        $order = $reordered;
    }

    return $order;
}

function turn_order_public(array $entry): array {
    return ['name' => $entry['name'], 'kind' => $entry['kind'], 'initiative' => $entry['initiative']];
}

function encounter_target_exists(array $encounter, string $target): bool {
    return isset($encounter['monsters'][$target]) || isset($encounter['combatants'][$target]);
}

// Decrements remaining_rounds for every condition on $target by one and
// drops any that reach zero. Returns the updated $encounter.
function decrement_encounter_conditions(array $encounter, string $target): array {
    if (!isset($encounter['conditions'][$target])) {
        return $encounter;
    }
    $remaining = [];
    foreach ($encounter['conditions'][$target] as $c) {
        $c['remaining_rounds'] -= 1;
        if ($c['remaining_rounds'] > 0) {
            $remaining[] = $c;
        }
    }
    $encounter['conditions'][$target] = $remaining;
    return $encounter;
}

function encounter_conditions_public(array $encounter, string $target): array {
    return array_map(function ($c) {
        return ['condition' => $c['condition'], 'remaining_rounds' => $c['remaining_rounds']];
    }, $encounter['conditions'][$target] ?? []);
}

function encounter_conditions_map(array $encounter): array {
    $map = [];
    foreach ($encounter['conditions'] ?? [] as $target => $conds) {
        $map[$target] = array_map(function ($c) {
            return ['condition' => $c['condition'], 'remaining_rounds' => $c['remaining_rounds']];
        }, $conds);
    }
    return $map;
}

// Applies a signed HP delta to an encounter target, which may be a monster
// (state lives on the encounter) or a bound party member (state lives on the
// play_campaign_members row). HP is clamped to [0, hp_max]. Returns
// [$encounter, $hpBefore, $hpAfter] or null if the target isn't found.
function apply_encounter_hp_change(PDO $db, string $campaignId, array $encounter, string $target, int $delta): ?array {
    $monsters = $encounter['monsters'] ?? [];
    if (isset($monsters[$target])) {
        $monster = $monsters[$target];
        $hpMax = (int)$monster['hp_max'];
        $hpBefore = (int)($monster['hp_current'] ?? $hpMax);
        $hpAfter = max(0, min($hpMax, $hpBefore + $delta));
        $monster['hp_current'] = $hpAfter;
        $monsters[$target] = $monster;
        $encounter['monsters'] = $monsters;
        return [$encounter, $hpBefore, $hpAfter];
    }

    $combatants = $encounter['combatants'] ?? [];
    if (isset($combatants[$target])) {
        $stmt = $db->prepare('SELECT data FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
        $stmt->execute([$campaignId, $target]);
        $row = $stmt->fetch(PDO::FETCH_ASSOC);
        $member = $row !== false ? json_decode($row['data'], true) : [];
        $hpMax = (int)($member['hp_max'] ?? 20);
        $hpBefore = (int)($member['hp_current'] ?? $hpMax);
        $hpAfter = max(0, min($hpMax, $hpBefore + $delta));
        $member['hp_max'] = $hpMax;
        $member['hp_current'] = $hpAfter;
        $stmt = $db->prepare('UPDATE play_campaign_members SET data = ? WHERE campaign_id = ? AND username = ?');
        $stmt->execute([json_encode($member), $campaignId, $target]);
        return [$encounter, $hpBefore, $hpAfter];
    }

    return null;
}


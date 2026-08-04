<?php
declare(strict_types=1);

// Core rules helpers (ability scores, dice, encounter difficulty).
// ---------------------------------------------------------------------------

function ability_modifier(int $score): int {
    return (int)floor(($score - 10) / 2);
}

function proficiency_bonus(int $level): int {
    if ($level <= 4) {
        return 2;
    }
    if ($level <= 8) {
        return 3;
    }
    if ($level <= 12) {
        return 4;
    }
    if ($level <= 16) {
        return 5;
    }
    return 6;
}

// XP-by-challenge-rating table used by both the standalone XP calculator and
// the DM encounter builder. Only the CRs below are supported by design.
const CR_XP = [
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800,
];

// Party-level -> difficulty-threshold table (DMG-style). Only level 3 is
// populated; other levels intentionally fail validation as "unsupported".
const LEVEL_THRESHOLDS = [
    3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
];

const LOOT_TIERS = [
    1 => ['coins_gp' => 75, 'items' => [['slug' => 'healing-potion', 'quantity' => 2]]],
];

const SPELL_SLOT_TABLES = [
    'wizard' => [
        5 => ['1' => 4, '2' => 3, '3' => 2],
    ],
];

// DMG encounter-multiplier table: how much a monster group's base XP is
// scaled based on how many monsters are in it.
function encounter_multiplier(int $monsterCount) {
    if ($monsterCount === 1) {
        return 1;
    }
    if ($monsterCount === 2) {
        return 1.5;
    }
    if ($monsterCount >= 3 && $monsterCount <= 6) {
        return 2;
    }
    if ($monsterCount >= 7 && $monsterCount <= 10) {
        return 2.5;
    }
    if ($monsterCount >= 11 && $monsterCount <= 14) {
        return 3;
    }
    return 4;
}

// Sums each party member's per-level thresholds from LEVEL_THRESHOLDS.
// Exits with 400 if a member is malformed or its level has no table entry.
function compute_party_thresholds(array $party): array {
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || !isset($member['level'])) {
            bad_request('invalid party member');
        }
        $level = (int)$member['level'];
        if (!isset(LEVEL_THRESHOLDS[$level])) {
            bad_request('unsupported level');
        }
        foreach (LEVEL_THRESHOLDS[$level] as $key => $value) {
            $thresholds[$key] += $value;
        }
    }
    return $thresholds;
}

function determine_difficulty(float $adjustedXp, array $thresholds): string {
    if ($adjustedXp >= $thresholds['deadly']) {
        return 'deadly';
    }
    if ($adjustedXp >= $thresholds['hard']) {
        return 'hard';
    }
    if ($adjustedXp >= $thresholds['medium']) {
        return 'medium';
    }
    if ($adjustedXp >= $thresholds['easy']) {
        return 'easy';
    }
    return 'trivial';
}

// ---------------------------------------------------------------------------
// Combat/initiative helpers.
// ---------------------------------------------------------------------------

// Validates a raw combatant list (name/dex/roll), computes each combatant's
// initiative score (dex + roll), and returns them sorted highest-first, with
// ties broken by dex then name. Shared by /v1/initiative/order and
// /v1/combat/sessions creation, which use identical ordering rules.
function parse_and_sort_combatants(array $rawCombatants): array {
    $combatants = [];
    foreach ($rawCombatants as $c) {
        if (!is_array($c) || !isset($c['name'], $c['dex'], $c['roll'])
            || !is_string($c['name']) || !is_numeric($c['dex']) || !is_numeric($c['roll'])) {
            bad_request('invalid combatant');
        }
        $dex = $c['dex'] + 0;
        $roll = $c['roll'] + 0;
        $combatants[] = [
            'name' => $c['name'],
            'dex' => $dex,
            'score' => $roll + $dex,
        ];
    }

    usort($combatants, function ($a, $b) {
        if ($a['score'] !== $b['score']) {
            return $b['score'] <=> $a['score'];
        }
        if ($a['dex'] !== $b['dex']) {
            return $b['dex'] <=> $a['dex'];
        }
        return $a['name'] <=> $b['name'];
    });

    return array_map(function ($c) {
        return ['name' => $c['name'], 'score' => $c['score']];
    }, $combatants);
}

function load_combat_sessions(PDO $db): array {
    $sessions = [];
    foreach ($db->query('SELECT id, data FROM combat_sessions') as $row) {
        $sessions[$row['id']] = json_decode($row['data'], true);
    }
    return $sessions;
}

function save_combat_session(PDO $db, string $id, array $session): void {
    $stmt = $db->prepare('INSERT OR REPLACE INTO combat_sessions (id, data) VALUES (?, ?)');
    $stmt->execute([$id, json_encode($session)]);
}

function build_active(array $session): array {
    $order = $session['order'];
    $active = $order[$session['turn_index']];
    return ['name' => $active['name'], 'score' => $active['score']];
}

function conditions_public(array $session): array {
    $result = [];
    foreach ($session['conditions'] as $name => $conds) {
        $result[$name] = array_map(function ($c) {
            return ['condition' => $c['condition'], 'remaining_rounds' => $c['remaining_rounds']];
        }, $conds);
    }
    return $result;
}

// ---------------------------------------------------------------------------

<?php

// D&D REST Engine — PHP built-in server router (no Composer packages).

function send(mixed $data, int $status = 200): never
{
    http_response_code($status);
    header('Content-Type: application/json');
    echo json_encode($data);
    exit;
}

function body(): array
{
    $raw = file_get_contents('php://input');
    if ($raw === false || $raw === '') {
        return [];
    }
    $data = json_decode($raw, true);
    return is_array($data) ? $data : [];
}

function encounter_multiplier(int $count): int|float
{
    if ($count <= 1) return 1;
    if ($count === 2) return 1.5;
    if ($count <= 6) return 2;
    if ($count <= 10) return 2.5;
    if ($count <= 14) return 3;
    return 4;
}

// D&D ability modifier: floor((score - 10) / 2). Floors negative halves.
function ability_modifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

// D&D proficiency bonus by character level (1-20).
function proficiency_bonus(int $level): int
{
    return match (true) {
        $level >= 17 => 6,
        $level >= 13 => 5,
        $level >= 9 => 4,
        $level >= 5 => 3,
        default => 2,
    };
}

// ---- Combat session state ----
// The PHP built-in server re-executes the router script for every request, so
// all PHP-level state (statics/globals) resets each time. We persist combat
// sessions to a JSON file in the script directory. run.sh wipes it on start so
// each server process begins with clean state.
function state_file(): string
{
    return __DIR__ . '/.combat-sessions.json';
}

function load_sessions(): array
{
    $f = state_file();
    if (!file_exists($f)) {
        return [];
    }
    $data = json_decode(file_get_contents($f), true);
    return is_array($data) ? $data : [];
}

function save_sessions(array $sessions): void
{
    file_put_contents(state_file(), json_encode($sessions));
}

$method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);

// GET /health
if ($method === 'GET' && $path === '/health') {
    send(['ok' => true]);
}

if ($method === 'POST') {
    $b = body();

    switch ($path) {
        // POST /v1/dice/stats
        case '/v1/dice/stats':
            $expr = $b['expression'] ?? '';
            if (!is_string($expr) || !preg_match('/^(\d+)d(\d+)(?:([+-])(\d+))?$/', $expr, $m)) {
                send(['error' => 'invalid expression'], 400);
            }
            $count = (int) $m[1];
            $sides = (int) $m[2];
            if ($count < 1 || $sides < 1) {
                send(['error' => 'invalid expression'], 400);
            }
            $modifier = 0;
            if (isset($m[3]) && $m[3] !== '') {
                $modifier = (int) $m[4];
                if ($m[3] === '-') {
                    $modifier = -$modifier;
                }
            }
            $min = $count + $modifier;
            $max = $count * $sides + $modifier;
            send([
                'dice_count' => $count,
                'sides' => $sides,
                'modifier' => $modifier,
                'min' => $min,
                'max' => $max,
                'average' => ($min + $max) / 2,
            ]);

        // POST /v1/checks/ability
        case '/v1/checks/ability':
            $roll = (int) ($b['roll'] ?? 0);
            $modifier = (int) ($b['modifier'] ?? 0);
            $dc = (int) ($b['dc'] ?? 0);
            $total = $roll + $modifier;
            send([
                'total' => $total,
                'success' => $total >= $dc,
                'margin' => $total - $dc,
            ]);

        // POST /v1/encounters/adjusted-xp
        case '/v1/encounters/adjusted-xp':
            $xpTable = [
                '0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100,
                '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800,
            ];
            $levelThresholds = [
                3 => ['easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400],
            ];
            $baseXp = 0;
            $monsterCount = 0;
            foreach (($b['monsters'] ?? []) as $monster) {
                $cr = (string) ($monster['cr'] ?? '');
                $count = (int) ($monster['count'] ?? 0);
                if (!array_key_exists($cr, $xpTable)) {
                    send(['error' => 'unknown challenge rating'], 400);
                }
                $baseXp += $xpTable[$cr] * $count;
                $monsterCount += $count;
            }
            $multiplier = encounter_multiplier($monsterCount);
            $adjustedXp = $baseXp * $multiplier;
            $easy = $medium = $hard = $deadly = 0;
            foreach (($b['party'] ?? []) as $member) {
                $level = (int) ($member['level'] ?? 3);
                $t = $levelThresholds[$level] ?? $levelThresholds[3];
                $easy += $t['easy'];
                $medium += $t['medium'];
                $hard += $t['hard'];
                $deadly += $t['deadly'];
            }
            $difficulty = 'trivial';
            if ($adjustedXp >= $deadly) {
                $difficulty = 'deadly';
            } elseif ($adjustedXp >= $hard) {
                $difficulty = 'hard';
            } elseif ($adjustedXp >= $medium) {
                $difficulty = 'medium';
            } elseif ($adjustedXp >= $easy) {
                $difficulty = 'easy';
            }
            send([
                'base_xp' => $baseXp,
                'monster_count' => $monsterCount,
                'multiplier' => $multiplier,
                'adjusted_xp' => $adjustedXp,
                'difficulty' => $difficulty,
                'thresholds' => [
                    'easy' => $easy,
                    'medium' => $medium,
                    'hard' => $hard,
                    'deadly' => $deadly,
                ],
            ]);

        // POST /v1/initiative/order
        case '/v1/initiative/order':
            $items = [];
            foreach (($b['combatants'] ?? []) as $c) {
                $dex = (int) ($c['dex'] ?? 0);
                $roll = (int) ($c['roll'] ?? 0);
                $items[] = [
                    'name' => (string) ($c['name'] ?? ''),
                    'dex' => $dex,
                    'score' => $roll + $dex,
                ];
            }
            usort($items, function ($x, $y) {
                if ($x['score'] !== $y['score']) {
                    return $y['score'] <=> $x['score']; // score desc
                }
                if ($x['dex'] !== $y['dex']) {
                    return $y['dex'] <=> $x['dex']; // dex desc
                }
                return $x['name'] <=> $y['name']; // name asc
            });
            send([
                'order' => array_map(
                    fn($c) => ['name' => $c['name'], 'score' => $c['score']],
                    $items
                ),
            ]);

        // POST /v1/characters/ability-modifier
        case '/v1/characters/ability-modifier':
            $score = $b['score'] ?? null;
            if (!is_int($score) || $score < 1 || $score > 30) {
                send(['error' => 'invalid score'], 400);
            }
            send([
                'score' => $score,
                'modifier' => ability_modifier($score),
            ]);

        // POST /v1/characters/proficiency
        case '/v1/characters/proficiency':
            $level = $b['level'] ?? null;
            if (!is_int($level) || $level < 1 || $level > 20) {
                send(['error' => 'invalid level'], 400);
            }
            send([
                'level' => $level,
                'proficiency_bonus' => proficiency_bonus($level),
            ]);

        // POST /v1/characters/derived-stats
        case '/v1/characters/derived-stats':
            $level = $b['level'] ?? null;
            if (!is_int($level) || $level < 1 || $level > 20) {
                send(['error' => 'invalid level'], 400);
            }
            $abilities = $b['abilities'] ?? null;
            $abilityKeys = ['str', 'dex', 'con', 'int', 'wis', 'cha'];
            if (!is_array($abilities)) {
                send(['error' => 'invalid abilities'], 400);
            }
            $modifiers = [];
            foreach ($abilityKeys as $k) {
                $v = $abilities[$k] ?? null;
                if (!is_int($v) || $v < 1 || $v > 30) {
                    send(['error' => "invalid ability: $k"], 400);
                }
                $modifiers[$k] = ability_modifier($v);
            }
            $armor = $b['armor'] ?? null;
            if (!is_array($armor)) {
                send(['error' => 'invalid armor'], 400);
            }
            $base = $armor['base'] ?? null;
            $dexCap = $armor['dex_cap'] ?? null;
            if (!is_int($base) || !is_int($dexCap)) {
                send(['error' => 'invalid armor fields'], 400);
            }
            $shieldBonus = ($armor['shield'] ?? false) === true ? 2 : 0;
            $hpMax = $level * (6 + $modifiers['con']);
            $armorClass = $base + min($modifiers['dex'], $dexCap) + $shieldBonus;
            send([
                'level' => $level,
                'proficiency_bonus' => proficiency_bonus($level),
                'hp_max' => $hpMax,
                'armor_class' => $armorClass,
                'modifiers' => $modifiers,
            ]);
    }

    // ---- Combat: stateful sessions ----

    // POST /v1/combat/sessions  — create combat session
    if ($path === '/v1/combat/sessions') {
        $id = $b['id'] ?? null;
        if (!is_string($id) || $id === '') {
            send(['error' => 'invalid id'], 400);
        }
        $combatants = $b['combatants'] ?? null;
        if (!is_array($combatants) || count($combatants) === 0) {
            send(['error' => 'invalid combatants'], 400);
        }
        $items = [];
        foreach ($combatants as $c) {
            if (!is_array($c)) {
                send(['error' => 'invalid combatant'], 400);
            }
            $name = $c['name'] ?? null;
            if (!is_string($name) || $name === '') {
                send(['error' => 'invalid combatant name'], 400);
            }
            $dex = (int) ($c['dex'] ?? 0);
            $roll = (int) ($c['roll'] ?? 0);
            $items[] = [
                'name' => $name,
                'dex' => $dex,
                'score' => $roll + $dex,
            ];
        }
        usort($items, function ($x, $y) {
            if ($x['score'] !== $y['score']) {
                return $y['score'] <=> $x['score']; // score desc
            }
            if ($x['dex'] !== $y['dex']) {
                return $y['dex'] <=> $x['dex']; // dex desc
            }
            return $x['name'] <=> $y['name']; // name asc
        });
        $order = array_map(
            fn($c) => ['name' => $c['name'], 'score' => $c['score']],
            $items
        );
        $sessions = load_sessions();
        $sessions[$id] = [
            'round' => 1,
            'turn_index' => 0,
            'order' => $order,
            'conditions' => [],
        ];
        save_sessions($sessions);
        send([
            'id' => $id,
            'round' => 1,
            'turn_index' => 0,
            'active' => $order[0],
            'order' => $order,
        ]);
    }

    // POST /v1/combat/sessions/{id}/conditions  — add condition to a combatant
    if (preg_match('#^/v1/combat/sessions/([^/]+)/conditions$#', $path, $m)) {
        $sid = urldecode($m[1]);
        $sessions = load_sessions();
        if (!isset($sessions[$sid])) {
            send(['error' => 'session not found'], 404);
        }
        $sess = $sessions[$sid];
        $target = $b['target'] ?? null;
        if (!is_string($target)) {
            send(['error' => 'invalid target'], 400);
        }
        $found = false;
        foreach ($sess['order'] as $c) {
            if ($c['name'] === $target) {
                $found = true;
                break;
            }
        }
        if (!$found) {
            send(['error' => 'unknown target'], 400);
        }
        $condition = $b['condition'] ?? null;
        if (!is_string($condition)) {
            send(['error' => 'invalid condition'], 400);
        }
        $duration = $b['duration_rounds'] ?? null;
        if (!is_int($duration) || $duration <= 0) {
            send(['error' => 'invalid duration_rounds'], 400);
        }
        if (!isset($sess['conditions'][$target]) || !is_array($sess['conditions'][$target])) {
            $sess['conditions'][$target] = [];
        }
        $sess['conditions'][$target][] = [
            'condition' => $condition,
            'remaining_rounds' => $duration,
        ];
        $sessions[$sid] = $sess;
        save_sessions($sessions);
        send([
            'target' => $target,
            'conditions' => array_values($sess['conditions'][$target]),
        ]);
    }

    // POST /v1/combat/sessions/{id}/advance  — advance to next turn
    if (preg_match('#^/v1/combat/sessions/([^/]+)/advance$#', $path, $m)) {
        $sid = urldecode($m[1]);
        $sessions = load_sessions();
        if (!isset($sessions[$sid])) {
            send(['error' => 'session not found'], 404);
        }
        $sess = $sessions[$sid];
        $order = $sess['order'];
        $count = count($order);
        $ti = $sess['turn_index'] + 1;
        $round = $sess['round'];
        if ($ti >= $count) {
            $ti = 0;
            $round += 1;
        }
        $active = $order[$ti];
        $activeName = $active['name'];
        // At the start of the new active combatant's turn, decrement each of
        // their conditions; remove any whose duration reaches 0.
        if (isset($sess['conditions'][$activeName]) && is_array($sess['conditions'][$activeName])) {
            foreach ($sess['conditions'][$activeName] as $idx => $cond) {
                $sess['conditions'][$activeName][$idx]['remaining_rounds'] = $cond['remaining_rounds'] - 1;
            }
            $sess['conditions'][$activeName] = array_values(array_filter(
                $sess['conditions'][$activeName],
                fn($c) => $c['remaining_rounds'] > 0
            ));
            // Keep the combatant's key as an empty array when their last
            // condition expires, so callers can see the target still exists
            // but has no active conditions.
        }
        $sess['turn_index'] = $ti;
        $sess['round'] = $round;
        $sessions[$sid] = $sess;
        save_sessions($sessions);
        // Include every combatant that has (or had) conditions, even those
        // whose conditions have all expired — they appear with an empty list.
        $condsOut = [];
        foreach ($sess['conditions'] as $cname => $clist) {
            $condsOut[$cname] = is_array($clist) ? array_values($clist) : [];
        }
        send([
            'id' => $sid,
            'round' => $round,
            'turn_index' => $ti,
            'active' => $active,
            'conditions' => (object) $condsOut,
        ]);
    }
}

send(['error' => 'not found'], 404);

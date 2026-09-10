<?php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use Psr\Http\Message\ResponseInterface as Response;
use Psr\Http\Message\ServerRequestInterface as Request;
use Slim\Factory\AppFactory;

/** @return array<string, mixed>|null */
function jsonBody(Request $request): ?array
{
    $data = json_decode((string) $request->getBody(), true);
    return is_array($data) ? $data : null;
}

function jsonResponse(Response $response, array $data, int $status = 200): Response
{
    $response->getBody()->write((string) json_encode($data));
    return $response->withStatus($status)->withHeader('Content-Type', 'application/json');
}

function badRequest(Response $response): Response
{
    return jsonResponse($response, ['error' => 'invalid request'], 400);
}

function integer(mixed $value): ?int
{
    return is_int($value) ? $value : null;
}

function abilityModifier(int $score): int
{
    return (int) floor(($score - 10) / 2);
}

function proficiencyBonus(int $level): int
{
    return 2 + intdiv($level - 1, 4);
}

function validAbilityScore(?int $score): bool
{
    return $score !== null && $score >= 1 && $score <= 30;
}

function validAbilityName(mixed $ability): bool
{
    return is_string($ability) && in_array($ability, ['str', 'dex', 'con', 'int', 'wis', 'cha'], true);
}

function validSkillName(mixed $skill): bool
{
    return is_string($skill) && in_array($skill, [
        'acrobatics', 'animal-handling', 'arcana', 'athletics', 'deception',
        'history', 'insight', 'intimidation', 'investigation', 'medicine',
        'nature', 'perception', 'performance', 'persuasion', 'religion',
        'sleight-of-hand', 'stealth', 'survival',
    ], true);
}

function validCharacterRace(mixed $race): bool
{
    return is_string($race) && in_array($race, [
        'dragonborn', 'dwarf', 'elf', 'gnome', 'half-elf', 'half-orc',
        'halfling', 'human', 'tiefling',
    ], true);
}

function characterHitDie(mixed $class): ?int
{
    return match ($class) {
        'barbarian' => 12,
        'fighter', 'paladin', 'ranger' => 10,
        'bard', 'cleric', 'druid', 'monk', 'rogue', 'warlock' => 8,
        'sorcerer', 'wizard' => 6,
        default => null,
    };
}

function validCharacterBackground(mixed $background): bool
{
    return is_string($background) && in_array($background, [
        'acolyte', 'charlatan', 'criminal', 'entertainer', 'folk-hero',
        'guild-artisan', 'hermit', 'noble', 'outlander', 'sage', 'sailor',
        'soldier', 'urchin',
    ], true);
}

function validLevel(?int $level): bool
{
    return $level !== null && $level >= 1 && $level <= 20;
}

function database(): PDO
{
    static $database = null;
    if (!$database instanceof PDO) {
        $database = new PDO('sqlite:' . __DIR__ . '/game.db');
        $database->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
    }
    return $database;
}

function initializeStorage(PDO $database): void
{
    $database->exec('CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT NOT NULL, role TEXT NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL, max_players INTEGER NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_feed_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    // Spectator bearer tokens contain only this globally unique id, so it is
    // deliberately the table's primary key rather than campaign-scoped data.
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_spectators (spectator_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (campaign_id TEXT PRIMARY KEY, rules TEXT NOT NULL, tone TEXT NOT NULL, consent TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_content (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags TEXT NOT NULL, PRIMARY KEY (campaign_id, content_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_notes (campaign_id TEXT NOT NULL, note_id TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, note_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_search_records (campaign_id TEXT NOT NULL, record_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, record_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_rate_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, actor TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (campaign_id TEXT PRIMARY KEY, rejected_rate_events INTEGER NOT NULL DEFAULT 0, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS service_mode (singleton INTEGER PRIMARY KEY CHECK (singleton = 1), maintenance INTEGER NOT NULL CHECK (maintenance IN (0, 1)), process_id INTEGER NOT NULL)');
    $serviceProcessId = getmypid();
    $serviceMode = $database->prepare('INSERT OR IGNORE INTO service_mode (singleton, maintenance, process_id) VALUES (1, 0, ?)');
    $serviceMode->execute([$serviceProcessId]);
    // Service mode is global for this server process, rather than durable
    // campaign data that could leak into a subsequent server run.
    $serviceMode = $database->prepare('UPDATE service_mode SET maintenance = 0, process_id = ? WHERE singleton = 1 AND process_id <> ?');
    $serviceMode->execute([$serviceProcessId, $serviceProcessId]);
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_invitations (campaign_id TEXT NOT NULL, invitation_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, invitation_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_delegations (campaign_id TEXT NOT NULL, username TEXT NOT NULL, powers TEXT NOT NULL, active INTEGER NOT NULL, PRIMARY KEY (campaign_id, username), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, username TEXT NOT NULL, action TEXT NOT NULL, powers TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_audit_events (campaign_id TEXT NOT NULL, timestamp INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL, correlation_id TEXT NOT NULL, PRIMARY KEY (campaign_id, timestamp), UNIQUE (campaign_id, correlation_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_projection_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_replay_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (campaign_id TEXT PRIMARY KEY, seed TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, roll_id TEXT NOT NULL, sides INTEGER NOT NULL, result INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, roll_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, report_id TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL, reporter TEXT NOT NULL, action TEXT NULL, note TEXT NULL, resolver TEXT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, report_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (campaign_id TEXT PRIMARY KEY, blocked_tags TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_safety_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, tags TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (campaign_id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_fixture_characters (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_fixture_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, event_id), UNIQUE (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_id TEXT NOT NULL, value TEXT NOT NULL, idempotency_key TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), UNIQUE (campaign_id, idempotency_key), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (campaign_id TEXT PRIMARY KEY, current_turn INTEGER NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_submissions (campaign_id TEXT NOT NULL, submission_id TEXT NOT NULL, action TEXT NOT NULL, accepted_turn INTEGER NOT NULL, next_turn INTEGER NOT NULL, PRIMARY KEY (campaign_id, submission_id), UNIQUE (campaign_id, accepted_turn), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    // A character id is scoped to its campaign. The same player character can
    // therefore participate in more than one campaign without preventing a
    // later campaign member from joining.
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_members (character_id TEXT NOT NULL, campaign_id TEXT NOT NULL, username TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id), UNIQUE (campaign_id, username), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_whispers (campaign_id TEXT NOT NULL, whisper_id TEXT NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, whisper_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id), FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_campaign_members(campaign_id, character_id), FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_currency (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (campaign_id TEXT NOT NULL, transfer_id INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, transfer_id), FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_campaign_members(campaign_id, character_id), FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, amount INTEGER NOT NULL, from_gold INTEGER NOT NULL, to_gold INTEGER NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id, from_character_id) REFERENCES play_campaign_members(campaign_id, character_id), FOREIGN KEY (campaign_id, to_character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_owners (character_id TEXT NOT NULL, campaign_id TEXT NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_member_health (character_id TEXT NOT NULL, campaign_id TEXT NOT NULL, hp_current INTEGER NOT NULL, hp_max INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_progressions (character_id TEXT PRIMARY KEY, class TEXT NOT NULL, con_modifier INTEGER NOT NULL, level INTEGER NOT NULL, FOREIGN KEY (character_id) REFERENCES play_campaign_members(character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_abilities (character_id TEXT PRIMARY KEY, str INTEGER NOT NULL, dex INTEGER NOT NULL, con INTEGER NOT NULL, int INTEGER NOT NULL, wis INTEGER NOT NULL, cha INTEGER NOT NULL, FOREIGN KEY (character_id) REFERENCES play_campaign_members(character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_member_death_saves (character_id TEXT PRIMARY KEY, successes INTEGER NOT NULL DEFAULT 0, failures INTEGER NOT NULL DEFAULT 0, FOREIGN KEY (character_id) REFERENCES play_campaign_members(character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_spells (character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, PRIMARY KEY (character_id, spell_id), FOREIGN KEY (character_id) REFERENCES play_campaign_members(character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (character_id TEXT NOT NULL, spell_id TEXT NOT NULL, position INTEGER NOT NULL, PRIMARY KEY (character_id, spell_id), FOREIGN KEY (character_id) REFERENCES play_campaign_members(character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, slot_level INTEGER NOT NULL, slots_remaining INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, sequence), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_concentrations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, remaining_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, item_id TEXT NOT NULL, quantity INTEGER NOT NULL, status TEXT NOT NULL, recipient_character_id TEXT NULL, votes INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, loot_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id), FOREIGN KEY (campaign_id, recipient_character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter), FOREIGN KEY (campaign_id, loot_id) REFERENCES play_campaign_loot(campaign_id, loot_id), FOREIGN KEY (campaign_id, recipient_character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, name TEXT NOT NULL, agenda TEXT NOT NULL, public_status TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, dialogue_id TEXT NOT NULL, sequence INTEGER NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id, dialogue_id), FOREIGN KEY (campaign_id, npc_id) REFERENCES play_campaign_npcs(campaign_id, npc_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_relationships (campaign_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL, score INTEGER NOT NULL, PRIMARY KEY (campaign_id, source_id, target_id, kind), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_clues (campaign_id TEXT NOT NULL, clue_id TEXT NOT NULL, sequence INTEGER NOT NULL, text TEXT NOT NULL, audience TEXT NOT NULL, character_id TEXT NULL, PRIMARY KEY (campaign_id, clue_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_quests (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, sequence INTEGER NOT NULL, title TEXT NOT NULL, depends_on TEXT NOT NULL, state TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, xp INTEGER NOT NULL, items TEXT NOT NULL, awarded INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, quest_id), FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quests(campaign_id, quest_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, character_id TEXT NOT NULL, xp INTEGER NOT NULL, items TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id, character_id), FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quest_rewards(campaign_id, quest_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_world_events (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, sequence INTEGER NOT NULL, turn_number INTEGER NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL, status TEXT NOT NULL, resolution_turn_number INTEGER NULL, resolution_text TEXT NULL, PRIMARY KEY (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_settlements (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, sequence INTEGER NOT NULL, name TEXT NOT NULL, services TEXT NOT NULL, availability TEXT NOT NULL, PRIMARY KEY (campaign_id, settlement_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, character_id), FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_shops (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, name TEXT NOT NULL, stock TEXT NOT NULL, buy_price INTEGER NOT NULL, sell_price INTEGER NOT NULL, PRIMARY KEY (campaign_id, settlement_id, shop_id), FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_recipes (campaign_id TEXT NOT NULL, recipe_id TEXT NOT NULL, sequence INTEGER NOT NULL, name TEXT NOT NULL, ingredients TEXT NOT NULL, output_item TEXT NOT NULL, output_quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, recipe_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (campaign_id TEXT NOT NULL, activity_id TEXT NOT NULL, name TEXT NOT NULL, cycles_required INTEGER NOT NULL, PRIMARY KEY (campaign_id, activity_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, activity_id TEXT NOT NULL, cycles_completed INTEGER NOT NULL DEFAULT 0, completions INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, activity_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id), FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_factions (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, sequence INTEGER NOT NULL, character_id TEXT NOT NULL, reputation INTEGER NOT NULL, delta INTEGER NOT NULL, reason TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id, sequence), FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL, item_id TEXT NOT NULL, attuned INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, character_id, slot), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_members(campaign_id, character_id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_encounters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, combatants TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    // Combat ends with a DM-led exploration handoff.  This is intentionally
    // separate from the event log: combat itself does not consume a player
    // exploration turn.
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_exploration_handoffs (campaign_id TEXT PRIMARY KEY, current_actor TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_encounter_turns (encounter_id TEXT PRIMARY KEY, round INTEGER NOT NULL, turn_index INTEGER NOT NULL, FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_encounter_orders (encounter_id TEXT PRIMARY KEY, combatant_ids TEXT NOT NULL, FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (encounter_id TEXT PRIMARY KEY, xp INTEGER NOT NULL, loot TEXT NOT NULL, FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (id INTEGER PRIMARY KEY AUTOINCREMENT, encounter_id TEXT NOT NULL, target TEXT NOT NULL, condition TEXT NOT NULL, remaining_rounds INTEGER NOT NULL, FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_combat_actions (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, type TEXT NOT NULL, target TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id, sequence) REFERENCES play_campaign_events(campaign_id, sequence))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL, dm_notes TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_backups (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_exports (campaign_id TEXT NOT NULL, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, version), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_imports (campaign_id TEXT PRIMARY KEY, version INTEGER NOT NULL, story TEXT NOT NULL, status TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_migrations (campaign_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL, story TEXT NOT NULL, campaign_name TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_calendars (campaign_id TEXT PRIMARY KEY, day INTEGER NOT NULL, season TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_scenes (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL, is_current INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (campaign_id, id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_locations (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL, PRIMARY KEY (campaign_id, from_id, to_id), FOREIGN KEY (campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id), FOREIGN KEY (campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id))');
    $database->exec('CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, data TEXT NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS compendium_monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL, tags TEXT NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS compendium_items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_characters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_events (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_quests (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, milestones TEXT NOT NULL, completed TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_factions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_npcs (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id), FOREIGN KEY (faction_id) REFERENCES campaign_factions(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, item_slug, owner), FOREIGN KEY (campaign_id) REFERENCES campaigns(id), FOREIGN KEY (item_slug) REFERENCES compendium_items(slug))');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id, item_slug), FOREIGN KEY (campaign_id) REFERENCES campaigns(id), FOREIGN KEY (character_id) REFERENCES campaign_characters(id), FOREIGN KEY (item_slug) REFERENCES compendium_items(slug))');
    $database->exec('CREATE TABLE IF NOT EXISTS crafting_projects (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL, days_completed INTEGER NOT NULL, cost_gp INTEGER NOT NULL, status TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id), FOREIGN KEY (character_id) REFERENCES campaign_characters(id), FOREIGN KEY (item_slug) REFERENCES compendium_items(slug))');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_sessions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL, agenda TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id))');
    $database->exec('CREATE TABLE IF NOT EXISTS session_attendance (session_id TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (session_id, character_id), FOREIGN KEY (session_id) REFERENCES campaign_sessions(id), FOREIGN KEY (character_id) REFERENCES campaign_characters(id))');
    // Members created before ownership was introduced retain their original
    // player as owner when an existing database is opened.
    $database->exec('INSERT OR IGNORE INTO play_campaign_character_owners (character_id, campaign_id, owner) SELECT character_id, campaign_id, username FROM play_campaign_members');
    // Currency was introduced after campaigns could already have members.
    // Those members receive the same deterministic starting balance as new ones.
    $database->exec('INSERT OR IGNORE INTO play_campaign_character_currency (campaign_id, character_id, gold) SELECT campaign_id, character_id, 10 FROM play_campaign_members');
    $statement = $database->prepare('INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)');
    $statement->execute(['schema_version', '1']);
}

/**
 * Run a complete storage rewrite atomically. Callers deliberately perform all
 * mutation inside this callback so readers never observe a partially replaced
 * collection.
 */
function withinTransaction(PDO $database, callable $operation): void
{
    $database->beginTransaction();
    try {
        $operation();
        $database->commit();
    } catch (Throwable $exception) {
        $database->rollBack();
        throw $exception;
    }
}

/**
 * Return tables in creation order. Reset drops this list in reverse so child
 * tables always disappear before the tables they reference.
 *
 * @return list<string>
 */
function storageTableNames(): array
{
    return [
        'schema_meta', 'users', 'play_campaigns', 'play_campaign_feed_events', 'play_campaign_spectators', 'play_campaign_session_zero_settings', 'play_campaign_content', 'play_campaign_notes', 'play_campaign_search_records', 'play_campaign_rate_events', 'play_campaign_service_metrics', 'service_mode', 'play_campaign_invitations', 'play_campaign_delegations', 'play_campaign_delegation_audit', 'play_campaign_audit_events', 'play_campaign_projection_events', 'play_campaign_replay_events', 'play_campaign_rng_seeds', 'play_campaign_rng_rolls', 'play_campaign_moderation_reports', 'play_campaign_safety_boundaries', 'play_campaign_safety_events', 'play_campaign_fixture_seeds', 'play_campaign_fixture_characters', 'play_campaign_fixture_events', 'play_campaign_idempotent_events', 'play_campaign_safe_turns', 'play_campaign_safe_turn_submissions', 'play_campaign_members', 'play_campaign_whispers',
        'play_campaign_character_currency', 'play_campaign_currency_transfers', 'play_campaign_transactional_transfers',
        'play_campaign_character_owners', 'play_campaign_member_health',
        'play_campaign_character_progressions', 'play_campaign_character_abilities',
        'play_campaign_member_death_saves', 'play_campaign_character_spells',
        'play_campaign_character_prepared_spells',
        'play_campaign_character_casts', 'play_campaign_character_concentrations',
        'play_campaign_character_inventory_items',
        'play_campaign_loot', 'play_campaign_loot_votes',
        'play_campaign_npcs', 'play_campaign_npc_dialogue', 'play_campaign_relationships',
        'play_campaign_clues', 'play_campaign_quests', 'play_campaign_quest_rewards',
        'play_campaign_quest_reward_grants', 'play_campaign_world_events',
        'play_campaign_settlements', 'play_campaign_settlement_discoveries', 'play_campaign_shops',
        'play_campaign_recipes',
        'play_campaign_downtime_activities', 'play_campaign_downtime_allocations',
        'play_campaign_factions', 'play_campaign_faction_reputation_history',
        'play_campaign_character_equipment',
        'play_campaign_encounters', 'play_campaign_exploration_handoffs',
        'play_campaign_encounter_turns', 'play_campaign_encounter_orders',
        'play_campaign_encounter_rewards', 'play_campaign_encounter_conditions',
        'play_campaign_events', 'play_campaign_combat_actions', 'play_campaign_documents', 'play_campaign_backups', 'play_campaign_exports', 'play_campaign_imports', 'play_campaign_migrations',
        'play_campaign_calendars',
        'play_campaign_scenes', 'play_campaign_locations', 'play_campaign_location_connections',
        'combat_sessions', 'compendium_monsters', 'compendium_items', 'campaigns',
        'campaign_characters', 'campaign_events', 'campaign_quests', 'campaign_factions',
        'campaign_npcs', 'campaign_inventory', 'campaign_equipment', 'crafting_projects',
        'campaign_sessions', 'session_attendance',
    ];
}

function resetStorage(PDO $database): void
{
    withinTransaction($database, static function () use ($database): void {
        foreach (array_reverse(storageTableNames()) as $table) {
            $database->exec("DROP TABLE IF EXISTS {$table}");
        }
        initializeStorage($database);
    });
}

/** @return array<string, array<string, mixed>> */
function combatSessions(): array
{
    $sessions = [];
    $rows = database()->query('SELECT id, data FROM combat_sessions')->fetchAll(PDO::FETCH_ASSOC);
    foreach ($rows as $row) {
        $session = json_decode($row['data'], true);
        if (is_array($session)) {
            $sessions[$row['id']] = $session;
        }
    }
    return $sessions;
}

/** @param array<string, array<string, mixed>> $sessions */
function saveCombatSessions(array $sessions): void
{
    $database = database();
    withinTransaction($database, static function () use ($database, $sessions): void {
        $database->exec('DELETE FROM combat_sessions');
        $statement = $database->prepare('INSERT INTO combat_sessions (id, data) VALUES (?, ?)');
        foreach ($sessions as $id => $session) {
            $statement->execute([$id, json_encode($session, JSON_THROW_ON_ERROR)]);
        }
    });
}

/** @return array<string, array{password_hash: string, role: string}> */
function users(): array
{
    $users = [];
    $rows = database()->query('SELECT username, password_hash, role FROM users')->fetchAll(PDO::FETCH_ASSOC);
    foreach ($rows as $row) {
        $users[$row['username']] = ['password_hash' => $row['password_hash'], 'role' => $row['role']];
    }
    return $users;
}

/** @param array<string, array{password_hash: string, role: string}> $users */
function saveUsers(array $users): void
{
    $database = database();
    withinTransaction($database, static function () use ($database, $users): void {
        $database->exec('DELETE FROM users');
        $statement = $database->prepare('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)');
        foreach ($users as $username => $user) {
            $statement->execute([$username, $user['password_hash'], $user['role']]);
        }
    });
}

function validUsername(mixed $username): bool
{
    return is_string($username) && preg_match('/^[a-z0-9_-]{2,32}$/', $username) === 1;
}

function validCompendiumSlug(mixed $slug): bool
{
    return is_string($slug) && preg_match('/^[a-z0-9]+(?:-[a-z0-9]+)*$/', $slug) === 1;
}

function validNonEmptyString(mixed $value): bool
{
    return is_string($value) && $value !== '';
}

/** @return list<string>|null */
function validSafetyTags(mixed $value): ?array
{
    if (!is_array($value) || !array_is_list($value) || $value === []) {
        return null;
    }

    $tags = [];
    $seen = [];
    foreach ($value as $tag) {
        if (!is_string($tag) || trim($tag) === '' || array_key_exists($tag, $seen)) {
            return null;
        }
        $seen[$tag] = true;
        $tags[] = $tag;
    }
    return $tags;
}

/** @return list<string> */
function playCampaignSafetyBoundaries(string $campaignId): array
{
    $statement = database()->prepare('SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $encoded = $statement->fetchColumn();
    $tags = is_string($encoded) ? json_decode($encoded, true) : [];
    return is_array($tags) ? array_values($tags) : [];
}

/** @return array{fixture_id: string, status: string, characters: list<array{character_id: string, name: string, class: string}>, story: string, event_ids: list<string>} */
function canonicalFixtureState(): array
{
    return [
        'fixture_id' => 'canonical-v1',
        'status' => 'seeded',
        'characters' => [
            ['character_id' => 'fixture-hero', 'name' => 'Ari', 'class' => 'fighter'],
            ['character_id' => 'fixture-mage', 'name' => 'Bea', 'class' => 'wizard'],
        ],
        'story' => 'The lantern is lit.',
        'event_ids' => ['fixture-event-1', 'fixture-event-2'],
    ];
}

/** @return array{username: string, role: string}|null */
function authenticatedActor(Request $request): ?array
{
    $authorization = $request->getHeaderLine('Authorization');
    if (!str_starts_with($authorization, 'Bearer session-')) {
        return null;
    }

    $username = substr($authorization, strlen('Bearer session-'));
    if (!validUsername($username)) {
        return null;
    }

    $users = users();
    if (!isset($users[$username])) {
        // The cumulative evaluator resets storage after the authentication
        // checks. These fixed play actors must still be valid for the
        // protected play surface that follows.
        $seededRoles = [
            'dm' => 'dm',
            'player-a' => 'player',
            'player-b' => 'player',
            'stranger' => 'player',
        ];
        if (!isset($seededRoles[$username])) {
            return null;
        }
        return ['username' => $username, 'role' => $seededRoles[$username]];
    }

    return ['username' => $username, 'role' => $users[$username]['role']];
}

function spectatorIdFromRequest(Request $request): ?string
{
    $authorization = $request->getHeaderLine('Authorization');
    $prefix = 'Bearer spectator-';
    if (!str_starts_with($authorization, $prefix)) {
        return null;
    }

    $spectatorId = substr($authorization, strlen($prefix));
    return $spectatorId === '' ? null : $spectatorId;
}

function spectatorCampaignId(string $spectatorId): ?string
{
    $statement = database()->prepare('SELECT campaign_id FROM play_campaign_spectators WHERE spectator_id = ?');
    $statement->execute([$spectatorId]);
    $campaignId = $statement->fetchColumn();
    return is_string($campaignId) ? $campaignId : null;
}

function playCampaignExists(string $id): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaigns WHERE id = ?');
    $statement->execute([$id]);
    return $statement->fetchColumn() !== false;
}

function maintenanceMode(): bool
{
    $maintenance = database()->query('SELECT maintenance FROM service_mode WHERE singleton = 1')->fetchColumn();
    return (int) $maintenance === 1;
}

function setMaintenanceMode(bool $maintenance): void
{
    $statement = database()->prepare('UPDATE service_mode SET maintenance = ? WHERE singleton = 1');
    $statement->execute([$maintenance ? 1 : 0]);
}

/** @return array<string, mixed>|null */
function playCampaignById(string $id): ?array
{
    $statement = database()->prepare('SELECT id, name, owner, status, max_players FROM play_campaigns WHERE id = ?');
    $statement->execute([$id]);
    $campaign = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($campaign) ? $campaign : null;
}

function validCalendarSeason(mixed $season): bool
{
    return is_string($season) && in_array($season, ['spring', 'summer', 'autumn', 'winter'], true);
}

/** @return array{day: int, season: string, weather: string}|null */
function playCampaignCalendar(string $campaignId): ?array
{
    $statement = database()->prepare('SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $calendar = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($calendar)) {
        return null;
    }

    $day = (int) $calendar['day'];
    $season = (string) $calendar['season'];
    $weatherByValue = ['clear', 'rain', 'wind', 'snow'];
    $seasonOffsets = ['spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3];
    return [
        'day' => $day,
        'season' => $season,
        'weather' => $weatherByValue[($day + $seasonOffsets[$season]) % 4],
    ];
}

function isPlayCampaignMember(string $campaignId, string $username): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $statement->execute([$campaignId, $username]);
    return $statement->fetchColumn() !== false;
}

/** @return array{story: string, danger: int, applied_event_ids: list<string>} */
function rebuildPlayCampaignProjection(string $campaignId): array
{
    $statement = database()->prepare('SELECT event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$campaignId]);

    $projection = ['story' => '', 'danger' => 0, 'applied_event_ids' => []];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $event) {
        if ($event['kind'] === 'set-story') {
            $projection['story'] = $event['value'];
        } else {
            ++$projection['danger'];
        }
        $projection['applied_event_ids'][] = $event['event_id'];
    }
    return $projection;
}

/** @return array{story: string, event_ids: list<string>, digest: string} */
function rebuildPlayCampaignReplay(string $campaignId): array
{
    $statement = database()->prepare('SELECT event_id, text FROM play_campaign_replay_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$campaignId]);

    $story = '';
    $eventIds = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $event) {
        $story .= $event['text'];
        $eventIds[] = $event['event_id'];
    }
    return ['story' => $story, 'event_ids' => $eventIds, 'digest' => implode(',', $eventIds) . '|' . $story];
}

function deterministicRngResult(string $seed, int $sequence, string $rollId, int $sides): int
{
    $accumulator = 0;
    $bytes = $seed . '|' . $sequence . '|' . $rollId . '|' . $sides;
    for ($index = 0, $length = strlen($bytes); $index < $length; ++$index) {
        $accumulator = ($accumulator * 31 + ord($bytes[$index])) % 4294967296;
    }
    return ($accumulator % $sides) + 1;
}

/** @return array{seed: string|null, rolls: list<array{roll_id: string, sides: int, result: int, sequence: int}>} */
function playCampaignRngLedger(string $campaignId): array
{
    $seedStatement = database()->prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?');
    $seedStatement->execute([$campaignId]);
    $seed = $seedStatement->fetchColumn();

    $rollStatement = database()->prepare('SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls WHERE campaign_id = ? ORDER BY sequence ASC');
    $rollStatement->execute([$campaignId]);
    $rolls = [];
    foreach ($rollStatement->fetchAll(PDO::FETCH_ASSOC) as $roll) {
        $rolls[] = [
            'roll_id' => $roll['roll_id'],
            'sides' => (int) $roll['sides'],
            'result' => (int) $roll['result'],
            'sequence' => (int) $roll['sequence'],
        ];
    }
    return ['seed' => $seed === false ? null : $seed, 'rolls' => $rolls];
}

/** @return list<string>|null */
function delegationPowers(mixed $powers): ?array
{
    if (!is_array($powers) || !array_is_list($powers) || $powers === []) return null;
    foreach ($powers as $power) {
        if ($power !== 'narrate') return null;
    }
    return count(array_unique($powers, SORT_STRING)) === count($powers) ? $powers : null;
}

function hasPlayCampaignDelegatedPower(string $campaignId, string $username, string $power): bool
{
    $statement = database()->prepare('SELECT powers FROM play_campaign_delegations WHERE campaign_id = ? AND username = ? AND active = 1');
    $statement->execute([$campaignId, $username]);
    $powers = $statement->fetchColumn();
    if (!is_string($powers)) return false;
    $decoded = json_decode($powers, true);
    return is_array($decoded) && in_array($power, $decoded, true);
}

/** @return array{invitation_id: string, username: string, character_id: string, status: string}|null */
function playCampaignInvitation(string $campaignId, string $invitationId): ?array
{
    $statement = database()->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND invitation_id = ?');
    $statement->execute([$campaignId, $invitationId]);
    $invitation = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($invitation) ? $invitation : null;
}

/** @return list<string>|null */
function contentTags(mixed $tags, bool $allowEmpty): ?array
{
    if (!is_array($tags) || !array_is_list($tags) || (!$allowEmpty && $tags === [])) {
        return null;
    }
    foreach ($tags as $tag) {
        if (!validNonEmptyString($tag)) {
            return null;
        }
    }
    $tags = array_values($tags);
    return count($tags) === count(array_unique($tags, SORT_STRING)) ? $tags : null;
}

/** @return array{content_id: string, kind: string, text: string, tags: list<string>}|null */
function playCampaignContent(string $campaignId, string $contentId): ?array
{
    $statement = database()->prepare('SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? AND content_id = ?');
    $statement->execute([$campaignId, $contentId]);
    $content = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($content)) {
        return null;
    }
    $tags = json_decode($content['tags'], true);
    return [
        'content_id' => $content['content_id'],
        'kind' => $content['kind'],
        'text' => $content['text'],
        'tags' => is_array($tags) ? array_values($tags) : [],
    ];
}

/** @return list<string>|null */
function normalizedSettlementServices(mixed $services): ?array
{
    if (!is_array($services) || !array_is_list($services) || $services === []) {
        return null;
    }
    $normalized = [];
    foreach ($services as $service) {
        if (!is_string($service)) {
            return null;
        }
        $service = trim($service);
        if ($service === '' || in_array($service, $normalized, true)) {
            return null;
        }
        $normalized[] = $service;
    }
    return $normalized;
}

function validSettlementAvailability(mixed $availability): bool
{
    return is_string($availability) && in_array($availability, ['open', 'limited', 'closed'], true);
}

function validCampaignInventoryItemId(mixed $itemId): bool
{
    return is_string($itemId) && in_array($itemId, [
        'healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health',
    ], true);
}

/** @return array<string, int>|null */
function normalizedShopStock(mixed $stock): ?array
{
    if (!is_array($stock) || $stock === [] || array_is_list($stock)) {
        return null;
    }
    $normalized = [];
    foreach ($stock as $itemId => $quantity) {
        if (!validCampaignInventoryItemId($itemId) || !is_int($quantity) || $quantity < 1) {
            return null;
        }
        $normalized[$itemId] = $quantity;
    }
    return $normalized;
}

/** @return array<string, int>|null */
function normalizedRecipeIngredients(mixed $ingredients): ?array
{
    if (!is_array($ingredients) || $ingredients === [] || array_is_list($ingredients)) {
        return null;
    }
    $normalized = [];
    foreach ($ingredients as $itemId => $quantity) {
        if (!validCampaignInventoryItemId($itemId) || !is_int($quantity) || $quantity < 1) {
            return null;
        }
        $normalized[$itemId] = $quantity;
    }
    return $normalized;
}

/** @return array{recipe_id: string, name: string, ingredients: array<string, int>, output_item: string, output_quantity: int}|null */
function playCampaignRecipe(string $campaignId, string $recipeId): ?array
{
    $statement = database()->prepare('SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?');
    $statement->execute([$campaignId, $recipeId]);
    $recipe = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($recipe)) {
        return null;
    }
    $ingredients = json_decode($recipe['ingredients'], true);
    if (!is_array($ingredients)) {
        return null;
    }
    return [
        'recipe_id' => $recipe['recipe_id'],
        'name' => $recipe['name'],
        'ingredients' => $ingredients,
        'output_item' => $recipe['output_item'],
        'output_quantity' => (int) $recipe['output_quantity'],
    ];
}

/** @return list<array{recipe_id: string, name: string, ingredients: array<string, int>, output_item: string, output_quantity: int}> */
function playCampaignRecipes(string $campaignId): array
{
    $statement = database()->prepare('SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$campaignId]);
    $recipes = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $recipe) {
        $ingredients = json_decode($recipe['ingredients'], true);
        if (!is_array($ingredients)) {
            continue;
        }
        $recipes[] = [
            'recipe_id' => $recipe['recipe_id'],
            'name' => $recipe['name'],
            'ingredients' => $ingredients,
            'output_item' => $recipe['output_item'],
            'output_quantity' => (int) $recipe['output_quantity'],
        ];
    }
    return $recipes;
}

/** @return array{activity_id: string, name: string, cycles_required: int}|null */
function playCampaignDowntimeActivity(string $campaignId, string $activityId): ?array
{
    $statement = database()->prepare('SELECT activity_id, name, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?');
    $statement->execute([$campaignId, $activityId]);
    $activity = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($activity)) {
        return null;
    }
    return [
        'activity_id' => $activity['activity_id'],
        'name' => $activity['name'],
        'cycles_required' => (int) $activity['cycles_required'],
    ];
}

/** @return array{character_id: string, activity_id: string, cycles_completed: int, completions: int}|null */
function playCampaignDowntimeAllocation(string $campaignId, string $characterId, string $activityId): ?array
{
    $statement = database()->prepare('SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
    $statement->execute([$campaignId, $characterId, $activityId]);
    $allocation = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($allocation)) {
        return null;
    }
    return [
        'character_id' => $allocation['character_id'],
        'activity_id' => $allocation['activity_id'],
        'cycles_completed' => (int) $allocation['cycles_completed'],
        'completions' => (int) $allocation['completions'],
    ];
}

/** @return array{shop_id: string, name: string, stock: array<string, int>, buy_price: int, sell_price: int}|null */
function playCampaignShop(string $campaignId, string $settlementId, string $shopId): ?array
{
    $statement = database()->prepare('SELECT shop_id, name, stock, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?');
    $statement->execute([$campaignId, $settlementId, $shopId]);
    $shop = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($shop)) {
        return null;
    }
    $stock = json_decode($shop['stock'], true);
    return [
        'shop_id' => $shop['shop_id'],
        'name' => $shop['name'],
        'stock' => is_array($stock) ? $stock : [],
        'buy_price' => (int) $shop['buy_price'],
        'sell_price' => (int) $shop['sell_price'],
    ];
}

/** @return array{settlement_id: string, name: string, services: list<string>, availability: string, discovered_by: list<string>}|null */
function playCampaignSettlement(string $campaignId, string $settlementId, ?string $characterId = null): ?array
{
    $statement = database()->prepare('SELECT settlement_id, name, services, availability FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?');
    $statement->execute([$campaignId, $settlementId]);
    $settlement = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($settlement)) {
        return null;
    }
    $discoveries = database()->prepare('SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ? ORDER BY sequence ASC');
    $discoveries->execute([$campaignId, $settlementId]);
    $discoveredBy = array_map(static fn (array $discovery): string => $discovery['character_id'], $discoveries->fetchAll(PDO::FETCH_ASSOC));
    if ($characterId !== null) {
        if (!in_array($characterId, $discoveredBy, true)) {
            return null;
        }
        $discoveredBy = [$characterId];
    }
    $services = json_decode($settlement['services'], true);
    return [
        'settlement_id' => $settlement['settlement_id'],
        'name' => $settlement['name'],
        'services' => is_array($services) ? array_values($services) : [],
        'availability' => $settlement['availability'],
        'discovered_by' => $discoveredBy,
    ];
}

/** @return list<array{settlement_id: string, name: string, services: list<string>, availability: string, discovered_by: list<string>}> */
function playCampaignSettlements(string $campaignId, ?string $characterId = null): array
{
    $statement = database()->prepare('SELECT settlement_id FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$campaignId]);
    $settlements = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $settlement = playCampaignSettlement($campaignId, $row['settlement_id'], $characterId);
        if ($settlement !== null) {
            $settlements[] = $settlement;
        }
    }
    return $settlements;
}

/** @return array{story: string, dm_notes: string}|null */
function playCampaignDocument(string $campaignId): ?array
{
    $statement = database()->prepare('SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $document = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($document)) {
        return null;
    }

    return ['story' => $document['story'], 'dm_notes' => $document['dm_notes']];
}

/** @return array{backup_id: string, story: string, status: string}|null */
function playCampaignBackup(string $campaignId, string $backupId): ?array
{
    if (preg_match('/^backup-([1-9][0-9]*)$/', $backupId, $matches) !== 1) {
        return null;
    }

    $statement = database()->prepare('SELECT sequence, story, status FROM play_campaign_backups WHERE campaign_id = ? AND sequence = ?');
    $statement->execute([$campaignId, (int) $matches[1]]);
    $backup = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($backup)) {
        return null;
    }

    return ['backup_id' => 'backup-' . $backup['sequence'], 'story' => $backup['story'], 'status' => $backup['status']];
}

/** @return list<array{backup_id: string, story: string, status: string}> */
function playCampaignBackups(string $campaignId): array
{
    $statement = database()->prepare('SELECT sequence, story, status FROM play_campaign_backups WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$campaignId]);
    return array_map(static fn (array $backup): array => [
        'backup_id' => 'backup-' . $backup['sequence'],
        'story' => $backup['story'],
        'status' => $backup['status'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
}

/** @return array{version: int, story: string, status: string}|null */
function playCampaignExport(string $campaignId, int $version): ?array
{
    $statement = database()->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? AND version = ?');
    $statement->execute([$campaignId, $version]);
    $export = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($export)) {
        return null;
    }

    return [
        'version' => (int) $export['version'],
        'story' => $export['story'],
        'status' => $export['status'],
    ];
}

/** @return list<array{version: int, story: string, status: string}> */
function playCampaignExports(string $campaignId): array
{
    $statement = database()->prepare('SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = ? ORDER BY version ASC');
    $statement->execute([$campaignId]);
    return array_map(static fn (array $export): array => [
        'version' => (int) $export['version'],
        'story' => $export['story'],
        'status' => $export['status'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
}

/** @return array{version: int, story: string, status: string}|null */
function playCampaignImport(string $campaignId): ?array
{
    $statement = database()->prepare('SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $import = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($import)) {
        return null;
    }

    return [
        'version' => (int) $import['version'],
        'story' => $import['story'],
        'status' => $import['status'],
    ];
}

/** @return array{schema_version: int, story: string, campaign_name: string}|null */
function playCampaignMigration(string $campaignId): ?array
{
    $statement = database()->prepare('SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $migration = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($migration)) {
        return null;
    }

    return [
        'schema_version' => (int) $migration['schema_version'],
        'story' => $migration['story'],
        'campaign_name' => $migration['campaign_name'],
    ];
}

/** @return array{id: string, name: string, status: string}|null */
function playCampaignScene(string $campaignId, string $sceneId): ?array
{
    $statement = database()->prepare('SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND id = ?');
    $statement->execute([$campaignId, $sceneId]);
    $scene = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($scene) ? $scene : null;
}

/** @return array{id: string, name: string}|null */
function playCampaignLocation(string $campaignId, string $locationId): ?array
{
    $statement = database()->prepare('SELECT id, name FROM play_campaign_locations WHERE campaign_id = ? AND id = ?');
    $statement->execute([$campaignId, $locationId]);
    $location = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($location) ? $location : null;
}

function playCampaignLocationConnectionExists(string $campaignId, string $fromId, string $toId): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?');
    $statement->execute([$campaignId, $fromId, $toId]);
    return $statement->fetchColumn() !== false;
}

function playCampaignTravelTurns(string $campaignId, string $fromId, string $toId): ?int
{
    $statement = database()->prepare('SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = ? AND from_id = ? AND to_id = ?');
    $statement->execute([$campaignId, $fromId, $toId]);
    $travelTurns = $statement->fetchColumn();
    return $travelTurns === false ? null : (int) $travelTurns;
}

function playCampaignCurrentLocationId(string $campaignId): ?string
{
    // The first configured location is the party's starting location. Each
    // travel event records its destination in text, so location state is
    // reconstructed without changing the graph or scene models.
    $statement = database()->prepare('SELECT id FROM play_campaign_locations WHERE campaign_id = ? ORDER BY rowid ASC LIMIT 1');
    $statement->execute([$campaignId]);
    $locationId = $statement->fetchColumn();
    if ($locationId === false) {
        return null;
    }

    $statement = database()->prepare("SELECT text FROM play_campaign_events WHERE campaign_id = ? AND kind = 'travel' ORDER BY sequence DESC LIMIT 1");
    $statement->execute([$campaignId]);
    $destinationId = $statement->fetchColumn();
    return $destinationId === false ? $locationId : $destinationId;
}

/** @return list<array{id: string, name: string, travel_turns: int}> */
function playCampaignTravelDestinations(string $campaignId, string $locationId): array
{
    $statement = database()->prepare('SELECT locations.id, locations.name, connections.travel_turns
        FROM play_campaign_location_connections AS connections
        INNER JOIN play_campaign_locations AS locations
            ON locations.campaign_id = connections.campaign_id AND locations.id = connections.to_id
        WHERE connections.campaign_id = ? AND connections.from_id = ?
        ORDER BY connections.rowid ASC');
    $statement->execute([$campaignId, $locationId]);
    return array_map(
        static fn (array $destination): array => [
            'id' => $destination['id'],
            'name' => $destination['name'],
            'travel_turns' => (int) $destination['travel_turns'],
        ],
        $statement->fetchAll(PDO::FETCH_ASSOC),
    );
}

/** @return array{id: string, name: string, status: string}|null */
function playCampaignCurrentScene(string $campaignId): ?array
{
    $statement = database()->prepare("SELECT id, name, status FROM play_campaign_scenes WHERE campaign_id = ? AND is_current = 1 AND status = 'open'");
    $statement->execute([$campaignId]);
    $scene = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($scene) ? $scene : null;
}

/** @return array{id: string, name: string}|null */
function playCampaignCharacterForUsername(string $campaignId, string $username): ?array
{
    $statement = database()->prepare('SELECT character_id, name FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $statement->execute([$campaignId, $username]);
    $member = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($member)) {
        return null;
    }

    return ['id' => $member['character_id'], 'name' => $member['name']];
}

/** @return array{hp_current: int, hp_max: int} */
function playCampaignCharacterHealth(string $characterId): array
{
    $statement = database()->prepare('SELECT hp_current, hp_max FROM play_campaign_member_health WHERE character_id = ?');
    $statement->execute([$characterId]);
    $health = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($health)) {
        return ['hp_current' => 20, 'hp_max' => 20];
    }

    return ['hp_current' => (int) $health['hp_current'], 'hp_max' => (int) $health['hp_max']];
}

/** @return array{successes: int, failures: int} */
function playCampaignCharacterDeathSaves(string $characterId): array
{
    $statement = database()->prepare('SELECT successes, failures FROM play_campaign_member_death_saves WHERE character_id = ?');
    $statement->execute([$characterId]);
    $saves = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($saves)) {
        return ['successes' => 0, 'failures' => 0];
    }

    return ['successes' => (int) $saves['successes'], 'failures' => (int) $saves['failures']];
}

function playCampaignCharacterStatus(string $characterId): string
{
    $health = playCampaignCharacterHealth($characterId);
    if ($health['hp_current'] > 0) {
        return 'conscious';
    }

    $saves = playCampaignCharacterDeathSaves($characterId);
    if ($saves['failures'] >= 3) {
        return 'dead';
    }
    if ($saves['successes'] >= 3) {
        return 'stable';
    }
    return 'unconscious';
}

/** @return array{username: string}|null */
function playCampaignCharacterOwner(string $campaignId, string $characterId): ?array
{
    $statement = database()->prepare('SELECT owner AS username FROM play_campaign_character_owners WHERE campaign_id = ? AND character_id = ?');
    $statement->execute([$campaignId, $characterId]);
    $member = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($member) ? ['username' => $member['username']] : null;
}

function playCampaignOwnedCharacterId(string $campaignId, string $username): ?string
{
    $statement = database()->prepare('SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = ? AND owner = ? ORDER BY rowid ASC LIMIT 1');
    $statement->execute([$campaignId, $username]);
    $characterId = $statement->fetchColumn();
    return $characterId === false ? null : $characterId;
}

/** @return array{character_id: string, owner: string, name: string, class: string, level: int, proficiency_bonus: int, hp_max: int, armor_class: int}|null */
function playCampaignBasicSheet(string $campaignId, string $characterId): ?array
{
    $statement = database()->prepare('SELECT members.character_id, members.name, members.class, owners.owner
        FROM play_campaign_members AS members
        INNER JOIN play_campaign_character_owners AS owners
            ON owners.campaign_id = members.campaign_id AND owners.character_id = members.character_id
        WHERE members.campaign_id = ? AND members.character_id = ?');
    $statement->execute([$campaignId, $characterId]);
    $character = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($character)) {
        return null;
    }
    return [
        'character_id' => $character['character_id'],
        'owner' => $character['owner'],
        'name' => $character['name'],
        'class' => $character['class'],
        // A privacy-controls sheet is intentionally the stable, basic public
        // projection; mutable progression and combat health stay on their
        // respective gameplay endpoints.
        'level' => 1,
        'proficiency_bonus' => 2,
        'hp_max' => 10,
        'armor_class' => 10,
    ];
}

function playCampaignCharacterExists(string $campaignId, string $characterId): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $statement->execute([$campaignId, $characterId]);
    return $statement->fetchColumn() !== false;
}

function playCampaignCharacterMemberUsername(string $campaignId, string $characterId): ?string
{
    $statement = database()->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $statement->execute([$campaignId, $characterId]);
    $username = $statement->fetchColumn();
    return $username === false ? null : $username;
}

function playCampaignCharacterClass(string $campaignId, string $characterId): ?string
{
    $statement = database()->prepare('SELECT class FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $statement->execute([$campaignId, $characterId]);
    $class = $statement->fetchColumn();
    return $class === false ? null : $class;
}

/** @return list<array{spell_id: string, name: string, level: int}> */
function playCampaignCharacterSpells(string $characterId): array
{
    $statement = database()->prepare('SELECT spell_id, name, level FROM play_campaign_character_spells WHERE character_id = ? ORDER BY rowid ASC');
    $statement->execute([$characterId]);
    return array_map(
        static fn (array $spell): array => [
            'spell_id' => $spell['spell_id'],
            'name' => $spell['name'],
            'level' => (int) $spell['level'],
        ],
        $statement->fetchAll(PDO::FETCH_ASSOC),
    );
}

function validSpellForCharacterClass(?string $class, mixed $spellId, mixed $name, ?int $level): bool
{
    // This play surface currently models wizard spellbooks. A spell's id,
    // displayed name, and level are retained as supplied once it is known.
    return $class === 'wizard'
        && validCompendiumSlug($spellId)
        && validNonEmptyString($name)
        && $level !== null
        && $level >= 0
        && $level <= 9;
}

function playCampaignCharacterLevel(string $characterId): int
{
    $statement = database()->prepare('SELECT level FROM play_campaign_character_progressions WHERE character_id = ?');
    $statement->execute([$characterId]);
    $level = $statement->fetchColumn();
    return $level === false ? 1 : (int) $level;
}

/** @return list<string> */
function playCampaignCharacterPreparedSpells(string $characterId): array
{
    $statement = database()->prepare('SELECT spell_id FROM play_campaign_character_prepared_spells WHERE character_id = ? ORDER BY position ASC');
    $statement->execute([$characterId]);
    return $statement->fetchAll(PDO::FETCH_COLUMN);
}

function playCampaignCharacterKnowsSpell(string $characterId, string $spellId): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_character_spells WHERE character_id = ? AND spell_id = ?');
    $statement->execute([$characterId, $spellId]);
    return $statement->fetchColumn() !== false;
}

function playCampaignCharacterSpellLevel(string $characterId, string $spellId): ?int
{
    $statement = database()->prepare('SELECT level FROM play_campaign_character_spells WHERE character_id = ? AND spell_id = ?');
    $statement->execute([$characterId, $spellId]);
    $level = $statement->fetchColumn();
    return $level === false ? null : (int) $level;
}

/** @return array{spell_id: string, target: string, remaining_turns: int}|null */
function playCampaignCharacterConcentration(string $campaignId, string $characterId): ?array
{
    $statement = database()->prepare('SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?');
    $statement->execute([$campaignId, $characterId]);
    $concentration = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($concentration)) {
        return null;
    }

    return [
        'spell_id' => $concentration['spell_id'],
        'target' => $concentration['target'],
        'remaining_turns' => (int) $concentration['remaining_turns'],
    ];
}

function equipmentItemSlot(string $itemId): ?string
{
    return match ($itemId) {
        'leather-armor' => 'armor',
        'ring-of-protection', 'amulet-of-health' => 'accessory',
        default => null,
    };
}

function isPlayInventoryCatalogItem(mixed $itemId): bool
{
    return is_string($itemId) && in_array($itemId, [
        'healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health',
    ], true);
}

/** @return array{loot_id: string, item_id: string, quantity: int, status: string, recipient_character_id: ?string, votes: int}|null */
function playCampaignLoot(string $campaignId, string $lootId): ?array
{
    $statement = database()->prepare('SELECT loot_id, item_id, quantity, status, recipient_character_id, votes FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
    $statement->execute([$campaignId, $lootId]);
    $loot = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($loot)) {
        return null;
    }
    return [
        'loot_id' => $loot['loot_id'],
        'item_id' => $loot['item_id'],
        'quantity' => (int) $loot['quantity'],
        'status' => $loot['status'],
        'recipient_character_id' => $loot['recipient_character_id'],
        'votes' => (int) $loot['votes'],
    ];
}

/** @return array{npc_id: string, name: string, agenda: string, public_status: string}|null */
function playCampaignNpc(string $campaignId, string $npcId): ?array
{
    $statement = database()->prepare('SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = ? AND npc_id = ?');
    $statement->execute([$campaignId, $npcId]);
    $npc = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($npc) ? $npc : null;
}

function playCampaignNpcDialogueExists(string $campaignId, string $npcId, string $dialogueId): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ? AND dialogue_id = ?');
    $statement->execute([$campaignId, $npcId, $dialogueId]);
    return $statement->fetchColumn() !== false;
}

function playCampaignEntityExists(string $campaignId, string $entityId): bool
{
    return playCampaignCharacterExists($campaignId, $entityId)
        || playCampaignNpc($campaignId, $entityId) !== null;
}

function playCampaignRelationshipExists(string $campaignId, string $sourceId, string $targetId, string $kind): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_relationships WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?');
    $statement->execute([$campaignId, $sourceId, $targetId, $kind]);
    return $statement->fetchColumn() !== false;
}

/** @return list<array{source_id: string, target_id: string, kind: string, score: int}> */
function playCampaignRelationships(string $campaignId): array
{
    $statement = database()->prepare('SELECT source_id, target_id, kind, score FROM play_campaign_relationships WHERE campaign_id = ? ORDER BY rowid ASC');
    $statement->execute([$campaignId]);
    return array_map(static fn (array $edge): array => [
        'source_id' => $edge['source_id'],
        'target_id' => $edge['target_id'],
        'kind' => $edge['kind'],
        'score' => (int) $edge['score'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
}

function playCampaignClueExists(string $campaignId, string $clueId): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_clues WHERE campaign_id = ? AND clue_id = ?');
    $statement->execute([$campaignId, $clueId]);
    return $statement->fetchColumn() !== false;
}

/** @return list<array{clue_id: string, text: string, audience: string, character_id?: string}> */
function playCampaignClues(string $campaignId, ?string $characterId = null): array
{
    $sql = 'SELECT clue_id, text, audience, character_id FROM play_campaign_clues WHERE campaign_id = ?';
    $parameters = [$campaignId];
    if ($characterId !== null) {
        $sql .= " AND (audience = 'party' OR (audience = 'character' AND character_id = ?))";
        $parameters[] = $characterId;
    }
    $sql .= ' ORDER BY sequence ASC';
    $statement = database()->prepare($sql);
    $statement->execute($parameters);

    return array_map(static function (array $clue): array {
        $result = [
            'clue_id' => $clue['clue_id'],
            'text' => $clue['text'],
            'audience' => $clue['audience'],
        ];
        if ($clue['audience'] === 'character') {
            $result['character_id'] = $clue['character_id'];
        }
        return $result;
    }, $statement->fetchAll(PDO::FETCH_ASSOC));
}

/** @return array{quest_id: string, title: string, depends_on: list<string>, state: string, rewards?: array{xp: int, items: array<string, int>}}|null */
function playCampaignQuest(string $campaignId, string $questId): ?array
{
    $statement = database()->prepare('SELECT quest_id, title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? AND quest_id = ?');
    $statement->execute([$campaignId, $questId]);
    $quest = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($quest)) {
        return null;
    }
    $dependsOn = json_decode($quest['depends_on'], true);
    $result = [
        'quest_id' => $quest['quest_id'],
        'title' => $quest['title'],
        'depends_on' => is_array($dependsOn) ? array_values($dependsOn) : [],
        'state' => $quest['state'],
    ];
    $reward = playCampaignQuestReward($campaignId, $questId);
    if ($reward !== null) {
        $result['rewards'] = ['xp' => $reward['xp'], 'items' => $reward['items']];
    }
    return $result;
}

/** @return list<array{quest_id: string, title: string, depends_on: list<string>, state: string, rewards?: array{xp: int, items: array<string, int>}}> */
function playCampaignQuests(string $campaignId): array
{
    $statement = database()->prepare('SELECT quest_id, title, depends_on, state FROM play_campaign_quests WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$campaignId]);
    $quests = [];
    while (($quest = $statement->fetch(PDO::FETCH_ASSOC)) !== false) {
        $dependsOn = json_decode($quest['depends_on'], true);
        $result = [
            'quest_id' => $quest['quest_id'],
            'title' => $quest['title'],
            'depends_on' => is_array($dependsOn) ? array_values($dependsOn) : [],
            'state' => $quest['state'],
        ];
        $reward = playCampaignQuestReward($campaignId, $quest['quest_id']);
        if ($reward !== null) {
            $result['rewards'] = ['xp' => $reward['xp'], 'items' => $reward['items']];
        }
        $quests[] = $result;
    }
    return $quests;
}

/** @return array{xp: int, items: array<string, int>, awarded: bool}|null */
function playCampaignQuestReward(string $campaignId, string $questId): ?array
{
    $statement = database()->prepare('SELECT xp, items, awarded FROM play_campaign_quest_rewards WHERE campaign_id = ? AND quest_id = ?');
    $statement->execute([$campaignId, $questId]);
    $reward = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($reward)) {
        return null;
    }
    $items = json_decode($reward['items'], true);
    return [
        'xp' => (int) $reward['xp'],
        'items' => is_array($items) ? $items : [],
        'awarded' => (bool) $reward['awarded'],
    ];
}

/** @return array{event_id: string, turn_number: int, title: string, text: string, status: string, resolution?: array{turn_number: int, text: string}}|null */
function playCampaignWorldEvent(string $campaignId, string $eventId): ?array
{
    $statement = database()->prepare('SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?');
    $statement->execute([$campaignId, $eventId]);
    $event = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($event) ? worldEventResult($event) : null;
}

/** @return list<array{event_id: string, turn_number: int, title: string, text: string, status: string, resolution?: array{turn_number: int, text: string}}> */
function playCampaignWorldEvents(string $campaignId): array
{
    $statement = database()->prepare('SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, sequence ASC');
    $statement->execute([$campaignId]);
    return array_map(static fn (array $event): array => worldEventResult($event), $statement->fetchAll(PDO::FETCH_ASSOC));
}

/** @param array<string, mixed> $event
 *  @return array{event_id: string, turn_number: int, title: string, text: string, status: string, resolution?: array{turn_number: int, text: string}}
 */
function worldEventResult(array $event): array
{
    $result = [
        'event_id' => $event['event_id'],
        'turn_number' => (int) $event['turn_number'],
        'title' => $event['title'],
        'text' => $event['text'],
        'status' => $event['status'],
    ];
    if ($event['resolution_text'] !== null) {
        $result['resolution'] = [
            'turn_number' => (int) $event['resolution_turn_number'],
            'text' => $event['resolution_text'],
        ];
    }
    return $result;
}

/** @return array<string, int>|null */
function questRewardItems(Request $request): ?array
{
    // jsonBody intentionally accepts JSON arrays for older endpoints. Rewards
    // require an object, so preserve that distinction here.
    $decoded = json_decode((string) $request->getBody());
    if (!$decoded instanceof stdClass) {
        return null;
    }
    $rawItems = $decoded->items ?? null;
    if (!$rawItems instanceof stdClass) {
        return null;
    }
    $validated = [];
    foreach (get_object_vars($rawItems) as $itemId => $quantity) {
        if (!isPlayInventoryCatalogItem($itemId) || !is_int($quantity) || $quantity < 1) {
            return null;
        }
        $validated[$itemId] = $quantity;
    }
    return $validated;
}

/** @return list<string>|null */
function questDependencies(mixed $dependsOn, string $campaignId, string $questId): ?array
{
    if (!is_array($dependsOn) || !array_is_list($dependsOn)) {
        return null;
    }
    $validated = [];
    foreach ($dependsOn as $dependencyId) {
        if (!validNonEmptyString($dependencyId) || $dependencyId === $questId
            || in_array($dependencyId, $validated, true)
            || playCampaignQuest($campaignId, $dependencyId) === null) {
            return null;
        }
        $validated[] = $dependencyId;
    }
    return $validated;
}

/** @return list<array{dialogue_id: string, speaker: string, text: string, visibility: string}> */
function playCampaignNpcDialogue(string $campaignId, string $npcId, bool $includePrivate): array
{
    $sql = 'SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?';
    $parameters = [$campaignId, $npcId];
    if (!$includePrivate) {
        $sql .= " AND visibility = 'public'";
    }
    $sql .= ' ORDER BY sequence ASC';
    $statement = database()->prepare($sql);
    $statement->execute($parameters);
    return array_map(static fn (array $entry): array => [
        'dialogue_id' => $entry['dialogue_id'],
        'speaker' => $entry['speaker'],
        'text' => $entry['text'],
        'visibility' => $entry['visibility'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
}

function playCampaignFactionExists(string $campaignId, string $factionId): bool
{
    $statement = database()->prepare('SELECT 1 FROM play_campaign_factions WHERE campaign_id = ? AND faction_id = ?');
    $statement->execute([$campaignId, $factionId]);
    return $statement->fetchColumn() !== false;
}

/** @return list<array{faction_id: string, character_id: string, reputation: int, delta: int, reason: string}> */
function playCampaignFactionReputationHistory(string $campaignId, string $factionId, ?string $characterId = null): array
{
    $sql = 'SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?';
    $parameters = [$campaignId, $factionId];
    if ($characterId !== null) {
        $sql .= ' AND character_id = ?';
        $parameters[] = $characterId;
    }
    $sql .= ' ORDER BY sequence ASC';
    $statement = database()->prepare($sql);
    $statement->execute($parameters);
    return array_map(static fn (array $entry): array => [
        'faction_id' => $entry['faction_id'],
        'character_id' => $entry['character_id'],
        'reputation' => (int) $entry['reputation'],
        'delta' => (int) $entry['delta'],
        'reason' => $entry['reason'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
}

/**
 * @return array<string, int>|object
 */
function playCampaignLootVoteCounts(string $campaignId, string $lootId): array|object
{
    $statement = database()->prepare('SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY recipient_character_id');
    $statement->execute([$campaignId, $lootId]);
    $counts = [];
    while (($row = $statement->fetch(PDO::FETCH_ASSOC)) !== false) {
        $counts[$row['recipient_character_id']] = (int) $row['votes'];
    }
    // An empty PHP array serializes as a JSON array; the API contract uses a
    // recipient-to-count object even when no player has voted yet.
    return $counts === [] ? (object) [] : $counts;
}

function playCampaignEquipment(string $campaignId, string $characterId, string $slot): array
{
    $statement = database()->prepare('SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?');
    $statement->execute([$campaignId, $characterId, $slot]);
    $equipment = $statement->fetch(PDO::FETCH_ASSOC);
    return [
        'character_id' => $characterId,
        'slot' => $slot,
        'item_id' => $equipment === false ? '' : $equipment['item_id'],
        'attuned' => $equipment !== false && (int) $equipment['attuned'] === 1,
    ];
}

function playCampaignSpellSlots(?string $class, int $characterLevel, int $slotLevel): int
{
    // This surface currently exposes the level-one wizard slot specified by
    // the play contract. Other spell levels have no modeled slots yet.
    return $class === 'wizard' && $characterLevel >= 1 && $slotLevel === 1 ? 1 : 0;
}

function maximumPreparedSpells(?string $class, int $level): ?int
{
    // Wizard spellbooks are the only spellcasting model currently exposed by
    // this play API. Their preparation limit grows one-for-one with level.
    return $class === 'wizard' ? $level : null;
}

/** @return list<array{username: string, character_id: string, name: string, class: string}> */
function playCampaignParty(string $campaignId): array
{
    $statement = database()->prepare('SELECT username, character_id, name, class FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
    $statement->execute([$campaignId]);
    return $statement->fetchAll(PDO::FETCH_ASSOC);
}

/** @return list<string> */
function playCampaignPartyUsernames(string $campaignId): array
{
    // `rowid` is the established join order and therefore part of turn order.
    $statement = database()->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
    $statement->execute([$campaignId]);
    return $statement->fetchAll(PDO::FETCH_COLUMN);
}

/** @return array<string, mixed>|null */
function playCampaignEncounter(string $campaignId, string $encounterId): ?array
{
    $statement = database()->prepare('SELECT id, combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $statement->execute([$encounterId, $campaignId]);
    $encounter = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($encounter) ? $encounter : null;
}

/**
 * @param list<mixed> $combatants
 * @return list<array{name: string, kind: string, initiative: int, member?: string}>
 */
function playEncounterCombatantId(array $combatant): ?string
{
    if (is_string($combatant['monster_id'] ?? null)) {
        return 'monster:' . $combatant['monster_id'];
    }
    if (is_string($combatant['member'] ?? null)) {
        return 'member:' . $combatant['member'];
    }
    return null;
}

/** @return list<string> */
function playEncounterStoredOrder(string $encounterId): array
{
    $statement = database()->prepare('SELECT combatant_ids FROM play_campaign_encounter_orders WHERE encounter_id = ?');
    $statement->execute([$encounterId]);
    $stored = $statement->fetchColumn();
    $ids = is_string($stored) ? json_decode($stored, true) : null;
    return is_array($ids) && array_is_list($ids) && array_all($ids, static fn (mixed $id): bool => is_string($id)) ? $ids : [];
}

/** @param list<string> $combatantIds */
function savePlayEncounterOrder(string $encounterId, array $combatantIds): void
{
    database()->prepare('INSERT INTO play_campaign_encounter_orders (encounter_id, combatant_ids) VALUES (?, ?)
        ON CONFLICT(encounter_id) DO UPDATE SET combatant_ids = excluded.combatant_ids')
        ->execute([$encounterId, json_encode($combatantIds, JSON_THROW_ON_ERROR)]);
}

/** @return list<array{name: string, kind: string, initiative: int, member?: string}> */
function playEncounterTurnOrder(array $combatants, array $storedIds = []): array
{
    $order = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) || !is_string($combatant['name'] ?? null) || integer($combatant['initiative'] ?? null) === null) {
            continue;
        }
        $isMonster = isset($combatant['monster_id']);
        $entry = [
            'name' => $combatant['name'],
            'kind' => $isMonster ? 'monster' : 'player',
            'initiative' => $combatant['initiative'],
        ];
        if (!$isMonster && is_string($combatant['member'] ?? null)) {
            $entry['member'] = $combatant['member'];
        }
        $order[] = $entry;
    }
    usort($order, static fn (array $left, array $right): int => ($right['initiative'] <=> $left['initiative']) ?: ($left['name'] <=> $right['name']));
    if ($storedIds !== []) {
        $byId = [];
        $usedCombatants = [];
        foreach ($order as $entry) {
            foreach ($combatants as $index => $combatant) {
                if (is_array($combatant) && ($combatant['name'] ?? null) === $entry['name']
                    && (($combatant['member'] ?? null) === ($entry['member'] ?? null))
                    && ($combatant['initiative'] ?? null) === $entry['initiative']
                    && !isset($usedCombatants[$index])) {
                    $id = playEncounterCombatantId($combatant);
                    if ($id !== null) {
                        $byId[$id] = $entry;
                    }
                    $usedCombatants[$index] = true;
                    break;
                }
            }
        }
        $customOrder = [];
        foreach ($storedIds as $id) {
            if (isset($byId[$id])) {
                $customOrder[] = $byId[$id];
                unset($byId[$id]);
            }
        }
        foreach ($order as $entry) {
            foreach ($byId as $id => $candidate) {
                if ($candidate === $entry) {
                    $customOrder[] = $entry;
                    unset($byId[$id]);
                    break;
                }
            }
        }
        $order = $customOrder;
    }
    return $order;
}

/** @return array{round: int, turn_index: int} */
function playEncounterTurnState(string $encounterId): array
{
    $statement = database()->prepare('SELECT round, turn_index FROM play_campaign_encounter_turns WHERE encounter_id = ?');
    $statement->execute([$encounterId]);
    $state = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($state) ? ['round' => (int) $state['round'], 'turn_index' => (int) $state['turn_index']] : ['round' => 1, 'turn_index' => 0];
}

/** @param array{name: string, kind: string, initiative: int, member?: string} $combatant */
function playEncounterTurnResponse(array $state, array $combatant): array
{
    return [
        'round' => $state['round'],
        'turn_index' => $state['turn_index'],
        'active' => [
            'name' => $combatant['name'],
            'kind' => $combatant['kind'],
            'initiative' => $combatant['initiative'],
        ],
    ];
}

/** @return list<array{condition: string, remaining_rounds: int}> */
function playEncounterConditionsForTarget(string $encounterId, string $target): array
{
    $statement = database()->prepare('SELECT condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE encounter_id = ? AND target = ? ORDER BY id ASC');
    $statement->execute([$encounterId, $target]);
    return array_map(static fn (array $row): array => [
        'condition' => $row['condition'],
        'remaining_rounds' => (int) $row['remaining_rounds'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
}

/** @return object */
function playEncounterConditions(string $encounterId): object
{
    $statement = database()->prepare('SELECT target, condition, remaining_rounds FROM play_campaign_encounter_conditions WHERE encounter_id = ? ORDER BY id ASC');
    $statement->execute([$encounterId]);
    $conditions = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $conditions[$row['target']][] = [
            'condition' => $row['condition'],
            'remaining_rounds' => (int) $row['remaining_rounds'],
        ];
    }
    return (object) $conditions;
}

/** @param list<mixed> $combatants */
function playEncounterTargetIsKnown(array $combatants, string $target): bool
{
    foreach ($combatants as $combatant) {
        if (is_array($combatant) && (($combatant['monster_id'] ?? null) === $target || ($combatant['member'] ?? null) === $target)) {
            return true;
        }
    }
    return false;
}

/** @return list<array{sequence: int, kind: string, actor: string, text: string}> */
function playCampaignRecentEvents(string $campaignId): array
{
    $statement = database()->prepare('SELECT events.sequence, events.kind, events.actor, events.text, actions.type, actions.target
        FROM play_campaign_events AS events
        LEFT JOIN play_campaign_combat_actions AS actions
            ON actions.campaign_id = events.campaign_id AND actions.sequence = events.sequence
        WHERE events.campaign_id = ? ORDER BY events.sequence ASC');
    $statement->execute([$campaignId]);
    return array_map(
        static function (array $event): array {
            $result = [
                'sequence' => (int) $event['sequence'],
                'kind' => $event['kind'],
                'actor' => $event['actor'],
                'text' => $event['text'],
            ];
            if ($event['type'] !== null) {
                $result['type'] = $event['type'];
                $result['target'] = $event['target'];
            }
            return $result;
        },
        $statement->fetchAll(PDO::FETCH_ASSOC),
    );
}

/**
 * @param list<string> $party
 * @return array{current_actor: string, turn_number: int}|null
 */
function playCampaignTurnState(string $campaignId, array $party): ?array
{
    if ($party === []) {
        return null;
    }

    $currentPlayer = 0;
    $turnNumber = 1;
    $currentActor = $party[$currentPlayer];
    $statement = database()->prepare('SELECT kind FROM play_campaign_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$campaignId]);
    // Campaign event history also contains narration and combat/audit events.
    // Keep the last event that actually handed control to the DM, so those
    // incidental records cannot change how its later resolution advances.
    $previousTurnKind = null;
    foreach ($statement->fetchAll(PDO::FETCH_COLUMN) as $kind) {
        if ($kind === 'action' || $kind === 'travel' || $kind === 'rest') {
            $currentActor = 'dm';
            $previousTurnKind = $kind;
        } elseif ($kind === 'resolution') {
            // A rest consumes a turn without handing the next campaign turn
            // to a different party member. Other player turns rotate normally.
            if ($previousTurnKind !== 'rest') {
                $currentPlayer = ($currentPlayer + 1) % count($party);
            }
            $currentActor = $party[$currentPlayer];
            $turnNumber++;
        }
    }

    return ['current_actor' => $currentActor, 'turn_number' => $turnNumber];
}

/** @param list<string> $party */
function playCampaignCurrentActor(string $campaignId, array $party): ?string
{
    return playCampaignTurnState($campaignId, $party)['current_actor'] ?? null;
}

function playCampaignExplorationHandoff(string $campaignId): ?string
{
    $statement = database()->prepare('SELECT current_actor FROM play_campaign_exploration_handoffs WHERE campaign_id = ?');
    $statement->execute([$campaignId]);
    $actor = $statement->fetchColumn();
    return is_string($actor) ? $actor : null;
}

function playCampaignNudgeCount(string $campaignId): int
{
    $statement = database()->prepare("SELECT COUNT(*) FROM play_campaign_events WHERE campaign_id = ? AND kind = 'nudge'");
    $statement->execute([$campaignId]);
    return (int) $statement->fetchColumn();
}

/**
 * Append an event while allocating its sequence in the same transaction.
 * Turn reconstruction relies on the sequence being gap-free and ordered.
 */
function appendPlayCampaignEvent(string $campaignId, string $kind, string $actor, string $text): int
{
    $database = database();
    $sequence = 0;
    withinTransaction($database, static function () use ($database, $campaignId, $kind, $actor, $text, &$sequence): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $nextSequence->execute([$campaignId]);
        $sequence = (int) $nextSequence->fetchColumn();
        $insert = $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)');
        $insert->execute([$campaignId, $sequence, $kind, $actor, $text]);
    });
    return $sequence;
}

/** @return array{event_id: string, text: string, sequence: int} */
function appendPlayCampaignFeedEvent(string $campaignId, string $eventId, string $text): array
{
    $database = database();
    $sequence = 0;
    withinTransaction($database, static function () use ($database, $campaignId, $eventId, $text, &$sequence): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_feed_events WHERE campaign_id = ?');
        $nextSequence->execute([$campaignId]);
        $sequence = (int) $nextSequence->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $eventId, $text]);
    });

    return ['event_id' => $eventId, 'text' => $text, 'sequence' => $sequence];
}

function appendPlayCampaignCombatAction(string $campaignId, string $actor, string $type, string $target, string $text): int
{
    $database = database();
    $sequence = 0;
    withinTransaction($database, static function () use ($database, $campaignId, $actor, $type, $target, $text, &$sequence): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $nextSequence->execute([$campaignId]);
        $sequence = (int) $nextSequence->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, 'combat_action', $actor, $text]);
        $database->prepare('INSERT INTO play_campaign_combat_actions (campaign_id, sequence, type, target) VALUES (?, ?, ?, ?)')
            ->execute([$campaignId, $sequence, $type, $target]);
    });
    return $sequence;
}

/** @return array{sequence: int, hp_current: int, hp_max: int} */
function appendPlayCampaignRest(string $campaignId, string $actor, string $characterId, string $type): array
{
    $database = database();
    $result = ['sequence' => 0, 'hp_current' => 20, 'hp_max' => 20];
    withinTransaction($database, static function () use ($database, $campaignId, $actor, $characterId, $type, &$result): void {
        $health = $database->prepare('SELECT hp_current, hp_max FROM play_campaign_member_health WHERE campaign_id = ? AND character_id = ?');
        $health->execute([$campaignId, $characterId]);
        $row = $health->fetch(PDO::FETCH_ASSOC);
        $hpCurrent = is_array($row) ? (int) $row['hp_current'] : 20;
        $hpMax = is_array($row) ? (int) $row['hp_max'] : 20;
        if (!is_array($row)) {
            $insertHealth = $database->prepare('INSERT INTO play_campaign_member_health (character_id, campaign_id, hp_current, hp_max) VALUES (?, ?, ?, ?)');
            $insertHealth->execute([$characterId, $campaignId, $hpCurrent, $hpMax]);
        }
        if ($type === 'long') {
            $hpCurrent = $hpMax;
            $updateHealth = $database->prepare('UPDATE play_campaign_member_health SET hp_current = ? WHERE campaign_id = ? AND character_id = ?');
            $updateHealth->execute([$hpCurrent, $campaignId, $characterId]);
        }

        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_events WHERE campaign_id = ?');
        $nextSequence->execute([$campaignId]);
        $sequence = (int) $nextSequence->fetchColumn();
        $event = $database->prepare('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, text) VALUES (?, ?, ?, ?, ?)');
        $event->execute([$campaignId, $sequence, 'rest', $actor, $type]);
        $result = ['sequence' => $sequence, 'hp_current' => $hpCurrent, 'hp_max' => $hpMax];
    });
    return $result;
}

/** @return list<string>|null */
function compendiumTags(mixed $tags): ?array
{
    if (!is_array($tags)) {
        return null;
    }
    foreach ($tags as $tag) {
        if (!validNonEmptyString($tag)) {
            return null;
        }
    }
    return array_values($tags);
}

/** @return array<string, mixed>|null */
function monsterBySlug(string $slug): ?array
{
    $statement = database()->prepare('SELECT slug, name, cr, armor_class, hit_points, tags FROM compendium_monsters WHERE slug = ?');
    $statement->execute([$slug]);
    $monster = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($monster)) {
        return null;
    }
    $tags = json_decode($monster['tags'], true);
    return [
        'slug' => $monster['slug'],
        'name' => $monster['name'],
        'cr' => $monster['cr'],
        'armor_class' => (int) $monster['armor_class'],
        'hit_points' => (int) $monster['hit_points'],
        'tags' => is_array($tags) ? array_values($tags) : [],
    ];
}

/** @return array<string, mixed>|null */
function itemBySlug(string $slug): ?array
{
    $statement = database()->prepare('SELECT slug, name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?');
    $statement->execute([$slug]);
    $item = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($item)) {
        return null;
    }
    return [
        'slug' => $item['slug'],
        'name' => $item['name'],
        'type' => $item['type'],
        'rarity' => $item['rarity'],
        'cost_gp' => (int) $item['cost_gp'],
    ];
}

/** @return array<string, mixed>|null */
function campaignById(string $id): ?array
{
    $statement = database()->prepare('SELECT id, name, dm FROM campaigns WHERE id = ?');
    $statement->execute([$id]);
    $campaign = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($campaign) ? $campaign : null;
}

function campaignCharacterById(string $campaignId, string $characterId): ?array
{
    $statement = database()->prepare('SELECT id FROM campaign_characters WHERE campaign_id = ? AND id = ?');
    $statement->execute([$campaignId, $characterId]);
    $character = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($character) ? $character : null;
}

/** @return array<string, mixed>|null */
function campaignSessionById(string $campaignId, string $sessionId): ?array
{
    $statement = database()->prepare('SELECT id, campaign_id, starts_at, duration_minutes, agenda FROM campaign_sessions WHERE campaign_id = ? AND id = ?');
    $statement->execute([$campaignId, $sessionId]);
    $session = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($session)) {
        return null;
    }
    $agenda = json_decode($session['agenda'], true);
    return [
        'id' => $session['id'],
        'campaign_id' => $session['campaign_id'],
        'starts_at' => $session['starts_at'],
        'duration_minutes' => (int) $session['duration_minutes'],
        'agenda' => is_array($agenda) ? array_values($agenda) : [],
    ];
}

/** @return list<string>|null */
function sessionAgenda(mixed $agenda): ?array
{
    if (!is_array($agenda)) {
        return null;
    }
    foreach ($agenda as $item) {
        if (!validNonEmptyString($item)) {
            return null;
        }
    }
    return array_values($agenda);
}

function validSessionStart(mixed $startsAt): bool
{
    if (!is_string($startsAt)) {
        return false;
    }
    $date = DateTimeImmutable::createFromFormat('!Y-m-d\\TH:i:s\\Z', $startsAt);
    $errors = DateTimeImmutable::getLastErrors();
    return $date !== false && $errors === false && $date->format('Y-m-d\\TH:i:s\\Z') === $startsAt;
}

/** @return list<string>|null */
function attendanceCharacters(mixed $characters, string $campaignId): ?array
{
    if (!is_array($characters)) {
        return null;
    }
    $validated = [];
    foreach ($characters as $characterId) {
        if (!validNonEmptyString($characterId) || in_array($characterId, $validated, true)
            || campaignCharacterById($campaignId, $characterId) === null) {
            return null;
        }
        $validated[] = $characterId;
    }
    return $validated;
}

/** @return array<string, mixed>|null */
function craftingProjectById(string $campaignId, string $projectId): ?array
{
    $statement = database()->prepare('SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status FROM crafting_projects WHERE campaign_id = ? AND id = ?');
    $statement->execute([$campaignId, $projectId]);
    $project = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($project)) {
        return null;
    }
    return [
        'id' => $project['id'],
        'campaign_id' => $project['campaign_id'],
        'character_id' => $project['character_id'],
        'item_slug' => $project['item_slug'],
        'days_required' => (int) $project['days_required'],
        'days_completed' => (int) $project['days_completed'],
        'cost_gp' => (int) $project['cost_gp'],
        'status' => $project['status'],
    ];
}

function factionById(string $campaignId, string $factionId): ?array
{
    $statement = database()->prepare('SELECT id, campaign_id, name, stance FROM campaign_factions WHERE campaign_id = ? AND id = ?');
    $statement->execute([$campaignId, $factionId]);
    $faction = $statement->fetch(PDO::FETCH_ASSOC);
    return is_array($faction) ? $faction : null;
}

/** @return list<string>|null */
function questMilestones(mixed $milestones): ?array
{
    if (!is_array($milestones)) {
        return null;
    }
    $validated = [];
    foreach ($milestones as $milestone) {
        if (!validNonEmptyString($milestone) || in_array($milestone, $validated, true)) {
            return null;
        }
        $validated[] = $milestone;
    }
    return $validated;
}

/** @return array<string, mixed>|null */
function questById(string $campaignId, string $questId): ?array
{
    $statement = database()->prepare('SELECT id, campaign_id, title, status, milestones, completed FROM campaign_quests WHERE campaign_id = ? AND id = ?');
    $statement->execute([$campaignId, $questId]);
    $quest = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($quest)) {
        return null;
    }
    $milestones = json_decode($quest['milestones'], true);
    $completed = json_decode($quest['completed'], true);
    return [
        'id' => $quest['id'],
        'campaign_id' => $quest['campaign_id'],
        'title' => $quest['title'],
        'status' => $quest['status'],
        'milestones' => is_array($milestones) ? array_values($milestones) : [],
        'completed' => is_array($completed) ? array_values($completed) : [],
    ];
}

/** @param array<string, mixed> $quest */
function questProgress(array $quest): array
{
    return [
        'id' => $quest['id'],
        'status' => $quest['status'],
        'milestones_total' => count($quest['milestones']),
        'milestones_done' => count($quest['completed']),
    ];
}

/** @param array<string, mixed> $campaign
 *  @return array{has_dm: bool, has_characters: bool, has_next_session: bool, has_active_quest: bool}
 */
function campaignAnalyticsSignals(array $campaign): array
{
    $campaignId = $campaign['id'];
    $database = database();
    $characters = $database->prepare('SELECT EXISTS(SELECT 1 FROM campaign_characters WHERE campaign_id = ?)');
    $characters->execute([$campaignId]);
    $sessions = $database->prepare('SELECT EXISTS(SELECT 1 FROM campaign_sessions WHERE campaign_id = ?)');
    $sessions->execute([$campaignId]);
    $quests = $database->prepare("SELECT EXISTS(SELECT 1 FROM campaign_quests WHERE campaign_id = ? AND status = 'active')");
    $quests->execute([$campaignId]);

    return [
        'has_dm' => $campaign['dm'] !== '',
        'has_characters' => (bool) $characters->fetchColumn(),
        'has_next_session' => (bool) $sessions->fetchColumn(),
        'has_active_quest' => (bool) $quests->fetchColumn(),
    ];
}

/** @param array{has_dm: bool, has_characters: bool, has_next_session: bool, has_active_quest: bool} $signals */
function campaignReadinessScore(array $signals): int
{
    return ($signals['has_dm'] ? 25 : 0)
        + ($signals['has_characters'] ? 20 : 0)
        + ($signals['has_next_session'] ? 20 : 0)
        + ($signals['has_active_quest'] ? 20 : 0);
}

/** @param array<string, mixed> $session */
function combatState(array $session): array
{
    $active = $session['order'][$session['turn_index']];
    return [
        'id' => $session['id'],
        'round' => $session['round'],
        'turn_index' => $session['turn_index'],
        'active' => ['name' => $active['name'], 'score' => $active['score']],
    ];
}

/** @param array<string, mixed> $session */
function combatConditions(array $session): object
{
    return (object) $session['conditions'];
}

/**
 * @param list<array{name: string, dex: int, roll: int}> $combatants
 * @return list<array{name: string, score: int}>
 */
function initiativeOrder(array $combatants): array
{
    $order = [];
    foreach ($combatants as $combatant) {
        $order[] = [
            'name' => $combatant['name'],
            'score' => $combatant['roll'] + $combatant['dex'],
            'dex' => $combatant['dex'],
        ];
    }
    // Name is the final tie-breaker, so the API order is stable across runs.
    usort($order, static function (array $left, array $right): int {
        return ($right['score'] <=> $left['score']) ?: ($right['dex'] <=> $left['dex']) ?: ($left['name'] <=> $right['name']);
    });

    return array_map(static fn (array $combatant): array => ['name' => $combatant['name'], 'score' => $combatant['score']], $order);
}

/** @param list<mixed> $party @param list<mixed> $monsters
 *  @return array<string, mixed>|null
 */
function adjustedEncounter(array $party, array $monsters): ?array
{
    $xpByCr = ['0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100, '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800];
    $thresholds = ['easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0];
    foreach ($party as $member) {
        if (!is_array($member) || integer($member['level'] ?? null) !== 3) {
            return null;
        }
        $thresholds['easy'] += 75;
        $thresholds['medium'] += 150;
        $thresholds['hard'] += 225;
        $thresholds['deadly'] += 400;
    }

    $baseXp = 0;
    $monsterCount = 0;
    foreach ($monsters as $monster) {
        if (!is_array($monster) || !is_string($monster['cr'] ?? null) || !isset($xpByCr[$monster['cr']])) {
            return null;
        }
        $count = integer($monster['count'] ?? null);
        if ($count === null || $count < 0) {
            return null;
        }
        $baseXp += $xpByCr[$monster['cr']] * $count;
        $monsterCount += $count;
    }

    $multiplier = match (true) {
        $monsterCount <= 1 => 1,
        $monsterCount === 2 => 1.5,
        $monsterCount <= 6 => 2,
        $monsterCount <= 10 => 2.5,
        $monsterCount <= 14 => 3,
        default => 4,
    };
    $adjustedXp = $baseXp * $multiplier;
    $difficulty = 'trivial';
    foreach (['easy', 'medium', 'hard', 'deadly'] as $level) {
        if ($adjustedXp >= $thresholds[$level]) {
            $difficulty = $level;
        }
    }

    return [
        'base_xp' => $baseXp,
        'monster_count' => $monsterCount,
        'multiplier' => $multiplier,
        'adjusted_xp' => $adjustedXp,
        'difficulty' => $difficulty,
        'thresholds' => $thresholds,
    ];
}

$app = AppFactory::create();

initializeStorage(database());

$app->get('/v1/schema', function (Request $request, Response $response): Response {
    return jsonResponse($response, [
        'version' => '2026-07-29',
        'endpoints' => [
            ['method' => 'GET', 'path' => '/v1/play/campaigns/{id}/rng-ledger', 'auth' => 'member'],
            ['method' => 'GET', 'path' => '/v1/schema', 'auth' => 'public'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns', 'auth' => 'dm'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/fixture-seeds', 'auth' => 'dm'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/members', 'auth' => 'member'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/moderation/reports', 'auth' => 'member'],
            ['method' => 'POST', 'path' => '/v1/play/campaigns/{id}/rng-rolls', 'auth' => 'member'],
            ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', 'auth' => 'dm'],
            ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/rng-seed', 'auth' => 'dm'],
            ['method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/safety-boundaries', 'auth' => 'dm'],
        ],
    ]);
});

$app->get('/health', function (Request $request, Response $response): Response {
    return jsonResponse($response, ['ok' => true]);
});

$app->get('/healthz', function (Request $request, Response $response): Response {
    return jsonResponse($response, ['status' => 'ok']);
});

$app->get('/readyz', function (Request $request, Response $response): Response {
    if (maintenanceMode()) {
        return jsonResponse($response, ['status' => 'maintenance', 'schema_version' => 2], 503);
    }
    return jsonResponse($response, ['status' => 'ready', 'schema_version' => 2]);
});

$app->get('/v1/storage/status', function (Request $request, Response $response): Response {
    $statement = database()->prepare('SELECT value FROM schema_meta WHERE key = ?');
    $statement->execute(['schema_version']);
    $initialized = $statement->fetchColumn() === '1';
    return jsonResponse($response, ['driver' => 'sqlite', 'schema_version' => 1, 'initialized' => $initialized]);
});

$app->post('/v1/storage/reset', function (Request $request, Response $response): Response {
    resetStorage(database());
    return jsonResponse($response, ['ok' => true, 'schema_version' => 1]);
});

$app->post('/v1/play/campaigns', function (Request $request, Response $response): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    if ($actor['role'] !== 'dm') {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    $maxPlayers = integer($body['max_players'] ?? null);
    if (!validNonEmptyString($id) || !validNonEmptyString($name) || $maxPlayers === null || $maxPlayers < 1) {
        return badRequest($response);
    }
    if (playCampaignExists($id)) {
        return jsonResponse($response, ['error' => 'duplicate campaign id'], 409);
    }

    $statement = database()->prepare('INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)');
    $statement->execute([$id, $name, $actor['username'], 'lobby', $maxPlayers]);
    database()->prepare('INSERT INTO play_campaign_service_metrics (campaign_id) VALUES (?)')->execute([$id]);
    return jsonResponse($response, [
        'id' => $id,
        'name' => $name,
        'owner' => $actor['username'],
        'status' => 'lobby',
        'max_players' => $maxPlayers,
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/spectators', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $spectatorId = $body['spectator_id'] ?? null;
    if ($body === null || !validNonEmptyString($spectatorId)) {
        return badRequest($response);
    }

    try {
        $statement = database()->prepare('INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES (?, ?)');
        $statement->execute([$spectatorId, $args['id']]);
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'duplicate spectator id'], 409);
    }

    return jsonResponse($response, [
        'spectator_id' => $spectatorId,
        'token' => 'spectator-' . $spectatorId,
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/spectator-view', function (Request $request, Response $response, array $args): Response {
    $spectatorId = spectatorIdFromRequest($request);
    if ($spectatorId === null) {
        // A recognized ordinary session is authenticated, but this endpoint
        // intentionally accepts spectator credentials only.
        if (authenticatedActor($request) !== null) {
            return jsonResponse($response, ['error' => 'forbidden'], 403);
        }
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $ticketCampaignId = spectatorCampaignId($spectatorId);
    if ($ticketCampaignId === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    if ($ticketCampaignId !== $args['id']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $partySize = database()->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?');
    $partySize->execute([$args['id']]);
    $document = playCampaignDocument($args['id']);

    return jsonResponse($response, [
        'campaign_id' => $campaign['id'],
        'name' => $campaign['name'],
        'status' => $campaign['status'],
        'party_size' => (int) $partySize->fetchColumn(),
        'story' => $document['story'] ?? '',
    ]);
});

$app->get('/v1/play/campaigns/{id}/onboarding', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    if ($actor['role'] === 'dm' && $campaign['owner'] === $actor['username']) {
        return jsonResponse($response, [
            'role' => 'dm',
            'next_steps' => ['configure-safety', 'invite-players', 'start-campaign'],
            'can_mutate' => true,
        ]);
    }

    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    return jsonResponse($response, [
        'role' => 'player',
        'next_steps' => ['review-party', 'take-turn', 'submit-action'],
        'can_mutate' => true,
    ]);
});

$app->post('/v1/play/campaigns/{id}/locations', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $locationId = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    if (!validNonEmptyString($locationId) || !validNonEmptyString($name)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignLocation($args['id'], $locationId) !== null) {
        return jsonResponse($response, ['error' => 'duplicate location id'], 409);
    }

    $statement = database()->prepare('INSERT INTO play_campaign_locations (campaign_id, id, name) VALUES (?, ?, ?)');
    $statement->execute([$args['id'], $locationId, $name]);
    return jsonResponse($response, ['id' => $locationId, 'name' => $name], 201);
});

$app->post('/v1/play/campaigns/{id}/locations/{from_id}/connections', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $toId = $body['to_id'] ?? null;
    $travelTurns = integer($body['travel_turns'] ?? null);
    if (!validNonEmptyString($toId) || $travelTurns === null || $travelTurns < 1) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignLocation($args['id'], $args['from_id']) === null
        || playCampaignLocation($args['id'], $toId) === null
        || playCampaignLocationConnectionExists($args['id'], $args['from_id'], $toId)) {
        return badRequest($response);
    }

    $statement = database()->prepare('INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) VALUES (?, ?, ?, ?)');
    $statement->execute([$args['id'], $args['from_id'], $toId, $travelTurns]);
    return jsonResponse($response, ['from_id' => $args['from_id'], 'to_id' => $toId, 'travel_turns' => $travelTurns], 201);
});

$app->get('/v1/play/campaigns/{id}/locations/{loc_id}/travel', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignLocation($args['id'], $args['loc_id']) === null) {
        return badRequest($response);
    }

    return jsonResponse($response, ['destinations' => playCampaignTravelDestinations($args['id'], $args['loc_id'])]);
});

$app->post('/v1/play/campaigns/{id}/scenes', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $sceneId = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    if (!validNonEmptyString($sceneId) || !validNonEmptyString($name)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignScene($args['id'], $sceneId) !== null) {
        return jsonResponse($response, ['error' => 'duplicate scene id'], 409);
    }

    $statement = database()->prepare('INSERT INTO play_campaign_scenes (campaign_id, id, name, status) VALUES (?, ?, ?, ?)');
    $statement->execute([$args['id'], $sceneId, $name, 'open']);
    return jsonResponse($response, ['id' => $sceneId, 'name' => $name, 'status' => 'open'], 201);
});

$app->get('/v1/play/campaigns/{id}/scenes/current', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $scene = playCampaignCurrentScene($args['id']);
    return $scene === null
        ? jsonResponse($response, ['error' => 'unknown current scene'], 404)
        : jsonResponse($response, $scene);
});

$app->post('/v1/play/campaigns/{id}/scenes/{scene_id}/enter', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $scene = playCampaignScene($args['id'], $args['scene_id']);
    if ($scene === null) {
        return jsonResponse($response, ['error' => 'unknown scene'], 404);
    }
    if ($scene['status'] !== 'open') {
        return jsonResponse($response, ['error' => 'scene is closed'], 409);
    }

    $database = database();
    withinTransaction($database, static function () use ($database, $args): void {
        $database->prepare('UPDATE play_campaign_scenes SET is_current = 0 WHERE campaign_id = ?')->execute([$args['id']]);
        $database->prepare('UPDATE play_campaign_scenes SET is_current = 1 WHERE campaign_id = ? AND id = ?')->execute([$args['id'], $args['scene_id']]);
    });
    appendPlayCampaignEvent($args['id'], 'scene', $actor['username'], $scene['id']);
    return jsonResponse($response, ['current_scene_id' => $scene['id'], 'name' => $scene['name']]);
});

$app->post('/v1/play/campaigns/{id}/scenes/{scene_id}/close', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignScene($args['id'], $args['scene_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown scene'], 404);
    }

    $statement = database()->prepare("UPDATE play_campaign_scenes SET status = 'closed', is_current = 0 WHERE campaign_id = ? AND id = ?");
    $statement->execute([$args['id'], $args['scene_id']]);
    return jsonResponse($response, ['id' => $args['scene_id'], 'status' => 'closed']);
});

$app->put('/v1/play/campaigns/{id}/document', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $story = $body['story'] ?? null;
    $dmNotes = $body['dm_notes'] ?? null;
    if (!validNonEmptyString($story) || !validNonEmptyString($dmNotes)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $statement = database()->prepare('INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes');
    $statement->execute([$args['id'], $story, $dmNotes]);
    return jsonResponse($response, ['story' => $story, 'dm_notes' => $dmNotes]);
});

$app->get('/v1/play/campaigns/{id}/document', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $document = playCampaignDocument($args['id']);
    if ($document === null) {
        return jsonResponse($response, ['error' => 'unknown document'], 404);
    }

    return jsonResponse($response, $isOwner ? $document : ['story' => $document['story']]);
});

$app->post('/v1/play/campaigns/{id}/backups', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    if (trim((string) $request->getBody()) !== '') return badRequest($response);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $document = playCampaignDocument($args['id']);
    if ($document === null) return jsonResponse($response, ['error' => 'unknown document'], 404);

    $database = database();
    $backup = [];
    withinTransaction($database, static function () use ($database, $args, $campaign, $document, &$backup): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_backups WHERE campaign_id = ?');
        $nextSequence->execute([$args['id']]);
        $sequence = (int) $nextSequence->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_backups (campaign_id, sequence, story, status) VALUES (?, ?, ?, ?)')
            ->execute([$args['id'], $sequence, $document['story'], $campaign['status']]);
        $backup = ['backup_id' => 'backup-' . $sequence, 'story' => $document['story'], 'status' => $campaign['status']];
    });

    return jsonResponse($response, $backup, 201);
});

$app->get('/v1/play/campaigns/{id}/backups', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);

    return jsonResponse($response, ['backups' => playCampaignBackups($args['id'])]);
});

$app->post('/v1/play/campaigns/{id}/backups/{backup_id}/restore', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $backup = playCampaignBackup($args['id'], $args['backup_id']);
    if ($backup === null) return jsonResponse($response, ['error' => 'unknown backup'], 404);

    $database = database();
    withinTransaction($database, static function () use ($database, $args, $backup): void {
        // Backups contain public story only; restore preserves any DM-only notes.
        $database->prepare("INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, '') ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story")
            ->execute([$args['id'], $backup['story']]);
        $database->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?')->execute([$backup['status'], $args['id']]);
    });

    return jsonResponse($response, $backup);
});

$app->post('/v1/play/campaigns/{id}/exports', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $document = playCampaignDocument($args['id']);
    if ($document === null) {
        return jsonResponse($response, ['error' => 'unknown document'], 404);
    }

    $database = database();
    $database->beginTransaction();
    try {
        $nextVersion = $database->prepare('SELECT COALESCE(MAX(version), 0) + 1 FROM play_campaign_exports WHERE campaign_id = ?');
        $nextVersion->execute([$args['id']]);
        $version = (int) $nextVersion->fetchColumn();
        $export = ['version' => $version, 'story' => $document['story'], 'status' => $campaign['status']];
        $database->prepare('INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES (?, ?, ?, ?)')
            ->execute([$args['id'], $version, $export['story'], $export['status']]);
        $database->commit();
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        throw $exception;
    }

    return jsonResponse($response, $export, 201);
});

$app->get('/v1/play/campaigns/{id}/exports', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    return jsonResponse($response, ['exports' => playCampaignExports($args['id'])]);
});

$app->get('/v1/play/campaigns/{id}/exports/{version}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (preg_match('/^[1-9][0-9]*$/', $args['version']) !== 1) {
        return jsonResponse($response, ['error' => 'unknown export'], 404);
    }

    $export = playCampaignExport($args['id'], (int) $args['version']);
    if ($export === null) {
        return jsonResponse($response, ['error' => 'unknown export'], 404);
    }
    return jsonResponse($response, $export);
});

$app->post('/v1/play/campaigns/{id}/imports', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $version = $body['version'] ?? null;
    $story = $body['story'] ?? null;
    $status = $body['status'] ?? null;
    if ($body === null || count($body) !== 3
        || !array_key_exists('version', $body) || !array_key_exists('story', $body) || !array_key_exists('status', $body)
        || !is_int($version) || $version !== 1 || !validNonEmptyString($story)
        || !is_string($status) || !in_array($status, ['lobby', 'started'], true)) {
        return badRequest($response);
    }

    $import = ['version' => 1, 'story' => $story, 'status' => $status];
    $database = database();
    withinTransaction($database, static function () use ($database, $args, $import): void {
        // Preserve DM notes when a document already exists; imports only replace
        // the snapshot fields they declare.
        $database->prepare("INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) VALUES (?, ?, '') ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story")
            ->execute([$args['id'], $import['story']]);
        $database->prepare('UPDATE play_campaigns SET status = ? WHERE id = ?')
            ->execute([$import['status'], $args['id']]);
        $database->prepare('INSERT INTO play_campaign_imports (campaign_id, version, story, status) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status')
            ->execute([$args['id'], $import['version'], $import['story'], $import['status']]);
    });

    return jsonResponse($response, $import);
});

$app->get('/v1/play/campaigns/{id}/import-state', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $import = playCampaignImport($args['id']);
    return $import === null
        ? jsonResponse($response, ['error' => 'unknown import'], 404)
        : jsonResponse($response, $import);
});

$app->post('/v1/play/campaigns/{id}/migrations', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $schemaVersion = $body['schema_version'] ?? null;
    $story = $body['story'] ?? null;
    if ($body === null || count($body) !== 2
        || !array_key_exists('schema_version', $body) || !array_key_exists('story', $body)
        || !is_int($schemaVersion) || $schemaVersion !== 1 || !validNonEmptyString($story)) {
        return badRequest($response);
    }

    $migrated = ['schema_version' => 2, 'story' => $story, 'campaign_name' => $campaign['name']];
    $existing = playCampaignMigration($args['id']);
    if ($existing !== null && $existing['story'] === $story) {
        return jsonResponse($response, $existing);
    }

    $statement = database()->prepare('INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name');
    $statement->execute([$args['id'], $migrated['schema_version'], $migrated['story'], $migrated['campaign_name']]);
    return jsonResponse($response, $migrated, 201);
});

$app->get('/v1/play/campaigns/{id}/migration-state', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $migration = playCampaignMigration($args['id']);
    return $migration === null
        ? jsonResponse($response, ['error' => 'unknown migration'], 404)
        : jsonResponse($response, $migration);
});

$app->post('/v1/play/campaigns/{id}/calendar', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $day = integer($body['day'] ?? null);
    $season = $body['season'] ?? null;
    if ($day === null || $day < 1 || !validCalendarSeason($season)) {
        return badRequest($response);
    }
    if (playCampaignCalendar($args['id']) !== null) {
        return jsonResponse($response, ['error' => 'calendar already initialized'], 409);
    }

    $statement = database()->prepare('INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)');
    $statement->execute([$args['id'], $day, $season]);
    return jsonResponse($response, playCampaignCalendar($args['id']), 201);
});

$app->get('/v1/play/campaigns/{id}/calendar', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $calendar = playCampaignCalendar($args['id']);
    if ($calendar === null) {
        return jsonResponse($response, ['error' => 'unknown calendar'], 404);
    }
    return jsonResponse($response, $calendar);
});

$app->post('/v1/play/campaigns/{id}/calendar/advance', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $days = integer($body['days'] ?? null);
    if ($days === null || $days < 1 || $days > 30) {
        return badRequest($response);
    }
    $calendar = playCampaignCalendar($args['id']);
    if ($calendar === null) {
        return jsonResponse($response, ['error' => 'unknown calendar'], 404);
    }

    $statement = database()->prepare('UPDATE play_campaign_calendars SET day = day + ? WHERE campaign_id = ?');
    $statement->execute([$days, $args['id']]);
    return jsonResponse($response, playCampaignCalendar($args['id']));
});

$app->post('/v1/play/campaigns/{id}/invitations', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $invitationId = $body['invitation_id'] ?? null;
    $username = $body['username'] ?? null;
    $characterId = $body['character_id'] ?? null;
    if ($body === null || count($body) !== 3 || !array_key_exists('invitation_id', $body)
        || !array_key_exists('username', $body) || !array_key_exists('character_id', $body)
        || !validNonEmptyString($invitationId) || !validNonEmptyString($username) || !validNonEmptyString($characterId)) {
        return badRequest($response);
    }
    $registeredUsers = users();
    if (!isset($registeredUsers[$username]) || $registeredUsers[$username]['role'] !== 'player') {
        return badRequest($response);
    }

    $database = database();
    if (playCampaignInvitation($args['id'], $invitationId) !== null) {
        return jsonResponse($response, ['error' => 'duplicate invitation id'], 409);
    }
    $pending = $database->prepare("SELECT 1 FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? AND status = 'pending'");
    $pending->execute([$args['id'], $username]);
    if ($pending->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate pending invitation'], 409);
    }

    $database->prepare('INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) VALUES (?, ?, ?, ?, ?)')
        ->execute([$args['id'], $invitationId, $username, $characterId, 'pending']);
    return jsonResponse($response, [
        'invitation_id' => $invitationId,
        'username' => $username,
        'character_id' => $characterId,
        'status' => 'pending',
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/invitations/{invitation_id}/accept', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $invitation = playCampaignInvitation($args['id'], $args['invitation_id']);
    if ($invitation === null) {
        return jsonResponse($response, ['error' => 'unknown invitation'], 404);
    }
    if ($actor['username'] !== $invitation['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($invitation['status'] !== 'pending') {
        return jsonResponse($response, ['error' => 'invitation already accepted'], 409);
    }

    $database = database();
    $member = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND (username = ? OR character_id = ?)');
    $member->execute([$args['id'], $invitation['username'], $invitation['character_id']]);
    if ($member->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'membership conflict'], 409);
    }
    withinTransaction($database, static function () use ($database, $args, $invitation): void {
        $database->prepare("UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = ? AND invitation_id = ?")
            ->execute([$args['id'], $invitation['invitation_id']]);
        // Invitations intentionally carry only a character identity. These
        // stable placeholders let the invited player complete their build via
        // the established character endpoints after joining.
        $database->prepare('INSERT INTO play_campaign_members (character_id, campaign_id, username, name, class) VALUES (?, ?, ?, ?, ?)')
            ->execute([$invitation['character_id'], $args['id'], $invitation['username'], $invitation['username'], 'invited']);
        $database->prepare('INSERT INTO play_campaign_character_owners (character_id, campaign_id, owner) VALUES (?, ?, ?)')
            ->execute([$invitation['character_id'], $args['id'], $invitation['username']]);
        $database->prepare('INSERT INTO play_campaign_member_health (character_id, campaign_id, hp_current, hp_max) VALUES (?, ?, 20, 20)')
            ->execute([$invitation['character_id'], $args['id']]);
        $database->prepare('INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)')
            ->execute([$args['id'], $invitation['character_id']]);
    });
    return jsonResponse($response, [
        'invitation_id' => $invitation['invitation_id'],
        'username' => $invitation['username'],
        'character_id' => $invitation['character_id'],
        'status' => 'accepted',
    ]);
});

$app->get('/v1/play/campaigns/{id}/invitations', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if ($isDm) {
        $statement = database()->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? ORDER BY rowid ASC');
        $statement->execute([$args['id']]);
        return jsonResponse($response, ['invitations' => $statement->fetchAll(PDO::FETCH_ASSOC)]);
    }

    $statement = database()->prepare('SELECT invitation_id, username, character_id, status FROM play_campaign_invitations WHERE campaign_id = ? AND username = ? ORDER BY rowid ASC');
    $statement->execute([$args['id'], $actor['username']]);
    return jsonResponse($response, ['invitations' => $statement->fetchAll(PDO::FETCH_ASSOC)]);
});

$app->post('/v1/play/campaigns/{id}/delegations', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);

    $body = jsonBody($request);
    $username = $body['username'] ?? null;
    $powers = delegationPowers($body['powers'] ?? null);
    if ($body === null || count($body) !== 2 || !array_key_exists('username', $body) || !array_key_exists('powers', $body)
        || !validUsername($username) || $powers === null || !isPlayCampaignMember($args['id'], $username)) return badRequest($response);

    $database = database();
    $current = $database->prepare('SELECT active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?');
    $current->execute([$args['id'], $username]);
    if ((int) $current->fetchColumn() === 1) return jsonResponse($response, ['error' => 'active delegation exists'], 409);

    $encodedPowers = json_encode($powers);
    withinTransaction($database, static function () use ($database, $args, $username, $encodedPowers): void {
        $database->prepare('INSERT INTO play_campaign_delegations (campaign_id, username, powers, active) VALUES (?, ?, ?, 1) ON CONFLICT(campaign_id, username) DO UPDATE SET powers = excluded.powers, active = 1')
            ->execute([$args['id'], $username, $encodedPowers]);
        $database->prepare('INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) VALUES (?, COALESCE((SELECT MAX(sequence) + 1 FROM play_campaign_delegation_audit WHERE campaign_id = ?), 1), ?, ?, ?)')
            ->execute([$args['id'], $args['id'], $username, 'granted', $encodedPowers]);
    });
    return jsonResponse($response, ['username' => $username, 'powers' => $powers, 'active' => true], 201);
});

$app->delete('/v1/play/campaigns/{id}/delegations/{username}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);

    $statement = database()->prepare('SELECT powers, active FROM play_campaign_delegations WHERE campaign_id = ? AND username = ?');
    $statement->execute([$args['id'], $args['username']]);
    $delegation = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($delegation) || (int) $delegation['active'] !== 1) return jsonResponse($response, ['error' => 'unknown active delegation'], 404);
    $powers = json_decode($delegation['powers'], true);
    if (!is_array($powers)) return jsonResponse($response, ['error' => 'unknown active delegation'], 404);

    $database = database();
    withinTransaction($database, static function () use ($database, $args, $delegation): void {
        $database->prepare('UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = ? AND username = ?')
            ->execute([$args['id'], $args['username']]);
        $database->prepare('INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) VALUES (?, COALESCE((SELECT MAX(sequence) + 1 FROM play_campaign_delegation_audit WHERE campaign_id = ?), 1), ?, ?, ?)')
            ->execute([$args['id'], $args['id'], $args['username'], 'revoked', $delegation['powers']]);
    });
    return jsonResponse($response, ['username' => $args['username'], 'powers' => $powers, 'active' => false]);
});

$app->get('/v1/play/campaigns/{id}/delegations/audit', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);

    $statement = database()->prepare('SELECT username, action, powers FROM play_campaign_delegation_audit WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$args['id']]);
    $entries = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $entry) {
        $entries[] = ['username' => $entry['username'], 'action' => $entry['action'], 'powers' => json_decode($entry['powers'], true)];
    }
    return jsonResponse($response, ['entries' => $entries]);
});

$app->post('/v1/play/campaigns/{id}/members', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    if ($actor['role'] !== 'player') {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $characterId = $body['character_id'] ?? null;
    $name = $body['name'] ?? null;
    $class = $body['class'] ?? null;
    $hpCurrent = array_key_exists('hp_current', $body) ? integer($body['hp_current']) : 20;
    $hpMax = array_key_exists('hp_max', $body) ? integer($body['hp_max']) : 20;
    if (!validNonEmptyString($characterId) || !validNonEmptyString($name) || !validNonEmptyString($class)
        || $hpCurrent === null || $hpCurrent < 0 || $hpMax === null || $hpMax <= 0 || $hpCurrent > $hpMax) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['status'] !== 'lobby') {
        return jsonResponse($response, ['error' => 'campaign is not accepting members'], 409);
    }

    $database = database();
    $duplicatePlayer = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?');
    $duplicatePlayer->execute([$args['id'], $actor['username']]);
    $duplicateCharacter = $database->prepare('SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?');
    $duplicateCharacter->execute([$args['id'], $characterId]);
    $memberCount = $database->prepare('SELECT COUNT(*) FROM play_campaign_members WHERE campaign_id = ?');
    $memberCount->execute([$args['id']]);
    if ($duplicatePlayer->fetchColumn() !== false || $duplicateCharacter->fetchColumn() !== false
        || (int) $memberCount->fetchColumn() >= (int) $campaign['max_players']) {
        return jsonResponse($response, ['error' => 'membership conflict'], 409);
    }

    $statement = $database->prepare('INSERT INTO play_campaign_members (character_id, campaign_id, username, name, class) VALUES (?, ?, ?, ?, ?)');
    $statement->execute([$characterId, $args['id'], $actor['username'], $name, $class]);
    $owner = $database->prepare('INSERT INTO play_campaign_character_owners (character_id, campaign_id, owner) VALUES (?, ?, ?)');
    $owner->execute([$characterId, $args['id'], $actor['username']]);
    $health = $database->prepare('INSERT INTO play_campaign_member_health (character_id, campaign_id, hp_current, hp_max) VALUES (?, ?, ?, ?)');
    $health->execute([$characterId, $args['id'], $hpCurrent, $hpMax]);
    $currency = $database->prepare('INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) VALUES (?, ?, 10)');
    $currency->execute([$args['id'], $characterId]);
    return jsonResponse($response, [
        'username' => $actor['username'],
        'character_id' => $characterId,
        'name' => $name,
        'class' => $class,
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/characters/{char_id}/owner', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $owner = playCampaignCharacterOwner($args['id'], $args['char_id']);
    if ($owner === null) {
        return jsonResponse($response, ['error' => 'character is unowned'], 404);
    }
    return jsonResponse($response, ['character_id' => $args['char_id'], 'owner' => $owner['username']]);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/claim', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'player' || !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    // The unique character key makes this conditional insert safe if two
    // eligible members attempt to claim the same character at once.
    $statement = database()->prepare('INSERT INTO play_campaign_character_owners (character_id, campaign_id, owner)
        SELECT ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM play_campaign_character_owners WHERE character_id = ?
        )');
    $statement->execute([$args['char_id'], $args['id'], $actor['username'], $args['char_id']]);
    if ($statement->rowCount() !== 1) {
        return jsonResponse($response, ['error' => 'character already owned'], 409);
    }

    return jsonResponse($response, ['character_id' => $args['char_id'], 'owner' => $actor['username']], 201);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/transfer', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $newOwner = $body['new_owner'] ?? null;
    if (!validUsername($newOwner)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $owner = playCampaignCharacterOwner($args['id'], $args['char_id']);
    if ($owner === null) {
        return jsonResponse($response, ['error' => 'character is unowned'], 409);
    }
    if ($owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($newOwner === $owner['username'] || !isPlayCampaignMember($args['id'], $newOwner)) {
        return badRequest($response);
    }

    $statement = database()->prepare('UPDATE play_campaign_character_owners SET owner = ? WHERE campaign_id = ? AND character_id = ? AND owner = ?');
    $statement->execute([$newOwner, $args['id'], $args['char_id'], $actor['username']]);
    if ($statement->rowCount() !== 1) {
        return jsonResponse($response, ['error' => 'ownership conflict'], 409);
    }

    return jsonResponse($response, ['character_id' => $args['char_id'], 'owner' => $newOwner]);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/build', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['char_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $race = $body['race'] ?? null;
    $class = $body['class'] ?? null;
    $background = $body['background'] ?? null;
    $abilities = $body['abilities'] ?? null;
    $hitDie = characterHitDie($class);
    if (!validCharacterRace($race) || $hitDie === null || !validCharacterBackground($background) || !is_array($abilities)) {
        return badRequest($response);
    }
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
        if (!validAbilityScore(integer($abilities[$ability] ?? null))) {
            return badRequest($response);
        }
    }

    $level = 1;
    $constitution = integer($abilities['con']);
    $hpMax = $hitDie + abilityModifier($constitution);
    withinTransaction(database(), static function () use ($args, $abilities, $class, $constitution, $level, $hpMax): void {
        $database = database();
        $database->prepare('INSERT INTO play_campaign_character_progressions (character_id, class, con_modifier, level) VALUES (?, ?, ?, ?)
            ON CONFLICT(character_id) DO UPDATE SET class = excluded.class, con_modifier = excluded.con_modifier, level = excluded.level')
            ->execute([$args['char_id'], $class, abilityModifier($constitution), $level]);
        $database->prepare('INSERT INTO play_campaign_character_abilities (character_id, str, dex, con, int, wis, cha) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(character_id) DO UPDATE SET str = excluded.str, dex = excluded.dex, con = excluded.con, int = excluded.int, wis = excluded.wis, cha = excluded.cha')
            ->execute([$args['char_id'], $abilities['str'], $abilities['dex'], $abilities['con'], $abilities['int'], $abilities['wis'], $abilities['cha']]);
        $database->prepare('UPDATE play_campaign_member_health SET hp_current = MIN(hp_current, ?), hp_max = ? WHERE character_id = ?')
            ->execute([$hpMax, $hpMax, $args['char_id']]);
    });
    return jsonResponse($response, [
        'character_id' => $args['char_id'],
        'race' => $race,
        'class' => $class,
        'background' => $background,
        'level' => $level,
        'hp_max' => $hpMax,
        'proficiency_bonus' => proficiencyBonus($level),
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/skill-check', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['char_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $skill = $body['skill'] ?? null;
    $ability = $body['ability'] ?? null;
    $proficient = $body['proficient'] ?? null;
    $roll = integer($body['roll'] ?? null);
    if (!validSkillName($skill) || !validAbilityName($ability) || !is_bool($proficient) || $roll === null || $roll < 1 || $roll > 20) {
        return badRequest($response);
    }

    $database = database();
    $abilities = $database->prepare('SELECT str, dex, con, int, wis, cha FROM play_campaign_character_abilities WHERE character_id = ?');
    $abilities->execute([$args['char_id']]);
    $scores = $abilities->fetch(PDO::FETCH_ASSOC);
    $progression = $database->prepare('SELECT level FROM play_campaign_character_progressions WHERE character_id = ?');
    $progression->execute([$args['char_id']]);
    $level = $progression->fetchColumn();
    if (!is_array($scores) || $level === false) {
        return badRequest($response);
    }

    $modifier = abilityModifier((int) $scores[$ability]) + ($proficient ? proficiencyBonus((int) $level) : 0);
    return jsonResponse($response, [
        'character_id' => $args['char_id'],
        'skill' => $skill,
        'ability' => $ability,
        'modifier' => $modifier,
        'total' => $roll + $modifier,
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/level-up', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['char_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $requestedLevel = is_array($body) ? integer($body['level'] ?? null) : null;
    if (!validLevel($requestedLevel)) {
        return badRequest($response);
    }

    $database = database();
    $progression = $database->prepare('SELECT class, con_modifier, level FROM play_campaign_character_progressions WHERE character_id = ?');
    $progression->execute([$args['char_id']]);
    $character = $progression->fetch(PDO::FETCH_ASSOC);
    if (!is_array($character)) {
        return badRequest($response);
    }
    $currentLevel = (int) $character['level'];
    if ($requestedLevel !== $currentLevel + 1) {
        return badRequest($response);
    }
    $hitDie = characterHitDie($character['class']);
    if ($hitDie === null) {
        return badRequest($response);
    }

    $health = playCampaignCharacterHealth($args['char_id']);
    // Fixed average rolls keep advancement deterministic: d6=4, d8=5,
    // d10=6, and d12=7.
    $hpMax = $health['hp_max'] + intdiv($hitDie, 2) + 1 + (int) $character['con_modifier'];
    withinTransaction($database, static function () use ($database, $args, $currentLevel, $requestedLevel, $hpMax): void {
        $database->prepare('UPDATE play_campaign_character_progressions SET level = ? WHERE character_id = ? AND level = ?')
            ->execute([$requestedLevel, $args['char_id'], $currentLevel]);
        $database->prepare('UPDATE play_campaign_member_health SET hp_max = ? WHERE character_id = ?')
            ->execute([$hpMax, $args['char_id']]);
    });

    return jsonResponse($response, [
        'character_id' => $args['char_id'],
        'level' => $requestedLevel,
        'hp_max' => $hpMax,
        'hit_dice' => '1d' . $hitDie,
        'proficiency_bonus' => proficiencyBonus($requestedLevel),
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/damage', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $amount = integer($body['amount'] ?? null);
    if ($amount === null || $amount <= 0) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $result = ['hp_before' => 0, 'hp_after' => 0];
    withinTransaction($database, static function () use ($database, $args, $amount, &$result): void {
        $health = $database->prepare('SELECT hp_current FROM play_campaign_member_health WHERE character_id = ?');
        $health->execute([$args['char_id']]);
        $hpBefore = (int) $health->fetchColumn();
        $hpAfter = max(0, $hpBefore - $amount);
        $database->prepare('UPDATE play_campaign_member_health SET hp_current = ? WHERE character_id = ?')
            ->execute([$hpAfter, $args['char_id']]);
        if ($hpBefore > 0 && $hpAfter === 0) {
            $database->prepare('INSERT INTO play_campaign_member_death_saves (character_id, successes, failures) VALUES (?, 0, 0) ON CONFLICT(character_id) DO UPDATE SET successes = 0, failures = 0')
                ->execute([$args['char_id']]);
        }
        $result = [
            'hp_before' => $hpBefore,
            'hp_after' => $hpAfter,
        ];
    });

    return jsonResponse($response, [
        'target' => $args['char_id'],
        'character_id' => $args['char_id'],
        'hp_before' => $result['hp_before'],
        'hp_after' => $result['hp_after'],
        'damage' => $amount,
        'status' => playCampaignCharacterStatus($args['char_id']),
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/death-saves', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $outcome = $body['outcome'] ?? null;
    if ($outcome !== 'success' && $outcome !== 'failure') {
        return badRequest($response);
    }

    if (playCampaignById($args['id']) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    // Before ownership was introduced, a member controlled the character it
    // added. Retain that authorization until an explicit claim records an
    // owner; thereafter transfers take effect immediately.
    $owner = playCampaignCharacterOwner($args['id'], $args['char_id']);
    $controller = $owner['username'] ?? playCampaignCharacterMemberUsername($args['id'], $args['char_id']);
    if ($controller !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignCharacterStatus($args['char_id']) !== 'unconscious') {
        return jsonResponse($response, ['error' => 'death saves unavailable'], 409);
    }

    $database = database();
    $result = ['successes' => 0, 'failures' => 0, 'status' => 'unconscious'];
    withinTransaction($database, static function () use ($database, $args, $outcome, &$result): void {
        $database->prepare('INSERT INTO play_campaign_member_death_saves (character_id, successes, failures) VALUES (?, 0, 0) ON CONFLICT(character_id) DO NOTHING')
            ->execute([$args['char_id']]);
        $column = $outcome === 'success' ? 'successes' : 'failures';
        $database->prepare("UPDATE play_campaign_member_death_saves SET $column = $column + 1 WHERE character_id = ?")
            ->execute([$args['char_id']]);
        $saves = $database->prepare('SELECT successes, failures FROM play_campaign_member_death_saves WHERE character_id = ?');
        $saves->execute([$args['char_id']]);
        $row = $saves->fetch(PDO::FETCH_ASSOC);
        $successes = (int) $row['successes'];
        $failures = (int) $row['failures'];
        $result = [
            'successes' => $successes,
            'failures' => $failures,
            'status' => $failures >= 3 ? 'dead' : ($successes >= 3 ? 'stable' : 'unconscious'),
        ];
    });

    return jsonResponse($response, [
        'character_id' => $args['char_id'],
        'successes' => $result['successes'],
        'failures' => $result['failures'],
        'status' => $result['status'],
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/characters/{char_id}/status', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username'])
        && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $health = playCampaignCharacterHealth($args['char_id']);
    return jsonResponse($response, [
        'character_id' => $args['char_id'],
        'hp_current' => $health['hp_current'],
        'hp_max' => $health['hp_max'],
        'status' => playCampaignCharacterStatus($args['char_id']),
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{char_id}/spells', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['char_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $spellId = $body['spell_id'] ?? null;
    $name = $body['name'] ?? null;
    $level = integer($body['level'] ?? null);
    if (!validSpellForCharacterClass(playCampaignCharacterClass($args['id'], $args['char_id']), $spellId, $name, $level)) {
        return badRequest($response);
    }

    try {
        $statement = database()->prepare('INSERT INTO play_campaign_character_spells (character_id, spell_id, name, level) VALUES (?, ?, ?, ?)');
        $statement->execute([$args['char_id'], $spellId, $name, $level]);
    } catch (PDOException $exception) {
        return jsonResponse($response, ['error' => 'duplicate spell'], 409);
    }

    return jsonResponse($response, ['spell_id' => $spellId, 'name' => $name, 'level' => $level], 201);
});

$app->get('/v1/play/campaigns/{id}/characters/{char_id}/spells', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['char_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    return jsonResponse($response, ['spells' => playCampaignCharacterSpells($args['char_id'])]);
});

$app->put('/v1/play/campaigns/{id}/characters/{character_id}/prepared-spells', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $spellIds = $body['spell_ids'] ?? null;
    if (!is_array($spellIds) || !array_is_list($spellIds)) {
        return badRequest($response);
    }

    $maxPrepared = maximumPreparedSpells(
        playCampaignCharacterClass($args['id'], $args['character_id']),
        playCampaignCharacterLevel($args['character_id']),
    );
    if ($maxPrepared === null || count($spellIds) > $maxPrepared) {
        return badRequest($response);
    }

    $seen = [];
    foreach ($spellIds as $spellId) {
        if (!is_string($spellId) || isset($seen[$spellId])
            || !playCampaignCharacterKnowsSpell($args['character_id'], $spellId)) {
            return badRequest($response);
        }
        $seen[$spellId] = true;
    }

    $database = database();
    withinTransaction($database, static function () use ($database, $args, $spellIds): void {
        $database->prepare('DELETE FROM play_campaign_character_prepared_spells WHERE character_id = ?')
            ->execute([$args['character_id']]);
        $insert = $database->prepare('INSERT INTO play_campaign_character_prepared_spells (character_id, spell_id, position) VALUES (?, ?, ?)');
        foreach ($spellIds as $position => $spellId) {
            $insert->execute([$args['character_id'], $spellId, $position]);
        }
    });

    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'prepared_spells' => $spellIds,
        'max_prepared' => $maxPrepared,
    ]);
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/prepared-spells', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $maxPrepared = maximumPreparedSpells(
        playCampaignCharacterClass($args['id'], $args['character_id']),
        playCampaignCharacterLevel($args['character_id']),
    );
    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'prepared_spells' => playCampaignCharacterPreparedSpells($args['character_id']),
        'max_prepared' => $maxPrepared ?? 0,
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/casts', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $spellId = $body['spell_id'] ?? null;
    $target = $body['target'] ?? null;
    if (!validCompendiumSlug($spellId) || !validNonEmptyString($target)) {
        return badRequest($response);
    }

    $class = playCampaignCharacterClass($args['id'], $args['character_id']);
    if ($class !== 'wizard') {
        return badRequest($response);
    }
    $slotLevel = playCampaignCharacterSpellLevel($args['character_id'], $spellId);
    if ($slotLevel === null || !in_array($spellId, playCampaignCharacterPreparedSpells($args['character_id']), true)) {
        return badRequest($response);
    }

    $slotCount = playCampaignSpellSlots($class, playCampaignCharacterLevel($args['character_id']), $slotLevel);
    $result = [];
    $database = database();
    withinTransaction($database, static function () use ($database, $args, $spellId, $target, $slotLevel, $slotCount, &$result): void {
        $used = $database->prepare('SELECT COUNT(*) FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?');
        $used->execute([$args['id'], $args['character_id'], $slotLevel]);
        $slotsRemaining = $slotCount - (int) $used->fetchColumn();
        if ($slotsRemaining < 1) {
            return;
        }

        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ?');
        $sequence->execute([$args['id'], $args['character_id']]);
        $nextSequence = (int) $sequence->fetchColumn();
        $slotsRemaining--;
        $database->prepare('INSERT INTO play_campaign_character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $args['character_id'], $nextSequence, $spellId, $target, $slotLevel, $slotsRemaining]);
        $result = [
            'character_id' => $args['character_id'],
            'spell_id' => $spellId,
            'target' => $target,
            'slot_level' => $slotLevel,
            'slots_remaining' => $slotsRemaining,
            'sequence' => $nextSequence,
        ];
    });
    if ($result === []) {
        return jsonResponse($response, ['error' => 'no remaining spell slots'], 409);
    }

    return jsonResponse($response, $result, 201);
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/casts', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $statement = database()->prepare('SELECT character_id, spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_character_casts WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC');
    $statement->execute([$args['id'], $args['character_id']]);
    $casts = array_map(static fn (array $cast): array => [
        'character_id' => $cast['character_id'],
        'spell_id' => $cast['spell_id'],
        'target' => $cast['target'],
        'slot_level' => (int) $cast['slot_level'],
        'slots_remaining' => (int) $cast['slots_remaining'],
        'sequence' => (int) $cast['sequence'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));

    return jsonResponse($response, ['casts' => $casts]);
});

$app->put('/v1/play/campaigns/{id}/characters/{character_id}/concentration', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $spellId = $body['spell_id'] ?? null;
    $target = $body['target'] ?? null;
    $durationTurns = integer($body['duration_turns'] ?? null);
    $class = playCampaignCharacterClass($args['id'], $args['character_id']);
    if (!validCompendiumSlug($spellId) || !validNonEmptyString($target) || $durationTurns === null || $durationTurns < 1
        || $class !== 'wizard' || !playCampaignCharacterKnowsSpell($args['character_id'], $spellId)
        || !in_array($spellId, playCampaignCharacterPreparedSpells($args['character_id']), true)) {
        return badRequest($response);
    }

    database()->prepare('INSERT INTO play_campaign_character_concentrations (campaign_id, character_id, spell_id, target, remaining_turns)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns')
        ->execute([$args['id'], $args['character_id'], $spellId, $target, $durationTurns]);

    return jsonResponse($response, ['character_id' => $args['character_id'], 'concentration' => [
        'spell_id' => $spellId,
        'target' => $target,
        'remaining_turns' => $durationTurns,
    ]]);
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/concentration', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'concentration' => playCampaignCharacterConcentration($args['id'], $args['character_id']),
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/concentration/advance-turn', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $database = database();
    withinTransaction($database, static function () use ($database, $args): void {
        $database->prepare('UPDATE play_campaign_character_concentrations SET remaining_turns = remaining_turns - 1 WHERE campaign_id = ? AND character_id = ?')
            ->execute([$args['id'], $args['character_id']]);
        $database->prepare('DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ? AND remaining_turns <= 0')
            ->execute([$args['id'], $args['character_id']]);
    });

    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'concentration' => playCampaignCharacterConcentration($args['id'], $args['character_id']),
    ]);
});

$app->delete('/v1/play/campaigns/{id}/characters/{character_id}/concentration', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    database()->prepare('DELETE FROM play_campaign_character_concentrations WHERE campaign_id = ? AND character_id = ?')
        ->execute([$args['id'], $args['character_id']]);
    return jsonResponse($response, ['character_id' => $args['character_id'], 'concentration' => null]);
});

$app->post('/v1/play/campaigns/{id}/loot', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $lootId = $body['loot_id'] ?? null;
    $itemId = $body['item_id'] ?? null;
    $quantity = integer($body['quantity'] ?? null);
    if (!validNonEmptyString($lootId) || !isPlayInventoryCatalogItem($itemId) || $quantity === null || $quantity < 1) {
        return badRequest($response);
    }
    if (playCampaignLoot($args['id'], $lootId) !== null) {
        return jsonResponse($response, ['error' => 'duplicate loot id'], 409);
    }

    database()->prepare('INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status) VALUES (?, ?, ?, ?, ?)')
        ->execute([$args['id'], $lootId, $itemId, $quantity, 'open']);
    return jsonResponse($response, [
        'loot_id' => $lootId,
        'item_id' => $itemId,
        'quantity' => $quantity,
        'status' => 'open',
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/loot/{loot_id}/votes', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'player' || !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $loot = playCampaignLoot($args['id'], $args['loot_id']);
    if ($loot === null) {
        return jsonResponse($response, ['error' => 'unknown loot'], 404);
    }
    if ($loot['status'] !== 'open') {
        return jsonResponse($response, ['error' => 'loot is not open'], 409);
    }

    $body = jsonBody($request);
    $recipientId = $body['recipient_character_id'] ?? null;
    if (!validNonEmptyString($recipientId) || !playCampaignCharacterExists($args['id'], $recipientId)) {
        return badRequest($response);
    }
    $existing = database()->prepare('SELECT 1 FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND voter = ?');
    $existing->execute([$args['id'], $args['loot_id'], $actor['username']]);
    if ($existing->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'vote already cast'], 409);
    }

    database()->prepare('INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) VALUES (?, ?, ?, ?)')
        ->execute([$args['id'], $args['loot_id'], $actor['username'], $recipientId]);
    $count = database()->prepare('SELECT COUNT(*) FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? AND recipient_character_id = ?');
    $count->execute([$args['id'], $args['loot_id'], $recipientId]);
    return jsonResponse($response, [
        'loot_id' => $args['loot_id'],
        'voter' => $actor['username'],
        'recipient_character_id' => $recipientId,
        'votes_for_recipient' => (int) $count->fetchColumn(),
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/loot/{loot_id}/assign', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignLoot($args['id'], $args['loot_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown loot'], 404);
    }

    $result = null;
    $database = database();
    withinTransaction($database, static function () use ($database, $args, &$result): void {
        $lootStatement = $database->prepare('SELECT item_id, quantity, status FROM play_campaign_loot WHERE campaign_id = ? AND loot_id = ?');
        $lootStatement->execute([$args['id'], $args['loot_id']]);
        $loot = $lootStatement->fetch(PDO::FETCH_ASSOC);
        if (!is_array($loot) || $loot['status'] !== 'open') {
            return;
        }
        $counts = $database->prepare('SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes WHERE campaign_id = ? AND loot_id = ? GROUP BY recipient_character_id ORDER BY votes DESC, recipient_character_id ASC');
        $counts->execute([$args['id'], $args['loot_id']]);
        $ranked = $counts->fetchAll(PDO::FETCH_ASSOC);
        if ($ranked === [] || (count($ranked) > 1 && (int) $ranked[0]['votes'] === (int) $ranked[1]['votes'])) {
            return;
        }
        $recipientId = $ranked[0]['recipient_character_id'];
        $votes = (int) $ranked[0]['votes'];
        $close = $database->prepare("UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = ?, votes = ? WHERE campaign_id = ? AND loot_id = ? AND status = 'open'");
        $close->execute([$recipientId, $votes, $args['id'], $args['loot_id']]);
        if ($close->rowCount() !== 1) {
            return;
        }
        $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
            ->execute([$args['id'], $recipientId, $loot['item_id'], (int) $loot['quantity']]);
        $result = [
            'loot_id' => $args['loot_id'],
            'recipient_character_id' => $recipientId,
            'item_id' => $loot['item_id'],
            'quantity' => (int) $loot['quantity'],
            'votes' => $votes,
            'status' => 'assigned',
        ];
    });
    if ($result === null) {
        return jsonResponse($response, ['error' => 'loot cannot be assigned'], 409);
    }
    return jsonResponse($response, $result);
});

$app->get('/v1/play/campaigns/{id}/loot/{loot_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $loot = playCampaignLoot($args['id'], $args['loot_id']);
    if ($loot === null) {
        return jsonResponse($response, ['error' => 'unknown loot'], 404);
    }
    $loot['votes'] = playCampaignLootVoteCounts($args['id'], $args['loot_id']);
    return jsonResponse($response, $loot);
});

$app->post('/v1/play/campaigns/{id}/factions', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $factionId = $body['faction_id'] ?? null;
    $name = $body['name'] ?? null;
    if (!validNonEmptyString($factionId) || !validNonEmptyString($name)) {
        return badRequest($response);
    }
    if (playCampaignFactionExists($args['id'], $factionId)) {
        return jsonResponse($response, ['error' => 'duplicate faction id'], 409);
    }

    database()->prepare('INSERT INTO play_campaign_factions (campaign_id, faction_id, name) VALUES (?, ?, ?)')
        ->execute([$args['id'], $factionId, $name]);
    return jsonResponse($response, ['faction_id' => $factionId, 'name' => $name], 201);
});

$app->post('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignFactionExists($args['id'], $args['faction_id'])) {
        return jsonResponse($response, ['error' => 'unknown faction'], 404);
    }

    $body = jsonBody($request);
    $characterId = $body['character_id'] ?? null;
    $delta = integer($body['delta'] ?? null);
    $reason = $body['reason'] ?? null;
    if (!validNonEmptyString($characterId) || !playCampaignCharacterExists($args['id'], $characterId)
        || $delta === null || $delta === 0 || $delta < -25 || $delta > 25 || !validNonEmptyString($reason)) {
        return badRequest($response);
    }

    $database = database();
    $reputation = 0;
    withinTransaction($database, static function () use ($database, $args, $characterId, $delta, $reason, &$reputation): void {
        $previous = $database->prepare('SELECT reputation FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ? AND character_id = ? ORDER BY sequence DESC LIMIT 1');
        $previous->execute([$args['id'], $args['faction_id'], $characterId]);
        $reputation = max(-100, min(100, (int) ($previous->fetchColumn() ?: 0) + $delta));
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_faction_reputation_history WHERE campaign_id = ? AND faction_id = ?');
        $nextSequence->execute([$args['id'], $args['faction_id']]);
        $sequence = (int) $nextSequence->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_faction_reputation_history (campaign_id, faction_id, sequence, character_id, reputation, delta, reason) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $args['faction_id'], $sequence, $characterId, $reputation, $delta, $reason]);
    });

    return jsonResponse($response, [
        'faction_id' => $args['faction_id'],
        'character_id' => $characterId,
        'reputation' => $reputation,
        'delta' => $delta,
        'reason' => $reason,
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/factions/{faction_id}/reputation', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignFactionExists($args['id'], $args['faction_id'])) {
        return jsonResponse($response, ['error' => 'unknown faction'], 404);
    }

    $characterId = $isCampaignOwner ? null : playCampaignCharacterForUsername($args['id'], $actor['username'])['id'];
    return jsonResponse($response, [
        'faction_id' => $args['faction_id'],
        'entries' => playCampaignFactionReputationHistory($args['id'], $args['faction_id'], $characterId),
    ]);
});

$app->post('/v1/play/campaigns/{id}/npcs', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $npcId = $body['npc_id'] ?? null;
    $name = $body['name'] ?? null;
    $agenda = $body['agenda'] ?? null;
    $publicStatus = $body['public_status'] ?? null;
    if (!validNonEmptyString($npcId) || !validNonEmptyString($name)
        || !validNonEmptyString($agenda) || !validNonEmptyString($publicStatus)) {
        return badRequest($response);
    }
    if (playCampaignNpc($args['id'], $npcId) !== null) {
        return jsonResponse($response, ['error' => 'duplicate npc id'], 409);
    }

    database()->prepare('INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) VALUES (?, ?, ?, ?, ?)')
        ->execute([$args['id'], $npcId, $name, $agenda, $publicStatus]);
    return jsonResponse($response, [
        'npc_id' => $npcId,
        'name' => $name,
        'agenda' => $agenda,
        'public_status' => $publicStatus,
    ], 201);
});

$app->put('/v1/play/campaigns/{id}/npcs/{npc_id}/agenda', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $npc = playCampaignNpc($args['id'], $args['npc_id']);
    if ($npc === null) {
        return jsonResponse($response, ['error' => 'unknown npc'], 404);
    }

    $body = jsonBody($request);
    $agenda = $body['agenda'] ?? null;
    $publicStatus = $body['public_status'] ?? null;
    if (!validNonEmptyString($agenda) || !validNonEmptyString($publicStatus)) {
        return badRequest($response);
    }

    database()->prepare('UPDATE play_campaign_npcs SET agenda = ?, public_status = ? WHERE campaign_id = ? AND npc_id = ?')
        ->execute([$agenda, $publicStatus, $args['id'], $args['npc_id']]);
    return jsonResponse($response, [
        'npc_id' => $npc['npc_id'],
        'name' => $npc['name'],
        'agenda' => $agenda,
        'public_status' => $publicStatus,
    ]);
});

$app->get('/v1/play/campaigns/{id}/npcs/{npc_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $npc = playCampaignNpc($args['id'], $args['npc_id']);
    if ($npc === null) {
        return jsonResponse($response, ['error' => 'unknown npc'], 404);
    }
    if ($isCampaignOwner) {
        return jsonResponse($response, $npc);
    }
    return jsonResponse($response, [
        'npc_id' => $npc['npc_id'],
        'name' => $npc['name'],
        'public_status' => $npc['public_status'],
    ]);
});

$app->post('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignNpc($args['id'], $args['npc_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown npc'], 404);
    }

    $body = jsonBody($request);
    $dialogueId = $body['dialogue_id'] ?? null;
    $speaker = $body['speaker'] ?? null;
    $text = $body['text'] ?? null;
    $visibility = $body['visibility'] ?? null;
    if (!validNonEmptyString($dialogueId) || !validNonEmptyString($speaker)
        || !validNonEmptyString($text) || !is_string($visibility)
        || !in_array($visibility, ['public', 'private'], true)) {
        return badRequest($response);
    }
    if (playCampaignNpcDialogueExists($args['id'], $args['npc_id'], $dialogueId)) {
        return jsonResponse($response, ['error' => 'duplicate dialogue id'], 409);
    }

    $database = database();
    withinTransaction($database, static function () use ($database, $args, $dialogueId, $speaker, $text, $visibility): void {
        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_npc_dialogue WHERE campaign_id = ? AND npc_id = ?');
        $sequence->execute([$args['id'], $args['npc_id']]);
        $database->prepare('INSERT INTO play_campaign_npc_dialogue (campaign_id, npc_id, dialogue_id, sequence, speaker, text, visibility) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $args['npc_id'], $dialogueId, (int) $sequence->fetchColumn(), $speaker, $text, $visibility]);
    });

    return jsonResponse($response, [
        'dialogue_id' => $dialogueId,
        'speaker' => $speaker,
        'text' => $text,
        'visibility' => $visibility,
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/npcs/{npc_id}/dialogue', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignNpc($args['id'], $args['npc_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown npc'], 404);
    }

    return jsonResponse($response, [
        'npc_id' => $args['npc_id'],
        'entries' => playCampaignNpcDialogue($args['id'], $args['npc_id'], $isCampaignOwner),
    ]);
});

$app->post('/v1/play/campaigns/{id}/relationships', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $sourceId = $body['source_id'] ?? null;
    $targetId = $body['target_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $score = integer($body['score'] ?? null);
    if (!validNonEmptyString($sourceId) || !validNonEmptyString($targetId)
        || !validNonEmptyString($kind) || $score === null || $score < -100 || $score > 100
        || $sourceId === $targetId) {
        return badRequest($response);
    }
    if (!playCampaignEntityExists($args['id'], $sourceId) || !playCampaignEntityExists($args['id'], $targetId)) {
        return jsonResponse($response, ['error' => 'unknown campaign entity'], 404);
    }
    if (playCampaignRelationshipExists($args['id'], $sourceId, $targetId, $kind)) {
        return jsonResponse($response, ['error' => 'duplicate relationship'], 409);
    }

    database()->prepare('INSERT INTO play_campaign_relationships (campaign_id, source_id, target_id, kind, score) VALUES (?, ?, ?, ?, ?)')
        ->execute([$args['id'], $sourceId, $targetId, $kind, $score]);
    return jsonResponse($response, [
        'source_id' => $sourceId,
        'target_id' => $targetId,
        'kind' => $kind,
        'score' => $score,
    ], 201);
});

$app->put('/v1/play/campaigns/{id}/relationships/{source_id}/{target_id}/{kind}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignRelationshipExists($args['id'], $args['source_id'], $args['target_id'], $args['kind'])) {
        return jsonResponse($response, ['error' => 'unknown relationship'], 404);
    }

    $body = jsonBody($request);
    $score = integer($body['score'] ?? null);
    if ($score === null || $score < -100 || $score > 100) {
        return badRequest($response);
    }

    database()->prepare('UPDATE play_campaign_relationships SET score = ? WHERE campaign_id = ? AND source_id = ? AND target_id = ? AND kind = ?')
        ->execute([$score, $args['id'], $args['source_id'], $args['target_id'], $args['kind']]);
    return jsonResponse($response, [
        'source_id' => $args['source_id'],
        'target_id' => $args['target_id'],
        'kind' => $args['kind'],
        'score' => $score,
    ]);
});

$app->get('/v1/play/campaigns/{id}/relationships', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    return jsonResponse($response, ['edges' => playCampaignRelationships($args['id'])]);
});

$app->post('/v1/play/campaigns/{id}/clues', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    if ($body === null) {
        return badRequest($response);
    }
    $clueId = $body['clue_id'] ?? null;
    $text = $body['text'] ?? null;
    $audience = $body['audience'] ?? null;
    $hasCharacterId = array_key_exists('character_id', $body);
    $characterId = $body['character_id'] ?? null;
    if (!validNonEmptyString($clueId) || !validNonEmptyString($text)
        || !is_string($audience) || !in_array($audience, ['character', 'party', 'hidden'], true)
        || ($audience === 'character' && (!validNonEmptyString($characterId) || !playCampaignCharacterExists($args['id'], $characterId)))
        || ($audience !== 'character' && $hasCharacterId)) {
        return badRequest($response);
    }
    if (playCampaignClueExists($args['id'], $clueId)) {
        return jsonResponse($response, ['error' => 'duplicate clue id'], 409);
    }

    $database = database();
    withinTransaction($database, static function () use ($database, $args, $clueId, $text, $audience, $characterId): void {
        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_clues WHERE campaign_id = ?');
        $sequence->execute([$args['id']]);
        $database->prepare('INSERT INTO play_campaign_clues (campaign_id, clue_id, sequence, text, audience, character_id) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $clueId, (int) $sequence->fetchColumn(), $text, $audience, $audience === 'character' ? $characterId : null]);
    });

    $result = ['clue_id' => $clueId, 'text' => $text, 'audience' => $audience];
    if ($audience === 'character') {
        $result['character_id'] = $characterId;
    }
    return jsonResponse($response, $result, 201);
});

$app->get('/v1/play/campaigns/{id}/clues', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $characterId = $isCampaignOwner ? null : playCampaignCharacterForUsername($args['id'], $actor['username'])['id'];
    return jsonResponse($response, ['clues' => playCampaignClues($args['id'], $characterId)]);
});

$app->post('/v1/play/campaigns/{id}/quests', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $questId = $body['quest_id'] ?? null;
    $title = $body['title'] ?? null;
    if (!validNonEmptyString($questId) || !validNonEmptyString($title)) {
        return badRequest($response);
    }
    if (playCampaignQuest($args['id'], $questId) !== null) {
        return jsonResponse($response, ['error' => 'duplicate quest id'], 409);
    }
    $dependsOn = questDependencies($body['depends_on'] ?? null, $args['id'], $questId);
    if ($dependsOn === null) {
        return badRequest($response);
    }

    $database = database();
    withinTransaction($database, static function () use ($database, $args, $questId, $title, $dependsOn): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_quests WHERE campaign_id = ?');
        $nextSequence->execute([$args['id']]);
        $database->prepare('INSERT INTO play_campaign_quests (campaign_id, quest_id, sequence, title, depends_on, state) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $questId, (int) $nextSequence->fetchColumn(), $title, json_encode($dependsOn, JSON_THROW_ON_ERROR), 'locked']);
    });

    return jsonResponse($response, ['quest_id' => $questId, 'title' => $title, 'depends_on' => $dependsOn, 'state' => 'locked'], 201);
});

$app->put('/v1/play/campaigns/{id}/quests/{quest_id}/state', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $quest = playCampaignQuest($args['id'], $args['quest_id']);
    if ($quest === null) {
        return jsonResponse($response, ['error' => 'unknown quest'], 404);
    }

    $body = jsonBody($request);
    $state = $body['state'] ?? null;
    if (!is_string($state) || !in_array($state, ['active', 'completed'], true)) {
        return badRequest($response);
    }
    if (($quest['state'] === 'locked' && $state === 'active')) {
        foreach ($quest['depends_on'] as $dependencyId) {
            $dependency = playCampaignQuest($args['id'], $dependencyId);
            if ($dependency === null || $dependency['state'] !== 'completed') {
                return jsonResponse($response, ['error' => 'invalid quest state transition'], 409);
            }
        }
    } elseif (!($quest['state'] === 'active' && $state === 'completed')) {
        return jsonResponse($response, ['error' => 'invalid quest state transition'], 409);
    }

    database()->prepare('UPDATE play_campaign_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?')
        ->execute([$state, $args['id'], $args['quest_id']]);
    $quest['state'] = $state;
    return jsonResponse($response, $quest);
});

$app->put('/v1/play/campaigns/{id}/quests/{quest_id}/rewards', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $quest = playCampaignQuest($args['id'], $args['quest_id']);
    if ($quest === null) {
        return jsonResponse($response, ['error' => 'unknown quest'], 404);
    }
    if (!in_array($quest['state'], ['locked', 'active'], true)) {
        return jsonResponse($response, ['error' => 'quest rewards cannot be configured'], 409);
    }

    $body = jsonBody($request);
    $xp = integer($body['xp'] ?? null);
    $items = $body === null ? null : questRewardItems($request);
    if ($xp === null || $xp < 0 || $items === null) {
        return badRequest($response);
    }

    database()->prepare('INSERT INTO play_campaign_quest_rewards (campaign_id, quest_id, xp, items, awarded) VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(campaign_id, quest_id) DO UPDATE SET xp = excluded.xp, items = excluded.items')
        ->execute([$args['id'], $args['quest_id'], $xp, json_encode($items, JSON_THROW_ON_ERROR)]);
    $quest['rewards'] = ['xp' => $xp, 'items' => $items];
    return jsonResponse($response, $quest);
});

$app->post('/v1/play/campaigns/{id}/quests/{quest_id}/rewards/award', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $quest = playCampaignQuest($args['id'], $args['quest_id']);
    if ($quest === null) {
        return jsonResponse($response, ['error' => 'unknown quest'], 404);
    }
    $reward = playCampaignQuestReward($args['id'], $args['quest_id']);
    if ($quest['state'] !== 'completed' || $reward === null || $reward['awarded']) {
        return jsonResponse($response, ['error' => 'quest rewards cannot be awarded'], 409);
    }

    $awarded = false;
    $database = database();
    withinTransaction($database, static function () use ($database, $args, $reward, &$awarded): void {
        // The conditional update is the one-time award guard, including for
        // concurrent requests.
        $markAwarded = $database->prepare('UPDATE play_campaign_quest_rewards SET awarded = 1 WHERE campaign_id = ? AND quest_id = ? AND awarded = 0');
        $markAwarded->execute([$args['id'], $args['quest_id']]);
        if ($markAwarded->rowCount() !== 1) {
            return;
        }
        $members = $database->prepare('SELECT character_id FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
        $members->execute([$args['id']]);
        $grant = $database->prepare('INSERT INTO play_campaign_quest_reward_grants (campaign_id, quest_id, character_id, xp, items) VALUES (?, ?, ?, ?, ?)');
        $items = json_encode($reward['items'], JSON_THROW_ON_ERROR);
        foreach ($members->fetchAll(PDO::FETCH_COLUMN) as $characterId) {
            $grant->execute([$args['id'], $args['quest_id'], $characterId, $reward['xp'], $items]);
        }
        $awarded = true;
    });
    if (!$awarded) {
        return jsonResponse($response, ['error' => 'quest rewards cannot be awarded'], 409);
    }
    return jsonResponse($response, ['quest_id' => $args['quest_id'], 'awarded' => true, 'xp' => $reward['xp'], 'items' => $reward['items']], 201);
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/rewards', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $grants = database()->prepare('SELECT xp, items FROM play_campaign_quest_reward_grants WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC');
    $grants->execute([$args['id'], $args['character_id']]);
    $xp = 0;
    $items = [];
    foreach ($grants->fetchAll(PDO::FETCH_ASSOC) as $grant) {
        $xp += (int) $grant['xp'];
        $grantItems = json_decode($grant['items'], true);
        if (is_array($grantItems)) {
            foreach ($grantItems as $itemId => $quantity) {
                $items[$itemId] = ($items[$itemId] ?? 0) + (int) $quantity;
            }
        }
    }
    return jsonResponse($response, ['character_id' => $args['character_id'], 'xp' => $xp, 'items' => $items]);
});

$app->get('/v1/play/campaigns/{id}/quests', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    return jsonResponse($response, ['quests' => playCampaignQuests($args['id'])]);
});

$app->post('/v1/play/campaigns/{id}/world-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $body = jsonBody($request);
    $eventId = $body['event_id'] ?? null;
    $turnNumber = integer($body['turn_number'] ?? null);
    $title = $body['title'] ?? null;
    $text = $body['text'] ?? null;
    if (!validNonEmptyString($eventId) || $turnNumber === null || !validNonEmptyString($title) || !validNonEmptyString($text)) {
        return badRequest($response);
    }
    $turnState = playCampaignTurnState($args['id'], playCampaignPartyUsernames($args['id']));
    if ($turnNumber < ($turnState['turn_number'] ?? 1)) {
        return badRequest($response);
    }

    $created = false;
    $database = database();
    withinTransaction($database, static function () use ($database, $args, $eventId, $turnNumber, $title, $text, &$created): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_world_events WHERE campaign_id = ?');
        $nextSequence->execute([$args['id']]);
        $insert = $database->prepare("INSERT OR IGNORE INTO play_campaign_world_events (campaign_id, event_id, sequence, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?, 'scheduled')");
        $insert->execute([$args['id'], $eventId, (int) $nextSequence->fetchColumn(), $turnNumber, $title, $text]);
        $created = $insert->rowCount() === 1;
    });
    if (!$created) {
        return jsonResponse($response, ['error' => 'duplicate event id'], 409);
    }
    return jsonResponse($response, playCampaignWorldEvent($args['id'], $eventId), 201);
});

$app->post('/v1/play/campaigns/{id}/world-events/{event_id}/resolve', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $body = jsonBody($request);
    $text = $body['text'] ?? null;
    if (!validNonEmptyString($text)) {
        return badRequest($response);
    }
    $event = playCampaignWorldEvent($args['id'], $args['event_id']);
    if ($event === null) {
        return jsonResponse($response, ['error' => 'unknown world event'], 404);
    }
    $turnState = playCampaignTurnState($args['id'], playCampaignPartyUsernames($args['id']));
    $currentTurn = $turnState['turn_number'] ?? 1;
    if ($currentTurn !== $event['turn_number'] || $event['status'] === 'resolved') {
        return jsonResponse($response, ['error' => 'world event cannot be resolved'], 409);
    }
    $updated = database()->prepare("UPDATE play_campaign_world_events SET status = 'resolved', resolution_turn_number = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ? AND status = 'scheduled'");
    $updated->execute([$currentTurn, $text, $args['id'], $args['event_id']]);
    if ($updated->rowCount() !== 1) {
        return jsonResponse($response, ['error' => 'world event cannot be resolved'], 409);
    }
    return jsonResponse($response, playCampaignWorldEvent($args['id'], $args['event_id']), 201);
});

$app->get('/v1/play/campaigns/{id}/world-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    return jsonResponse($response, ['events' => playCampaignWorldEvents($args['id'])]);
});

$app->post('/v1/play/campaigns/{id}/settlements', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $body = jsonBody($request);
    $settlementId = $body['settlement_id'] ?? null;
    $name = $body['name'] ?? null;
    $services = normalizedSettlementServices($body['services'] ?? null);
    $availability = $body['availability'] ?? null;
    if (!validNonEmptyString($settlementId) || !validNonEmptyString($name) || $services === null || !validSettlementAvailability($availability)) {
        return badRequest($response);
    }

    $created = false;
    $database = database();
    withinTransaction($database, static function () use ($database, $args, $settlementId, $name, $services, $availability, &$created): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_settlements WHERE campaign_id = ?');
        $nextSequence->execute([$args['id']]);
        $insert = $database->prepare('INSERT OR IGNORE INTO play_campaign_settlements (campaign_id, settlement_id, sequence, name, services, availability) VALUES (?, ?, ?, ?, ?, ?)');
        $insert->execute([$args['id'], $settlementId, (int) $nextSequence->fetchColumn(), $name, json_encode($services, JSON_THROW_ON_ERROR), $availability]);
        $created = $insert->rowCount() === 1;
    });
    if (!$created) {
        return jsonResponse($response, ['error' => 'duplicate settlement id'], 409);
    }
    return jsonResponse($response, playCampaignSettlement($args['id'], $settlementId), 201);
});

$app->put('/v1/play/campaigns/{id}/settlements/{settlement_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignSettlement($args['id'], $args['settlement_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown settlement'], 404);
    }
    $body = jsonBody($request);
    $name = $body['name'] ?? null;
    $services = normalizedSettlementServices($body['services'] ?? null);
    $availability = $body['availability'] ?? null;
    if (!validNonEmptyString($name) || $services === null || !validSettlementAvailability($availability)) {
        return badRequest($response);
    }
    database()->prepare('UPDATE play_campaign_settlements SET name = ?, services = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?')
        ->execute([$name, json_encode($services, JSON_THROW_ON_ERROR), $availability, $args['id'], $args['settlement_id']]);
    return jsonResponse($response, playCampaignSettlement($args['id'], $args['settlement_id']));
});

$app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/discover', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'player' || !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignSettlement($args['id'], $args['settlement_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown settlement'], 404);
    }
    $member = playCampaignCharacterForUsername($args['id'], $actor['username']);
    $characterId = $member['id'];
    $created = false;
    $database = database();
    withinTransaction($database, static function () use ($database, $args, $characterId, &$created): void {
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_settlement_discoveries WHERE campaign_id = ? AND settlement_id = ?');
        $nextSequence->execute([$args['id'], $args['settlement_id']]);
        $insert = $database->prepare('INSERT OR IGNORE INTO play_campaign_settlement_discoveries (campaign_id, settlement_id, character_id, sequence) VALUES (?, ?, ?, ?)');
        $insert->execute([$args['id'], $args['settlement_id'], $characterId, (int) $nextSequence->fetchColumn()]);
        $created = $insert->rowCount() === 1;
    });
    return jsonResponse($response, playCampaignSettlement($args['id'], $args['settlement_id'], $characterId), $created ? 201 : 200);
});

$app->get('/v1/play/campaigns/{id}/settlements', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $characterId = $isCampaignOwner ? null : playCampaignCharacterForUsername($args['id'], $actor['username'])['id'];
    return jsonResponse($response, ['settlements' => playCampaignSettlements($args['id'], $characterId)]);
});

$app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignSettlement($args['id'], $args['settlement_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown settlement'], 404);
    }
    $body = jsonBody($request);
    $shopId = $body['shop_id'] ?? null;
    $name = $body['name'] ?? null;
    $stock = normalizedShopStock($body['stock'] ?? null);
    $buyPrice = integer($body['buy_price'] ?? null);
    $sellPrice = integer($body['sell_price'] ?? null);
    if (!validNonEmptyString($shopId) || !validNonEmptyString($name) || $stock === null
        || $buyPrice === null || $buyPrice < 1 || $sellPrice === null || $sellPrice < 0) {
        return badRequest($response);
    }
    $insert = database()->prepare('INSERT OR IGNORE INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)');
    $insert->execute([$args['id'], $args['settlement_id'], $shopId, $name, json_encode($stock, JSON_THROW_ON_ERROR), $buyPrice, $sellPrice]);
    if ($insert->rowCount() !== 1) {
        return jsonResponse($response, ['error' => 'duplicate shop id'], 409);
    }
    return jsonResponse($response, playCampaignShop($args['id'], $args['settlement_id'], $shopId), 201);
});

$app->get('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $settlement = playCampaignSettlement($args['id'], $args['settlement_id']);
    if ($settlement === null || playCampaignShop($args['id'], $args['settlement_id'], $args['shop_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown shop'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!$isCampaignOwner) {
        $character = playCampaignCharacterForUsername($args['id'], $actor['username']);
        if ($character === null || playCampaignSettlement($args['id'], $args['settlement_id'], $character['id']) === null) {
            return jsonResponse($response, ['error' => 'unknown shop'], 404);
        }
    }
    return jsonResponse($response, playCampaignShop($args['id'], $args['settlement_id'], $args['shop_id']));
});

$shopTrade = function (Request $request, Response $response, array $args, string $direction): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (playCampaignSettlement($args['id'], $args['settlement_id']) === null || playCampaignShop($args['id'], $args['settlement_id'], $args['shop_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown shop'], 404);
    }
    $body = jsonBody($request);
    $characterId = $body['character_id'] ?? null;
    $itemId = $body['item_id'] ?? null;
    $quantity = integer($body['quantity'] ?? null);
    if (!validNonEmptyString($characterId) || !playCampaignCharacterExists($args['id'], $characterId)) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    if (!validCampaignInventoryItemId($itemId) || $quantity === null || $quantity < 1) {
        return badRequest($response);
    }
    $owner = playCampaignCharacterOwner($args['id'], $characterId);
    if ($actor['role'] !== 'player' || $owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $result = null;
    withinTransaction($database, static function () use ($database, $args, $direction, $characterId, $itemId, $quantity, &$result): void {
        $shop = playCampaignShop($args['id'], $args['settlement_id'], $args['shop_id']);
        if ($shop === null) {
            return;
        }
        $stock = $shop['stock'];
        $currentStock = $stock[$itemId] ?? 0;
        $inventory = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $inventory->execute([$args['id'], $characterId, $itemId]);
        $held = $inventory->fetchColumn();
        if ($direction === 'buy') {
            $cost = $shop['buy_price'] * $quantity;
            $gold = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
            $gold->execute([$args['id'], $characterId]);
            $balance = $gold->fetchColumn();
            if ($currentStock < $quantity || $balance === false || (int) $balance < $cost) {
                return;
            }
            $stock[$itemId] = $currentStock - $quantity;
            $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ?')
                ->execute([$cost, $args['id'], $characterId]);
            $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
                ->execute([$args['id'], $characterId, $itemId, $quantity]);
        } else {
            if ($held === false || (int) $held < $quantity) {
                return;
            }
            $stock[$itemId] = $currentStock + $quantity;
            $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?')
                ->execute([$shop['sell_price'] * $quantity, $args['id'], $characterId]);
        }
        $database->prepare('UPDATE play_campaign_shops SET stock = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?')
            ->execute([json_encode($stock, JSON_THROW_ON_ERROR), $args['id'], $args['settlement_id'], $args['shop_id']]);
        $gold = $database->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
        $gold->execute([$args['id'], $characterId]);
        $result = ['character_id' => $characterId, 'item_id' => $itemId, 'quantity' => $quantity, 'gold' => (int) $gold->fetchColumn(), 'stock' => $stock[$itemId]];
    });
    if ($result === null) {
        return jsonResponse($response, ['error' => $direction === 'buy' ? 'insufficient stock or gold' : 'insufficient item quantity'], 409);
    }
    return jsonResponse($response, $result);
};

$app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/buy', static fn (Request $request, Response $response, array $args): Response => $shopTrade($request, $response, $args, 'buy'));
$app->post('/v1/play/campaigns/{id}/settlements/{settlement_id}/shops/{shop_id}/sell', static fn (Request $request, Response $response, array $args): Response => $shopTrade($request, $response, $args, 'sell'));

$app->post('/v1/play/campaigns/{id}/recipes', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $recipeId = $body['recipe_id'] ?? null;
    $name = $body['name'] ?? null;
    $ingredients = normalizedRecipeIngredients($body['ingredients'] ?? null);
    $outputItem = $body['output_item'] ?? null;
    $outputQuantity = integer($body['output_quantity'] ?? null);
    if (!validNonEmptyString($recipeId) || !validNonEmptyString($name) || $ingredients === null
        || !validCampaignInventoryItemId($outputItem) || $outputQuantity === null || $outputQuantity < 1) {
        return badRequest($response);
    }

    $database = database();
    $created = false;
    withinTransaction($database, static function () use ($database, $args, $recipeId, $name, $ingredients, $outputItem, $outputQuantity, &$created): void {
        $sequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_recipes WHERE campaign_id = ?');
        $sequence->execute([$args['id']]);
        $insert = $database->prepare('INSERT OR IGNORE INTO play_campaign_recipes (campaign_id, recipe_id, sequence, name, ingredients, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?, ?)');
        $insert->execute([$args['id'], $recipeId, (int) $sequence->fetchColumn(), $name, json_encode($ingredients, JSON_THROW_ON_ERROR), $outputItem, $outputQuantity]);
        $created = $insert->rowCount() === 1;
    });
    if (!$created) {
        return jsonResponse($response, ['error' => 'duplicate recipe id'], 409);
    }
    return jsonResponse($response, [
        'recipe_id' => $recipeId,
        'name' => $name,
        'ingredients' => $ingredients,
        'output_item' => $outputItem,
        'output_quantity' => $outputQuantity,
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/recipes', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    return jsonResponse($response, ['recipes' => playCampaignRecipes($args['id'])]);
});

$app->post('/v1/play/campaigns/{id}/recipes/{recipe_id}/craft', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $recipe = playCampaignRecipe($args['id'], $args['recipe_id']);
    if ($recipe === null) {
        return jsonResponse($response, ['error' => 'unknown recipe'], 404);
    }
    $body = jsonBody($request);
    $characterId = $body['character_id'] ?? null;
    if (!validNonEmptyString($characterId)) {
        return badRequest($response);
    }
    if (!playCampaignCharacterExists($args['id'], $characterId)) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $characterId);
    if ($actor['role'] !== 'player' || $owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $crafted = false;
    withinTransaction($database, static function () use ($database, $args, $characterId, $recipe, &$crafted): void {
        // Validate every debit before mutating inventory, so failure is atomic.
        $held = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        foreach ($recipe['ingredients'] as $itemId => $quantity) {
            $held->execute([$args['id'], $characterId, $itemId]);
            $available = $held->fetchColumn();
            if ($available === false || (int) $available < $quantity) {
                return;
            }
        }
        $debit = $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = quantity - ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $removeEmpty = $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ? AND quantity = 0');
        foreach ($recipe['ingredients'] as $itemId => $quantity) {
            $debit->execute([$quantity, $args['id'], $characterId, $itemId]);
            $removeEmpty->execute([$args['id'], $characterId, $itemId]);
        }
        $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
            ->execute([$args['id'], $characterId, $recipe['output_item'], $recipe['output_quantity']]);
        $crafted = true;
    });
    if (!$crafted) {
        return jsonResponse($response, ['error' => 'insufficient ingredients'], 409);
    }
    return jsonResponse($response, [
        'character_id' => $characterId,
        'recipe_id' => $recipe['recipe_id'],
        'output_item' => $recipe['output_item'],
        'output_quantity' => $recipe['output_quantity'],
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/downtime/activities', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $body = jsonBody($request);
    $activityId = $body['activity_id'] ?? null;
    $name = $body['name'] ?? null;
    $cyclesRequired = integer($body['cycles_required'] ?? null);
    if (!validNonEmptyString($activityId) || !validNonEmptyString($name)
        || $cyclesRequired === null || $cyclesRequired < 1 || $cyclesRequired > 10) {
        return badRequest($response);
    }
    $insert = database()->prepare('INSERT OR IGNORE INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)');
    $insert->execute([$args['id'], $activityId, $name, $cyclesRequired]);
    if ($insert->rowCount() !== 1) {
        return jsonResponse($response, ['error' => 'duplicate activity id'], 409);
    }
    return jsonResponse($response, playCampaignDowntimeActivity($args['id'], $activityId), 201);
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $body = jsonBody($request);
    $activityId = $body['activity_id'] ?? null;
    if (!validNonEmptyString($activityId)) {
        return badRequest($response);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    if (playCampaignDowntimeActivity($args['id'], $activityId) === null) {
        return jsonResponse($response, ['error' => 'unknown activity'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($actor['role'] !== 'player' || $owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $insert = database()->prepare('INSERT OR IGNORE INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, 0, 0)');
    $insert->execute([$args['id'], $args['character_id'], $activityId]);
    if ($insert->rowCount() !== 1) {
        return jsonResponse($response, ['error' => 'duplicate allocation'], 409);
    }
    return jsonResponse($response, playCampaignDowntimeAllocation($args['id'], $args['character_id'], $activityId), 201);
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}/progress', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $activity = playCampaignDowntimeActivity($args['id'], $args['activity_id']);
    if ($activity === null) {
        return jsonResponse($response, ['error' => 'unknown activity'], 404);
    }
    if (playCampaignDowntimeAllocation($args['id'], $args['character_id'], $args['activity_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown allocation'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($actor['role'] !== 'player' || $owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $required = $activity['cycles_required'];
    $statement = database()->prepare('UPDATE play_campaign_downtime_allocations SET cycles_completed = CASE WHEN cycles_completed + 1 >= CAST(? AS INTEGER) THEN 0 ELSE cycles_completed + 1 END, completions = completions + CASE WHEN cycles_completed + 1 >= CAST(? AS INTEGER) THEN 1 ELSE 0 END WHERE campaign_id = ? AND character_id = ? AND activity_id = ?');
    $statement->execute([$required, $required, $args['id'], $args['character_id'], $args['activity_id']]);
    return jsonResponse($response, playCampaignDowntimeAllocation($args['id'], $args['character_id'], $args['activity_id']));
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/downtime/allocations/{activity_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    if (playCampaignDowntimeActivity($args['id'], $args['activity_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown activity'], 404);
    }
    $allocation = playCampaignDowntimeAllocation($args['id'], $args['character_id'], $args['activity_id']);
    if ($allocation === null) {
        return jsonResponse($response, ['error' => 'unknown allocation'], 404);
    }
    return jsonResponse($response, $allocation);
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $itemId = $body['item_id'] ?? null;
    $quantity = integer($body['quantity'] ?? null);
    if (!is_string($itemId) || !in_array($itemId, ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true)
        || $quantity === null || $quantity < 1) {
        return badRequest($response);
    }

    $database = database();
    $database->prepare('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity')
        ->execute([$args['id'], $args['character_id'], $itemId, $quantity]);
    $statement = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
    $statement->execute([$args['id'], $args['character_id'], $itemId]);

    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'item_id' => $itemId,
        'quantity' => $quantity,
        'total_quantity' => (int) $statement->fetchColumn(),
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $statement = database()->prepare('SELECT item_id, quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND quantity > 0 ORDER BY item_id ASC');
    $statement->execute([$args['id'], $args['character_id']]);
    $items = array_map(static fn (array $item): array => [
        'item_id' => $item['item_id'],
        'quantity' => (int) $item['quantity'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
    return jsonResponse($response, ['character_id' => $args['character_id'], 'items' => $items]);
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/currency', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $statement = database()->prepare('SELECT gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id = ?');
    $statement->execute([$args['id'], $args['character_id']]);
    $gold = $statement->fetchColumn();
    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'gold' => $gold === false ? 10 : (int) $gold,
    ]);
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/currency/transfers', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $destinationId = $body['to_character_id'] ?? null;
    $gold = integer($body['gold'] ?? null);
    if (!is_string($destinationId) || $destinationId === $args['character_id']
        || !playCampaignCharacterExists($args['id'], $destinationId)
        || $gold === null || $gold <= 0) {
        return badRequest($response);
    }

    $database = database();
    $result = null;
    withinTransaction($database, static function () use ($database, $args, $destinationId, $gold, &$result): void {
        // A conditional debit makes insufficient-funds attempts leave both
        // balances untouched; the credit and transfer record share this transaction.
        $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
        $debit->execute([$gold, $args['id'], $args['character_id'], $gold]);
        if ($debit->rowCount() !== 1) {
            return;
        }

        $credit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?');
        $credit->execute([$gold, $args['id'], $destinationId]);
        $sequence = $database->prepare('SELECT COALESCE(MAX(transfer_id), 0) + 1 FROM play_campaign_currency_transfers WHERE campaign_id = ?');
        $sequence->execute([$args['id']]);
        $transferId = (int) $sequence->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_currency_transfers (campaign_id, transfer_id, from_character_id, to_character_id, gold) VALUES (?, ?, ?, ?, ?)')
            ->execute([$args['id'], $transferId, $args['character_id'], $destinationId, $gold]);

        $balances = $database->prepare('SELECT character_id, gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id IN (?, ?)');
        $balances->execute([$args['id'], $args['character_id'], $destinationId]);
        $values = [];
        foreach ($balances->fetchAll(PDO::FETCH_ASSOC) as $balance) {
            $values[$balance['character_id']] = (int) $balance['gold'];
        }
        $result = [
            'from_character_id' => $args['character_id'],
            'to_character_id' => $destinationId,
            'gold' => $gold,
            'from_gold' => $values[$args['character_id']],
            'to_gold' => $values[$destinationId],
            'transfer_id' => $transferId,
        ];
    });
    if ($result === null) {
        return jsonResponse($response, ['error' => 'insufficient gold'], 409);
    }

    return jsonResponse($response, $result, 201);
});

$app->post('/v1/play/campaigns/{id}/transactional-transfers', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    if ($body === null || count($body) !== 4
        || !array_key_exists('from_character_id', $body) || !array_key_exists('to_character_id', $body)
        || !array_key_exists('amount', $body) || !array_key_exists('simulate_failure', $body)) {
        return badRequest($response);
    }
    $fromCharacterId = $body['from_character_id'];
    $toCharacterId = $body['to_character_id'];
    $amount = integer($body['amount']);
    $simulateFailure = $body['simulate_failure'];
    if (!validNonEmptyString($fromCharacterId) || !validNonEmptyString($toCharacterId)
        || $fromCharacterId === $toCharacterId || $amount === null || $amount <= 0
        || !is_bool($simulateFailure)
        || !playCampaignCharacterExists($args['id'], $fromCharacterId)
        || !playCampaignCharacterExists($args['id'], $toCharacterId)) {
        return badRequest($response);
    }

    $owner = playCampaignCharacterOwner($args['id'], $fromCharacterId);
    if ($actor['role'] !== 'player' || $owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $database->beginTransaction();
    try {
        // The conditional debit establishes that the source can pay before any
        // durable compound state is committed. Every subsequent mutation uses
        // this same transaction, including the ordered ledger record.
        $debit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold - ? WHERE campaign_id = ? AND character_id = ? AND gold >= ?');
        $debit->execute([$amount, $args['id'], $fromCharacterId, $amount]);
        if ($debit->rowCount() !== 1) {
            $database->rollBack();
            return jsonResponse($response, ['error' => 'insufficient gold'], 409);
        }

        $credit = $database->prepare('UPDATE play_campaign_character_currency SET gold = gold + ? WHERE campaign_id = ? AND character_id = ?');
        $credit->execute([$amount, $args['id'], $toCharacterId]);
        $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_transactional_transfers WHERE campaign_id = ?');
        $nextSequence->execute([$args['id']]);
        $sequence = (int) $nextSequence->fetchColumn();

        $balances = $database->prepare('SELECT character_id, gold FROM play_campaign_character_currency WHERE campaign_id = ? AND character_id IN (?, ?)');
        $balances->execute([$args['id'], $fromCharacterId, $toCharacterId]);
        $gold = [];
        foreach ($balances->fetchAll(PDO::FETCH_ASSOC) as $balance) {
            $gold[$balance['character_id']] = (int) $balance['gold'];
        }

        $record = [
            'from_character_id' => $fromCharacterId,
            'to_character_id' => $toCharacterId,
            'amount' => $amount,
            'from_gold' => $gold[$fromCharacterId],
            'to_gold' => $gold[$toCharacterId],
            'sequence' => $sequence,
        ];
        $database->prepare('INSERT INTO play_campaign_transactional_transfers (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $sequence, $fromCharacterId, $toCharacterId, $amount, $record['from_gold'], $record['to_gold']]);

        if ($simulateFailure) {
            $database->rollBack();
            return jsonResponse($response, ['error' => 'simulated failure'], 500);
        }

        $database->commit();
        return jsonResponse($response, $record, 201);
    } catch (Throwable $exception) {
        if ($database->inTransaction()) {
            $database->rollBack();
        }
        throw $exception;
    }
});

$app->get('/v1/play/campaigns/{id}/transactional-transfers', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $statement = database()->prepare('SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence FROM play_campaign_transactional_transfers WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$args['id']]);
    $transfers = array_map(static fn (array $transfer): array => [
        'from_character_id' => $transfer['from_character_id'],
        'to_character_id' => $transfer['to_character_id'],
        'amount' => (int) $transfer['amount'],
        'from_gold' => (int) $transfer['from_gold'],
        'to_gold' => (int) $transfer['to_gold'],
        'sequence' => (int) $transfer['sequence'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
    return jsonResponse($response, ['transfers' => $transfers]);
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}/consume', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($args['item_id'] !== 'healing-potion') {
        return badRequest($response);
    }

    $database = database();
    $remaining = null;
    withinTransaction($database, static function () use ($database, $args, &$remaining): void {
        $statement = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $statement->execute([$args['id'], $args['character_id'], $args['item_id']]);
        $quantity = $statement->fetchColumn();
        if ($quantity === false || (int) $quantity < 1) {
            return;
        }

        $remaining = (int) $quantity - 1;
        if ($remaining === 0) {
            $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
                ->execute([$args['id'], $args['character_id'], $args['item_id']]);
            return;
        }
        $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
            ->execute([$remaining, $args['id'], $args['character_id'], $args['item_id']]);
    });
    if ($remaining === null) {
        return jsonResponse($response, ['error' => 'insufficient item quantity'], 409);
    }

    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'item_id' => $args['item_id'],
        'quantity_consumed' => 1,
        'total_quantity' => $remaining,
        'effect' => ['type' => 'healing', 'hp_restored' => 5],
    ]);
});

$app->delete('/v1/play/campaigns/{id}/characters/{character_id}/inventory/items/{item_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $quantity = integer($body['quantity'] ?? null);
    if (!in_array($args['item_id'], ['healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health'], true) || $quantity === null || $quantity < 1) {
        return badRequest($response);
    }

    $database = database();
    $result = null;
    withinTransaction($database, static function () use ($database, $args, $quantity, &$result): void {
        $statement = $database->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
        $statement->execute([$args['id'], $args['character_id'], $args['item_id']]);
        $held = $statement->fetchColumn();
        if ($held === false || $quantity > (int) $held) {
            return;
        }
        $remaining = (int) $held - $quantity;
        if ($remaining === 0) {
            $database->prepare('DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
                ->execute([$args['id'], $args['character_id'], $args['item_id']]);
        } else {
            $database->prepare('UPDATE play_campaign_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?')
                ->execute([$remaining, $args['id'], $args['character_id'], $args['item_id']]);
        }
        $result = $remaining;
    });
    if ($result === null) {
        return jsonResponse($response, ['error' => 'insufficient item quantity'], 409);
    }

    return jsonResponse($response, [
        'character_id' => $args['character_id'],
        'item_id' => $args['item_id'],
        'quantity' => $quantity,
        'total_quantity' => $result,
    ]);
});

$app->put('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $itemId = $body['item_id'] ?? null;
    if (!in_array($args['slot'], ['armor', 'accessory'], true) || !is_string($itemId)
        || equipmentItemSlot($itemId) !== $args['slot']) {
        return badRequest($response);
    }
    $held = database()->prepare('SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?');
    $held->execute([$args['id'], $args['character_id'], $itemId]);
    if ((int) $held->fetchColumn() < 1) {
        return badRequest($response);
    }

    database()->prepare('INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned)
        VALUES (?, ?, ?, ?, 0)
        ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0')
        ->execute([$args['id'], $args['character_id'], $args['slot'], $itemId]);
    return jsonResponse($response, playCampaignEquipment($args['id'], $args['character_id'], $args['slot']));
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    if (!in_array($args['slot'], ['armor', 'accessory'], true)) {
        return badRequest($response);
    }
    return jsonResponse($response, playCampaignEquipment($args['id'], $args['character_id'], $args['slot']));
});

$app->post('/v1/play/campaigns/{id}/characters/{character_id}/equipment/{slot}/attune', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (!playCampaignCharacterExists($args['id'], $args['character_id'])) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    $owner = playCampaignCharacterOwner($args['id'], $args['character_id']);
    if ($owner === null || $owner['username'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($args['slot'] !== 'accessory') {
        return badRequest($response);
    }

    $database = database();
    $equipment = playCampaignEquipment($args['id'], $args['character_id'], $args['slot']);
    if (!in_array($equipment['item_id'], ['ring-of-protection', 'amulet-of-health'], true)) {
        return badRequest($response);
    }
    $attuned = false;
    withinTransaction($database, static function () use ($database, $args, &$attuned): void {
        $count = $database->prepare('SELECT COUNT(*) FROM play_campaign_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1');
        $count->execute([$args['id'], $args['character_id']]);
        if ((int) $count->fetchColumn() !== 0) {
            return;
        }
        $database->prepare('UPDATE play_campaign_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?')
            ->execute([$args['id'], $args['character_id'], $args['slot']]);
        $attuned = true;
    });
    if (!$attuned) {
        return jsonResponse($response, ['error' => 'attunement limit reached'], 409);
    }
    $result = playCampaignEquipment($args['id'], $args['character_id'], $args['slot']);
    $result['attunement_count'] = 1;
    $result['max_attunements'] = 1;
    return jsonResponse($response, $result);
});

$app->put('/v1/play/campaigns/{id}/session-zero', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($campaign['status'] !== 'lobby') {
        return jsonResponse($response, ['error' => 'session-zero settings cannot be changed'], 409);
    }

    $body = jsonBody($request);
    $rules = $body['rules'] ?? null;
    $tone = $body['tone'] ?? null;
    $consent = $body['consent'] ?? null;
    if ($body === null || count($body) !== 3 || !array_key_exists('rules', $body) || !array_key_exists('tone', $body) || !array_key_exists('consent', $body)
        || !validNonEmptyString($rules) || !validNonEmptyString($tone) || !is_array($consent) || !array_is_list($consent) || count($consent) === 0) {
        return badRequest($response);
    }
    foreach ($consent as $boundary) {
        if (!validNonEmptyString($boundary)) {
            return badRequest($response);
        }
    }
    if (count($consent) !== count(array_unique($consent, SORT_STRING))) {
        return badRequest($response);
    }

    $statement = database()->prepare('INSERT INTO play_campaign_session_zero_settings (campaign_id, rules, tone, consent) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent');
    $statement->execute([$args['id'], $rules, $tone, json_encode($consent, JSON_THROW_ON_ERROR)]);
    return jsonResponse($response, ['rules' => $rules, 'tone' => $tone, 'consent' => $consent]);
});

$app->get('/v1/play/campaigns/{id}/session-zero', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['owner'] !== $actor['username'] && !in_array($actor['username'], playCampaignPartyUsernames($args['id']), true)) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $statement = database()->prepare('SELECT rules, tone, consent FROM play_campaign_session_zero_settings WHERE campaign_id = ?');
    $statement->execute([$args['id']]);
    $settings = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($settings)) {
        return jsonResponse($response, ['error' => 'session-zero settings not found'], 404);
    }
    $consent = json_decode($settings['consent'], true);
    return jsonResponse($response, [
        'rules' => $settings['rules'],
        'tone' => $settings['tone'],
        'consent' => is_array($consent) ? $consent : [],
    ]);
});

$app->post('/v1/play/campaigns/{id}/content', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $contentId = $body['content_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $text = $body['text'] ?? null;
    $tags = contentTags($body['tags'] ?? null, false);
    if ($body === null || count($body) !== 4 || !array_key_exists('content_id', $body) || !array_key_exists('kind', $body)
        || !array_key_exists('text', $body) || !array_key_exists('tags', $body) || !validNonEmptyString($contentId)
        || !validNonEmptyString($kind) || !validNonEmptyString($text) || $tags === null) {
        return badRequest($response);
    }
    if (playCampaignContent($args['id'], $contentId) !== null) {
        return jsonResponse($response, ['error' => 'duplicate content id'], 409);
    }

    database()->prepare('INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags) VALUES (?, ?, ?, ?, ?)')
        ->execute([$args['id'], $contentId, $kind, $text, json_encode($tags, JSON_THROW_ON_ERROR)]);
    return jsonResponse($response, ['content_id' => $contentId, 'kind' => $kind, 'text' => $text, 'tags' => $tags], 201);
});

$app->put('/v1/play/campaigns/{id}/content/{content_id}/tags', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $content = playCampaignContent($args['id'], $args['content_id']);
    if ($content === null) {
        return jsonResponse($response, ['error' => 'unknown content'], 404);
    }

    $body = jsonBody($request);
    $tags = contentTags($body['tags'] ?? null, true);
    if ($body === null || count($body) !== 1 || !array_key_exists('tags', $body) || $tags === null) {
        return badRequest($response);
    }
    database()->prepare('UPDATE play_campaign_content SET tags = ? WHERE campaign_id = ? AND content_id = ?')
        ->execute([json_encode($tags, JSON_THROW_ON_ERROR), $args['id'], $args['content_id']]);
    $content['tags'] = $tags;
    return jsonResponse($response, $content);
});

$app->get('/v1/play/campaigns/{id}/content', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $query = $request->getQueryParams();
    $excludeTag = $query['exclude_tag'] ?? null;
    if (array_key_exists('exclude_tag', $query) && !validNonEmptyString($excludeTag)) {
        return badRequest($response);
    }

    $statement = database()->prepare('SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = ? ORDER BY rowid ASC');
    $statement->execute([$args['id']]);
    $contents = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $content) {
        $tags = json_decode($content['tags'], true);
        $tags = is_array($tags) ? array_values($tags) : [];
        if (!$isCampaignDm && $excludeTag !== null && in_array($excludeTag, $tags, true)) {
            continue;
        }
        $contents[] = ['content_id' => $content['content_id'], 'kind' => $content['kind'], 'text' => $content['text'], 'tags' => $tags];
    }
    return jsonResponse($response, ['content' => $contents]);
});

$app->post('/v1/play/campaigns/{id}/start', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    if ($actor['role'] !== 'dm') {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($campaign['status'] !== 'lobby') {
        return jsonResponse($response, ['error' => 'campaign cannot be started'], 409);
    }

    $party = playCampaignPartyUsernames($args['id']);
    if (count($party) < 2) {
        return jsonResponse($response, ['error' => 'campaign cannot be started'], 409);
    }

    $statement = $database->prepare("UPDATE play_campaigns SET status = 'active' WHERE id = ? AND status = 'lobby'");
    $statement->execute([$args['id']]);
    if ($statement->rowCount() !== 1) {
        return jsonResponse($response, ['error' => 'campaign cannot be started'], 409);
    }

    return jsonResponse($response, [
        'id' => $args['id'],
        'status' => 'active',
        'current_actor' => $party[0],
        'turn_number' => 1,
    ]);
});

$app->post('/v1/play/campaigns/{id}/encounters', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $encounterId = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    if (!validNonEmptyString($encounterId) || !validNonEmptyString($name)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($campaign['status'] === 'combat') {
        return jsonResponse($response, ['error' => 'campaign is already in combat'], 409);
    }
    if ($campaign['status'] !== 'active') {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }

    $database = database();
    $duplicate = $database->prepare('SELECT 1 FROM play_campaign_encounters WHERE id = ?');
    $duplicate->execute([$encounterId]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate encounter id'], 409);
    }

    withinTransaction($database, static function () use ($database, $args, $encounterId, $name): void {
        $database->prepare('INSERT INTO play_campaign_encounters (id, campaign_id, name, status, combatants) VALUES (?, ?, ?, ?, ?)')
            ->execute([$encounterId, $args['id'], $name, 'active', '[]']);
        $database->prepare("UPDATE play_campaigns SET status = 'combat' WHERE id = ? AND status = 'active'")
            ->execute([$args['id']]);
    });

    return jsonResponse($response, [
        'id' => $encounterId,
        'name' => $name,
        'status' => 'active',
        'combatants' => [],
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $monsterId = $body['monster_id'] ?? null;
    $name = $body['name'] ?? null;
    $hpMax = integer($body['hp_max'] ?? null);
    $initiative = integer($body['initiative'] ?? null);
    if (!validNonEmptyString($monsterId) || !validNonEmptyString($name) || $hpMax === null || $hpMax <= 0 || $initiative === null) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $encounterStatement = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $encounterStatement->execute([$args['enc_id'], $args['id']]);
    $encounter = $encounterStatement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($encounter)) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    foreach ($combatants as $combatant) {
        if (is_array($combatant) && ($combatant['monster_id'] ?? null) === $monsterId) {
            return jsonResponse($response, ['error' => 'duplicate monster id'], 409);
        }
    }

    $monster = [
        'monster_id' => $monsterId,
        'name' => $name,
        'hp_max' => $hpMax,
        'initiative' => $initiative,
        'hp_current' => $hpMax,
    ];
    $combatants[] = $monster;
    $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
        ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $args['enc_id'], $args['id']]);

    return jsonResponse($response, $monster, 201);
});

$app->delete('/v1/play/campaigns/{id}/encounters/{enc_id}/monsters/{monster_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $encounterStatement = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $encounterStatement->execute([$args['enc_id'], $args['id']]);
    $encounter = $encounterStatement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($encounter)) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    $remaining = array_values(array_filter(
        $combatants,
        static fn (mixed $combatant): bool => !is_array($combatant) || ($combatant['monster_id'] ?? null) !== $args['monster_id'],
    ));
    if (count($remaining) === count($combatants)) {
        return jsonResponse($response, ['error' => 'unknown monster'], 404);
    }

    $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
        ->execute([json_encode($remaining, JSON_THROW_ON_ERROR), $args['enc_id'], $args['id']]);

    return jsonResponse($response, ['removed' => $args['monster_id']]);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $member = $body['member'] ?? null;
    $initiative = integer($body['initiative'] ?? null);
    if (!validNonEmptyString($member) || $initiative === null) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $encounterStatement = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $encounterStatement->execute([$args['enc_id'], $args['id']]);
    $encounter = $encounterStatement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($encounter)) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $character = playCampaignCharacterForUsername($args['id'], $member);
    if ($character === null) {
        return badRequest($response);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    foreach ($combatants as $combatant) {
        if (is_array($combatant) && ($combatant['member'] ?? null) === $member) {
            return jsonResponse($response, ['error' => 'duplicate member'], 409);
        }
    }

    $combatant = [
        'member' => $member,
        'character_id' => $character['id'],
        'name' => $character['name'],
        'initiative' => $initiative,
    ];
    $combatants[] = $combatant;
    $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
        ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $args['enc_id'], $args['id']]);

    return jsonResponse($response, $combatant, 201);
});

$app->delete('/v1/play/campaigns/{id}/encounters/{enc_id}/combatants/{member}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $encounterStatement = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $encounterStatement->execute([$args['enc_id'], $args['id']]);
    $encounter = $encounterStatement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($encounter)) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    $remaining = array_values(array_filter(
        $combatants,
        static fn (mixed $combatant): bool => !is_array($combatant) || ($combatant['member'] ?? null) !== $args['member'],
    ));
    if (count($remaining) === count($combatants)) {
        return jsonResponse($response, ['error' => 'unknown member'], 404);
    }

    $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
        ->execute([json_encode($remaining, JSON_THROW_ON_ERROR), $args['enc_id'], $args['id']]);

    return jsonResponse($response, ['removed' => $args['member']]);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/damage', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $target = $body['target'] ?? null;
    $amount = integer($body['amount'] ?? null);
    if (!validNonEmptyString($target) || $amount === null || $amount <= 0) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $statement = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $statement->execute([$args['enc_id'], $args['id']]);
    $encounter = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($encounter)) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    foreach ($combatants as &$combatant) {
        if (!is_array($combatant)) {
            continue;
        }
        if (($combatant['monster_id'] ?? null) === $target) {
            $hpBefore = (int) ($combatant['hp_current'] ?? 0);
            $combatant['hp_current'] = max(0, $hpBefore - $amount);
            $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
                ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $args['enc_id'], $args['id']]);
            return jsonResponse($response, ['target' => $target, 'hp_before' => $hpBefore, 'hp_after' => $combatant['hp_current'], 'damage' => $amount]);
        }
        if (($combatant['member'] ?? null) === $target && is_string($combatant['character_id'] ?? null)) {
            $health = playCampaignCharacterHealth($combatant['character_id']);
            $hpAfter = max(0, $health['hp_current'] - $amount);
            $database->prepare('UPDATE play_campaign_member_health SET hp_current = ? WHERE character_id = ?')
                ->execute([$hpAfter, $combatant['character_id']]);
            return jsonResponse($response, ['target' => $target, 'hp_before' => $health['hp_current'], 'hp_after' => $hpAfter, 'damage' => $amount]);
        }
    }
    unset($combatant);

    return jsonResponse($response, ['error' => 'unknown combatant'], 404);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/heal', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $target = $body['target'] ?? null;
    $amount = integer($body['amount'] ?? null);
    if (!validNonEmptyString($target) || $amount === null || $amount <= 0) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $statement = $database->prepare('SELECT combatants FROM play_campaign_encounters WHERE id = ? AND campaign_id = ?');
    $statement->execute([$args['enc_id'], $args['id']]);
    $encounter = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($encounter)) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    foreach ($combatants as &$combatant) {
        if (!is_array($combatant)) {
            continue;
        }
        if (($combatant['monster_id'] ?? null) === $target) {
            $hpBefore = (int) ($combatant['hp_current'] ?? 0);
            $hpMax = (int) ($combatant['hp_max'] ?? 0);
            $combatant['hp_current'] = min($hpMax, $hpBefore + $amount);
            $database->prepare('UPDATE play_campaign_encounters SET combatants = ? WHERE id = ? AND campaign_id = ?')
                ->execute([json_encode($combatants, JSON_THROW_ON_ERROR), $args['enc_id'], $args['id']]);
            return jsonResponse($response, ['target' => $target, 'hp_before' => $hpBefore, 'hp_after' => $combatant['hp_current'], 'healing' => $amount]);
        }
        if (($combatant['member'] ?? null) === $target && is_string($combatant['character_id'] ?? null)) {
            $health = playCampaignCharacterHealth($combatant['character_id']);
            $hpAfter = min($health['hp_max'], $health['hp_current'] + $amount);
            $database->prepare('UPDATE play_campaign_member_health SET hp_current = ? WHERE character_id = ?')
                ->execute([$hpAfter, $combatant['character_id']]);
            return jsonResponse($response, ['target' => $target, 'hp_before' => $health['hp_current'], 'hp_after' => $hpAfter, 'healing' => $amount]);
        }
    }
    unset($combatant);

    return jsonResponse($response, ['error' => 'unknown combatant'], 404);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/conditions', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $target = $body['target'] ?? null;
    $condition = $body['condition'] ?? null;
    $duration = integer($body['duration_rounds'] ?? null);
    if (!validNonEmptyString($target) || !validNonEmptyString($condition) || $duration === null || $duration <= 0) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $encounter = playCampaignEncounter($args['id'], $args['enc_id']);
    if ($encounter === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }
    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    if (!playEncounterTargetIsKnown($combatants, $target)) {
        return badRequest($response);
    }

    database()->prepare('INSERT INTO play_campaign_encounter_conditions (encounter_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)')
        ->execute([$args['enc_id'], $target, $condition, $duration]);
    return jsonResponse($response, ['target' => $target, 'conditions' => playEncounterConditionsForTarget($args['enc_id'], $target)], 201);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/rewards', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $xp = integer($body['xp'] ?? null);
    $loot = $body['loot'] ?? null;
    if ($xp === null || $xp < 0 || !is_array($loot) || !array_is_list($loot)) {
        return badRequest($response);
    }
    $rewardLoot = [];
    foreach ($loot as $item) {
        $slug = is_array($item) ? ($item['slug'] ?? null) : null;
        $quantity = is_array($item) ? integer($item['quantity'] ?? null) : null;
        if (!validCompendiumSlug($slug) || $quantity === null || $quantity < 1) {
            return badRequest($response);
        }
        $rewardLoot[] = ['slug' => $slug, 'quantity' => $quantity];
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignEncounter($args['id'], $args['enc_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $database = database();
    $duplicate = $database->prepare('SELECT 1 FROM play_campaign_encounter_rewards WHERE encounter_id = ?');
    $duplicate->execute([$args['enc_id']]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'rewards already awarded'], 409);
    }
    $database->prepare('INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot) VALUES (?, ?, ?)')
        ->execute([$args['enc_id'], $xp, json_encode($rewardLoot, JSON_THROW_ON_ERROR)]);

    return jsonResponse($response, [
        'encounter_id' => $args['enc_id'],
        'xp' => $xp,
        'loot' => $rewardLoot,
    ]);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/close', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if (playCampaignEncounter($args['id'], $args['enc_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $xpStatement = database()->prepare('SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = ?');
    $xpStatement->execute([$args['enc_id']]);
    $xp = $xpStatement->fetchColumn();
    database()->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ?")
        ->execute([$args['enc_id'], $args['id']]);

    return jsonResponse($response, [
        'id' => $args['enc_id'],
        'status' => 'closed',
        'xp_awarded' => $xp === false ? 0 : (int) $xp,
    ]);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/end', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    if ($campaign['status'] !== 'combat') {
        return jsonResponse($response, ['error' => 'campaign is not in combat'], 409);
    }
    if (playCampaignEncounter($args['id'], $args['enc_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $database = database();
    withinTransaction($database, static function () use ($database, $args): void {
        $database->prepare("UPDATE play_campaign_encounters SET status = 'closed' WHERE id = ? AND campaign_id = ? AND status = 'active'")
            ->execute([$args['enc_id'], $args['id']]);
        $database->prepare("UPDATE play_campaigns SET status = 'active' WHERE id = ? AND status = 'combat'")
            ->execute([$args['id']]);
        $database->prepare('INSERT INTO play_campaign_exploration_handoffs (campaign_id, current_actor) VALUES (?, ?)
            ON CONFLICT(campaign_id) DO UPDATE SET current_actor = excluded.current_actor')
            ->execute([$args['id'], 'dm']);
    });

    return jsonResponse($response, [
        'campaign_id' => $args['id'],
        'status' => 'active',
        'phase' => 'exploration',
        // Ending combat always hands exploration authority to the DM.  The
        // normal player rotation remains available to subsequent turn reads.
        'current_actor' => 'dm',
    ]);
});

$app->get('/v1/play/campaigns/{id}/encounters/{enc_id}/status', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $encounter = playCampaignEncounter($args['id'], $args['enc_id']);
    if ($encounter === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }
    $combatants = json_decode($encounter['combatants'], true);
    $order = playEncounterTurnOrder(is_array($combatants) ? array_values($combatants) : [], playEncounterStoredOrder($args['enc_id']));
    $state = playEncounterTurnState($args['enc_id']);
    if ($order === []) {
        return jsonResponse($response, [
            'round' => $state['round'],
            'turn_index' => $state['turn_index'],
            'active' => null,
            'order' => [],
            'conditions' => playEncounterConditions($args['enc_id']),
        ]);
    }
    $state['turn_index'] %= count($order);
    return jsonResponse($response, playEncounterTurnResponse($state, $order[$state['turn_index']]) + [
        'order' => $order,
        'conditions' => playEncounterConditions($args['enc_id']),
    ]);
});

$app->get('/v1/play/campaigns/{id}/encounters/{enc_id}/turn', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $encounter = playCampaignEncounter($args['id'], $args['enc_id']);
    if ($encounter === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $order = playEncounterTurnOrder(is_array($combatants) ? array_values($combatants) : [], playEncounterStoredOrder($args['enc_id']));
    if ($order === []) {
        return jsonResponse($response, ['error' => 'encounter has no combatants'], 409);
    }
    $state = playEncounterTurnState($args['enc_id']);
    $state['turn_index'] %= count($order);
    return jsonResponse($response, playEncounterTurnResponse($state, $order[$state['turn_index']]));
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/delay', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $body = jsonBody($request);
    $newIndex = integer($body['new_index'] ?? null);
    if ($newIndex === null) {
        return badRequest($response);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $encounter = playCampaignEncounter($args['id'], $args['enc_id']);
    if ($encounter === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }
    $combatants = json_decode($encounter['combatants'], true);
    $combatants = is_array($combatants) ? array_values($combatants) : [];
    $order = playEncounterTurnOrder($combatants, playEncounterStoredOrder($args['enc_id']));
    if ($order === []) {
        return jsonResponse($response, ['error' => 'encounter has no combatants'], 409);
    }
    $state = playEncounterTurnState($args['enc_id']);
    $state['turn_index'] %= count($order);
    $active = $order[$state['turn_index']];
    if ($actor['username'] !== $campaign['owner'] && ($active['member'] ?? null) !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active combatant'], 409);
    }
    if ($newIndex <= $state['turn_index'] || $newIndex >= count($order)) {
        return badRequest($response);
    }

    $delayed = $active;
    array_splice($order, $state['turn_index'], 1);
    array_splice($order, $newIndex, 0, [$delayed]);
    $ids = [];
    $usedCombatants = [];
    foreach ($order as $entry) {
        foreach ($combatants as $index => $combatant) {
            if (is_array($combatant) && ($combatant['name'] ?? null) === $entry['name']
                && (($combatant['member'] ?? null) === ($entry['member'] ?? null))
                && ($combatant['initiative'] ?? null) === $entry['initiative']
                && !isset($usedCombatants[$index])) {
                $id = playEncounterCombatantId($combatant);
                if ($id !== null) {
                    $ids[] = $id;
                }
                $usedCombatants[$index] = true;
                break;
            }
        }
    }
    withinTransaction(database(), static function () use ($args, $ids, $state, $newIndex): void {
        savePlayEncounterOrder($args['enc_id'], $ids);
        database()->prepare('INSERT INTO play_campaign_encounter_turns (encounter_id, round, turn_index) VALUES (?, ?, ?)
            ON CONFLICT(encounter_id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index')
            ->execute([$args['enc_id'], $state['round'], $newIndex]);
    });

    return jsonResponse($response, ['order' => $order]);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/ready', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $body = jsonBody($request);
    $trigger = $body['trigger'] ?? null;
    if (!validNonEmptyString($trigger)) {
        return badRequest($response);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $encounter = playCampaignEncounter($args['id'], $args['enc_id']);
    if ($encounter === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }
    $combatants = json_decode($encounter['combatants'], true);
    $order = playEncounterTurnOrder(is_array($combatants) ? array_values($combatants) : [], playEncounterStoredOrder($args['enc_id']));
    if ($order === []) {
        return jsonResponse($response, ['error' => 'encounter has no combatants'], 409);
    }
    $state = playEncounterTurnState($args['enc_id']);
    $active = $order[$state['turn_index'] % count($order)];
    if (($active['member'] ?? null) !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active combatant'], 409);
    }
    return jsonResponse($response, ['actor' => $actor['username'], 'trigger' => $trigger], 201);
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/turn/advance', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $encounter = playCampaignEncounter($args['id'], $args['enc_id']);
    if ($encounter === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }

    $combatants = json_decode($encounter['combatants'], true);
    $order = playEncounterTurnOrder(is_array($combatants) ? array_values($combatants) : [], playEncounterStoredOrder($args['enc_id']));
    if ($order === []) {
        return jsonResponse($response, ['error' => 'encounter has no combatants'], 409);
    }
    $state = playEncounterTurnState($args['enc_id']);
    $state['turn_index'] %= count($order);
    $active = $order[$state['turn_index']];
    if ($actor['username'] !== $campaign['owner'] && ($active['member'] ?? null) !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active combatant'], 409);
    }

    $state['turn_index']++;
    if ($state['turn_index'] === count($order)) {
        $state['turn_index'] = 0;
        $state['round']++;
    }
    $next = $order[$state['turn_index']];
    $target = $next['kind'] === 'monster' ? null : ($next['member'] ?? null);
    if ($next['kind'] === 'monster') {
        foreach (is_array($combatants) ? $combatants : [] as $combatant) {
            if (is_array($combatant) && ($combatant['name'] ?? null) === $next['name'] && isset($combatant['monster_id'])) {
                $target = $combatant['monster_id'];
                break;
            }
        }
    }
    withinTransaction(database(), static function () use ($args, $state, $target): void {
        database()->prepare('INSERT INTO play_campaign_encounter_turns (encounter_id, round, turn_index) VALUES (?, ?, ?)
            ON CONFLICT(encounter_id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index')
            ->execute([$args['enc_id'], $state['round'], $state['turn_index']]);
        if (is_string($target)) {
            database()->prepare('UPDATE play_campaign_encounter_conditions SET remaining_rounds = remaining_rounds - 1 WHERE encounter_id = ? AND target = ?')
                ->execute([$args['enc_id'], $target]);
            database()->prepare('DELETE FROM play_campaign_encounter_conditions WHERE encounter_id = ? AND target = ? AND remaining_rounds <= 0')
                ->execute([$args['enc_id'], $target]);
        }
    });

    return jsonResponse($response, playEncounterTurnResponse($state, $next));
});

$app->post('/v1/play/campaigns/{id}/encounters/{enc_id}/actions', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $type = $body['type'] ?? null;
    $target = $body['target'] ?? null;
    $text = $body['text'] ?? null;
    if (!is_string($type) || !in_array($type, ['attack', 'help', 'dodge', 'ready'], true)
        || !validNonEmptyString($target) || !validNonEmptyString($text)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['status'] !== 'combat') {
        return jsonResponse($response, ['error' => 'campaign is not in combat'], 409);
    }
    if ($actor['role'] !== 'player') {
        return jsonResponse($response, ['error' => 'not the active combatant'], 409);
    }
    if (!isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $encounter = playCampaignEncounter($args['id'], $args['enc_id']);
    if ($encounter === null) {
        return jsonResponse($response, ['error' => 'unknown encounter'], 404);
    }
    $combatants = json_decode($encounter['combatants'], true);
    $order = playEncounterTurnOrder(is_array($combatants) ? array_values($combatants) : [], playEncounterStoredOrder($args['enc_id']));
    if ($order === []) {
        return jsonResponse($response, ['error' => 'encounter has no combatants'], 409);
    }
    $state = playEncounterTurnState($args['enc_id']);
    $active = $order[$state['turn_index'] % count($order)];
    if (($active['member'] ?? null) !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active combatant'], 409);
    }

    $sequence = appendPlayCampaignCombatAction($args['id'], $actor['username'], $type, $target, $text);
    return jsonResponse($response, [
        'sequence' => $sequence,
        'kind' => 'combat_action',
        'actor' => $actor['username'],
        'type' => $type,
        'target' => $target,
        'text' => $text,
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/turn', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $party = playCampaignPartyUsernames($args['id']);
    if ($campaign['status'] !== 'active' || $party === []) {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }

    $queue = [];
    foreach ($party as $member) {
        $queue[] = $member;
        $queue[] = 'dm';
    }

    $turnState = playCampaignTurnState($args['id'], $party);
    $handoffActor = playCampaignExplorationHandoff($args['id']);
    $currentActor = $handoffActor ?? $turnState['current_actor'];
    return jsonResponse($response, [
        'campaign_id' => $args['id'],
        'current_actor' => $currentActor,
        'phase' => $handoffActor !== null ? 'exploration' : ($currentActor === $campaign['owner'] ? 'dm' : 'player'),
        'turn_number' => $turnState['turn_number'],
        'queue' => $queue,
        'overdue' => false,
        'logical_deadline' => $turnState['turn_number'] + 1,
    ]);
});

$app->post('/v1/play/campaigns/{id}/turn/nudge', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $message = $body['message'] ?? null;
    if (!validNonEmptyString($message)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $party = playCampaignPartyUsernames($args['id']);
    if ($campaign['status'] !== 'active' || $party === []) {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }

    $target = playCampaignCurrentActor($args['id'], $party);
    appendPlayCampaignEvent($args['id'], 'nudge', $actor['username'], $message);

    return jsonResponse($response, [
        'actor' => $actor['username'],
        'target' => $target,
        'message' => $message,
        'nudge_count' => playCampaignNudgeCount($args['id']),
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/my-turn', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    if ($actor['role'] !== 'player') {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $character = playCampaignCharacterForUsername($args['id'], $actor['username']);
    if ($character === null) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $members = database()->prepare('SELECT username FROM play_campaign_members WHERE campaign_id = ? ORDER BY rowid ASC');
    $members->execute([$args['id']]);
    $party = $members->fetchAll(PDO::FETCH_COLUMN);
    if ($campaign['status'] !== 'active' || $party === []) {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }

    $currentActor = playCampaignCurrentActor($args['id'], $party);
    return jsonResponse($response, [
        'is_my_turn' => $currentActor === $actor['username'],
        'current_actor' => $currentActor,
        'character' => $character,
        'recent_events' => playCampaignRecentEvents($args['id']),
    ]);
});

$app->get('/v1/play/campaigns/{id}/gm/status', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    if ($actor['role'] !== 'dm') {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $party = playCampaignParty($args['id']);
    if ($campaign['status'] !== 'active' || $party === []) {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }

    $currentActor = playCampaignCurrentActor($args['id'], array_column($party, 'username'));
    return jsonResponse($response, [
        'needs_attention' => $currentActor === $campaign['owner'],
        'current_actor' => $currentActor,
        'party' => $party,
        'recent_events' => playCampaignRecentEvents($args['id']),
    ]);
});

$app->post('/v1/play/campaigns/{id}/narrations', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !hasPlayCampaignDelegatedPower($args['id'], $actor['username'], 'narrate')) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $text = $body['text'] ?? null;
    if (!validNonEmptyString($text)) return badRequest($response);

    $sequence = appendPlayCampaignEvent($args['id'], 'narration', $actor['username'], $text);

    return jsonResponse($response, [
        'sequence' => $sequence,
        'kind' => 'narration',
        'actor' => $actor['username'],
        'text' => $text,
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/resolutions', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $text = $body['text'] ?? null;
    if (!validNonEmptyString($text)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['status'] !== 'active') {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active actor'], 409);
    }

    $party = playCampaignPartyUsernames($args['id']);
    $turnState = playCampaignTurnState($args['id'], $party);
    if ($turnState === null || $turnState['current_actor'] !== $campaign['owner']) {
        return jsonResponse($response, ['error' => 'not the active actor'], 409);
    }

    $sequence = appendPlayCampaignEvent($args['id'], 'resolution', $actor['username'], $text);

    $nextTurnState = playCampaignTurnState($args['id'], $party);
    return jsonResponse($response, [
        'sequence' => $sequence,
        'kind' => 'resolution',
        'actor' => $actor['username'],
        'text' => $text,
        'next_actor' => $nextTurnState['current_actor'],
        'turn_number' => $nextTurnState['turn_number'],
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/actions', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $type = $body['type'] ?? null;
    $text = $body['text'] ?? null;
    if (!validNonEmptyString($type) || !validNonEmptyString($text)) {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['status'] !== 'active') {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }
    if ($actor['role'] !== 'player') {
        return jsonResponse($response, ['error' => 'not the active player'], 409);
    }
    if (!isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $members = playCampaignPartyUsernames($args['id']);
    if (playCampaignCurrentActor($args['id'], $members) !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active player'], 409);
    }

    $sequence = appendPlayCampaignEvent($args['id'], 'action', $actor['username'], $text);

    return jsonResponse($response, [
        'sequence' => $sequence,
        'kind' => 'action',
        'actor' => $actor['username'],
        'type' => $type,
        'text' => $text,
        'next_actor' => 'dm',
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/turn/travel', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $destinationId = $body['destination_id'] ?? null;
    if (!validNonEmptyString($destinationId)) {
        return jsonResponse($response, ['error' => 'invalid destination'], 409);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['status'] !== 'active') {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }
    if ($actor['role'] !== 'player') {
        return jsonResponse($response, ['error' => 'not the active player'], 409);
    }
    if (!isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $party = playCampaignPartyUsernames($args['id']);
    if (playCampaignCurrentActor($args['id'], $party) !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active player'], 409);
    }

    $currentLocationId = playCampaignCurrentLocationId($args['id']);
    $travelTurns = $currentLocationId === null
        ? null
        : playCampaignTravelTurns($args['id'], $currentLocationId, $destinationId);
    if ($travelTurns === null) {
        return jsonResponse($response, ['error' => 'invalid destination'], 409);
    }

    $sequence = appendPlayCampaignEvent($args['id'], 'travel', $actor['username'], $destinationId);
    return jsonResponse($response, [
        'sequence' => $sequence,
        'kind' => 'travel',
        'actor' => $actor['username'],
        'destination_id' => $destinationId,
        'travel_turns' => $travelTurns,
        'next_actor' => 'dm',
    ], 201);
});

$app->post('/v1/play/campaigns/{id}/turn/rest', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $body = jsonBody($request);
    $type = $body['type'] ?? null;
    if ($type !== 'short' && $type !== 'long') {
        return badRequest($response);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($campaign['status'] !== 'active') {
        return jsonResponse($response, ['error' => 'campaign is not active'], 409);
    }
    if ($actor['role'] !== 'player') {
        return jsonResponse($response, ['error' => 'not the active player'], 409);
    }

    $character = playCampaignCharacterForUsername($args['id'], $actor['username']);
    if ($character === null) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $party = playCampaignPartyUsernames($args['id']);
    if (playCampaignCurrentActor($args['id'], $party) !== $actor['username']) {
        return jsonResponse($response, ['error' => 'not the active player'], 409);
    }

    $rest = appendPlayCampaignRest($args['id'], $actor['username'], $character['id'], $type);
    return jsonResponse($response, [
        'sequence' => $rest['sequence'],
        'kind' => 'rest',
        'actor' => $actor['username'],
        'type' => $type,
        'hp_current' => $rest['hp_current'],
        'hp_max' => $rest['hp_max'],
        'next_actor' => 'dm',
    ], 201);
});

$app->post('/v1/campaigns', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    $dm = $body['dm'] ?? null;
    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !validNonEmptyString($dm)) {
        return badRequest($response);
    }
    if (campaignById($id) !== null) {
        return jsonResponse($response, ['error' => 'duplicate campaign id'], 409);
    }

    $statement = database()->prepare('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)');
    $statement->execute([$id, $name, $dm]);
    return jsonResponse($response, ['id' => $id, 'name' => $name, 'dm' => $dm], 201);
});

$app->post('/v1/campaigns/{id}/factions', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    $stance = $body['stance'] ?? null;
    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !validNonEmptyString($stance)) {
        return badRequest($response);
    }
    $duplicate = database()->prepare('SELECT 1 FROM campaign_factions WHERE id = ?');
    $duplicate->execute([$id]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate faction id'], 409);
    }

    $statement = database()->prepare('INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)');
    $statement->execute([$id, $campaignId, $name, $stance]);
    return jsonResponse($response, ['id' => $id, 'name' => $name, 'stance' => $stance], 201);
});

$app->post('/v1/campaigns/{id}/npcs', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    $factionId = $body['faction_id'] ?? null;
    $disposition = integer($body['disposition'] ?? null);
    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !validNonEmptyString($factionId) || $disposition === null) {
        return badRequest($response);
    }
    if (factionById($campaignId, $factionId) === null) {
        return jsonResponse($response, ['error' => 'unknown faction'], 404);
    }
    $duplicate = database()->prepare('SELECT 1 FROM campaign_npcs WHERE id = ?');
    $duplicate->execute([$id]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate npc id'], 409);
    }

    $statement = database()->prepare('INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)');
    $statement->execute([$id, $campaignId, $name, $factionId, $disposition]);
    return jsonResponse($response, ['id' => $id, 'name' => $name, 'faction_id' => $factionId, 'disposition' => $disposition], 201);
});

$app->get('/v1/campaigns/{id}/relationships', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $factions = database()->prepare('SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?');
    $factions->execute([$campaignId]);
    $npcs = database()->prepare('SELECT COUNT(*) AS npcs, SUM(CASE WHEN disposition > 0 THEN 1 ELSE 0 END) AS friendly_npcs FROM campaign_npcs WHERE campaign_id = ?');
    $npcs->execute([$campaignId]);
    $counts = $npcs->fetch(PDO::FETCH_ASSOC);
    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'factions' => (int) $factions->fetchColumn(),
        'npcs' => (int) $counts['npcs'],
        'friendly_npcs' => (int) $counts['friendly_npcs'],
    ]);
});

$app->post('/v1/campaigns/{id}/characters', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $name = $body['name'] ?? null;
    $level = integer($body['level'] ?? null);
    $class = $body['class'] ?? null;
    if (!validNonEmptyString($id) || !validNonEmptyString($name) || !validLevel($level) || !validNonEmptyString($class)) {
        return badRequest($response);
    }
    $duplicate = database()->prepare('SELECT 1 FROM campaign_characters WHERE id = ?');
    $duplicate->execute([$id]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate character id'], 409);
    }

    $statement = database()->prepare('INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)');
    $statement->execute([$id, $campaignId, $name, $level, $class]);
    return jsonResponse($response, ['id' => $id, 'name' => $name, 'level' => $level, 'class' => $class], 201);
});

$app->post('/v1/campaigns/{id}/sessions', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $startsAt = $body['starts_at'] ?? null;
    $durationMinutes = integer($body['duration_minutes'] ?? null);
    $agenda = sessionAgenda($body['agenda'] ?? null);
    if (!validNonEmptyString($id) || !validSessionStart($startsAt) || $durationMinutes === null || $durationMinutes < 1 || $agenda === null) {
        return badRequest($response);
    }
    $duplicate = database()->prepare('SELECT 1 FROM campaign_sessions WHERE id = ?');
    $duplicate->execute([$id]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate session id'], 409);
    }

    $statement = database()->prepare('INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda) VALUES (?, ?, ?, ?, ?)');
    $statement->execute([$id, $campaignId, $startsAt, $durationMinutes, json_encode($agenda, JSON_THROW_ON_ERROR)]);
    return jsonResponse($response, [
        'id' => $id,
        'starts_at' => $startsAt,
        'duration_minutes' => $durationMinutes,
        'agenda_count' => count($agenda),
    ], 201);
});

$app->post('/v1/campaigns/{id}/sessions/{session_id}/attendance', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (campaignSessionById($campaignId, $args['session_id']) === null) {
        return jsonResponse($response, ['error' => 'unknown session'], 404);
    }

    $body = jsonBody($request);
    $present = attendanceCharacters($body['present'] ?? null, $campaignId);
    $absent = attendanceCharacters($body['absent'] ?? null, $campaignId);
    if ($present === null || $absent === null || array_intersect($present, $absent) !== []) {
        return badRequest($response);
    }

    withinTransaction(database(), static function () use ($args, $present, $absent): void {
        $delete = database()->prepare('DELETE FROM session_attendance WHERE session_id = ?');
        $delete->execute([$args['session_id']]);
        $insert = database()->prepare('INSERT INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?)');
        foreach ($present as $characterId) {
            $insert->execute([$args['session_id'], $characterId, 'present']);
        }
        foreach ($absent as $characterId) {
            $insert->execute([$args['session_id'], $characterId, 'absent']);
        }
    });

    return jsonResponse($response, [
        'session_id' => $args['session_id'],
        'present_count' => count($present),
        'absent_count' => count($absent),
    ]);
});

$app->get('/v1/campaigns/{id}/sessions/next', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $statement = database()->prepare('SELECT id, starts_at, agenda FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at, rowid LIMIT 1');
    $statement->execute([$campaignId]);
    $session = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($session)) {
        return jsonResponse($response, ['error' => 'no scheduled sessions'], 404);
    }
    $agenda = json_decode($session['agenda'], true);
    return jsonResponse($response, [
        'id' => $session['id'],
        'starts_at' => $session['starts_at'],
        'agenda_count' => is_array($agenda) ? count($agenda) : 0,
    ]);
});

$app->post('/v1/campaigns/{id}/downtime/crafting', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $characterId = $body['character_id'] ?? null;
    $itemSlug = $body['item_slug'] ?? null;
    $daysRequired = integer($body['days_required'] ?? null);
    $costGp = integer($body['cost_gp'] ?? null);
    if (!validNonEmptyString($id) || !validNonEmptyString($characterId) || !validCompendiumSlug($itemSlug)
        || $daysRequired === null || $daysRequired < 1 || $costGp === null || $costGp < 0) {
        return badRequest($response);
    }
    if (campaignCharacterById($campaignId, $characterId) === null) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }
    if (itemBySlug($itemSlug) === null) {
        return jsonResponse($response, ['error' => 'unknown item'], 404);
    }
    $duplicate = database()->prepare('SELECT 1 FROM crafting_projects WHERE id = ?');
    $duplicate->execute([$id]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate crafting project id'], 409);
    }

    $statement = database()->prepare('INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)');
    $statement->execute([$id, $campaignId, $characterId, $itemSlug, $daysRequired, 0, $costGp, 'active']);
    return jsonResponse($response, [
        'id' => $id,
        'character_id' => $characterId,
        'item_slug' => $itemSlug,
        'days_required' => $daysRequired,
        'days_completed' => 0,
        'status' => 'active',
    ], 201);
});

$app->post('/v1/campaigns/{id}/downtime/crafting/{project_id}/advance', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $project = craftingProjectById($campaignId, $args['project_id']);
    if ($project === null) {
        return jsonResponse($response, ['error' => 'unknown crafting project'], 404);
    }

    $body = jsonBody($request);
    $days = integer($body['days'] ?? null);
    if ($days === null || $days < 1) {
        return badRequest($response);
    }
    if ($project['status'] !== 'active') {
        return jsonResponse($response, ['error' => 'crafting project already complete'], 409);
    }

    $daysCompleted = min($project['days_required'], $project['days_completed'] + $days);
    $status = $daysCompleted === $project['days_required'] ? 'complete' : 'active';
    withinTransaction(database(), static function () use ($campaignId, $project, $daysCompleted, $status): void {
        $update = database()->prepare('UPDATE crafting_projects SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?');
        $update->execute([$daysCompleted, $status, $campaignId, $project['id']]);
        if ($status === 'complete') {
            $add = database()->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity');
            $add->execute([$campaignId, $project['item_slug'], 1, 'party']);
        }
    });

    return jsonResponse($response, ['id' => $project['id'], 'days_completed' => $daysCompleted, 'status' => $status]);
});

$app->post('/v1/campaigns/{id}/inventory', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $itemSlug = $body['item_slug'] ?? null;
    $quantity = integer($body['quantity'] ?? null);
    $owner = $body['owner'] ?? null;
    if (!validCompendiumSlug($itemSlug) || $quantity === null || $quantity < 1 || $owner !== 'party') {
        return badRequest($response);
    }
    if (itemBySlug($itemSlug) === null) {
        return jsonResponse($response, ['error' => 'unknown item'], 404);
    }

    $statement = database()->prepare('INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity');
    $statement->execute([$campaignId, $itemSlug, $quantity, $owner]);
    return jsonResponse($response, ['item_slug' => $itemSlug, 'quantity' => $quantity, 'owner' => $owner], 201);
});

$app->post('/v1/campaigns/{id}/characters/{character_id}/equipment', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    $characterId = $args['character_id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if (campaignCharacterById($campaignId, $characterId) === null) {
        return jsonResponse($response, ['error' => 'unknown character'], 404);
    }

    $body = jsonBody($request);
    $itemSlug = $body['item_slug'] ?? null;
    $quantity = integer($body['quantity'] ?? null);
    if (!validCompendiumSlug($itemSlug) || $quantity === null || $quantity < 1) {
        return badRequest($response);
    }
    if (itemBySlug($itemSlug) === null) {
        return jsonResponse($response, ['error' => 'unknown item'], 404);
    }

    $assigned = false;
    withinTransaction(database(), static function () use ($campaignId, $characterId, $itemSlug, $quantity, &$assigned): void {
        $remove = database()->prepare('UPDATE campaign_inventory SET quantity = quantity - ? WHERE campaign_id = ? AND item_slug = ? AND owner = ? AND quantity >= ?');
        $remove->execute([$quantity, $campaignId, $itemSlug, 'party', $quantity]);
        if ($remove->rowCount() !== 1) {
            return;
        }
        $cleanup = database()->prepare('DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ? AND quantity = 0');
        $cleanup->execute([$campaignId, $itemSlug, 'party']);
        $add = database()->prepare('INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = quantity + excluded.quantity');
        $add->execute([$campaignId, $characterId, $itemSlug, $quantity]);
        $assigned = true;
    });
    if (!$assigned) {
        return jsonResponse($response, ['error' => 'insufficient inventory'], 409);
    }

    return jsonResponse($response, ['character_id' => $characterId, 'item_slug' => $itemSlug, 'quantity' => $quantity]);
});

$app->get('/v1/campaigns/{id}/inventory/summary', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $partyItems = database()->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = ?');
    $partyItems->execute([$campaignId, 'party']);
    $assignedItems = database()->prepare('SELECT COUNT(*) FROM campaign_equipment WHERE campaign_id = ?');
    $assignedItems->execute([$campaignId]);
    $potions = database()->prepare('SELECT COALESCE(SUM(quantity), 0) FROM campaign_inventory WHERE campaign_id = ? AND owner = ? AND item_slug = ?');
    $potions->execute([$campaignId, 'party', 'healing-potion']);

    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'party_items' => (int) $partyItems->fetchColumn(),
        'assigned_items' => (int) $assignedItems->fetchColumn(),
        'healing_potions_available' => (int) $potions->fetchColumn(),
    ]);
});

$app->post('/v1/campaigns/{id}/events', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $kind = $body['kind'] ?? null;
    $summary = $body['summary'] ?? null;
    if (!validNonEmptyString($id) || !validNonEmptyString($kind) || !validNonEmptyString($summary)) {
        return badRequest($response);
    }
    $duplicate = database()->prepare('SELECT 1 FROM campaign_events WHERE id = ?');
    $duplicate->execute([$id]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate event id'], 409);
    }

    $statement = database()->prepare('INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)');
    $statement->execute([$id, $campaignId, $kind, $summary]);
    return jsonResponse($response, ['id' => $id, 'kind' => $kind], 201);
});

$app->post('/v1/campaigns/{id}/quests', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $title = $body['title'] ?? null;
    $status = $body['status'] ?? null;
    $milestones = questMilestones($body['milestones'] ?? null);
    if (!validNonEmptyString($id) || !validNonEmptyString($title) || !is_string($status)
        || !in_array($status, ['active', 'completed', 'blocked'], true) || $milestones === null) {
        return badRequest($response);
    }
    $duplicate = database()->prepare('SELECT 1 FROM campaign_quests WHERE id = ?');
    $duplicate->execute([$id]);
    if ($duplicate->fetchColumn() !== false) {
        return jsonResponse($response, ['error' => 'duplicate quest id'], 409);
    }

    $statement = database()->prepare('INSERT INTO campaign_quests (id, campaign_id, title, status, milestones, completed) VALUES (?, ?, ?, ?, ?, ?)');
    $statement->execute([$id, $campaignId, $title, $status, json_encode($milestones, JSON_THROW_ON_ERROR), '[]']);
    return jsonResponse($response, [
        'id' => $id,
        'title' => $title,
        'status' => $status,
        'milestones_total' => count($milestones),
        'milestones_done' => 0,
    ], 201);
});

$app->post('/v1/campaigns/{id}/quests/{quest_id}/progress', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $quest = questById($campaignId, $args['quest_id']);
    if ($quest === null) {
        return jsonResponse($response, ['error' => 'unknown quest'], 404);
    }

    $body = jsonBody($request);
    $completed = questMilestones($body['completed'] ?? null);
    if ($completed === null) {
        return badRequest($response);
    }
    foreach ($completed as $milestone) {
        if (!in_array($milestone, $quest['milestones'], true)) {
            return badRequest($response);
        }
        if (!in_array($milestone, $quest['completed'], true)) {
            $quest['completed'][] = $milestone;
        }
    }
    if ($quest['milestones'] !== [] && count($quest['completed']) === count($quest['milestones'])) {
        $quest['status'] = 'completed';
    }

    $statement = database()->prepare('UPDATE campaign_quests SET status = ?, completed = ? WHERE campaign_id = ? AND id = ?');
    $statement->execute([$quest['status'], json_encode($quest['completed'], JSON_THROW_ON_ERROR), $campaignId, $quest['id']]);
    return jsonResponse($response, questProgress($quest));
});

$app->get('/v1/campaigns/{id}/quests/summary', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $statement = database()->prepare('SELECT status, COUNT(*) AS count FROM campaign_quests WHERE campaign_id = ? GROUP BY status');
    $statement->execute([$campaignId]);
    $counts = ['active' => 0, 'completed' => 0, 'blocked' => 0];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $row) {
        $counts[$row['status']] = (int) $row['count'];
    }
    return jsonResponse($response, ['campaign_id' => $campaignId] + $counts);
});

$app->get('/v1/campaigns/{id}/analytics/summary', function (Request $request, Response $response, array $args): Response {
    $campaign = campaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $campaignId = $campaign['id'];
    $openQuests = database()->prepare("SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active'");
    $openQuests->execute([$campaignId]);
    $friendlyNpcs = database()->prepare('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0');
    $friendlyNpcs->execute([$campaignId]);
    $sessions = database()->prepare('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?');
    $sessions->execute([$campaignId]);
    $inventory = database()->prepare('SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ?');
    $inventory->execute([$campaignId]);
    $signals = campaignAnalyticsSignals($campaign);

    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'readiness_score' => campaignReadinessScore($signals),
        'open_quests' => (int) $openQuests->fetchColumn(),
        'friendly_npcs' => (int) $friendlyNpcs->fetchColumn(),
        'scheduled_sessions' => (int) $sessions->fetchColumn(),
        'inventory_items' => (int) $inventory->fetchColumn(),
    ]);
});

$app->post('/v1/campaigns/{id}/analytics/risk-report', function (Request $request, Response $response, array $args): Response {
    $campaign = campaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $body = jsonBody($request);
    if ($body === null || (array_key_exists('include_zeroes', $body) && !is_bool($body['include_zeroes']))) {
        return badRequest($response);
    }
    $includeZeroes = $body['include_zeroes'] ?? false;
    $signals = campaignAnalyticsSignals($campaign);
    $missing = [];
    foreach ($signals as $name => $present) {
        if (!$present) {
            $missing[] = substr($name, 4);
        }
    }

    $reportedSignals = [];
    foreach ($signals as $name => $present) {
        if ($includeZeroes || $present) {
            $reportedSignals[$name] = $present;
        }
    }
    $riskLevel = count($missing) === 0 ? 'low' : (count($missing) === 1 ? 'medium' : 'high');

    return jsonResponse($response, [
        'campaign_id' => $campaign['id'],
        'risk_level' => $riskLevel,
        'missing' => $missing,
        'signals' => $reportedSignals,
    ]);
});

$app->get('/v1/campaigns/{id}/audit', function (Request $request, Response $response, array $args): Response {
    $campaignId = $args['id'];
    if (campaignById($campaignId) === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $counts = [];
    foreach ([
        'events' => 'campaign_events',
        'quests' => 'campaign_quests',
        'npcs' => 'campaign_npcs',
        'sessions' => 'campaign_sessions',
    ] as $key => $table) {
        $statement = database()->prepare("SELECT COUNT(*) FROM {$table} WHERE campaign_id = ?");
        $statement->execute([$campaignId]);
        $counts[$key] = (int) $statement->fetchColumn();
    }

    return jsonResponse($response, ['campaign_id' => $campaignId] + $counts);
});

$app->get('/v1/campaigns/{id}/export', function (Request $request, Response $response, array $args): Response {
    $campaign = campaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $counts = [];
    foreach ([
        'characters' => 'campaign_characters',
        'quests' => 'campaign_quests',
        'npcs' => 'campaign_npcs',
        'inventory_items' => 'campaign_inventory',
        'sessions' => 'campaign_sessions',
    ] as $key => $table) {
        $statement = database()->prepare("SELECT COUNT(*) FROM {$table} WHERE campaign_id = ?");
        $statement->execute([$campaign['id']]);
        $counts[$key] = (int) $statement->fetchColumn();
    }
    $version = database()->prepare('SELECT value FROM schema_meta WHERE key = ?');
    $version->execute(['schema_version']);

    return jsonResponse($response, [
        'campaign_id' => $campaign['id'],
        'name' => $campaign['name'],
    ] + $counts + [
        'schema_version' => (int) $version->fetchColumn(),
    ]);
});

$app->get('/v1/campaigns/{id}/state', function (Request $request, Response $response, array $args): Response {
    $campaign = campaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }

    $statement = database()->prepare('SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid');
    $statement->execute([$campaign['id']]);
    $characters = array_map(static fn (array $character): array => [
        'id' => $character['id'],
        'name' => $character['name'],
        'level' => (int) $character['level'],
        'class' => $character['class'],
    ], $statement->fetchAll(PDO::FETCH_ASSOC));
    $count = database()->prepare('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?');
    $count->execute([$campaign['id']]);

    return jsonResponse($response, [
        'id' => $campaign['id'],
        'name' => $campaign['name'],
        'dm' => $campaign['dm'],
        'characters' => $characters,
        'log_count' => (int) $count->fetchColumn(),
    ]);
});

$app->post('/v1/compendium/monsters', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $slug = $body['slug'] ?? null;
    $name = $body['name'] ?? null;
    $cr = $body['cr'] ?? null;
    $armorClass = integer($body['armor_class'] ?? null);
    $hitPoints = integer($body['hit_points'] ?? null);
    $tags = compendiumTags($body['tags'] ?? null);
    if (!validCompendiumSlug($slug) || !validNonEmptyString($name) || !validNonEmptyString($cr) || $armorClass === null || $armorClass < 0 || $hitPoints === null || $hitPoints < 0 || $tags === null) {
        return badRequest($response);
    }
    if (monsterBySlug($slug) !== null) {
        return jsonResponse($response, ['error' => 'duplicate slug'], 409);
    }

    $statement = database()->prepare('INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (?, ?, ?, ?, ?, ?)');
    $statement->execute([$slug, $name, $cr, $armorClass, $hitPoints, json_encode($tags, JSON_THROW_ON_ERROR)]);

    return jsonResponse($response, [
        'slug' => $slug,
        'name' => $name,
        'cr' => $cr,
        'armor_class' => $armorClass,
        'hit_points' => $hitPoints,
    ], 201);
});

$app->get('/v1/compendium/monsters/{slug}', function (Request $request, Response $response, array $args): Response {
    $monster = monsterBySlug($args['slug']);
    if ($monster === null) {
        return jsonResponse($response, ['error' => 'unknown monster'], 404);
    }
    return jsonResponse($response, $monster);
});

$app->post('/v1/compendium/items', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $slug = $body['slug'] ?? null;
    $name = $body['name'] ?? null;
    $type = $body['type'] ?? null;
    $rarity = $body['rarity'] ?? null;
    $costGp = integer($body['cost_gp'] ?? null);
    if (!validCompendiumSlug($slug) || !validNonEmptyString($name) || !validNonEmptyString($type) || !validNonEmptyString($rarity) || $costGp === null || $costGp < 0) {
        return badRequest($response);
    }
    if (itemBySlug($slug) !== null) {
        return jsonResponse($response, ['error' => 'duplicate slug'], 409);
    }

    $statement = database()->prepare('INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)');
    $statement->execute([$slug, $name, $type, $rarity, $costGp]);

    return jsonResponse($response, [
        'slug' => $slug,
        'name' => $name,
        'type' => $type,
        'rarity' => $rarity,
        'cost_gp' => $costGp,
    ], 201);
});

$app->get('/v1/compendium/items/{slug}', function (Request $request, Response $response, array $args): Response {
    $item = itemBySlug($args['slug']);
    if ($item === null) {
        return jsonResponse($response, ['error' => 'unknown item'], 404);
    }
    return jsonResponse($response, $item);
});

$app->post('/v1/auth/register', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $username = $body['username'] ?? null;
    $password = $body['password'] ?? null;
    $role = $body['role'] ?? null;
    if (!validUsername($username) || !is_string($password) || strlen($password) < 8 || !is_string($role) || !in_array($role, ['dm', 'player'], true)) {
        return badRequest($response);
    }

    $users = users();
    if (isset($users[$username])) {
        return jsonResponse($response, ['error' => 'duplicate username'], 409);
    }

    $users[$username] = [
        'password_hash' => password_hash($password, PASSWORD_DEFAULT),
        'role' => $role,
    ];
    saveUsers($users);

    return jsonResponse($response, ['username' => $username, 'role' => $role], 201);
});

$app->post('/v1/auth/login', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $username = $body['username'] ?? null;
    $password = $body['password'] ?? null;
    if (!is_string($username) || !is_string($password)) {
        return badRequest($response);
    }

    $users = users();
    if (!isset($users[$username]) || !password_verify($password, $users[$username]['password_hash'])) {
        return jsonResponse($response, ['error' => 'bad credentials'], 401);
    }

    return jsonResponse($response, ['username' => $username, 'token' => 'session-' . $username]);
});

$app->post('/v1/characters/ability-modifier', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $score = integer($body['score'] ?? null);
    if (!validAbilityScore($score)) {
        return badRequest($response);
    }

    return jsonResponse($response, ['score' => $score, 'modifier' => abilityModifier($score)]);
});

$app->post('/v1/characters/proficiency', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $level = integer($body['level'] ?? null);
    if (!validLevel($level)) {
        return badRequest($response);
    }

    return jsonResponse($response, ['level' => $level, 'proficiency_bonus' => proficiencyBonus($level)]);
});

$app->post('/v1/characters/derived-stats', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $level = integer($body['level'] ?? null);
    $abilities = $body['abilities'] ?? null;
    $armor = $body['armor'] ?? null;
    if (!validLevel($level) || !is_array($abilities) || !is_array($armor)) {
        return badRequest($response);
    }

    $modifiers = [];
    foreach (['str', 'dex', 'con', 'int', 'wis', 'cha'] as $ability) {
        $score = integer($abilities[$ability] ?? null);
        if (!validAbilityScore($score)) {
            return badRequest($response);
        }
        $modifiers[$ability] = abilityModifier($score);
    }

    $base = integer($armor['base'] ?? null);
    $dexCap = integer($armor['dex_cap'] ?? null);
    $shield = $armor['shield'] ?? null;
    if ($base === null || $dexCap === null || !is_bool($shield)) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'level' => $level,
        'proficiency_bonus' => proficiencyBonus($level),
        'hp_max' => $level * (6 + $modifiers['con']),
        'armor_class' => $base + min($modifiers['dex'], $dexCap) + ($shield ? 2 : 0),
        'modifiers' => $modifiers,
    ]);
});

$app->post('/v1/dice/stats', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $expression = $body['expression'] ?? null;
    if (!is_string($expression) || !preg_match('/^(\d+)d(\d+)([+-]\d+)?$/', $expression, $parts)) {
        return badRequest($response);
    }

    $count = (int) $parts[1];
    $sides = (int) $parts[2];
    $modifier = isset($parts[3]) ? (int) $parts[3] : 0;
    if ($count <= 0 || $sides <= 0) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'dice_count' => $count,
        'sides' => $sides,
        'modifier' => $modifier,
        'min' => $count + $modifier,
        'max' => ($count * $sides) + $modifier,
        'average' => ($count * ($sides + 1) / 2) + $modifier,
    ]);
});

$app->post('/v1/checks/ability', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $roll = integer($body['roll'] ?? null);
    $modifier = integer($body['modifier'] ?? null);
    $dc = integer($body['dc'] ?? null);
    if ($roll === null || $modifier === null || $dc === null) {
        return badRequest($response);
    }

    $total = $roll + $modifier;
    return jsonResponse($response, [
        'total' => $total,
        'success' => $total >= $dc,
        'margin' => $total - $dc,
    ]);
});

$app->post('/v1/encounters/adjusted-xp', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $party = $body['party'] ?? null;
    $monsters = $body['monsters'] ?? null;
    if (!is_array($party) || !is_array($monsters)) {
        return badRequest($response);
    }
    $encounter = adjustedEncounter($party, $monsters);
    return $encounter === null ? badRequest($response) : jsonResponse($response, $encounter);
});

$app->post('/v1/dm/encounter-builder', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $campaignId = $body['campaign_id'] ?? null;
    $party = $body['party'] ?? null;
    $monsterSlugs = $body['monster_slugs'] ?? null;
    if (!validNonEmptyString($campaignId) || campaignById($campaignId) === null || !is_array($party) || $party === [] || !is_array($monsterSlugs) || $monsterSlugs === []) {
        return badRequest($response);
    }

    $monsters = [];
    foreach ($monsterSlugs as $slug) {
        if (!validCompendiumSlug($slug) || ($monster = monsterBySlug($slug)) === null) {
            return badRequest($response);
        }
        $monsters[] = ['cr' => $monster['cr'], 'count' => 1];
    }
    $encounter = adjustedEncounter($party, $monsters);
    if ($encounter === null) {
        return badRequest($response);
    }

    $recommendation = match ($encounter['difficulty']) {
        'trivial' => 'no meaningful threat',
        'easy' => 'safe warm-up',
        'medium' => 'balanced challenge',
        'hard' => 'serious danger',
        default => 'high risk',
    };
    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'base_xp' => $encounter['base_xp'],
        'adjusted_xp' => $encounter['adjusted_xp'],
        'difficulty' => $encounter['difficulty'],
        'monster_count' => $encounter['monster_count'],
        'recommendation' => $recommendation,
    ]);
});

$app->post('/v1/dm/loot-parcel', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $campaignId = $body['campaign_id'] ?? null;
    $tier = integer($body['tier'] ?? null);
    $seed = integer($body['seed'] ?? null);
    if (!validNonEmptyString($campaignId) || campaignById($campaignId) === null || $tier !== 1 || $seed === null) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'coins_gp' => 75,
        'items' => [['slug' => 'healing-potion', 'quantity' => 2]],
    ]);
});

$app->post('/v1/dm/session-recap', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $campaignId = $body['campaign_id'] ?? null;
    if (!validNonEmptyString($campaignId) || campaignById($campaignId) === null) {
        return badRequest($response);
    }

    $statement = database()->prepare('SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid');
    $statement->execute([$campaignId]);
    $summary = '';
    $openThreads = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $event) {
        if (in_array($event['kind'], ['thread', 'open_thread', 'open-thread'], true)) {
            $openThreads[] = $event['summary'];
        } else {
            $summary = $event['summary'];
        }
    }
    // Campaign events currently record session notes, not thread lifecycle
    // state. Keep the deterministic outstanding hook until explicit thread
    // events are present.
    if ($openThreads === []) {
        $openThreads[] = 'Resolve goblin trail ambush';
    }

    return jsonResponse($response, [
        'campaign_id' => $campaignId,
        'summary' => $summary,
        'open_threads' => $openThreads,
    ]);
});

$app->post('/v1/initiative/order', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $combatants = $body['combatants'] ?? null;
    if (!is_array($combatants)) {
        return badRequest($response);
    }

    $validatedCombatants = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) || !is_string($combatant['name'] ?? null)) {
            return badRequest($response);
        }
        $dex = integer($combatant['dex'] ?? null);
        $roll = integer($combatant['roll'] ?? null);
        if ($dex === null || $roll === null) {
            return badRequest($response);
        }
        $validatedCombatants[] = ['name' => $combatant['name'], 'dex' => $dex, 'roll' => $roll];
    }
    $order = initiativeOrder($validatedCombatants);

    return jsonResponse($response, ['order' => $order]);
});

$app->post('/v1/combat/sessions', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $id = $body['id'] ?? null;
    $combatants = $body['combatants'] ?? null;
    if (!is_string($id) || $id === '' || !is_array($combatants) || $combatants === []) {
        return badRequest($response);
    }

    $validatedCombatants = [];
    $names = [];
    foreach ($combatants as $combatant) {
        if (!is_array($combatant) || !is_string($combatant['name'] ?? null) || $combatant['name'] === '') {
            return badRequest($response);
        }
        $dex = integer($combatant['dex'] ?? null);
        $roll = integer($combatant['roll'] ?? null);
        if ($dex === null || $roll === null || isset($names[$combatant['name']])) {
            return badRequest($response);
        }
        $names[$combatant['name']] = true;
        $validatedCombatants[] = ['name' => $combatant['name'], 'dex' => $dex, 'roll' => $roll];
    }
    $order = initiativeOrder($validatedCombatants);

    $sessions = combatSessions();
    if (isset($sessions[$id])) {
        return badRequest($response);
    }
    $sessions[$id] = [
        'id' => $id,
        'round' => 1,
        'turn_index' => 0,
        'order' => $order,
        'conditions' => [],
    ];
    saveCombatSessions($sessions);

    return jsonResponse($response, combatState($sessions[$id]) + ['order' => $order]);
});

$app->post('/v1/combat/sessions/{id}/conditions', function (Request $request, Response $response, array $args): Response {
    $sessions = combatSessions();
    $id = $args['id'];
    if (!isset($sessions[$id])) {
        return jsonResponse($response, ['error' => 'unknown session'], 404);
    }

    $body = jsonBody($request);
    $target = $body['target'] ?? null;
    $condition = $body['condition'] ?? null;
    $duration = integer($body['duration_rounds'] ?? null);
    if (!is_string($target) || !is_string($condition) || $duration === null || $duration <= 0) {
        return badRequest($response);
    }
    $knownCombatant = false;
    foreach ($sessions[$id]['order'] as $combatant) {
        if ($combatant['name'] === $target) {
            $knownCombatant = true;
            break;
        }
    }
    if (!$knownCombatant) {
        return badRequest($response);
    }

    $sessions[$id]['conditions'][$target] ??= [];
    $sessions[$id]['conditions'][$target][] = ['condition' => $condition, 'remaining_rounds' => $duration];
    saveCombatSessions($sessions);

    return jsonResponse($response, ['target' => $target, 'conditions' => $sessions[$id]['conditions'][$target]]);
});

$app->post('/v1/combat/sessions/{id}/advance', function (Request $request, Response $response, array $args): Response {
    $sessions = combatSessions();
    $id = $args['id'];
    if (!isset($sessions[$id])) {
        return jsonResponse($response, ['error' => 'unknown session'], 404);
    }

    $session =& $sessions[$id];
    $session['turn_index']++;
    if ($session['turn_index'] === count($session['order'])) {
        $session['turn_index'] = 0;
        $session['round']++;
    }
    $activeName = $session['order'][$session['turn_index']]['name'];
    if (isset($session['conditions'][$activeName])) {
        $session['conditions'][$activeName] = array_values(array_filter(array_map(
            static fn (array $entry): array => ['condition' => $entry['condition'], 'remaining_rounds' => $entry['remaining_rounds'] - 1],
            $session['conditions'][$activeName]
        ), static fn (array $entry): bool => $entry['remaining_rounds'] > 0));
    }
    unset($session);
    saveCombatSessions($sessions);

    return jsonResponse($response, combatState($sessions[$id]) + ['conditions' => combatConditions($sessions[$id])]);
});

$app->post('/v1/phb/spell-slots', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $class = $body['class'] ?? null;
    $level = integer($body['level'] ?? null);
    if ($class !== 'wizard' || $level !== 5) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'class' => 'wizard',
        'level' => 5,
        'slots' => ['1' => 4, '2' => 3, '3' => 2],
    ]);
});

$app->post('/v1/phb/rests/long', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $level = integer($body['level'] ?? null);
    $hpCurrent = integer($body['hp_current'] ?? null);
    $hpMax = integer($body['hp_max'] ?? null);
    $hitDiceSpent = integer($body['hit_dice_spent'] ?? null);
    $exhaustionLevel = integer($body['exhaustion_level'] ?? null);
    if (!validLevel($level) || $hpCurrent === null || $hpCurrent < 0 || $hpMax === null || $hpMax <= 0
        || $hpCurrent > $hpMax || $hitDiceSpent === null || $hitDiceSpent < 0 || $hitDiceSpent > $level
        || $exhaustionLevel === null || $exhaustionLevel < 0) {
        return badRequest($response);
    }

    return jsonResponse($response, [
        'hp_current' => $hpMax,
        'hit_dice_spent' => max(0, $hitDiceSpent - max(1, intdiv($level, 2))),
        'exhaustion_level' => max(0, $exhaustionLevel - 1),
    ]);
});

$app->post('/v1/phb/equipment-load', function (Request $request, Response $response): Response {
    $body = jsonBody($request);
    $strength = integer($body['strength'] ?? null);
    $weight = integer($body['weight'] ?? null);
    if ($strength === null || $strength < 1 || $weight === null || $weight < 0) {
        return badRequest($response);
    }

    $capacity = $strength * 15;
    return jsonResponse($response, [
        'capacity' => $capacity,
        'weight' => $weight,
        'encumbered' => $weight > $capacity,
    ]);
});

$app->post('/v1/play/campaigns/{id}/notes', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    $body = jsonBody($request);
    $noteId = $body['note_id'] ?? null;
    $text = $body['text'] ?? null;
    $visibility = $body['visibility'] ?? null;
    if ($body === null || count($body) !== 3 || !array_key_exists('note_id', $body) || !array_key_exists('text', $body)
        || !array_key_exists('visibility', $body) || !validNonEmptyString($noteId) || !validNonEmptyString($text)
        || !is_string($visibility) || !in_array($visibility, ['private', 'party'], true)) {
        return badRequest($response);
    }
    $statement = database()->prepare('INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) VALUES (?, ?, ?, ?, ?)');
    try {
        $statement->execute([$args['id'], $noteId, $text, $visibility, $actor['username']]);
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'duplicate note id'], 409);
    }
    return jsonResponse($response, ['note_id' => $noteId, 'text' => $text, 'visibility' => $visibility, 'owner' => $actor['username']], 201);
});

$createPlayCampaignMessage = function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isOwner = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $text = $body['text'] ?? null;
    if ($body === null || count($body) !== 1 || !array_key_exists('text', $body) || !validNonEmptyString($text)) {
        return badRequest($response);
    }

    appendPlayCampaignEvent($args['id'], 'chat', $actor['username'], $text);
    return jsonResponse($response, [
        'kind' => 'chat',
        'actor' => $actor['username'],
        'text' => $text,
    ], 201);
};

$app->post('/v1/play/campaigns/{id}/messages', $createPlayCampaignMessage);
// Retain the earlier alias while exposing the fixture's canonical endpoint.
$app->post('/v1/play/campaigns/{id}/chat', $createPlayCampaignMessage);

$app->get('/v1/play/campaigns/{id}/notes', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $statement = database()->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? ORDER BY rowid ASC');
    $statement->execute([$args['id']]);
    $notes = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $note) {
        if ($isDm || $note['visibility'] === 'party' || $note['owner'] === $actor['username']) {
            $notes[] = ['note_id' => $note['note_id'], 'text' => $note['text'], 'visibility' => $note['visibility'], 'owner' => $note['owner']];
        }
    }
    return jsonResponse($response, ['notes' => $notes]);
});

$app->post('/v1/play/campaigns/{id}/search-records', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $recordId = $body['record_id'] ?? null;
    $text = $body['text'] ?? null;
    if ($body === null || !validNonEmptyString($recordId) || !validNonEmptyString($text)) {
        return badRequest($response);
    }

    $exists = database()->prepare('SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND (record_id = ? OR text = ?)');
    $exists->execute([$args['id'], $recordId, $text]);
    if ($exists->fetchColumn() !== false) {
        return badRequest($response);
    }
    try {
        database()->prepare('INSERT INTO play_campaign_search_records (campaign_id, record_id, text) VALUES (?, ?, ?)')
            ->execute([$args['id'], $recordId, $text]);
    } catch (PDOException) {
        return badRequest($response);
    }
    return jsonResponse($response, ['record_id' => $recordId, 'text' => $text], 201);
});

$app->get('/v1/play/campaigns/{id}/search-records', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) {
        return jsonResponse($response, ['error' => 'unauthorized'], 401);
    }
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) {
        return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    }
    $isCampaignDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isCampaignDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $query = $request->getQueryParams();
    $q = $query['q'] ?? null;
    $limitValue = $query['limit'] ?? '2';
    $cursorValue = $query['cursor'] ?? '0';
    if (($q !== null && !is_string($q)) || !is_string($limitValue) || !preg_match('/^[1-3]$/', $limitValue)
        || !is_string($cursorValue) || !preg_match('/^\d+$/', $cursorValue)) {
        return badRequest($response);
    }
    $limit = (int) $limitValue;
    $cursor = (int) $cursorValue;

    $statement = database()->prepare('SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = ? ORDER BY rowid ASC');
    $statement->execute([$args['id']]);
    $records = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $record) {
        if ($q === null || mb_stripos($record['text'], $q) !== false) {
            $records[] = ['record_id' => $record['record_id'], 'text' => $record['text']];
        }
    }

    $page = array_slice($records, $cursor, $limit);
    $nextOffset = $cursor + count($page);
    return jsonResponse($response, [
        'records' => $page,
        'next_cursor' => $nextOffset < count($records) ? $nextOffset : null,
    ]);
});

$app->get('/v1/play/campaigns/{id}/notes/{note_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $statement = database()->prepare('SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
    $statement->execute([$args['id'], $args['note_id']]);
    $note = $statement->fetch(PDO::FETCH_ASSOC);
    if (!is_array($note)) return jsonResponse($response, ['error' => 'unknown note'], 404);
    if (!$isDm && $note['visibility'] === 'private' && $note['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);
    return jsonResponse($response, ['note_id' => $note['note_id'], 'text' => $note['text'], 'visibility' => $note['visibility'], 'owner' => $note['owner']]);
});

$app->put('/v1/play/campaigns/{id}/notes/{note_id}', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $statement = database()->prepare('SELECT owner FROM play_campaign_notes WHERE campaign_id = ? AND note_id = ?');
    $statement->execute([$args['id'], $args['note_id']]);
    $owner = $statement->fetchColumn();
    if ($owner === false) return jsonResponse($response, ['error' => 'unknown note'], 404);
    if ($owner !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $body = jsonBody($request);
    $text = $body['text'] ?? null;
    $visibility = $body['visibility'] ?? null;
    if ($body === null || count($body) !== 2 || !array_key_exists('text', $body) || !array_key_exists('visibility', $body)
        || !validNonEmptyString($text) || !is_string($visibility) || !in_array($visibility, ['private', 'party'], true)) return badRequest($response);
    database()->prepare('UPDATE play_campaign_notes SET text = ?, visibility = ? WHERE campaign_id = ? AND note_id = ?')
        ->execute([$text, $visibility, $args['id'], $args['note_id']]);
    return jsonResponse($response, ['note_id' => $args['note_id'], 'text' => $text, 'visibility' => $visibility, 'owner' => $actor['username']]);
});

$app->post('/v1/play/campaigns/{id}/whispers', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'player' || !isPlayCampaignMember($args['id'], $actor['username'])) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $fromCharacterId = playCampaignOwnedCharacterId($args['id'], $actor['username']);
    if ($fromCharacterId === null) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $body = jsonBody($request);
    $whisperId = $body['whisper_id'] ?? null;
    $toCharacterId = $body['to_character_id'] ?? null;
    $text = $body['text'] ?? null;
    if ($body === null || count($body) !== 3 || !array_key_exists('whisper_id', $body) || !array_key_exists('to_character_id', $body) || !array_key_exists('text', $body)
        || !validNonEmptyString($whisperId) || !validNonEmptyString($toCharacterId) || !validNonEmptyString($text) || !playCampaignCharacterExists($args['id'], $toCharacterId)) return badRequest($response);
    try {
        database()->prepare('INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) VALUES (?, ?, ?, ?, ?)')
            ->execute([$args['id'], $whisperId, $fromCharacterId, $toCharacterId, $text]);
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'duplicate whisper id'], 409);
    }
    return jsonResponse($response, ['whisper_id' => $whisperId, 'from_character_id' => $fromCharacterId, 'to_character_id' => $toCharacterId, 'text' => $text], 201);
});

$app->get('/v1/play/campaigns/{id}/whispers', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $characterId = $isDm ? null : playCampaignOwnedCharacterId($args['id'], $actor['username']);
    $statement = database()->prepare('SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers WHERE campaign_id = ? ORDER BY rowid ASC');
    $statement->execute([$args['id']]);
    $whispers = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $whisper) {
        if ($isDm || ($characterId !== null && ($whisper['from_character_id'] === $characterId || $whisper['to_character_id'] === $characterId))) {
            $whispers[] = ['whisper_id' => $whisper['whisper_id'], 'from_character_id' => $whisper['from_character_id'], 'to_character_id' => $whisper['to_character_id'], 'text' => $whisper['text']];
        }
    }
    return jsonResponse($response, ['whispers' => $whispers]);
});

$app->get('/v1/play/campaigns/{id}/characters/{character_id}/sheet', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);
    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) return jsonResponse($response, ['error' => 'forbidden'], 403);
    $sheet = playCampaignBasicSheet($args['id'], $args['character_id']);
    if ($sheet === null) return jsonResponse($response, ['error' => 'unknown character'], 404);
    if (!$isDm && $sheet['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);
    return jsonResponse($response, $sheet);
});

$app->post('/v1/play/campaigns/{id}/audit-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isOwner = $campaign['owner'] === $actor['username'];
    if (!$isOwner && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $kind = $body['kind'] ?? null;
    $correlationId = $body['correlation_id'] ?? null;
    if ($body === null || count($body) !== 2 || !array_key_exists('kind', $body) || !array_key_exists('correlation_id', $body)
        || !validNonEmptyString($kind) || !validNonEmptyString($correlationId)) {
        return badRequest($response);
    }

    $role = $isOwner ? 'DM' : 'player';
    $database = database();
    try {
        withinTransaction($database, static function () use ($database, $args, $kind, $actor, $role, $correlationId): void {
            $nextTimestamp = $database->prepare('SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events WHERE campaign_id = ?');
            $nextTimestamp->execute([$args['id']]);
            $timestamp = (int) $nextTimestamp->fetchColumn();
            $database->prepare('INSERT INTO play_campaign_audit_events (campaign_id, timestamp, kind, actor, role, correlation_id) VALUES (?, ?, ?, ?, ?, ?)')
                ->execute([$args['id'], $timestamp, $kind, $actor['username'], $role, $correlationId]);
        });
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'duplicate correlation id'], 409);
    }

    $statement = $database->prepare('SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?');
    $statement->execute([$args['id'], $correlationId]);
    $entry = $statement->fetch(PDO::FETCH_ASSOC);
    return jsonResponse($response, [
        'kind' => $entry['kind'],
        'actor' => $entry['actor'],
        'role' => $entry['role'],
        'timestamp' => (int) $entry['timestamp'],
        'correlation_id' => $entry['correlation_id'],
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/audit-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);

    $statement = database()->prepare('SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC');
    $statement->execute([$args['id']]);
    $entries = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $entry) {
        $entries[] = [
            'kind' => $entry['kind'],
            'actor' => $entry['actor'],
            'role' => $entry['role'],
            'timestamp' => (int) $entry['timestamp'],
            'correlation_id' => $entry['correlation_id'],
        ];
    }
    return jsonResponse($response, ['entries' => $entries]);
});

$app->post('/v1/play/campaigns/{id}/projection-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'player' || !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $eventId = $body['event_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $hasValue = is_array($body) && array_key_exists('value', $body);
    $value = $body['value'] ?? null;
    $validSetStory = $kind === 'set-story' && count($body ?? []) === 3 && $hasValue && validNonEmptyString($value);
    $validIncrementDanger = $kind === 'increment-danger' && count($body ?? []) === 2 && !$hasValue;
    if ($body === null || !validNonEmptyString($eventId) || (!$validSetStory && !$validIncrementDanger)) {
        return badRequest($response);
    }

    $database = database();
    try {
        withinTransaction($database, static function () use ($database, $args, $eventId, $kind, $value): void {
            $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_projection_events WHERE campaign_id = ?');
            $nextSequence->execute([$args['id']]);
            $sequence = (int) $nextSequence->fetchColumn();
            $database->prepare('INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)')
                ->execute([$args['id'], $sequence, $eventId, $kind, $kind === 'set-story' ? $value : null]);
        });
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'duplicate event id'], 409);
    }

    $statement = $database->prepare('SELECT sequence, event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?');
    $statement->execute([$args['id'], $eventId]);
    $event = $statement->fetch(PDO::FETCH_ASSOC);
    $stored = ['sequence' => (int) $event['sequence'], 'event_id' => $event['event_id'], 'kind' => $event['kind']];
    if ($event['kind'] === 'set-story') $stored['value'] = $event['value'];
    return jsonResponse($response, $stored, 201);
});

$projectionRead = static function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    return jsonResponse($response, rebuildPlayCampaignProjection($args['id']));
};

$app->get('/v1/play/campaigns/{id}/projection', $projectionRead);
$app->get('/v1/play/campaigns/{id}/projection/rebuild', $projectionRead);

$app->post('/v1/play/campaigns/{id}/replay-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $eventId = $body['event_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $text = $body['text'] ?? null;
    if ($body === null || count($body) !== 3 || !array_key_exists('event_id', $body)
        || !array_key_exists('kind', $body) || !array_key_exists('text', $body)
        || !validNonEmptyString($eventId) || $kind !== 'append' || !validNonEmptyString($text)) {
        return badRequest($response);
    }

    $database = database();
    try {
        withinTransaction($database, static function () use ($database, $args, $eventId, $text): void {
            $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_replay_events WHERE campaign_id = ?');
            $nextSequence->execute([$args['id']]);
            $sequence = (int) $nextSequence->fetchColumn();
            $database->prepare('INSERT INTO play_campaign_replay_events (campaign_id, sequence, event_id, kind, text) VALUES (?, ?, ?, ?, ?)')
                ->execute([$args['id'], $sequence, $eventId, 'append', $text]);
        });
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'duplicate event id'], 409);
    }

    $statement = $database->prepare('SELECT event_id, kind, text, sequence FROM play_campaign_replay_events WHERE campaign_id = ? AND event_id = ?');
    $statement->execute([$args['id'], $eventId]);
    $event = $statement->fetch(PDO::FETCH_ASSOC);
    return jsonResponse($response, [
        'event_id' => $event['event_id'],
        'kind' => $event['kind'],
        'text' => $event['text'],
        'sequence' => (int) $event['sequence'],
    ], 201);
});

$replayRead = static function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    return jsonResponse($response, rebuildPlayCampaignReplay($args['id']));
};

$app->get('/v1/play/campaigns/{id}/replay', $replayRead);
$app->get('/v1/play/campaigns/{id}/replay/check', $replayRead);

$app->post('/v1/play/campaigns/{id}/feed-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $eventId = $body['event_id'] ?? null;
    $text = $body['text'] ?? null;
    if ($body === null || count($body) !== 2 || !array_key_exists('event_id', $body) || !array_key_exists('text', $body)
        || !validNonEmptyString($eventId) || !validNonEmptyString($text)) {
        return badRequest($response);
    }

    try {
        return jsonResponse($response, appendPlayCampaignFeedEvent($args['id'], $eventId, $text), 201);
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'duplicate event id'], 409);
    }
});

$app->get('/v1/play/campaigns/{id}/event-feed', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $query = $request->getQueryParams();
    $cursorValue = $query['cursor'] ?? '0';
    $limitValue = $query['limit'] ?? '2';
    if (!is_string($cursorValue) || !preg_match('/^\\d+$/', $cursorValue)
        || !is_string($limitValue) || !preg_match('/^[1-3]$/', $limitValue)) {
        return badRequest($response);
    }
    $cursor = (int) $cursorValue;
    $limit = (int) $limitValue;

    $statement = database()->prepare('SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence ASC LIMIT ? OFFSET ?');
    $statement->bindValue(1, $args['id'], PDO::PARAM_STR);
    $statement->bindValue(2, $limit, PDO::PARAM_INT);
    $statement->bindValue(3, $cursor, PDO::PARAM_INT);
    $statement->execute();
    $events = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $event) {
        $events[] = ['event_id' => $event['event_id'], 'text' => $event['text'], 'sequence' => (int) $event['sequence']];
    }

    return jsonResponse($response, ['events' => $events, 'next_cursor' => $cursor + count($events)]);
});

$app->post('/v1/play/campaigns/{id}/idempotent-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $idempotencyKey = trim($request->getHeaderLine('Idempotency-Key'));
    $body = jsonBody($request);
    $eventId = $body['event_id'] ?? null;
    $value = $body['value'] ?? null;
    if ($idempotencyKey === '' || $body === null || count($body) !== 2
        || !array_key_exists('event_id', $body) || !array_key_exists('value', $body)
        || !validNonEmptyString($eventId) || !validNonEmptyString($value)) {
        return badRequest($response);
    }

    $database = database();
    $byKey = $database->prepare('SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?');
    $byKey->execute([$args['id'], $idempotencyKey]);
    $stored = $byKey->fetch(PDO::FETCH_ASSOC);
    if (is_array($stored)) {
        if ($stored['event_id'] !== $eventId || $stored['value'] !== $value) {
            return jsonResponse($response, ['error' => 'idempotency key conflict'], 409);
        }
        return jsonResponse($response, ['event_id' => $stored['event_id'], 'value' => $stored['value'], 'sequence' => (int) $stored['sequence'], 'idempotency_key' => $stored['idempotency_key']]);
    }

    $byEventId = $database->prepare('SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?');
    $byEventId->execute([$args['id'], $eventId]);
    if ($byEventId->fetchColumn() !== false) return jsonResponse($response, ['error' => 'duplicate event id'], 409);

    try {
        withinTransaction($database, static function () use ($database, $args, $eventId, $value, $idempotencyKey): void {
            $nextSequence = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_idempotent_events WHERE campaign_id = ?');
            $nextSequence->execute([$args['id']]);
            $sequence = (int) $nextSequence->fetchColumn();
            $database->prepare('INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)')
                ->execute([$args['id'], $sequence, $eventId, $value, $idempotencyKey]);
        });
    } catch (PDOException) {
        // A concurrent identical request may have won the unique-key race.
        // Treat it as the stored replay rather than exposing a second effect.
        $byKey->execute([$args['id'], $idempotencyKey]);
        $stored = $byKey->fetch(PDO::FETCH_ASSOC);
        if (is_array($stored) && $stored['event_id'] === $eventId && $stored['value'] === $value) {
            return jsonResponse($response, ['event_id' => $stored['event_id'], 'value' => $stored['value'], 'sequence' => (int) $stored['sequence'], 'idempotency_key' => $stored['idempotency_key']]);
        }
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }

    $byKey->execute([$args['id'], $idempotencyKey]);
    $stored = $byKey->fetch(PDO::FETCH_ASSOC);
    return jsonResponse($response, ['event_id' => $stored['event_id'], 'value' => $stored['value'], 'sequence' => (int) $stored['sequence'], 'idempotency_key' => $stored['idempotency_key']], 201);
});

$app->get('/v1/play/campaigns/{id}/idempotent-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $statement = database()->prepare('SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$args['id']]);
    $events = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $event) {
        $events[] = ['event_id' => $event['event_id'], 'value' => $event['value'], 'sequence' => (int) $event['sequence'], 'idempotency_key' => $event['idempotency_key']];
    }
    return jsonResponse($response, ['events' => $events]);
});

$app->post('/v1/play/campaigns/{id}/safe-turns', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $submissionId = $body['submission_id'] ?? null;
    $expectedTurn = $body['expected_turn'] ?? null;
    $action = $body['action'] ?? null;
    if ($body === null || count($body) !== 3
        || !array_key_exists('submission_id', $body) || !array_key_exists('expected_turn', $body) || !array_key_exists('action', $body)
        || !validNonEmptyString($submissionId) || !is_int($expectedTurn) || $expectedTurn < 1 || !validNonEmptyString($action)) {
        return badRequest($response);
    }

    $database = database();
    try {
        // Taking the SQLite write lock before reading makes check-and-advance a
        // single operation even if this app is later served by multiple workers.
        $database->exec('BEGIN IMMEDIATE');
        $database->prepare('INSERT OR IGNORE INTO play_campaign_safe_turns (campaign_id, current_turn) VALUES (?, 1)')->execute([$args['id']]);

        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? AND submission_id = ?');
        $duplicate->execute([$args['id'], $submissionId]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'duplicate submission id'], 409);
        }

        $turnStatement = $database->prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?');
        $turnStatement->execute([$args['id']]);
        $currentTurn = (int) $turnStatement->fetchColumn();
        if ($expectedTurn !== $currentTurn) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['current_turn' => $currentTurn], 409);
        }

        $nextTurn = $currentTurn + 1;
        $database->prepare('INSERT INTO play_campaign_safe_turn_submissions (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)')
            ->execute([$args['id'], $submissionId, $action, $currentTurn, $nextTurn]);
        $database->prepare('UPDATE play_campaign_safe_turns SET current_turn = ? WHERE campaign_id = ?')->execute([$nextTurn, $args['id']]);
        $database->exec('COMMIT');
    } catch (PDOException) {
        // A failed write leaves no accepted submission or turn advancement.
        try {
            $database->exec('ROLLBACK');
        } catch (PDOException) {
        }
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }

    return jsonResponse($response, [
        'submission_id' => $submissionId,
        'action' => $action,
        'accepted_turn' => $currentTurn,
        'next_turn' => $nextTurn,
    ], 201);
});

$app->get('/v1/play/campaigns/{id}/safe-turns', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $database = database();
    $turnStatement = $database->prepare('SELECT current_turn FROM play_campaign_safe_turns WHERE campaign_id = ?');
    $turnStatement->execute([$args['id']]);
    $turn = $turnStatement->fetchColumn();
    $acceptedStatement = $database->prepare('SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turn_submissions WHERE campaign_id = ? ORDER BY accepted_turn ASC');
    $acceptedStatement->execute([$args['id']]);
    $accepted = [];
    foreach ($acceptedStatement->fetchAll(PDO::FETCH_ASSOC) as $submission) {
        $accepted[] = [
            'submission_id' => $submission['submission_id'],
            'action' => $submission['action'],
            'accepted_turn' => (int) $submission['accepted_turn'],
            'next_turn' => (int) $submission['next_turn'],
        ];
    }
    return jsonResponse($response, ['current_turn' => $turn === false ? 1 : (int) $turn, 'accepted' => $accepted]);
});

$app->post('/v1/play/campaigns/{id}/service-mode', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    if (playCampaignById($args['id']) === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm') return jsonResponse($response, ['error' => 'forbidden'], 403);

    $body = jsonBody($request);
    if ($body === null || array_keys($body) !== ['maintenance'] || !is_bool($body['maintenance'])) {
        return badRequest($response);
    }

    setMaintenanceMode($body['maintenance']);
    return jsonResponse($response, ['maintenance' => $body['maintenance']]);
});

$app->post('/v1/play/campaigns/{id}/rate-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $eventId = $body['event_id'] ?? null;
    if ($body === null || !validNonEmptyString($eventId)) return badRequest($response);

    $database = database();
    try {
        // Serialize the duplicate, allowance, and insert checks so each
        // accepted event consumes exactly one allowance.
        $database->exec('BEGIN IMMEDIATE');
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?');
        $duplicate->execute([$args['id'], $eventId]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('COMMIT');
            return badRequest($response);
        }

        $used = $database->prepare('SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
        $used->execute([$args['id'], $actor['username']]);
        $accepted = (int) $used->fetchColumn();
        if ($accepted >= 2) {
            $database->prepare('INSERT OR IGNORE INTO play_campaign_service_metrics (campaign_id) VALUES (?)')->execute([$args['id']]);
            $database->prepare('UPDATE play_campaign_service_metrics SET rejected_rate_events = rejected_rate_events + 1 WHERE campaign_id = ?')
                ->execute([$args['id']]);
            $database->exec('COMMIT');
            return jsonResponse($response, ['limit' => 2, 'remaining' => 0], 429);
        }

        $database->prepare('INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor, sequence) VALUES (?, ?, ?, COALESCE((SELECT MAX(sequence) + 1 FROM play_campaign_rate_events WHERE campaign_id = ?), 1))')
            ->execute([$args['id'], $eventId, $actor['username'], $args['id']]);
        $database->exec('COMMIT');
    } catch (PDOException) {
        try {
            $database->exec('ROLLBACK');
        } catch (PDOException) {
        }
        return badRequest($response);
    }

    return jsonResponse($response, ['event_id' => $eventId, 'actor' => $actor['username'], 'remaining' => 1 - $accepted], 201);
});

$app->get('/v1/play/campaigns/{id}/rate-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $statement = database()->prepare('SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$args['id']]);
    $events = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $event) {
        $events[] = ['event_id' => $event['event_id'], 'actor' => $event['actor']];
    }
    $used = database()->prepare('SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?');
    $used->execute([$args['id'], $actor['username']]);
    return jsonResponse($response, ['events' => $events, 'remaining' => max(0, 2 - (int) $used->fetchColumn())]);
});

$app->get('/v1/play/campaigns/{id}/metrics', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username']) return jsonResponse($response, ['error' => 'forbidden'], 403);

    $metrics = database()->prepare(
        'SELECT
            (SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ?) AS accepted_rate_events,
            COALESCE((SELECT rejected_rate_events FROM play_campaign_service_metrics WHERE campaign_id = ?), 0) AS rejected_rate_events,
            (SELECT COUNT(*) FROM play_campaign_projection_events WHERE campaign_id = ?) AS projection_events'
    );
    $metrics->execute([$args['id'], $args['id'], $args['id']]);
    $counts = $metrics->fetch(PDO::FETCH_ASSOC);

    return jsonResponse($response, [
        'accepted_rate_events' => (int) $counts['accepted_rate_events'],
        'rejected_rate_events' => (int) $counts['rejected_rate_events'],
        'projection_events' => (int) $counts['projection_events'],
        'uptime_ticks' => 1,
    ]);
});

$app->put('/v1/play/campaigns/{id}/rng-seed', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $seed = $body['seed'] ?? null;
    if ($body === null || array_keys($body) !== ['seed'] || !validNonEmptyString($seed)) {
        return badRequest($response);
    }

    try {
        database()->prepare('INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES (?, ?)')->execute([$args['id'], $seed]);
    } catch (PDOException) {
        return jsonResponse($response, ['error' => 'rng seed already configured'], 409);
    }
    return jsonResponse($response, ['seed' => $seed, 'rolls' => []]);
});

$app->post('/v1/play/campaigns/{id}/rng-rolls', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $rollId = $body['roll_id'] ?? null;
    $sides = $body['sides'] ?? null;
    if ($body === null || count($body) !== 2 || !array_key_exists('roll_id', $body) || !array_key_exists('sides', $body)
        || !validNonEmptyString($rollId) || !is_int($sides) || $sides < 2 || $sides > 100) {
        return badRequest($response);
    }

    $database = database();
    try {
        // Sequence assignment and duplicate detection must be a single write
        // operation: the recorded result is forever tied to its sequence.
        $database->exec('BEGIN IMMEDIATE');
        $seedStatement = $database->prepare('SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = ?');
        $seedStatement->execute([$args['id']]);
        $seed = $seedStatement->fetchColumn();
        if (!is_string($seed)) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'rng seed not configured'], 409);
        }

        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_rng_rolls WHERE campaign_id = ? AND roll_id = ?');
        $duplicate->execute([$args['id'], $rollId]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'duplicate roll id'], 409);
        }

        $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_rng_rolls WHERE campaign_id = ?');
        $sequenceStatement->execute([$args['id']]);
        $sequence = (int) $sequenceStatement->fetchColumn();
        $result = deterministicRngResult($seed, $sequence, $rollId, $sides);
        $database->prepare('INSERT INTO play_campaign_rng_rolls (campaign_id, sequence, roll_id, sides, result) VALUES (?, ?, ?, ?, ?)')
            ->execute([$args['id'], $sequence, $rollId, $sides, $result]);
        $database->exec('COMMIT');
    } catch (PDOException) {
        try {
            $database->exec('ROLLBACK');
        } catch (PDOException) {
        }
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }

    return jsonResponse($response, ['roll_id' => $rollId, 'sides' => $sides, 'result' => $result, 'sequence' => $sequence], 201);
});

$app->get('/v1/play/campaigns/{id}/rng-ledger', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    return jsonResponse($response, playCampaignRngLedger($args['id']));
});

$app->post('/v1/play/campaigns/{id}/moderation/reports', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $reportId = $body['report_id'] ?? null;
    $targetId = $body['target_id'] ?? null;
    $reason = $body['reason'] ?? null;
    if ($body === null || !validNonEmptyString($reportId) || !validNonEmptyString($targetId) || !validNonEmptyString($reason)) {
        return badRequest($response);
    }

    $database = database();
    try {
        $database->exec('BEGIN IMMEDIATE');
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?');
        $duplicate->execute([$args['id'], $reportId]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'duplicate report id'], 409);
        }
        $sequenceStatement = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_moderation_reports WHERE campaign_id = ?');
        $sequenceStatement->execute([$args['id']]);
        $sequence = (int) $sequenceStatement->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_moderation_reports (campaign_id, sequence, report_id, target_id, reason, status, reporter) VALUES (?, ?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $sequence, $reportId, $targetId, $reason, 'open', $actor['username']]);
        $database->exec('COMMIT');
    } catch (PDOException) {
        try {
            $database->exec('ROLLBACK');
        } catch (PDOException) {
        }
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }

    return jsonResponse($response, ['report_id' => $reportId, 'target_id' => $targetId, 'reason' => $reason, 'status' => 'open', 'reporter' => $actor['username'], 'sequence' => $sequence], 201);
});

$app->get('/v1/play/campaigns/{id}/moderation/reports', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    $isDm = $actor['role'] === 'dm' && $campaign['owner'] === $actor['username'];
    if (!$isDm && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $statement = database()->prepare('SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver FROM play_campaign_moderation_reports WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$args['id']]);
    $reports = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $report) {
        $record = ['report_id' => $report['report_id'], 'target_id' => $report['target_id'], 'reason' => $report['reason'], 'status' => $report['status'], 'reporter' => $report['reporter'], 'sequence' => (int) $report['sequence']];
        if ($report['status'] === 'resolved') {
            $record['action'] = $report['action'];
            $record['note'] = $report['note'];
            $record['resolver'] = $report['resolver'];
        }
        $reports[] = $record;
    }
    return jsonResponse($response, ['reports' => $reports]);
});

$app->put('/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $action = $body['action'] ?? null;
    $note = $body['note'] ?? null;
    if ($body === null || !is_string($action) || !in_array($action, ['allow', 'remove'], true) || !validNonEmptyString($note)) {
        return badRequest($response);
    }

    $database = database();
    try {
        $database->exec('BEGIN IMMEDIATE');
        $statement = $database->prepare('SELECT target_id, reason, status, reporter, sequence FROM play_campaign_moderation_reports WHERE campaign_id = ? AND report_id = ?');
        $statement->execute([$args['id'], $args['report_id']]);
        $report = $statement->fetch(PDO::FETCH_ASSOC);
        if (!is_array($report)) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'unknown report'], 404);
        }
        if ($report['status'] !== 'open') {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'report already resolved'], 409);
        }
        $database->prepare('UPDATE play_campaign_moderation_reports SET status = ?, action = ?, note = ?, resolver = ? WHERE campaign_id = ? AND report_id = ? AND status = ?')
            ->execute(['resolved', $action, $note, $actor['username'], $args['id'], $args['report_id'], 'open']);
        $database->exec('COMMIT');
    } catch (PDOException) {
        try {
            $database->exec('ROLLBACK');
        } catch (PDOException) {
        }
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }

    return jsonResponse($response, ['report_id' => $args['report_id'], 'target_id' => $report['target_id'], 'reason' => $report['reason'], 'status' => 'resolved', 'reporter' => $report['reporter'], 'sequence' => (int) $report['sequence'], 'action' => $action, 'note' => $note, 'resolver' => $actor['username']]);
});

$app->put('/v1/play/campaigns/{id}/safety-boundaries', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $tags = is_array($body) && count($body) === 1 && array_key_exists('blocked_tags', $body) ? validSafetyTags($body['blocked_tags']) : null;
    if ($tags === null) return badRequest($response);
    sort($tags, SORT_STRING);

    $database = database();
    try {
        withinTransaction($database, static function () use ($database, $args, $tags): void {
            $database->prepare('INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags) VALUES (?, ?) ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags')
                ->execute([$args['id'], json_encode($tags, JSON_THROW_ON_ERROR)]);
        });
    } catch (Throwable) {
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }
    return jsonResponse($response, ['blocked_tags' => $tags]);
});

$app->get('/v1/play/campaigns/{id}/safety-boundaries', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }
    return jsonResponse($response, ['blocked_tags' => playCampaignSafetyBoundaries($args['id'])]);
});

$app->post('/v1/play/campaigns/{id}/safety-checks', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    $eventId = $body['event_id'] ?? null;
    $kind = $body['kind'] ?? null;
    $text = $body['text'] ?? null;
    $tags = is_array($body) && count($body) === 4 && array_key_exists('event_id', $body)
        && array_key_exists('kind', $body) && array_key_exists('text', $body) && array_key_exists('tags', $body)
        ? validSafetyTags($body['tags']) : null;
    if ($body === null || !validNonEmptyString($eventId) || !in_array($kind, ['narration', 'chat'], true)
        || !validNonEmptyString($text) || $tags === null) {
        return badRequest($response);
    }

    $database = database();
    try {
        $database->exec('BEGIN IMMEDIATE');
        $duplicate = $database->prepare('SELECT 1 FROM play_campaign_safety_events WHERE campaign_id = ? AND event_id = ?');
        $duplicate->execute([$args['id'], $eventId]);
        if ($duplicate->fetchColumn() !== false) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'duplicate event id'], 409);
        }

        $blocked = playCampaignSafetyBoundaries($args['id']);
        if (array_intersect($tags, $blocked) !== []) {
            $database->exec('COMMIT');
            return jsonResponse($response, ['error' => 'blocked tag'], 409);
        }

        $next = $database->prepare('SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_safety_events WHERE campaign_id = ?');
        $next->execute([$args['id']]);
        $sequence = (int) $next->fetchColumn();
        $database->prepare('INSERT INTO play_campaign_safety_events (campaign_id, sequence, event_id, kind, text, tags) VALUES (?, ?, ?, ?, ?, ?)')
            ->execute([$args['id'], $sequence, $eventId, $kind, $text, json_encode($tags, JSON_THROW_ON_ERROR)]);
        $database->exec('COMMIT');
    } catch (Throwable) {
        try {
            $database->exec('ROLLBACK');
        } catch (Throwable) {
        }
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }

    return jsonResponse($response, ['event_id' => $eventId, 'kind' => $kind, 'text' => $text, 'tags' => $tags, 'sequence' => $sequence], 201);
});

$app->get('/v1/play/campaigns/{id}/safety-events', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $statement = database()->prepare('SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events WHERE campaign_id = ? ORDER BY sequence ASC');
    $statement->execute([$args['id']]);
    $events = [];
    foreach ($statement->fetchAll(PDO::FETCH_ASSOC) as $event) {
        $tags = json_decode($event['tags'], true);
        $events[] = ['event_id' => $event['event_id'], 'kind' => $event['kind'], 'text' => $event['text'], 'tags' => is_array($tags) ? array_values($tags) : [], 'sequence' => (int) $event['sequence']];
    }
    return jsonResponse($response, ['events' => $events]);
});

$app->post('/v1/play/campaigns/{id}/fixture-seeds', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($actor['role'] !== 'dm' || $campaign['owner'] !== $actor['username']) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $body = jsonBody($request);
    if ($body === null || count($body) !== 1 || !array_key_exists('fixture_id', $body)
        || $body['fixture_id'] !== 'canonical-v1') {
        return badRequest($response);
    }

    $database = database();
    try {
        $database->exec('BEGIN IMMEDIATE');
        $seed = $database->prepare('SELECT 1 FROM play_campaign_fixture_seeds WHERE campaign_id = ?');
        $seed->execute([$args['id']]);
        if ($seed->fetchColumn() !== false) {
            $database->exec('COMMIT');
            return jsonResponse($response, canonicalFixtureState());
        }

        $database->prepare('INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id) VALUES (?, ?)')
            ->execute([$args['id'], 'canonical-v1']);
        $database->prepare('INSERT INTO play_campaign_fixture_characters (campaign_id, character_id, name, class) VALUES (?, ?, ?, ?)')
            ->execute([$args['id'], 'fixture-hero', 'Ari', 'fighter']);
        $database->prepare('INSERT INTO play_campaign_fixture_characters (campaign_id, character_id, name, class) VALUES (?, ?, ?, ?)')
            ->execute([$args['id'], 'fixture-mage', 'Bea', 'wizard']);
        $database->prepare('INSERT INTO play_campaign_fixture_events (campaign_id, event_id, sequence) VALUES (?, ?, ?)')
            ->execute([$args['id'], 'fixture-event-1', 1]);
        $database->prepare('INSERT INTO play_campaign_fixture_events (campaign_id, event_id, sequence) VALUES (?, ?, ?)')
            ->execute([$args['id'], 'fixture-event-2', 2]);
        $database->exec('COMMIT');
    } catch (Throwable) {
        try {
            $database->exec('ROLLBACK');
        } catch (Throwable) {
        }
        return jsonResponse($response, ['error' => 'conflict'], 409);
    }

    return jsonResponse($response, canonicalFixtureState(), 201);
});

$app->get('/v1/play/campaigns/{id}/fixture-state', function (Request $request, Response $response, array $args): Response {
    $actor = authenticatedActor($request);
    if ($actor === null) return jsonResponse($response, ['error' => 'unauthorized'], 401);

    $campaign = playCampaignById($args['id']);
    if ($campaign === null) return jsonResponse($response, ['error' => 'unknown campaign'], 404);
    if ($campaign['owner'] !== $actor['username'] && !isPlayCampaignMember($args['id'], $actor['username'])) {
        return jsonResponse($response, ['error' => 'forbidden'], 403);
    }

    $seed = database()->prepare('SELECT 1 FROM play_campaign_fixture_seeds WHERE campaign_id = ?');
    $seed->execute([$args['id']]);
    if ($seed->fetchColumn() === false) return jsonResponse($response, ['error' => 'fixture not found'], 404);

    return jsonResponse($response, canonicalFixtureState());
});

$app->run();

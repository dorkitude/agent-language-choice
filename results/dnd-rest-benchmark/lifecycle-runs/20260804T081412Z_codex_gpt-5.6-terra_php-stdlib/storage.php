<?php
declare(strict_types=1);

/** The database schema is intentionally versioned even though migrations are small. */
const SCHEMA_VERSION = 1;

/**
 * Returns the current column names for a table.
 *
 * Schema migrations use this instead of assuming a fresh database: benchmark
 * runs may reuse a database created by an earlier version of the service.
 *
 * @return array<string, true>
 */
function tableColumnNames(PDO $database, string $table): array
{
    $columns = [];
    foreach ($database->query("PRAGMA table_info({$table})") as $column) {
        $columns[$column['name']] = true;
    }
    return $columns;
}

/**
 * Creates the complete schema idempotently.
 *
 * This function is shared by the HTTP application and run.sh so both entry
 * points agree on the persistent storage contract.
 */
function initializeSchema(PDO $database): void
{
    $database->exec('CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)');
    // This is intentionally service-wide rather than campaign-owned.  PHP
    // serves each request independently, so the one-row table retains the
    // process service mode between requests.
    $database->exec('CREATE TABLE IF NOT EXISTS service_mode (id INTEGER PRIMARY KEY CHECK (id = 1), maintenance INTEGER NOT NULL CHECK (maintenance IN (0, 1)))');
    $database->exec('INSERT OR IGNORE INTO service_mode (id, maintenance) VALUES (1, 0)');
    $database->exec('CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, role TEXT NOT NULL, password_hash TEXT NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, state_json TEXT NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS compendium_monsters (slug TEXT PRIMARY KEY, name TEXT NOT NULL, cr TEXT NOT NULL, armor_class INTEGER NOT NULL, hit_points INTEGER NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS compendium_monster_tags (monster_slug TEXT NOT NULL, position INTEGER NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (monster_slug, position), FOREIGN KEY (monster_slug) REFERENCES compendium_monsters(slug) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS compendium_items (slug TEXT PRIMARY KEY, name TEXT NOT NULL, type TEXT NOT NULL, rarity TEXT NOT NULL, cost_gp INTEGER NOT NULL)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, dm TEXT NOT NULL)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaigns (id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL, status TEXT NOT NULL CHECK (status = 'lobby'), max_players INTEGER NOT NULL CHECK (max_players > 0))");
    // A spectator token deliberately contains only this globally unique ID.
    // Keeping the campaign binding server-side prevents it from being reused
    // to view another campaign.
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_spectators (spectator_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    // Feed events are intentionally separate from the campaign activity log:
    // their sequence is the stable cursor ordering exposed by the feed API.
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_feed_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), event_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    // Fixtures are a write-once, campaign-scoped deterministic test surface.
    // The primary key makes an accepted seed idempotent across requests.
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (campaign_id TEXT PRIMARY KEY, fixture_id TEXT NOT NULL CHECK (fixture_id = 'canonical-v1'), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (campaign_id TEXT PRIMARY KEY, rules TEXT NOT NULL, tone TEXT NOT NULL, consent_json TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_content (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, content_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_content_tags (campaign_id TEXT NOT NULL, content_id TEXT NOT NULL, position INTEGER NOT NULL CHECK (position >= 0), tag TEXT NOT NULL, PRIMARY KEY (campaign_id, content_id, position), UNIQUE (campaign_id, content_id, tag), FOREIGN KEY (campaign_id, content_id) REFERENCES play_campaign_content(campaign_id, content_id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_notes (campaign_id TEXT NOT NULL, note_id TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL CHECK (visibility IN ('private', 'party')), owner TEXT NOT NULL, PRIMARY KEY (campaign_id, note_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_whispers (campaign_id TEXT NOT NULL, whisper_id TEXT NOT NULL, from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, whisper_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_documents (campaign_id TEXT PRIMARY KEY, story TEXT NOT NULL, dm_notes TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_backups (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), story TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN (\'lobby\', \'active\')), PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_replay_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), event_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind = 'append'), text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    // The RNG seed is write-once and rolls are append-only.  Keep both pieces
    // of state campaign-scoped so their deterministic sequence is independent
    // from every other event stream.
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (campaign_id TEXT PRIMARY KEY, seed TEXT NOT NULL CHECK (seed <> \'\'), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), roll_id TEXT NOT NULL, sides INTEGER NOT NULL CHECK (sides BETWEEN 2 AND 100), result INTEGER NOT NULL CHECK (result BETWEEN 1 AND 100), PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, roll_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), report_id TEXT NOT NULL, target_id TEXT NOT NULL, reason TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('open', 'resolved')), reporter TEXT NOT NULL, action TEXT CHECK (action IN ('allow', 'remove')), note TEXT, resolver TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, report_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_safety_boundary_tags (campaign_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY (campaign_id, tag), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_safety_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), event_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('narration', 'chat')), text TEXT NOT NULL, tags_json TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_exports (campaign_id TEXT NOT NULL, version INTEGER NOT NULL CHECK (version > 0), story TEXT NOT NULL, status TEXT NOT NULL, PRIMARY KEY (campaign_id, version), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_imports (campaign_id TEXT PRIMARY KEY, version INTEGER NOT NULL CHECK (version = 1), story TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('lobby', 'started')), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_migration_states (campaign_id TEXT PRIMARY KEY, schema_version INTEGER NOT NULL CHECK (schema_version = 2), story TEXT NOT NULL, campaign_name TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_search_records (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), record_id TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, record_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_rate_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), event_id TEXT NOT NULL, actor TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (campaign_id TEXT PRIMARY KEY, accepted_rate_events INTEGER NOT NULL DEFAULT 0 CHECK (accepted_rate_events >= 0), rejected_rate_events INTEGER NOT NULL DEFAULT 0 CHECK (rejected_rate_events >= 0), projection_events INTEGER NOT NULL DEFAULT 0 CHECK (projection_events >= 0), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('INSERT OR IGNORE INTO play_campaign_service_metrics (campaign_id) SELECT id FROM play_campaigns');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_scenes (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('open', 'closed')), PRIMARY KEY (campaign_id, id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_scene_states (campaign_id TEXT PRIMARY KEY, current_scene_id TEXT NOT NULL, FOREIGN KEY (campaign_id, current_scene_id) REFERENCES play_campaign_scenes(campaign_id, id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_locations (campaign_id TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_location_states (campaign_id TEXT PRIMARY KEY, current_location_id TEXT NOT NULL, FOREIGN KEY (campaign_id, current_location_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_location_connections (campaign_id TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, travel_turns INTEGER NOT NULL CHECK (travel_turns > 0), PRIMARY KEY (campaign_id, from_id, to_id), FOREIGN KEY (campaign_id, from_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE, FOREIGN KEY (campaign_id, to_id) REFERENCES play_campaign_locations(campaign_id, id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, PRIMARY KEY (campaign_id, username), UNIQUE (campaign_id, character_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_invitations (campaign_id TEXT NOT NULL, invitation_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('pending', 'accepted')), PRIMARY KEY (campaign_id, invitation_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec("CREATE UNIQUE INDEX IF NOT EXISTS play_campaign_pending_invitation_username ON play_campaign_invitations (campaign_id, username) WHERE status = 'pending'");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_delegations (campaign_id TEXT NOT NULL, username TEXT NOT NULL, powers_json TEXT NOT NULL, active INTEGER NOT NULL CHECK (active IN (0, 1)), PRIMARY KEY (campaign_id, username), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), username TEXT NOT NULL, action TEXT NOT NULL CHECK (action IN ('granted', 'revoked')), powers_json TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_audit_events (campaign_id TEXT NOT NULL, timestamp INTEGER NOT NULL CHECK (timestamp > 0), kind TEXT NOT NULL, actor TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN (\'DM\', \'player\')), correlation_id TEXT NOT NULL, PRIMARY KEY (campaign_id, timestamp), UNIQUE (campaign_id, correlation_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_projection_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), event_id TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('set-story', 'increment-danger')), value TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), event_id TEXT NOT NULL, value TEXT NOT NULL, idempotency_key TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), UNIQUE (campaign_id, idempotency_key), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_states (campaign_id TEXT PRIMARY KEY, current_turn INTEGER NOT NULL CHECK (current_turn > 0), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (campaign_id TEXT NOT NULL, accepted_turn INTEGER NOT NULL CHECK (accepted_turn > 0), submission_id TEXT NOT NULL, action TEXT NOT NULL, PRIMARY KEY (campaign_id, accepted_turn), UNIQUE (campaign_id, submission_id), FOREIGN KEY (campaign_id) REFERENCES play_campaign_safe_turn_states(campaign_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_owners (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, owner TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_character_states (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, hp_current INTEGER NOT NULL CHECK (hp_current >= 0), hp_max INTEGER NOT NULL CHECK (hp_max > 0), death_save_successes INTEGER NOT NULL DEFAULT 0 CHECK (death_save_successes BETWEEN 0 AND 3), death_save_failures INTEGER NOT NULL DEFAULT 0 CHECK (death_save_failures BETWEEN 0 AND 3), status TEXT NOT NULL DEFAULT 'conscious' CHECK (status IN ('conscious', 'unconscious', 'stable', 'dead')), PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_progressions (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, level INTEGER NOT NULL CHECK (level BETWEEN 1 AND 20), class TEXT NOT NULL, con_modifier INTEGER NOT NULL, hp_max INTEGER NOT NULL CHECK (hp_max > 0), PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_abilities (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, str INTEGER NOT NULL, dex INTEGER NOT NULL, con INTEGER NOT NULL, int INTEGER NOT NULL, wis INTEGER NOT NULL, cha INTEGER NOT NULL, PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL CHECK (level BETWEEN 0 AND 9), PRIMARY KEY (campaign_id, character_id, spell_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, position INTEGER NOT NULL CHECK (position >= 0), spell_id TEXT NOT NULL, PRIMARY KEY (campaign_id, character_id, position), UNIQUE (campaign_id, character_id, spell_id), FOREIGN KEY (campaign_id, character_id, spell_id) REFERENCES play_campaign_character_spells(campaign_id, character_id, spell_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_casts (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), spell_id TEXT NOT NULL, target TEXT NOT NULL, slot_level INTEGER NOT NULL CHECK (slot_level BETWEEN 0 AND 9), slots_remaining INTEGER NOT NULL CHECK (slots_remaining >= 0), PRIMARY KEY (campaign_id, character_id, sequence), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_concentrations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, spell_id TEXT NOT NULL, target TEXT NOT NULL, remaining_turns INTEGER NOT NULL CHECK (remaining_turns > 0), PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL CHECK (item_id IN (\'healing-potion\', \'torch\', \'leather-armor\', \'ring-of-protection\', \'amulet-of-health\')), quantity INTEGER NOT NULL CHECK (quantity > 0), PRIMARY KEY (campaign_id, character_id, item_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_loot (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, item_id TEXT NOT NULL CHECK (item_id IN ('healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health')), quantity INTEGER NOT NULL CHECK (quantity > 0), status TEXT NOT NULL CHECK (status IN ('open', 'assigned')), recipient_character_id TEXT, votes INTEGER NOT NULL DEFAULT 0 CHECK (votes >= 0), PRIMARY KEY (campaign_id, loot_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (campaign_id TEXT NOT NULL, loot_id TEXT NOT NULL, voter TEXT NOT NULL, recipient_character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, loot_id, voter), FOREIGN KEY (campaign_id, loot_id) REFERENCES play_campaign_loot(campaign_id, loot_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_npcs (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, name TEXT NOT NULL, agenda TEXT NOT NULL, public_status TEXT NOT NULL, PRIMARY KEY (campaign_id, npc_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (campaign_id TEXT NOT NULL, npc_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), dialogue_id TEXT NOT NULL, speaker TEXT NOT NULL, text TEXT NOT NULL, visibility TEXT NOT NULL CHECK (visibility IN ('public', 'private')), PRIMARY KEY (campaign_id, npc_id, sequence), UNIQUE (campaign_id, npc_id, dialogue_id), FOREIGN KEY (campaign_id, npc_id) REFERENCES play_campaign_npcs(campaign_id, npc_id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_relationships (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), source_id TEXT NOT NULL, target_id TEXT NOT NULL, kind TEXT NOT NULL, score INTEGER NOT NULL CHECK (score BETWEEN -100 AND 100), PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, source_id, target_id, kind), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_clues (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), clue_id TEXT NOT NULL, text TEXT NOT NULL, audience TEXT NOT NULL CHECK (audience IN ('character', 'party', 'hidden')), character_id TEXT, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, clue_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_quests (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), quest_id TEXT NOT NULL, title TEXT NOT NULL, depends_on_json TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('locked', 'active', 'completed')), PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, quest_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_configs (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, xp INTEGER NOT NULL CHECK (xp >= 0), items_json TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id), FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quests(campaign_id, quest_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_awards (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id), FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quest_reward_configs(campaign_id, quest_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_quest_rewards (campaign_id TEXT NOT NULL, quest_id TEXT NOT NULL, character_id TEXT NOT NULL, xp INTEGER NOT NULL CHECK (xp >= 0), items_json TEXT NOT NULL, PRIMARY KEY (campaign_id, quest_id, character_id), FOREIGN KEY (campaign_id, quest_id) REFERENCES play_campaign_quest_reward_awards(campaign_id, quest_id) ON DELETE CASCADE, FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_world_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), event_id TEXT NOT NULL, turn_number INTEGER NOT NULL CHECK (turn_number > 0), title TEXT NOT NULL, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, event_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_world_event_resolutions (campaign_id TEXT NOT NULL, event_id TEXT NOT NULL, turn_number INTEGER NOT NULL CHECK (turn_number > 0), text TEXT NOT NULL, PRIMARY KEY (campaign_id, event_id), FOREIGN KEY (campaign_id, event_id) REFERENCES play_campaign_world_events(campaign_id, event_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_exploration_handoffs (campaign_id TEXT PRIMARY KEY, actor TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_factions (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, name TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (campaign_id TEXT NOT NULL, faction_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), character_id TEXT NOT NULL, reputation INTEGER NOT NULL CHECK (reputation BETWEEN -100 AND 100), delta INTEGER NOT NULL CHECK (delta BETWEEN -25 AND 25 AND delta != 0), reason TEXT NOT NULL, PRIMARY KEY (campaign_id, faction_id, sequence), FOREIGN KEY (campaign_id, faction_id) REFERENCES play_campaign_factions(campaign_id, faction_id) ON DELETE CASCADE, FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_currency (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, gold INTEGER NOT NULL CHECK (gold >= 0), PRIMARY KEY (campaign_id, character_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (campaign_id TEXT NOT NULL, transfer_id INTEGER NOT NULL CHECK (transfer_id > 0), from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, gold INTEGER NOT NULL CHECK (gold > 0), PRIMARY KEY (campaign_id, transfer_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), from_character_id TEXT NOT NULL, to_character_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK (amount > 0), from_gold INTEGER NOT NULL CHECK (from_gold >= 0), to_gold INTEGER NOT NULL CHECK (to_gold >= 0), PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, slot TEXT NOT NULL CHECK (slot IN ('armor', 'accessory')), item_id TEXT NOT NULL, attuned INTEGER NOT NULL DEFAULT 0 CHECK (attuned IN (0, 1)), PRIMARY KEY (campaign_id, character_id, slot), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)");
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_encounters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('active', 'closed')), combatants_json TEXT NOT NULL, conditions_json TEXT NOT NULL DEFAULT '{}', combat_round INTEGER NOT NULL DEFAULT 1 CHECK (combat_round > 0), combat_turn_index INTEGER NOT NULL DEFAULT 0 CHECK (combat_turn_index >= 0), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_states (campaign_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status = 'active'), phase TEXT NOT NULL DEFAULT 'player' CHECK (phase IN ('player', 'exploration', 'combat')), current_actor TEXT NOT NULL, turn_number INTEGER NOT NULL CHECK (turn_number > 0), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_calendars (campaign_id TEXT PRIMARY KEY, day INTEGER NOT NULL CHECK (day >= 1), season TEXT NOT NULL CHECK (season IN ('spring', 'summer', 'autumn', 'winter')), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_settlements (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, name TEXT NOT NULL, services_json TEXT NOT NULL, availability TEXT NOT NULL CHECK (availability IN ('open', 'limited', 'closed')), PRIMARY KEY (campaign_id, settlement_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, character_id TEXT NOT NULL, PRIMARY KEY (campaign_id, settlement_id, character_id), FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_settlement_shops (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, name TEXT NOT NULL, buy_price INTEGER NOT NULL CHECK (buy_price > 0), sell_price INTEGER NOT NULL CHECK (sell_price >= 0), PRIMARY KEY (campaign_id, settlement_id, shop_id), FOREIGN KEY (campaign_id, settlement_id) REFERENCES play_campaign_settlements(campaign_id, settlement_id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS play_campaign_settlement_shop_stock (campaign_id TEXT NOT NULL, settlement_id TEXT NOT NULL, shop_id TEXT NOT NULL, item_id TEXT NOT NULL CHECK (item_id IN ('healing-potion', 'torch', 'leather-armor', 'ring-of-protection', 'amulet-of-health')), quantity INTEGER NOT NULL CHECK (quantity > 0), PRIMARY KEY (campaign_id, settlement_id, shop_id, item_id), FOREIGN KEY (campaign_id, settlement_id, shop_id) REFERENCES play_campaign_settlement_shops(campaign_id, settlement_id, shop_id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_recipes (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), recipe_id TEXT NOT NULL, name TEXT NOT NULL, ingredients_json TEXT NOT NULL, output_item TEXT NOT NULL CHECK (output_item IN (\'healing-potion\', \'torch\', \'leather-armor\', \'ring-of-protection\', \'amulet-of-health\')), output_quantity INTEGER NOT NULL CHECK (output_quantity > 0), PRIMARY KEY (campaign_id, sequence), UNIQUE (campaign_id, recipe_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (campaign_id TEXT NOT NULL, activity_id TEXT NOT NULL, name TEXT NOT NULL, cycles_required INTEGER NOT NULL CHECK (cycles_required BETWEEN 1 AND 10), PRIMARY KEY (campaign_id, activity_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, activity_id TEXT NOT NULL, cycles_completed INTEGER NOT NULL DEFAULT 0 CHECK (cycles_completed >= 0), completions INTEGER NOT NULL DEFAULT 0 CHECK (completions >= 0), PRIMARY KEY (campaign_id, character_id, activity_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE, FOREIGN KEY (campaign_id, activity_id) REFERENCES play_campaign_downtime_activities(campaign_id, activity_id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), kind TEXT NOT NULL, actor TEXT NOT NULL, type TEXT, target TEXT, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_characters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, level INTEGER NOT NULL, class TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_events (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, kind TEXT NOT NULL, summary TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_factions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, stance TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_npcs (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, faction_id TEXT NOT NULL, disposition INTEGER NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE, FOREIGN KEY (faction_id) REFERENCES campaign_factions(id) ON DELETE RESTRICT)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_quests (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, title TEXT NOT NULL, status TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_quest_milestones (quest_id TEXT NOT NULL, position INTEGER NOT NULL, title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (quest_id, position), UNIQUE (quest_id, title), FOREIGN KEY (quest_id) REFERENCES campaign_quests(id) ON DELETE CASCADE)');
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_sessions (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, starts_at TEXT NOT NULL, duration_minutes INTEGER NOT NULL CHECK (duration_minutes > 0), agenda_json TEXT NOT NULL, FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)');
    $database->exec("CREATE TABLE IF NOT EXISTS campaign_session_attendance (session_id TEXT NOT NULL, character_id TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('present', 'absent')), PRIMARY KEY (session_id, character_id), FOREIGN KEY (session_id) REFERENCES campaign_sessions(id) ON DELETE CASCADE, FOREIGN KEY (character_id) REFERENCES campaign_characters(id) ON DELETE CASCADE)");
    $database->exec("CREATE TABLE IF NOT EXISTS crafting_projects (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, days_required INTEGER NOT NULL CHECK (days_required > 0), days_completed INTEGER NOT NULL DEFAULT 0 CHECK (days_completed >= 0), cost_gp INTEGER NOT NULL CHECK (cost_gp >= 0), status TEXT NOT NULL CHECK (status IN ('active', 'complete')), FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE, FOREIGN KEY (character_id) REFERENCES campaign_characters(id) ON DELETE CASCADE)");
    $database->exec("CREATE TABLE IF NOT EXISTS campaign_inventory (campaign_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity > 0), owner TEXT NOT NULL CHECK (owner = 'party'), PRIMARY KEY (campaign_id, item_slug), FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE)");
    $database->exec('CREATE TABLE IF NOT EXISTS campaign_equipment (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_slug TEXT NOT NULL, quantity INTEGER NOT NULL CHECK (quantity > 0), PRIMARY KEY (campaign_id, character_id, item_slug), FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE, FOREIGN KEY (character_id) REFERENCES campaign_characters(id) ON DELETE CASCADE)');
    // A character belongs to at most one member record within a campaign, but
    // can join a separate campaign. Earlier schemas made character_id global,
    // which prevented an existing player from joining a second campaign.
    $memberSchema = $database->query("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'play_campaign_members'")->fetchColumn();
    if (!is_string($memberSchema) || !str_contains($memberSchema, 'UNIQUE (campaign_id, character_id)')) {
        $database->beginTransaction();
        try {
            $database->exec('ALTER TABLE play_campaign_members RENAME TO play_campaign_members_legacy');
            $database->exec('CREATE TABLE play_campaign_members (campaign_id TEXT NOT NULL, username TEXT NOT NULL, character_id TEXT NOT NULL, name TEXT NOT NULL, class TEXT NOT NULL, PRIMARY KEY (campaign_id, username), UNIQUE (campaign_id, character_id), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
            $database->exec('INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) SELECT campaign_id, username, character_id, name, class FROM play_campaign_members_legacy');
            $database->exec('DROP TABLE play_campaign_members_legacy');
            $database->commit();
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    }

    // Membership records predate explicit character ownership.  They already
    // establish the one-to-one initial owner relationship, so preserve it.
    $database->exec('INSERT OR IGNORE INTO play_campaign_character_owners (campaign_id, character_id, owner) SELECT campaign_id, character_id, username FROM play_campaign_members');

    // Currency was introduced after campaigns could already have members.
    // Every character receives the same deterministic initial balance exactly
    // once, whether they joined before or after this schema version.
    $database->exec('INSERT OR IGNORE INTO play_campaign_character_currency (campaign_id, character_id, gold) SELECT campaign_id, character_id, 10 FROM play_campaign_members');

    // The inventory catalog grows without changing the stack API. SQLite
    // cannot alter CHECK constraints, so rebuild older catalogs once.
    $inventorySchema = $database->query("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'play_campaign_character_inventory_items'")->fetchColumn();
    if (!is_string($inventorySchema) || !str_contains($inventorySchema, "'leather-armor'")) {
        $database->beginTransaction();
        try {
            $database->exec('ALTER TABLE play_campaign_character_inventory_items RENAME TO play_campaign_character_inventory_items_legacy');
            $database->exec('CREATE TABLE play_campaign_character_inventory_items (campaign_id TEXT NOT NULL, character_id TEXT NOT NULL, item_id TEXT NOT NULL CHECK (item_id IN (\'healing-potion\', \'torch\', \'leather-armor\', \'ring-of-protection\', \'amulet-of-health\')), quantity INTEGER NOT NULL CHECK (quantity > 0), PRIMARY KEY (campaign_id, character_id, item_id), FOREIGN KEY (campaign_id, character_id) REFERENCES play_campaign_character_states(campaign_id, character_id) ON DELETE CASCADE)');
            $database->exec('INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) SELECT campaign_id, character_id, item_id, quantity FROM play_campaign_character_inventory_items_legacy');
            $database->exec('DROP TABLE play_campaign_character_inventory_items_legacy');
            $database->commit();
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    }
    // Stage 25 adds player action events.  Earlier databases constrained this
    // table to DM narration and did not retain an action type, so rebuild it
    // once while preserving every existing narration event.
    $eventColumns = tableColumnNames($database, 'play_campaign_events');
    $hasEventType = isset($eventColumns['type']);
    $hasEventTarget = isset($eventColumns['target']);
    if (!$hasEventType) {
        $database->beginTransaction();
        try {
            $database->exec('ALTER TABLE play_campaign_events RENAME TO play_campaign_events_legacy');
            $database->exec('CREATE TABLE play_campaign_events (campaign_id TEXT NOT NULL, sequence INTEGER NOT NULL CHECK (sequence > 0), kind TEXT NOT NULL, actor TEXT NOT NULL, type TEXT, target TEXT, text TEXT NOT NULL, PRIMARY KEY (campaign_id, sequence), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)');
            $database->exec('INSERT INTO play_campaign_events (campaign_id, sequence, kind, actor, type, target, text) SELECT campaign_id, sequence, kind, actor, NULL, NULL, text FROM play_campaign_events_legacy');
            $database->exec('DROP TABLE play_campaign_events_legacy');
            $database->commit();
            $hasEventTarget = true;
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    }
    if (!$hasEventTarget) {
        $database->exec('ALTER TABLE play_campaign_events ADD COLUMN target TEXT');
    }

    // Combat turn state was added after encounters were already persisted.
    // SQLite only supports additive migrations here, so retain every roster
    // and initialize existing encounters at the first combatant.
    $encounterColumns = tableColumnNames($database, 'play_campaign_encounters');
    $hasCombatRound = isset($encounterColumns['combat_round']);
    $hasCombatTurnIndex = isset($encounterColumns['combat_turn_index']);
    $hasConditions = isset($encounterColumns['conditions_json']);
    if (!$hasCombatRound) {
        $database->exec('ALTER TABLE play_campaign_encounters ADD COLUMN combat_round INTEGER NOT NULL DEFAULT 1 CHECK (combat_round > 0)');
    }
    if (!$hasCombatTurnIndex) {
        $database->exec('ALTER TABLE play_campaign_encounters ADD COLUMN combat_turn_index INTEGER NOT NULL DEFAULT 0 CHECK (combat_turn_index >= 0)');
    }
    if (!$hasConditions) {
        $database->exec("ALTER TABLE play_campaign_encounters ADD COLUMN conditions_json TEXT NOT NULL DEFAULT '{}'");
    }

    // Combat temporarily pauses the exploration queue.  Existing active
    // campaigns predate that distinction, so they resume in exploration.
    $stateColumns = tableColumnNames($database, 'play_campaign_states');
    $hasPhase = isset($stateColumns['phase']);
    if (!$hasPhase) {
        $database->exec("ALTER TABLE play_campaign_states ADD COLUMN phase TEXT NOT NULL DEFAULT 'exploration'");
    }

    // The original turn API calls its initial player-controlled phase
    // "player".  Combat later introduced the distinct "exploration" phase,
    // so retain both values rather than collapsing the older contract.
    $stateSchema = $database->query("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'play_campaign_states'")->fetchColumn();
    if (!is_string($stateSchema) || !str_contains($stateSchema, "'player'")) {
        $database->beginTransaction();
        try {
            $database->exec('ALTER TABLE play_campaign_states RENAME TO play_campaign_states_legacy');
            $database->exec("CREATE TABLE play_campaign_states (campaign_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status = 'active'), phase TEXT NOT NULL DEFAULT 'player' CHECK (phase IN ('player', 'exploration', 'combat')), current_actor TEXT NOT NULL, turn_number INTEGER NOT NULL CHECK (turn_number > 0), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
            $database->exec('INSERT INTO play_campaign_states (campaign_id, status, phase, current_actor, turn_number) SELECT campaign_id, status, phase, current_actor, turn_number FROM play_campaign_states_legacy');
            $database->exec('DROP TABLE play_campaign_states_legacy');
            $database->commit();
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    }

    // Earlier encounter rows could never leave the active state and allowed
    // only one encounter per campaign. Rebuild once so closed encounters and
    // their subsequent replacements can coexist while retaining combat data.
    $encounterSchema = $database->query("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'play_campaign_encounters'")->fetchColumn();
    if (!is_string($encounterSchema) || !str_contains($encounterSchema, "'closed'")) {
        $database->beginTransaction();
        try {
            $database->exec('ALTER TABLE play_campaign_encounters RENAME TO play_campaign_encounters_legacy');
            $database->exec("CREATE TABLE play_campaign_encounters (id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, name TEXT NOT NULL, status TEXT NOT NULL CHECK (status IN ('active', 'closed')), combatants_json TEXT NOT NULL, conditions_json TEXT NOT NULL DEFAULT '{}', combat_round INTEGER NOT NULL DEFAULT 1 CHECK (combat_round > 0), combat_turn_index INTEGER NOT NULL DEFAULT 0 CHECK (combat_turn_index >= 0), FOREIGN KEY (campaign_id) REFERENCES play_campaigns(id) ON DELETE CASCADE)");
            $database->exec('INSERT INTO play_campaign_encounters (id, campaign_id, name, status, combatants_json, conditions_json, combat_round, combat_turn_index) SELECT id, campaign_id, name, status, combatants_json, conditions_json, combat_round, combat_turn_index FROM play_campaign_encounters_legacy');
            $database->exec('DROP TABLE play_campaign_encounters_legacy');
            $database->commit();
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    }

    $database->exec('CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (encounter_id TEXT PRIMARY KEY, xp INTEGER NOT NULL CHECK (xp >= 0), loot_json TEXT NOT NULL, FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE)');
    $rewardForeignKeys = $database->query('PRAGMA foreign_key_list(play_campaign_encounter_rewards)')->fetchAll(PDO::FETCH_ASSOC);
    if (($rewardForeignKeys[0]['table'] ?? null) !== 'play_campaign_encounters') {
        $database->beginTransaction();
        try {
            $database->exec('ALTER TABLE play_campaign_encounter_rewards RENAME TO play_campaign_encounter_rewards_legacy');
            $database->exec('CREATE TABLE play_campaign_encounter_rewards (encounter_id TEXT PRIMARY KEY, xp INTEGER NOT NULL CHECK (xp >= 0), loot_json TEXT NOT NULL, FOREIGN KEY (encounter_id) REFERENCES play_campaign_encounters(id) ON DELETE CASCADE)');
            $database->exec('INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot_json) SELECT encounter_id, xp, loot_json FROM play_campaign_encounter_rewards_legacy');
            $database->exec('DROP TABLE play_campaign_encounter_rewards_legacy');
            $database->commit();
        } catch (Throwable $exception) {
            if ($database->inTransaction()) {
                $database->rollBack();
            }
            throw $exception;
        }
    }

    // Death saves extend the original HP state. Additive migrations preserve
    // existing campaign state and give every pre-existing character a
    // deterministic zero-save starting condition.
    $characterStateColumns = tableColumnNames($database, 'play_campaign_character_states');
    $hasDeathSaveSuccesses = isset($characterStateColumns['death_save_successes']);
    $hasDeathSaveFailures = isset($characterStateColumns['death_save_failures']);
    $hasCharacterStatus = isset($characterStateColumns['status']);
    if (!$hasDeathSaveSuccesses) {
        $database->exec('ALTER TABLE play_campaign_character_states ADD COLUMN death_save_successes INTEGER NOT NULL DEFAULT 0');
    }
    if (!$hasDeathSaveFailures) {
        $database->exec('ALTER TABLE play_campaign_character_states ADD COLUMN death_save_failures INTEGER NOT NULL DEFAULT 0');
    }
    if (!$hasCharacterStatus) {
        $database->exec("ALTER TABLE play_campaign_character_states ADD COLUMN status TEXT NOT NULL DEFAULT 'conscious'");
        $database->exec("UPDATE play_campaign_character_states SET status = 'unconscious' WHERE hp_current = 0");
    }

    $statement = $database->prepare('INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)');
    $statement->execute(['schema_version', (string) SCHEMA_VERSION]);
}

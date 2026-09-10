require 'sinatra/base'
require 'json'
require 'openssl'
require 'securerandom'
require 'open3'
require 'time'

module GameStorage
  PATH = File.expand_path('game.db', __dir__)

  module_function

  def execute(sql)
    run_sql(sql)
  end

  def query(sql)
    output = run_sql(sql, '-json')
    output.empty? ? [] : JSON.parse(output)
  end

  def quote(value)
    "'#{value.to_s.gsub("'", "''")}'"
  end

  # All database access uses the same sqlite executable and fails consistently.
  def run_sql(sql, *options)
    output, error, status = Open3.capture3('/usr/bin/sqlite3', *options, PATH, stdin_data: sql)
    raise "sqlite error: #{error}" unless status.success?

    output
  end

  def initialize_schema!
    execute <<~SQL
      CREATE TABLE IF NOT EXISTS schema_metadata (version INTEGER NOT NULL);
      CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, role TEXT NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS combat_sessions (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        owner TEXT NOT NULL,
        status TEXT NOT NULL,
        max_players INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_spectators (
        spectator_id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_chats (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        actor TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_session_zero_settings (
        campaign_id TEXT PRIMARY KEY,
        rules TEXT NOT NULL,
        tone TEXT NOT NULL,
        consent TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_content (
        campaign_id TEXT NOT NULL,
        content_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        tags TEXT NOT NULL,
        PRIMARY KEY (campaign_id, content_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_notes (
        campaign_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        text TEXT NOT NULL,
        visibility TEXT NOT NULL,
        owner TEXT NOT NULL,
        PRIMARY KEY (campaign_id, note_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_whispers (
        campaign_id TEXT NOT NULL,
        whisper_id TEXT NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, whisper_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_calendars (
        campaign_id TEXT PRIMARY KEY,
        day INTEGER NOT NULL,
        season TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_settlements (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        name TEXT NOT NULL,
        services TEXT NOT NULL,
        availability TEXT NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_settlement_discoveries (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_shops (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        shop_id TEXT NOT NULL,
        name TEXT NOT NULL,
        stock TEXT NOT NULL,
        buy_price INTEGER NOT NULL,
        sell_price INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id, shop_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_members (
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        character_id TEXT NOT NULL,
        name TEXT NOT NULL,
        class TEXT NOT NULL,
        PRIMARY KEY (campaign_id, username),
        UNIQUE (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_invitations (
        campaign_id TEXT NOT NULL,
        invitation_id TEXT NOT NULL,
        username TEXT NOT NULL,
        character_id TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, invitation_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_delegations (
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        powers TEXT NOT NULL,
        active INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, username)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        powers TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        kind TEXT NOT NULL,
        actor TEXT NOT NULL,
        role TEXT NOT NULL,
        correlation_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, correlation_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        value TEXT,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        value TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id),
        UNIQUE (campaign_id, idempotency_key)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
        campaign_id TEXT NOT NULL,
        submission_id TEXT NOT NULL,
        action TEXT NOT NULL,
        accepted_turn INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, submission_id),
        UNIQUE (campaign_id, accepted_turn)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_owners (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        owner TEXT NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_progressions (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL,
        con_modifier INTEGER NOT NULL,
        hp_max INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_abilities (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        str INTEGER NOT NULL,
        dex INTEGER NOT NULL,
        con INTEGER NOT NULL,
        int INTEGER NOT NULL,
        wis INTEGER NOT NULL,
        cha INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_spells (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, spell_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_prepared_spells (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        position INTEGER NOT NULL,
        spell_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, character_id, position),
        UNIQUE (campaign_id, character_id, spell_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_casts (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        spell_id TEXT NOT NULL,
        target TEXT NOT NULL,
        slot_level INTEGER NOT NULL,
        slots_remaining INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_concentrations (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        spell_id TEXT NOT NULL,
        target TEXT NOT NULL,
        remaining_turns INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_inventory_items (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, item_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_recipes (
        campaign_id TEXT NOT NULL,
        recipe_id TEXT NOT NULL,
        name TEXT NOT NULL,
        ingredients TEXT NOT NULL,
        output_item TEXT NOT NULL,
        output_quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, recipe_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
        campaign_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        name TEXT NOT NULL,
        cycles_required INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, activity_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        cycles_completed INTEGER NOT NULL,
        completions INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, activity_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_loot (
        campaign_id TEXT NOT NULL,
        loot_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        status TEXT NOT NULL,
        recipient_character_id TEXT,
        votes INTEGER,
        PRIMARY KEY (campaign_id, loot_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_loot_votes (
        campaign_id TEXT NOT NULL,
        loot_id TEXT NOT NULL,
        voter TEXT NOT NULL,
        recipient_character_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, loot_id, voter)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_npcs (
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        name TEXT NOT NULL,
        agenda TEXT NOT NULL,
        public_status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, npc_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        dialogue_id TEXT NOT NULL,
        speaker TEXT NOT NULL,
        text TEXT NOT NULL,
        visibility TEXT NOT NULL,
        PRIMARY KEY (campaign_id, npc_id, sequence),
        UNIQUE (campaign_id, npc_id, dialogue_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_relationships (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        score INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, source_id, target_id, kind)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_clues (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        clue_id TEXT NOT NULL,
        text TEXT NOT NULL,
        audience TEXT NOT NULL,
        character_id TEXT,
        PRIMARY KEY (campaign_id, clue_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_quests (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        quest_id TEXT NOT NULL,
        title TEXT NOT NULL,
        depends_on TEXT NOT NULL,
        state TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_quest_rewards (
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        xp INTEGER NOT NULL,
        items TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_awards (
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_quest_reward_grants (
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        xp INTEGER NOT NULL,
        items TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_world_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        turn_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        text TEXT NOT NULL,
        status TEXT NOT NULL,
        resolution_turn_number INTEGER,
        resolution_text TEXT,
        PRIMARY KEY (campaign_id, event_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_factions (
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (campaign_id, faction_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_faction_reputation_history (
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        character_id TEXT NOT NULL,
        reputation INTEGER NOT NULL,
        delta INTEGER NOT NULL,
        reason TEXT NOT NULL,
        PRIMARY KEY (campaign_id, faction_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_currency (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        gold INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_currency_transfers (
        campaign_id TEXT NOT NULL,
        transfer_id INTEGER NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        gold INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, transfer_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_transactional_transfers (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        from_character_id TEXT NOT NULL,
        to_character_id TEXT NOT NULL,
        amount INTEGER NOT NULL,
        from_gold INTEGER NOT NULL,
        to_gold INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_character_equipment (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        slot TEXT NOT NULL,
        item_id TEXT NOT NULL,
        attuned INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, slot)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_narrations (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_actions (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        actor TEXT NOT NULL,
        type TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_resolutions (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_travels (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        actor TEXT NOT NULL,
        destination_id TEXT NOT NULL,
        travel_turns INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_rests (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        actor TEXT NOT NULL,
        type TEXT NOT NULL,
        hp_current INTEGER NOT NULL,
        hp_max INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_member_health (
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        hp_current INTEGER NOT NULL,
        hp_max INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, username)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_member_death_saves (
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        successes INTEGER NOT NULL,
        failures INTEGER NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, username)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_encounters (
        id TEXT PRIMARY KEY,
        campaign_id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_combat_handoffs (
        campaign_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        end_sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, encounter_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_rewards (
        encounter_id TEXT PRIMARY KEY,
        xp INTEGER NOT NULL,
        loot TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_monsters (
        encounter_id TEXT NOT NULL,
        monster_id TEXT NOT NULL,
        name TEXT NOT NULL,
        hp_current INTEGER NOT NULL,
        hp_max INTEGER NOT NULL,
        initiative INTEGER NOT NULL,
        PRIMARY KEY (encounter_id, monster_id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_combatants (
        encounter_id TEXT NOT NULL,
        member TEXT NOT NULL,
        character_id TEXT NOT NULL,
        name TEXT NOT NULL,
        initiative INTEGER NOT NULL,
        PRIMARY KEY (encounter_id, member)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_turns (
        encounter_id TEXT PRIMARY KEY,
        round INTEGER NOT NULL,
        turn_index INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_turn_orders (
        encounter_id TEXT PRIMARY KEY,
        turn_order TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_encounter_conditions (
        encounter_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        target TEXT NOT NULL,
        condition TEXT NOT NULL,
        remaining_rounds INTEGER NOT NULL,
        PRIMARY KEY (encounter_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_combat_actions (
        campaign_id TEXT NOT NULL,
        encounter_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        actor TEXT NOT NULL,
        type TEXT NOT NULL,
        target TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_event_sequences (
        campaign_id TEXT PRIMARY KEY,
        sequence INTEGER NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_nudges (
        campaign_id TEXT NOT NULL,
        nudge_count INTEGER NOT NULL,
        actor TEXT NOT NULL,
        target TEXT NOT NULL,
        message TEXT NOT NULL,
        PRIMARY KEY (campaign_id, nudge_count)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_documents (
        campaign_id TEXT PRIMARY KEY,
        story TEXT NOT NULL,
        dm_notes TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_exports (
        campaign_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, version)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_backups (
        campaign_id TEXT NOT NULL,
        backup_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, backup_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_replay_events (
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, event_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_feed_events (
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        text TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, event_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_rng_seeds (
        campaign_id TEXT PRIMARY KEY,
        seed TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_rng_rolls (
        campaign_id TEXT NOT NULL,
        roll_id TEXT NOT NULL,
        sides INTEGER NOT NULL,
        result INTEGER NOT NULL,
        sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, roll_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_moderation_reports (
        campaign_id TEXT NOT NULL,
        report_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL,
        reporter TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        action TEXT,
        note TEXT,
        resolver TEXT,
        PRIMARY KEY (campaign_id, report_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_safety_boundaries (
        campaign_id TEXT PRIMARY KEY,
        blocked_tags TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_safety_events (
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        text TEXT NOT NULL,
        tags TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, event_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_fixture_seeds (
        campaign_id TEXT PRIMARY KEY,
        fixture_id TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_imports (
        campaign_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL,
        story TEXT NOT NULL,
        status TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_migrations (
        campaign_id TEXT PRIMARY KEY,
        schema_version INTEGER NOT NULL,
        story TEXT NOT NULL,
        campaign_name TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_search_records (
        campaign_id TEXT NOT NULL,
        record_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY (campaign_id, record_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_rate_events (
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        actor TEXT NOT NULL,
        PRIMARY KEY (campaign_id, event_id),
        UNIQUE (campaign_id, sequence)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_service_metrics (
        campaign_id TEXT PRIMARY KEY,
        accepted_rate_events INTEGER NOT NULL DEFAULT 0,
        rejected_rate_events INTEGER NOT NULL DEFAULT 0,
        projection_events INTEGER NOT NULL DEFAULT 0
      );
      CREATE TABLE IF NOT EXISTS play_campaign_scenes (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_scene_state (
        campaign_id TEXT PRIMARY KEY,
        current_scene_id TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS play_campaign_locations (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS play_campaign_location_connections (
        campaign_id TEXT NOT NULL,
        from_id TEXT NOT NULL,
        to_id TEXT NOT NULL,
        travel_turns INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, from_id, to_id)
      );
      CREATE TABLE IF NOT EXISTS campaign_characters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_quests (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        milestones TEXT NOT NULL,
        completed_milestones TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_factions (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        stance TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_npcs (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        disposition INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_inventory (
        campaign_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        owner TEXT NOT NULL,
        PRIMARY KEY (campaign_id, item_slug, owner)
      );
      CREATE TABLE IF NOT EXISTS campaign_equipment (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, item_slug)
      );
      CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        days_required INTEGER NOT NULL,
        days_completed INTEGER NOT NULL,
        cost_gp INTEGER NOT NULL,
        status TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_sessions (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        starts_at TEXT NOT NULL,
        starts_at_epoch REAL NOT NULL,
        duration_minutes INTEGER NOT NULL,
        agenda TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_session_attendance (
        campaign_id TEXT NOT NULL,
        session_id TEXT NOT NULL,
        present TEXT NOT NULL,
        absent TEXT NOT NULL,
        PRIMARY KEY (campaign_id, session_id)
      );
      CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        cr TEXT NOT NULL,
        armor_class INTEGER NOT NULL,
        hit_points INTEGER NOT NULL,
        tags TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL,
        rarity TEXT NOT NULL,
        cost_gp INTEGER NOT NULL
      );
      DELETE FROM schema_metadata;
      INSERT INTO schema_metadata (version) VALUES (1);
    SQL
    handoff_columns = query('PRAGMA table_info(play_campaign_combat_handoffs)').map { |column| column['name'] }
    execute('ALTER TABLE play_campaign_combat_handoffs ADD COLUMN end_sequence INTEGER NOT NULL DEFAULT 0;') unless handoff_columns.include?('end_sequence')
  end

  def reset!
    execute <<~SQL
      DROP TABLE IF EXISTS combat_sessions;
      DROP TABLE IF EXISTS campaign_npcs;
      DROP TABLE IF EXISTS campaign_factions;
      DROP TABLE IF EXISTS campaign_quests;
      DROP TABLE IF EXISTS campaign_events;
      DROP TABLE IF EXISTS campaign_session_attendance;
      DROP TABLE IF EXISTS campaign_sessions;
      DROP TABLE IF EXISTS campaign_crafting_projects;
      DROP TABLE IF EXISTS campaign_equipment;
      DROP TABLE IF EXISTS campaign_inventory;
      DROP TABLE IF EXISTS campaign_characters;
      DROP TABLE IF EXISTS campaigns;
      DROP TABLE IF EXISTS play_campaign_resolutions;
      DROP TABLE IF EXISTS play_campaign_travels;
      DROP TABLE IF EXISTS play_campaign_rests;
      DROP TABLE IF EXISTS play_campaign_member_health;
      DROP TABLE IF EXISTS play_campaign_member_death_saves;
      DROP TABLE IF EXISTS play_campaign_encounter_conditions;
      DROP TABLE IF EXISTS play_campaign_encounter_rewards;
      DROP TABLE IF EXISTS play_campaign_encounter_turn_orders;
      DROP TABLE IF EXISTS play_campaign_encounter_turns;
      DROP TABLE IF EXISTS play_campaign_combat_actions;
      DROP TABLE IF EXISTS play_campaign_encounter_combatants;
      DROP TABLE IF EXISTS play_campaign_encounter_monsters;
      DROP TABLE IF EXISTS play_campaign_encounters;
      DROP TABLE IF EXISTS play_campaign_combat_handoffs;
      DROP TABLE IF EXISTS play_campaign_event_sequences;
      DROP TABLE IF EXISTS play_campaign_actions;
      DROP TABLE IF EXISTS play_campaign_narrations;
      DROP TABLE IF EXISTS play_campaign_nudges;
      DROP TABLE IF EXISTS play_campaign_imports;
      DROP TABLE IF EXISTS play_campaign_migrations;
      DROP TABLE IF EXISTS play_campaign_search_records;
      DROP TABLE IF EXISTS play_campaign_rate_events;
      DROP TABLE IF EXISTS play_campaign_service_metrics;
      DROP TABLE IF EXISTS play_campaign_rng_rolls;
      DROP TABLE IF EXISTS play_campaign_rng_seeds;
      DROP TABLE IF EXISTS play_campaign_moderation_reports;
      DROP TABLE IF EXISTS play_campaign_replay_events;
      DROP TABLE IF EXISTS play_campaign_feed_events;
      DROP TABLE IF EXISTS play_campaign_backups;
      DROP TABLE IF EXISTS play_campaign_exports;
      DROP TABLE IF EXISTS play_campaign_documents;
      DROP TABLE IF EXISTS play_campaign_scene_state;
      DROP TABLE IF EXISTS play_campaign_scenes;
      DROP TABLE IF EXISTS play_campaign_location_connections;
      DROP TABLE IF EXISTS play_campaign_locations;
      DROP TABLE IF EXISTS play_campaign_character_abilities;
      DROP TABLE IF EXISTS play_campaign_character_equipment;
      DROP TABLE IF EXISTS play_campaign_character_inventory_items;
      DROP TABLE IF EXISTS play_campaign_recipes;
      DROP TABLE IF EXISTS play_campaign_downtime_allocations;
      DROP TABLE IF EXISTS play_campaign_downtime_activities;
      DROP TABLE IF EXISTS play_campaign_faction_reputation_history;
      DROP TABLE IF EXISTS play_campaign_factions;
      DROP TABLE IF EXISTS play_campaign_relationships;
      DROP TABLE IF EXISTS play_campaign_clues;
      DROP TABLE IF EXISTS play_campaign_quest_reward_grants;
      DROP TABLE IF EXISTS play_campaign_quest_reward_awards;
      DROP TABLE IF EXISTS play_campaign_quest_rewards;
      DROP TABLE IF EXISTS play_campaign_quests;
      DROP TABLE IF EXISTS play_campaign_world_events;
      DROP TABLE IF EXISTS play_campaign_npc_dialogue;
      DROP TABLE IF EXISTS play_campaign_npcs;
      DROP TABLE IF EXISTS play_campaign_loot_votes;
      DROP TABLE IF EXISTS play_campaign_loot;
      DROP TABLE IF EXISTS play_campaign_currency_transfers;
      DROP TABLE IF EXISTS play_campaign_transactional_transfers;
      DROP TABLE IF EXISTS play_campaign_character_currency;
      DROP TABLE IF EXISTS play_campaign_character_concentrations;
      DROP TABLE IF EXISTS play_campaign_character_casts;
      DROP TABLE IF EXISTS play_campaign_character_prepared_spells;
      DROP TABLE IF EXISTS play_campaign_character_spells;
      DROP TABLE IF EXISTS play_campaign_character_progressions;
      DROP TABLE IF EXISTS play_campaign_character_owners;
      DROP TABLE IF EXISTS play_campaign_delegation_audit;
      DROP TABLE IF EXISTS play_campaign_delegations;
      DROP TABLE IF EXISTS play_campaign_safe_turns;
      DROP TABLE IF EXISTS play_campaign_idempotent_events;
      DROP TABLE IF EXISTS play_campaign_projection_events;
      DROP TABLE IF EXISTS play_campaign_audit_events;
      DROP TABLE IF EXISTS play_campaign_invitations;
      DROP TABLE IF EXISTS play_campaign_members;
      DROP TABLE IF EXISTS play_campaign_shops;
      DROP TABLE IF EXISTS play_campaign_settlement_discoveries;
      DROP TABLE IF EXISTS play_campaign_settlements;
      DROP TABLE IF EXISTS play_campaign_calendars;
      DROP TABLE IF EXISTS play_campaign_content;
      DROP TABLE IF EXISTS play_campaign_notes;
      DROP TABLE IF EXISTS play_campaign_whispers;
      DROP TABLE IF EXISTS play_campaign_session_zero_settings;
      DROP TABLE IF EXISTS play_campaign_spectators;
      DROP TABLE IF EXISTS play_campaign_chats;
      DROP TABLE IF EXISTS play_campaigns;
      DROP TABLE IF EXISTS monsters;
      DROP TABLE IF EXISTS items;
      DROP TABLE IF EXISTS users;
      DROP TABLE IF EXISTS schema_metadata;
    SQL
    initialize_schema!
  end
end

class DndApi < Sinatra::Base
  set :bind, '127.0.0.1'
  set :port, ENV.fetch('PORT', '4567').to_i
  set :show_exceptions, false

  DATABASE_MUTEX = Mutex.new
  SERVICE_MODE_MUTEX = Mutex.new
  SCHEMA_VERSION = 1

  PASSWORD_HASH_ITERATIONS = 100_000
  PASSWORD_SALT_BYTES = 16
  PASSWORD_HASH_BYTES = 32
  API_SCHEMA_JSON = '{"version":"2026-07-29","endpoints":[{"method":"GET","path":"/v1/play/campaigns/{id}/rng-ledger","auth":"member"},{"method":"GET","path":"/v1/schema","auth":"public"},{"method":"POST","path":"/v1/play/campaigns","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/fixture-seeds","auth":"dm"},{"method":"POST","path":"/v1/play/campaigns/{id}/members","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/moderation/reports","auth":"member"},{"method":"POST","path":"/v1/play/campaigns/{id}/rng-rolls","auth":"member"},{"method":"PUT","path":"/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/rng-seed","auth":"dm"},{"method":"PUT","path":"/v1/play/campaigns/{id}/safety-boundaries","auth":"dm"}]}'.freeze

  XP_BY_CR = {
    '0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100,
    '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800
  }.freeze
  LEVEL_THREE_THRESHOLDS = { easy: 75, medium: 150, hard: 225, deadly: 400 }.freeze
  CHARACTER_RACES = %w[dwarf elf halfling human].freeze
  CHARACTER_CLASSES = { 'cleric' => 8, 'fighter' => 10, 'rogue' => 8, 'wizard' => 6 }.freeze
  CHARACTER_BACKGROUNDS = %w[acolyte criminal sage soldier].freeze
  SKILLS = %w[
    acrobatics animal_handling arcana athletics deception history insight intimidation
    investigation medicine nature perception performance persuasion religion sleight_of_hand
    stealth survival
  ].freeze
  ABILITIES = %w[str dex con int wis cha].freeze
  INVENTORY_ITEM_IDS = %w[
    amulet-of-health healing-potion leather-armor ring-of-protection torch
  ].freeze
  EQUIPMENT_ITEM_SLOTS = {
    'leather-armor' => 'armor',
    'ring-of-protection' => 'accessory',
    'amulet-of-health' => 'accessory'
  }.freeze
  ATTUNABLE_ITEM_IDS = %w[ring-of-protection amulet-of-health].freeze
  EQUIPMENT_SLOTS = %w[armor accessory].freeze

  class << self
    def maintenance_mode?
      SERVICE_MODE_MUTEX.synchronize { @maintenance_mode == true }
    end

    def maintenance_mode=(value)
      SERVICE_MODE_MUTEX.synchronize { @maintenance_mode = value }
    end
  end

  before { content_type :json }

  configure do
    DATABASE_MUTEX.synchronize { GameStorage.initialize_schema! }
  end

  helpers do
    def json_body
      JSON.parse(request.body.read)
    rescue JSON::ParserError
      halt_json 400, error: 'invalid JSON'
    end

    def halt_json(status_code, body)
      halt status_code, JSON.generate(body)
    end

    def integer!(value)
      value.is_a?(Integer) ? value : halt_json(400, error: 'expected integer')
    end

    def ability_score!(value)
      score = integer!(value)
      halt_json 400, error: 'score must be between 1 and 30' unless (1..30).cover?(score)
      score
    end

    def ability_modifier(score)
      (score - 10).div(2)
    end

    def character_level!(value)
      level = integer!(value)
      halt_json 400, error: 'level must be between 1 and 20' unless (1..20).cover?(level)
      level
    end

    def proficiency_bonus(level)
      2 + ((level - 1) / 4)
    end

    def combatant_response(combatant)
      { name: combatant[:name], score: combatant[:score] }
    end

    def combat_session_response(session)
      active = session[:order][session[:turn_index]]
      {
        id: session[:id],
        round: session[:round],
        turn_index: session[:turn_index],
        active: combatant_response(active),
        order: session[:order].map { |combatant| combatant_response(combatant) }
      }
    end

    def conditions_response(session)
      session[:conditions].each_with_object({}) do |(name, conditions), result|
        result[name] = conditions.map do |condition|
          { condition: condition[:condition], remaining_rounds: condition[:remaining_rounds] }
        end
      end
    end

    def password_digest(password, salt)
      OpenSSL::PKCS5.pbkdf2_hmac(
        password,
        salt,
        PASSWORD_HASH_ITERATIONS,
        PASSWORD_HASH_BYTES,
        'sha256'
      )
    end

    def valid_password?(password, user)
      candidate = password_digest(password, user[:salt])
      candidate.bytesize == user[:password_hash].bytesize &&
        OpenSSL.fixed_length_secure_compare(candidate, user[:password_hash])
    end

    def load_combat_session(id)
      row = GameStorage.query("SELECT payload FROM combat_sessions WHERE id = #{GameStorage.quote(id)} LIMIT 1").first
      return nil unless row

      payload = JSON.parse(row['payload'])
      {
        id: payload['id'], round: payload['round'], turn_index: payload['turn_index'],
        order: payload['order'].map { |combatant| { name: combatant['name'], dex: combatant['dex'], score: combatant['score'] } },
        conditions: payload['conditions'].each_with_object({}) do |(name, conditions), result|
          result[name] = conditions.map { |condition| { condition: condition['condition'], remaining_rounds: condition['remaining_rounds'] } }
        end
      }
    end

    def save_combat_session(session)
      id = GameStorage.quote(session[:id])
      payload = GameStorage.quote(JSON.generate(session))
      GameStorage.execute("INSERT INTO combat_sessions (id, payload) VALUES (#{id}, #{payload}) ON CONFLICT(id) DO UPDATE SET payload = excluded.payload;")
    end

    def non_empty_string!(value, field)
      halt_json 400, error: "#{field} must be a non-empty string" unless value.is_a?(String) && !value.empty?
      value
    end

    def iso8601_timestamp!(value, field)
      timestamp = non_empty_string!(value, field)
      Time.iso8601(timestamp)
    rescue ArgumentError
      halt_json 400, error: "#{field} must be an ISO 8601 timestamp"
    end

    def string_array!(value, field)
      halt_json 400, error: "#{field} must be an array of non-empty strings" unless value.is_a?(Array) && value.all? { |item| item.is_a?(String) && !item.empty? }
      value
    end

    def monster_response(row, include_tags: false)
      response = {
        slug: row['slug'],
        name: row['name'],
        cr: row['cr'],
        armor_class: row['armor_class'],
        hit_points: row['hit_points']
      }
      response[:tags] = JSON.parse(row['tags']) if include_tags
      response
    end

    def item_response(row)
      {
        slug: row['slug'],
        name: row['name'],
        type: row['type'],
        rarity: row['rarity'],
        cost_gp: row['cost_gp']
      }
    end

    def campaign_response(row, characters, log_count)
      {
        id: row['id'],
        name: row['name'],
        dm: row['dm'],
        characters: characters.map do |character|
          {
            id: character['id'],
            name: character['name'],
            level: character['level'],
            class: character['class']
          }
        end,
        log_count: log_count
      }
    end

    def quest_response(row)
      milestones = JSON.parse(row['milestones'])
      completed = JSON.parse(row['completed_milestones'])
      {
        id: row['id'],
        status: row['status'],
        milestones_total: milestones.length,
        milestones_done: completed.length
      }
    end

    def play_quest_response(row)
      response = {
        quest_id: row['quest_id'],
        title: row['title'],
        depends_on: JSON.parse(row['depends_on']),
        state: row['state']
      }
      response[:rewards] = { xp: row['reward_xp'], items: JSON.parse(row['reward_items']) } if row['reward_xp']
      response
    end

    def play_world_event_response(row)
      response = {
        event_id: row['event_id'],
        turn_number: row['turn_number'],
        title: row['title'],
        text: row['text'],
        status: row['status']
      }
      if row['status'] == 'resolved'
        response[:resolution] = {
          turn_number: row['resolution_turn_number'],
          text: row['resolution_text']
        }
      end
      response
    end

    def adjusted_encounter(party, monsters)
      halt_json 400, error: 'party and monsters must be arrays' unless party.is_a?(Array) && monsters.is_a?(Array)

      thresholds = LEVEL_THREE_THRESHOLDS.keys.to_h { |key| [key, 0] }
      party.each do |member|
        halt_json 400, error: 'only level 3 is supported' unless member.is_a?(Hash) && member['level'] == 3
        LEVEL_THREE_THRESHOLDS.each { |key, value| thresholds[key] += value }
      end

      base_xp = 0
      monster_count = 0
      monsters.each do |monster|
        halt_json 400, error: 'invalid monster' unless monster.is_a?(Hash)
        xp = XP_BY_CR[monster['cr']]
        count = monster['count']
        halt_json 400, error: 'unsupported challenge rating' unless xp
        halt_json 400, error: 'monster count must be positive' unless count.is_a?(Integer) && count.positive?
        base_xp += xp * count
        monster_count += count
      end

      multiplier = if monster_count == 1 then 1 elsif monster_count == 2 then 1.5 elsif monster_count <= 6 then 2 elsif monster_count <= 10 then 2.5 elsif monster_count <= 14 then 3 else 4 end
      adjusted_xp = base_xp * multiplier
      adjusted_xp = adjusted_xp.to_i if adjusted_xp == adjusted_xp.to_i
      difficulty = if adjusted_xp >= thresholds[:deadly] then 'deadly' elsif adjusted_xp >= thresholds[:hard] then 'hard' elsif adjusted_xp >= thresholds[:medium] then 'medium' elsif adjusted_xp >= thresholds[:easy] then 'easy' else 'trivial' end

      { base_xp: base_xp, monster_count: monster_count, multiplier: multiplier, adjusted_xp: adjusted_xp, difficulty: difficulty, thresholds: thresholds }
    end

    def campaign_exists!(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{GameStorage.quote(campaign_id)} LIMIT 1").any?
    end

    # SQLite rowid records join order, which is part of the deterministic
    # player-turn contract. Keep this ordering whenever reading a play party.
    def play_campaign_row(campaign_sql, fields)
      GameStorage.query("SELECT #{fields} FROM play_campaigns WHERE id = #{campaign_sql} LIMIT 1").first
    end

    def ordered_play_members(campaign_sql, fields = 'username')
      GameStorage.query(
        "SELECT #{fields} FROM play_campaign_members WHERE campaign_id = #{campaign_sql} ORDER BY rowid"
      )
    end

    # A joined character is owned by its joining player unless a later claim
    # or transfer explicitly overrides that default. Keeping ownership outside
    # the membership row preserves the identity used by turns and combat.
    def character_owner(campaign_sql, character_id_sql)
      explicit = GameStorage.query(
        "SELECT owner FROM play_campaign_character_owners WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      return explicit['owner'] if explicit

      GameStorage.query(
        "SELECT username FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first&.fetch('username')
    end

    def play_campaign_participant?(campaign_sql, campaign, username)
      return true if campaign['owner'] == username

      GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(username)} LIMIT 1"
      ).any?
    end

    def replay_state(campaign_sql)
      events = GameStorage.query(
        "SELECT event_id, text FROM play_campaign_replay_events WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      )
      event_ids = events.map { |event| event['event_id'] }
      story = events.map { |event| event['text'] }.join
      { story: story, event_ids: event_ids, digest: "#{event_ids.join(',')}|#{story}" }
    end

    def rng_ledger_state(campaign_sql)
      seed = GameStorage.query(
        "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      rolls = GameStorage.query(
        "SELECT roll_id, sides, result, sequence FROM play_campaign_rng_rolls " \
        "WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map do |roll|
        {
          roll_id: roll['roll_id'], sides: roll['sides'], result: roll['result'],
          sequence: roll['sequence']
        }
      end
      { seed: seed && seed['seed'], rolls: rolls }
    end

    def deterministic_rng_result(seed, sequence, roll_id, sides)
      accumulator = 0
      "#{seed}|#{sequence}|#{roll_id}|#{sides}".encode('UTF-8').bytes.each do |byte|
        accumulator = (accumulator * 31 + byte) & 0xffff_ffff
      end
      (accumulator % sides) + 1
    end

    def moderation_report_response(row)
      response = {
        report_id: row['report_id'], target_id: row['target_id'], reason: row['reason'],
        status: row['status'], reporter: row['reporter'], sequence: row['sequence']
      }
      if row['status'] == 'resolved'
        response[:action] = row['action']
        response[:note] = row['note']
        response[:resolver] = row['resolver']
      end
      response
    end

    def invitation_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      {
        invitation_id: non_empty_string!(payload['invitation_id'], 'invitation_id'),
        username: non_empty_string!(payload['username'], 'username'),
        character_id: non_empty_string!(payload['character_id'], 'character_id')
      }
    end

    def invitation_response(row)
      {
        invitation_id: row['invitation_id'],
        username: row['username'],
        character_id: row['character_id'],
        status: row['status']
      }
    end

    def delegation_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      username = non_empty_string!(payload['username'], 'username')
      powers = payload['powers']
      valid_powers = powers.is_a?(Array) && powers.any? && powers.all? { |power| power == 'narrate' } &&
        powers.uniq.length == powers.length
      halt_json 400, error: 'powers must be a non-empty array of unique valid values' unless valid_powers

      { username: username, powers: powers }
    end

    def audit_event_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      {
        kind: non_empty_string!(payload['kind'], 'kind'),
        correlation_id: non_empty_string!(payload['correlation_id'], 'correlation_id')
      }
    end

    def audit_event_response(row)
      {
        kind: row['kind'],
        actor: row['actor'],
        role: row['role'],
        timestamp: row['sequence'],
        correlation_id: row['correlation_id']
      }
    end

    def projection_event_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      event_id = non_empty_string!(payload['event_id'], 'event_id')
      kind = payload['kind']
      halt_json 400, error: 'kind must be set-story or increment-danger' unless %w[set-story increment-danger].include?(kind)

      if kind == 'set-story'
        { event_id: event_id, kind: kind, value: non_empty_string!(payload['value'], 'value') }
      else
        halt_json 400, error: 'value must be omitted for increment-danger' if payload.key?('value')
        { event_id: event_id, kind: kind }
      end
    end

    def idempotent_event_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      {
        event_id: non_empty_string!(payload['event_id'], 'event_id'),
        value: non_empty_string!(payload['value'], 'value')
      }
    end

    def idempotent_event_response(row)
      {
        event_id: row['event_id'],
        value: row['value'],
        sequence: row['sequence'],
        idempotency_key: row['idempotency_key']
      }
    end

    def projection_from_events(campaign_sql)
      events = GameStorage.query(
        "SELECT event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      )
      events.each_with_object({ story: '', danger: 0, applied_event_ids: [] }) do |event, projection|
        projection[:story] = event['value'] if event['kind'] == 'set-story'
        projection[:danger] += 1 if event['kind'] == 'increment-danger'
        projection[:applied_event_ids] << event['event_id']
      end
    end

    def delegation_response(row)
      { username: row['username'], powers: JSON.parse(row['powers']), active: row['active'] == 1 }
    end

    def active_narration_delegate?(campaign_sql, username)
      row = GameStorage.query(
        "SELECT powers FROM play_campaign_delegations WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(username)} AND active = 1 LIMIT 1"
      ).first
      row && JSON.parse(row['powers']).include?('narrate')
    end

    def session_zero_settings_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      rules = non_empty_string!(payload['rules'], 'rules')
      tone = non_empty_string!(payload['tone'], 'tone')
      consent = payload['consent']
      halt_json 400, error: 'consent must be a non-empty array of unique non-empty strings' unless
        consent.is_a?(Array) && consent.any? && consent.all? { |item| item.is_a?(String) && !item.empty? } &&
        consent.uniq.length == consent.length

      { rules: rules, tone: tone, consent: consent }
    end

    def content_tags!(tags, require_nonempty:)
      valid = tags.is_a?(Array) && (!require_nonempty || tags.any?) &&
        tags.all? { |tag| tag.is_a?(String) && !tag.empty? } &&
        tags.uniq.length == tags.length
      halt_json 400, error: 'tags must be an array of unique non-empty strings' unless valid

      tags
    end

    def safety_tags!(tags, field)
      valid = tags.is_a?(Array) && tags.any? &&
        tags.all? { |tag| tag.is_a?(String) && !tag.strip.empty? } &&
        tags.uniq.length == tags.length
      halt_json 400, error: "#{field} must be a non-empty array of unique non-empty strings" unless valid

      tags
    end

    def safety_boundary_state(campaign_sql)
      row = GameStorage.query(
        "SELECT blocked_tags FROM play_campaign_safety_boundaries WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      { blocked_tags: row ? JSON.parse(row['blocked_tags']) : [] }
    end

    def safety_event_response(row)
      {
        event_id: row['event_id'], kind: row['kind'], text: row['text'],
        tags: JSON.parse(row['tags']), sequence: row['sequence']
      }
    end

    def canonical_fixture_state
      {
        fixture_id: 'canonical-v1',
        status: 'seeded',
        characters: [
          { character_id: 'fixture-hero', name: 'Ari', class: 'fighter' },
          { character_id: 'fixture-mage', name: 'Bea', class: 'wizard' }
        ],
        story: 'The lantern is lit.',
        event_ids: ['fixture-event-1', 'fixture-event-2']
      }
    end

    def content_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      {
        content_id: non_empty_string!(payload['content_id'], 'content_id'),
        kind: non_empty_string!(payload['kind'], 'kind'),
        text: non_empty_string!(payload['text'], 'text'),
        tags: content_tags!(payload['tags'], require_nonempty: true)
      }
    end

    def search_record_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      {
        record_id: non_empty_string!(payload['record_id'], 'record_id'),
        text: non_empty_string!(payload['text'], 'text')
      }
    end

    def search_records_query!
      q = params['q']
      halt_json 400, error: 'q must be a string' unless q.nil? || q.is_a?(String)

      limit_value = params['limit']
      limit = if limit_value.nil?
                2
              elsif limit_value.is_a?(String) && /\A\d+\z/.match?(limit_value)
                limit_value.to_i
              else
                halt_json 400, error: 'limit must be an integer between 1 and 3'
              end
      halt_json 400, error: 'limit must be an integer between 1 and 3' unless (1..3).cover?(limit)

      cursor_value = params['cursor']
      cursor = if cursor_value.nil?
                 0
               elsif cursor_value.is_a?(String) && /\A\d+\z/.match?(cursor_value)
                 cursor_value.to_i
               else
                 halt_json 400, error: 'cursor must be a nonnegative integer'
               end

      { q: q, limit: limit, cursor: cursor }
    end

    def content_response(row)
      {
        content_id: row['content_id'],
        kind: row['kind'],
        text: row['text'],
        tags: JSON.parse(row['tags'])
      }
    end

    def note_attributes!(payload, include_id:)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      attributes = {
        text: non_empty_string!(payload['text'], 'text'),
        visibility: payload['visibility']
      }
      attributes[:note_id] = non_empty_string!(payload['note_id'], 'note_id') if include_id
      halt_json 400, error: 'visibility must be private or party' unless %w[private party].include?(attributes[:visibility])
      attributes
    end

    def note_response(row)
      {
        note_id: row['note_id'], text: row['text'], visibility: row['visibility'], owner: row['owner']
      }
    end

    def whisper_attributes!(payload)
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      {
        whisper_id: non_empty_string!(payload['whisper_id'], 'whisper_id'),
        to_character_id: non_empty_string!(payload['to_character_id'], 'to_character_id'),
        text: non_empty_string!(payload['text'], 'text')
      }
    end

    def whisper_response(row)
      {
        whisper_id: row['whisper_id'],
        from_character_id: row['from_character_id'],
        to_character_id: row['to_character_id'],
        text: row['text']
      }
    end

    def actor_owned_character_id(campaign_sql, username)
      explicit = GameStorage.query(
        "SELECT character_id FROM play_campaign_character_owners WHERE campaign_id = #{campaign_sql} " \
        "AND owner = #{GameStorage.quote(username)} ORDER BY rowid LIMIT 1"
      ).first
      return explicit['character_id'] if explicit

      GameStorage.query(
        "SELECT members.character_id FROM play_campaign_members AS members WHERE members.campaign_id = #{campaign_sql} " \
        "AND members.username = #{GameStorage.quote(username)} AND NOT EXISTS (" \
        "SELECT 1 FROM play_campaign_character_owners AS owners WHERE owners.campaign_id = members.campaign_id " \
        "AND owners.character_id = members.character_id) LIMIT 1"
      ).first&.fetch('character_id')
    end

    def calendar_response(day, season)
      offsets = { 'spring' => 0, 'summer' => 1, 'autumn' => 2, 'winter' => 3 }
      weather = %w[clear rain wind snow][(day + offsets.fetch(season)) % 4]
      { day: day, season: season, weather: weather }
    end

    def settlement_attributes!(payload, include_id:)
      settlement_id = non_empty_string!(payload['settlement_id'], 'settlement_id') if include_id
      name = non_empty_string!(payload['name'], 'name')
      raw_services = payload['services']
      halt_json 400, error: 'services must be a non-empty array of non-empty strings' unless raw_services.is_a?(Array) && raw_services.any? && raw_services.all? { |service| service.is_a?(String) }
      services = raw_services.map(&:strip)
      halt_json 400, error: 'services must be a non-empty array of non-empty strings' if services.any?(&:empty?) || services.uniq.length != services.length
      availability = payload['availability']
      halt_json 400, error: 'availability must be open, limited, or closed' unless %w[open limited closed].include?(availability)

      { settlement_id: settlement_id, name: name, services: services, availability: availability }
    end

    def settlement_response(row, campaign_sql, character_id: nil)
      discoveries = GameStorage.query(
        "SELECT character_id FROM play_campaign_settlement_discoveries WHERE campaign_id = #{campaign_sql} " \
        "AND settlement_id = #{GameStorage.quote(row['settlement_id'])} ORDER BY rowid"
      ).map { |discovery| discovery['character_id'] }
      discoveries &= [character_id] if character_id
      {
        settlement_id: row['settlement_id'],
        name: row['name'],
        services: JSON.parse(row['services']),
        availability: row['availability'],
        discovered_by: discoveries
      }
    end

    def shop_attributes!(payload)
      shop_id = non_empty_string!(payload['shop_id'], 'shop_id')
      name = non_empty_string!(payload['name'], 'name')
      stock = payload['stock']
      halt_json 400, error: 'stock must be a non-empty object of valid item quantities' unless stock.is_a?(Hash) && stock.any?
      halt_json 400, error: 'stock must be a non-empty object of valid item quantities' unless stock.all? do |item_id, quantity|
        item_id.is_a?(String) && INVENTORY_ITEM_IDS.include?(item_id) && quantity.is_a?(Integer) && quantity.positive?
      end
      buy_price = integer!(payload['buy_price'])
      sell_price = integer!(payload['sell_price'])
      halt_json 400, error: 'buy_price must be positive' unless buy_price.positive?
      halt_json 400, error: 'sell_price must be nonnegative' if sell_price.negative?

      { shop_id: shop_id, name: name, stock: stock, buy_price: buy_price, sell_price: sell_price }
    end

    def shop_response(row)
      {
        shop_id: row['shop_id'],
        name: row['name'],
        stock: JSON.parse(row['stock']),
        buy_price: row['buy_price'],
        sell_price: row['sell_price']
      }
    end

    def settlement_row(campaign_sql, settlement_sql)
      GameStorage.query(
        "SELECT settlement_id FROM play_campaign_settlements WHERE campaign_id = #{campaign_sql} " \
        "AND settlement_id = #{settlement_sql} LIMIT 1"
      ).first
    end

    def shop_row(campaign_sql, settlement_sql, shop_sql)
      GameStorage.query(
        "SELECT shop_id, name, stock, buy_price, sell_price FROM play_campaign_shops " \
        "WHERE campaign_id = #{campaign_sql} AND settlement_id = #{settlement_sql} " \
        "AND shop_id = #{shop_sql} LIMIT 1"
      ).first
    end

    def trade_attributes!(payload)
      character_id = non_empty_string!(payload['character_id'], 'character_id')
      item_id = non_empty_string!(payload['item_id'], 'item_id')
      quantity = integer!(payload['quantity'])
      halt_json 400, error: 'invalid item_id' unless INVENTORY_ITEM_IDS.include?(item_id)
      halt_json 400, error: 'quantity must be positive' unless quantity.positive?
      { character_id: character_id, item_id: item_id, quantity: quantity }
    end

    def recipe_attributes!(payload)
      recipe_id = non_empty_string!(payload['recipe_id'], 'recipe_id')
      name = non_empty_string!(payload['name'], 'name')
      ingredients = payload['ingredients']
      halt_json 400, error: 'ingredients must be a non-empty object of valid item quantities' unless ingredients.is_a?(Hash) && ingredients.any?
      halt_json 400, error: 'ingredients must be a non-empty object of valid item quantities' unless ingredients.all? do |item_id, quantity|
        item_id.is_a?(String) && INVENTORY_ITEM_IDS.include?(item_id) && quantity.is_a?(Integer) && quantity.positive?
      end
      output_item = non_empty_string!(payload['output_item'], 'output_item')
      halt_json 400, error: 'invalid output_item' unless INVENTORY_ITEM_IDS.include?(output_item)
      output_quantity = integer!(payload['output_quantity'])
      halt_json 400, error: 'output_quantity must be positive' unless output_quantity.positive?
      {
        recipe_id: recipe_id, name: name, ingredients: ingredients,
        output_item: output_item, output_quantity: output_quantity
      }
    end

    def recipe_response(row)
      {
        recipe_id: row['recipe_id'], name: row['name'], ingredients: JSON.parse(row['ingredients']),
        output_item: row['output_item'], output_quantity: row['output_quantity']
      }
    end

    def downtime_activity_attributes!(payload)
      activity_id = non_empty_string!(payload['activity_id'], 'activity_id')
      name = non_empty_string!(payload['name'], 'name')
      cycles_required = integer!(payload['cycles_required'])
      halt_json 400, error: 'cycles_required must be between 1 and 10' unless (1..10).cover?(cycles_required)
      { activity_id: activity_id, name: name, cycles_required: cycles_required }
    end

    def downtime_activity_response(row)
      {
        activity_id: row['activity_id'],
        name: row['name'],
        cycles_required: row['cycles_required']
      }
    end

    def downtime_allocation_response(row)
      {
        character_id: row['character_id'],
        activity_id: row['activity_id'],
        cycles_completed: row['cycles_completed'],
        completions: row['completions']
      }
    end

    def play_campaign_entity?(campaign_sql, entity_id)
      entity_id_sql = GameStorage.quote(entity_id)
      GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{entity_id_sql} UNION ALL " \
        "SELECT 1 AS found FROM play_campaign_npcs WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{entity_id_sql} LIMIT 1"
      ).any?
    end

    def authenticated_actor!
      authorization = request.env['HTTP_AUTHORIZATION']
      match = authorization.is_a?(String) && /\ABearer session-([a-z0-9_-]{2,32})\z/.match(authorization)
      halt_json 401, error: 'unauthorized' unless match

      user = GameStorage.query(
        "SELECT username, role FROM users WHERE username = #{GameStorage.quote(match[1])} LIMIT 1"
      ).first
      # Play-session tokens name their actor directly.  The cumulative storage
      # reset clears registered users before this surface is exercised, so a
      # syntactically valid session remains an authenticated play actor even
      # when it has no persisted login record.  Registered roles still take
      # precedence; the built-in DM actor is the sole default DM.
      user || { 'username' => match[1], 'role' => (match[1] == 'dm' ? 'dm' : 'player') }
    end

    # Spectator bearer tokens deliberately identify only their ticket.  Keep
    # this separate from play-session authentication so session holders cannot
    # accidentally receive the reduced public projection.
    def authenticated_spectator!
      authorization = request.env['HTTP_AUTHORIZATION']
      halt_json 403, error: 'forbidden' if authorization.is_a?(String) &&
        /\ABearer session-[a-z0-9_-]{2,32}\z/.match?(authorization)

      match = authorization.is_a?(String) && /\ABearer spectator-(.+)\z/.match(authorization)
      halt_json 401, error: 'unauthorized' unless match

      spectator = GameStorage.query(
        "SELECT spectator_id, campaign_id FROM play_campaign_spectators WHERE spectator_id = #{GameStorage.quote(match[1])} LIMIT 1"
      ).first
      halt_json 401, error: 'unauthorized' unless spectator

      spectator
    end

    def next_play_event_sequence(campaign_sql)
      current = GameStorage.query(
        "SELECT sequence FROM play_campaign_event_sequences WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      sequence = current ? current['sequence'] + 1 : 1
      GameStorage.execute(
        "INSERT INTO play_campaign_event_sequences (campaign_id, sequence) VALUES (#{campaign_sql}, #{sequence}) " \
        'ON CONFLICT(campaign_id) DO UPDATE SET sequence = excluded.sequence;'
      )
      sequence
    end

    # Turns are reconstructed from the event log: a player exploration event
    # gives the owner the turn, while each resolution advances the party in
    # join order.  Ending a combat that interrupted an owner turn consumes one
    # party handoff without creating an exploration resolution (and therefore
    # without changing the campaign turn number).  Recorded combat handoffs
    # supply that deterministic rotation offset.
    def play_turn_state(campaign_sql, members, owner)
      resolutions = GameStorage.query(
        "SELECT COUNT(*) AS count, COALESCE(MAX(sequence), 0) AS latest FROM play_campaign_resolutions " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first
      latest_action = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) AS latest FROM (" \
        "SELECT sequence FROM play_campaign_actions WHERE campaign_id = #{campaign_sql} " \
        "UNION ALL SELECT sequence FROM play_campaign_travels WHERE campaign_id = #{campaign_sql} " \
        "UNION ALL SELECT sequence FROM play_campaign_rests WHERE campaign_id = #{campaign_sql}" \
        ')'
      ).first['latest']
      resolution_count = resolutions['count']
      completed_combat_handoffs = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_combat_handoffs WHERE campaign_id = #{campaign_sql}"
      ).first['count']

      # An ended encounter is an explicit return to exploration.  Its
      # checkpoint lasts only until a later turn event; an older ended
      # encounter must not pin all subsequent resolutions to the DM.
      combat_checkpoint = GameStorage.query(
        "SELECT COALESCE(MAX(end_sequence), -1) AS sequence FROM play_campaign_combat_handoffs " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      latest_turn_event = [latest_action, resolutions['latest']].max
      if combat_checkpoint >= latest_turn_event
        return { current_actor: owner, phase: 'exploration', turn_number: resolution_count + 1 }
      end

      if latest_action > resolutions['latest']
        { current_actor: owner, phase: 'gm', turn_number: resolution_count + 1 }
      else
        index = (resolution_count + completed_combat_handoffs) % members.length
        { current_actor: members[index]['username'], phase: 'player', turn_number: resolution_count + 1 }
      end
    end

    def play_campaign_turn_number(campaign_sql)
      GameStorage.query(
        "SELECT COUNT(*) + 1 AS turn_number FROM play_campaign_resolutions WHERE campaign_id = #{campaign_sql}"
      ).first['turn_number']
    end

    def encounter_turn_order(encounter_sql)
      monsters = GameStorage.query(
        "SELECT monster_id, name, initiative FROM play_campaign_encounter_monsters " \
        "WHERE encounter_id = #{encounter_sql}"
      ).map do |row|
        { name: row['name'], kind: 'monster', initiative: row['initiative'], identity: row['monster_id'] }
      end
      players = GameStorage.query(
        "SELECT member, name, initiative FROM play_campaign_encounter_combatants " \
        "WHERE encounter_id = #{encounter_sql}"
      ).map do |row|
        { name: row['name'], kind: 'player', initiative: row['initiative'], identity: row['member'] }
      end
      combatants = (monsters + players).sort_by do |combatant|
        [-combatant[:initiative], combatant[:name], combatant[:kind], combatant[:identity]]
      end
      stored = GameStorage.query(
        "SELECT turn_order FROM play_campaign_encounter_turn_orders WHERE encounter_id = #{encounter_sql} LIMIT 1"
      ).first
      return combatants unless stored

      keys = JSON.parse(stored['turn_order'])
      return combatants unless keys.is_a?(Array) && keys.all? { |key| key.is_a?(String) }

      by_key = combatants.to_h { |combatant| [encounter_combatant_key(combatant), combatant] }
      ordered = keys.filter_map { |key| by_key[key] }.uniq
      ordered + combatants.reject { |combatant| ordered.include?(combatant) }
    rescue JSON::ParserError
      combatants
    end

    def encounter_combatant_key(combatant)
      "#{combatant[:kind]}:#{combatant[:identity]}"
    end

    def encounter_combatant_response(combatant)
      { name: combatant[:name], kind: combatant[:kind], initiative: combatant[:initiative] }
    end

    # A persisted index may have been written against an older turn order.
    # Normalize it only when reading; the next state-changing route persists
    # the normalized position, preserving the established recovery behavior.
    def encounter_turn_state!(encounter_sql)
      order = encounter_turn_order(encounter_sql)
      halt_json 409, error: 'encounter has no combatants' if order.empty?

      state = GameStorage.query(
        "SELECT round, turn_index FROM play_campaign_encounter_turns WHERE encounter_id = #{encounter_sql} LIMIT 1"
      ).first
      {
        order: order,
        round: state ? state['round'] : 1,
        turn_index: state ? state['turn_index'] % order.length : 0
      }
    end

    def encounter_turn_response(round, turn_index, order)
      active = order[turn_index]
      {
        round: round,
        turn_index: turn_index,
        active: encounter_combatant_response(active)
      }
    end

    def encounter_conditions_response(encounter_sql)
      GameStorage.query(
        "SELECT target, condition, remaining_rounds FROM play_campaign_encounter_conditions " \
        "WHERE encounter_id = #{encounter_sql} ORDER BY sequence"
      ).each_with_object({}) do |row, result|
        (result[row['target']] ||= []) << {
          condition: row['condition'], remaining_rounds: row['remaining_rounds']
        }
      end
    end

    def encounter_status_response(encounter_sql, round, turn_index, order)
      encounter_turn_response(round, turn_index, order).merge(
        order: order.map { |combatant| encounter_combatant_response(combatant) },
        conditions: encounter_conditions_response(encounter_sql)
      )
    end

    # Monster ids are encounter-local, while player health belongs to their
    # campaign member record.  Both are valid encounter combatants.
    def encounter_health_target!(campaign_sql, encounter_sql, target)
      target_sql = GameStorage.quote(target)
      monster = GameStorage.query(
        "SELECT hp_current, hp_max FROM play_campaign_encounter_monsters WHERE encounter_id = #{encounter_sql} " \
        "AND monster_id = #{target_sql} LIMIT 1"
      ).first
      return { row: monster, table: 'play_campaign_encounter_monsters', key: 'monster_id', key_sql: target_sql } if monster

      combatant = GameStorage.query(
        "SELECT member FROM play_campaign_encounter_combatants WHERE encounter_id = #{encounter_sql} " \
        "AND member = #{target_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'combatant not found' unless combatant

      health = GameStorage.query(
        "SELECT hp_current, hp_max FROM play_campaign_member_health WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{target_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'combatant not found' unless health
      { row: health, table: 'play_campaign_member_health', key: 'username', key_sql: target_sql }
    end

    def update_encounter_health!(campaign_sql, encounter_sql, target, amount, healing)
      health_target = encounter_health_target!(campaign_sql, encounter_sql, target)
      before = health_target[:row]['hp_current']
      maximum = health_target[:row]['hp_max']
      after = healing ? [before + amount, maximum].min : [before - amount, 0].max
      where = if health_target[:table] == 'play_campaign_encounter_monsters'
                "encounter_id = #{encounter_sql} AND #{health_target[:key]} = #{health_target[:key_sql]}"
              else
                "campaign_id = #{campaign_sql} AND #{health_target[:key]} = #{health_target[:key_sql]}"
              end
      GameStorage.execute("UPDATE #{health_target[:table]} SET hp_current = #{after} WHERE #{where};")
      if health_target[:table] == 'play_campaign_member_health' && after.zero?
        GameStorage.execute(
          "UPDATE play_campaign_member_death_saves SET successes = 0, failures = 0, status = 'unconscious' " \
          "WHERE campaign_id = #{campaign_sql} AND username = #{health_target[:key_sql]} AND status = 'conscious';"
        )
      end
      { hp_before: before, hp_after: after }
    end
  end

  get '/health' do
    JSON.generate(ok: true)
  end

  get '/healthz' do
    JSON.generate(status: 'ok')
  end

  get '/readyz' do
    if DndApi.maintenance_mode?
      status 503
      JSON.generate(status: 'maintenance', schema_version: 2)
    else
      JSON.generate(status: 'ready', schema_version: 2)
    end
  end

  get '/v1/schema' do
    API_SCHEMA_JSON
  end

  get '/v1/storage/status' do
    initialized = DATABASE_MUTEX.synchronize do
      GameStorage.query('SELECT version FROM schema_metadata LIMIT 1').dig(0, 'version') == SCHEMA_VERSION
    end
    JSON.generate(driver: 'sqlite', schema_version: SCHEMA_VERSION, initialized: initialized)
  end

  post '/v1/storage/reset' do
    DATABASE_MUTEX.synchronize do
      GameStorage.reset!
    end
    JSON.generate(ok: true, schema_version: SCHEMA_VERSION)
  end

  post '/v1/auth/register' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    username = payload['username']
    password = payload['password']
    role = payload['role']
    halt_json 400, error: 'invalid username' unless username.is_a?(String) && /\A[a-z0-9_-]{2,32}\z/.match?(username)
    halt_json 400, error: 'password must be at least 8 characters' unless password.is_a?(String) && password.length >= 8
    halt_json 400, error: 'invalid role' unless %w[dm player].include?(role)

    DATABASE_MUTEX.synchronize do
      username_sql = GameStorage.quote(username)
      halt_json 409, error: 'username already exists' if GameStorage.query("SELECT 1 AS found FROM users WHERE username = #{username_sql} LIMIT 1").any?

      salt = SecureRandom.random_bytes(PASSWORD_SALT_BYTES)
      digest = password_digest(password, salt)
      GameStorage.execute("INSERT INTO users (username, role, salt, password_hash) VALUES (#{username_sql}, #{GameStorage.quote(role)}, #{GameStorage.quote(salt.unpack1('H*'))}, #{GameStorage.quote(digest.unpack1('H*'))});")
    end

    status 201
    JSON.generate(username: username, role: role)
  end

  post '/v1/auth/login' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    username = payload['username']
    password = payload['password']
    halt_json 400, error: 'username and password must be strings' unless username.is_a?(String) && password.is_a?(String)

    authenticated = DATABASE_MUTEX.synchronize do
      row = GameStorage.query("SELECT salt, password_hash FROM users WHERE username = #{GameStorage.quote(username)} LIMIT 1").first
      user = row && { salt: [row['salt']].pack('H*'), password_hash: [row['password_hash']].pack('H*') }
      user && valid_password?(password, user)
    end
    halt_json 401, error: 'invalid credentials' unless authenticated

    JSON.generate(username: username, token: "session-#{username}")
  end

  post '/v1/play/campaigns' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      id = non_empty_string!(payload['id'], 'id')
      name = non_empty_string!(payload['name'], 'name')
      max_players = integer!(payload['max_players'])
      halt_json 400, error: 'max_players must be positive' unless max_players.positive?

      id_sql = GameStorage.quote(id)
      halt_json 409, error: 'campaign id already exists' if GameStorage.query("SELECT 1 AS found FROM play_campaigns WHERE id = #{id_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO play_campaigns (id, name, owner, status, max_players) " \
        "VALUES (#{id_sql}, #{GameStorage.quote(name)}, #{GameStorage.quote(actor['username'])}, 'lobby', #{max_players});"
      )
      { id: id, name: name, owner: actor['username'], status: 'lobby', max_players: max_players }
    end
    status 201
    JSON.generate(response)
  end

  # Chat is party-only state.  It is intentionally kept out of the spectator
  # projection, whose contract is a minimal public campaign summary.
  post '/v1/play/campaigns/:id/messages' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      text = non_empty_string!(payload['text'], 'text')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).first
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player' && member

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_chats " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_chats (campaign_id, sequence, actor, text) VALUES ' \
        "(#{campaign_sql}, #{sequence}, #{GameStorage.quote(actor['username'])}, #{GameStorage.quote(text)});"
      )
      { sequence: sequence, actor: actor['username'], kind: 'chat', text: text }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/feed-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      event_id = non_empty_string!(payload['event_id'], 'event_id')
      text = non_empty_string!(payload['text'], 'text')
      event_id_sql = GameStorage.quote(event_id)
      halt_json 409, error: 'event_id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_feed_events WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_id_sql} LIMIT 1"
      ).any?

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_feed_events " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_feed_events (campaign_id, event_id, text, sequence) VALUES ' \
        "(#{campaign_sql}, #{event_id_sql}, #{GameStorage.quote(text)}, #{sequence});"
      )
      { event_id: event_id, text: text, sequence: sequence }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/event-feed' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      cursor_value = params.key?('cursor') ? params['cursor'] : '0'
      limit_value = params.key?('limit') ? params['limit'] : '2'
      halt_json 400, error: 'invalid cursor' unless cursor_value.is_a?(String) && /\A\d+\z/.match?(cursor_value)
      halt_json 400, error: 'invalid limit' unless limit_value.is_a?(String) && /\A\d+\z/.match?(limit_value)
      cursor = cursor_value.to_i
      limit = limit_value.to_i
      halt_json 400, error: 'invalid limit' unless (1..3).cover?(limit)

      events = GameStorage.query(
        "SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = #{campaign_sql} " \
        "ORDER BY sequence LIMIT #{limit} OFFSET #{cursor}"
      ).map { |event| { event_id: event['event_id'], text: event['text'], sequence: event['sequence'] } }
      { events: events, next_cursor: cursor + events.length }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/spectators' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      spectator_id = non_empty_string!(payload['spectator_id'], 'spectator_id')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      spectator_id_sql = GameStorage.quote(spectator_id)
      halt_json 409, error: 'spectator id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_spectators WHERE spectator_id = #{spectator_id_sql} LIMIT 1"
      ).any?

      GameStorage.execute(
        'INSERT INTO play_campaign_spectators (spectator_id, campaign_id) VALUES ' \
        "(#{spectator_id_sql}, #{campaign_sql});"
      )
      { spectator_id: spectator_id, token: "spectator-#{spectator_id}" }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/spectator-view' do
    response = DATABASE_MUTEX.synchronize do
      spectator = authenticated_spectator!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'id, name, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless spectator['campaign_id'] == campaign['id']

      party_size = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = #{campaign_sql}"
      ).first['count']
      document = GameStorage.query(
        "SELECT story FROM play_campaign_documents WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      {
        campaign_id: campaign['id'],
        name: campaign['name'],
        status: campaign['status'],
        party_size: party_size,
        story: document ? document['story'] : ''
      }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/onboarding' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      if campaign['owner'] == actor['username']
        {
          role: 'dm',
          next_steps: ['configure-safety', 'invite-players', 'start-campaign'],
          can_mutate: true
        }
      else
        {
          role: 'player',
          next_steps: ['review-party', 'take-turn', 'submit-action'],
          can_mutate: true
        }
      end
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/service-mode' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      payload = json_body
      halt_json 400, error: 'request body must be exactly {"maintenance":true} or {"maintenance":false}' unless
        payload.is_a?(Hash) && payload.keys == ['maintenance'] && [true, false].include?(payload['maintenance'])

      DndApi.maintenance_mode = payload['maintenance']
      { maintenance: DndApi.maintenance_mode? }
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/session-zero' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      settings = session_zero_settings_attributes!(payload)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']
      halt_json 409, error: 'campaign has already started' unless campaign['status'] == 'lobby'

      GameStorage.execute(
        'INSERT INTO play_campaign_session_zero_settings (campaign_id, rules, tone, consent) ' \
        "VALUES (#{campaign_sql}, #{GameStorage.quote(settings[:rules])}, #{GameStorage.quote(settings[:tone])}, " \
        "#{GameStorage.quote(JSON.generate(settings[:consent]))}) " \
        'ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent = excluded.consent;'
      )
      settings
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/session-zero' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      settings = GameStorage.query(
        "SELECT rules, tone, consent FROM play_campaign_session_zero_settings WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'session-zero settings not found' unless settings

      { rules: settings['rules'], tone: settings['tone'], consent: JSON.parse(settings['consent']) }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/content' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      attributes = content_attributes!(json_body)
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      content_id_sql = GameStorage.quote(attributes[:content_id])
      halt_json 409, error: 'content id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_content WHERE campaign_id = #{campaign_sql} " \
        "AND content_id = #{content_id_sql} LIMIT 1"
      ).any?

      GameStorage.execute(
        'INSERT INTO play_campaign_content (campaign_id, content_id, kind, text, tags) ' \
        "VALUES (#{campaign_sql}, #{content_id_sql}, #{GameStorage.quote(attributes[:kind])}, " \
        "#{GameStorage.quote(attributes[:text])}, #{GameStorage.quote(JSON.generate(attributes[:tags]))});"
      )
      attributes
    end
    status 201
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/content/:content_id/tags' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      tags = content_tags!(payload['tags'], require_nonempty: false)
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      content_id_sql = GameStorage.quote(params['content_id'])
      content = GameStorage.query(
        "SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = #{campaign_sql} " \
        "AND content_id = #{content_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'content not found' unless content

      GameStorage.execute(
        "UPDATE play_campaign_content SET tags = #{GameStorage.quote(JSON.generate(tags))} " \
        "WHERE campaign_id = #{campaign_sql} AND content_id = #{content_id_sql};"
      )
      content['tags'] = JSON.generate(tags)
      content_response(content)
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/content' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      exclude_tag = params['exclude_tag']
      halt_json 400, error: 'exclude_tag must be a non-empty string' unless exclude_tag.nil? ||
        (exclude_tag.is_a?(String) && !exclude_tag.empty?)
      content = GameStorage.query(
        "SELECT content_id, kind, text, tags FROM play_campaign_content WHERE campaign_id = #{campaign_sql} ORDER BY rowid"
      ).map { |row| content_response(row) }
      if exclude_tag && campaign['owner'] != actor['username']
        content.reject! { |record| record[:tags].include?(exclude_tag) }
      end
      { content: content }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/notes' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      attributes = note_attributes!(json_body, include_id: true)

      note_id_sql = GameStorage.quote(attributes[:note_id])
      halt_json 409, error: 'note id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_notes WHERE campaign_id = #{campaign_sql} " \
        "AND note_id = #{note_id_sql} LIMIT 1"
      ).any?
      GameStorage.execute(
        'INSERT INTO play_campaign_notes (campaign_id, note_id, text, visibility, owner) ' \
        "VALUES (#{campaign_sql}, #{note_id_sql}, #{GameStorage.quote(attributes[:text])}, " \
        "#{GameStorage.quote(attributes[:visibility])}, #{GameStorage.quote(actor['username'])});"
      )
      attributes.merge(owner: actor['username'])
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/notes' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      notes = GameStorage.query(
        "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = #{campaign_sql} ORDER BY rowid"
      )
      unless campaign['owner'] == actor['username']
        notes.select! { |note| note['visibility'] == 'party' || note['owner'] == actor['username'] }
      end
      { notes: notes.map { |note| note_response(note) } }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/notes/:note_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      note = GameStorage.query(
        "SELECT note_id, text, visibility, owner FROM play_campaign_notes WHERE campaign_id = #{campaign_sql} " \
        "AND note_id = #{GameStorage.quote(params['note_id'])} LIMIT 1"
      ).first
      halt_json 404, error: 'note not found' unless note
      halt_json 403, error: 'forbidden' if note['visibility'] == 'private' &&
        campaign['owner'] != actor['username'] && note['owner'] != actor['username']
      note_response(note)
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/notes/:note_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      attributes = note_attributes!(json_body, include_id: false)
      note_id_sql = GameStorage.quote(params['note_id'])
      note = GameStorage.query(
        "SELECT note_id, owner FROM play_campaign_notes WHERE campaign_id = #{campaign_sql} AND note_id = #{note_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'note not found' unless note
      halt_json 403, error: 'forbidden' unless note['owner'] == actor['username']
      GameStorage.execute(
        "UPDATE play_campaign_notes SET text = #{GameStorage.quote(attributes[:text])}, " \
        "visibility = #{GameStorage.quote(attributes[:visibility])} WHERE campaign_id = #{campaign_sql} AND note_id = #{note_id_sql};"
      )
      { note_id: params['note_id'], text: attributes[:text], visibility: attributes[:visibility], owner: note['owner'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/whispers' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      attributes = whisper_attributes!(json_body)
      from_character_id = actor_owned_character_id(campaign_sql, actor['username'])
      halt_json 403, error: 'forbidden' unless from_character_id
      recipient = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{GameStorage.quote(attributes[:to_character_id])} LIMIT 1"
      ).first
      halt_json 400, error: 'to_character_id must be a campaign member character' unless recipient
      whisper_id_sql = GameStorage.quote(attributes[:whisper_id])
      halt_json 409, error: 'whisper id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_whispers WHERE campaign_id = #{campaign_sql} " \
        "AND whisper_id = #{whisper_id_sql} LIMIT 1"
      ).any?
      GameStorage.execute(
        'INSERT INTO play_campaign_whispers (campaign_id, whisper_id, from_character_id, to_character_id, text) ' \
        "VALUES (#{campaign_sql}, #{whisper_id_sql}, #{GameStorage.quote(from_character_id)}, " \
        "#{GameStorage.quote(attributes[:to_character_id])}, #{GameStorage.quote(attributes[:text])});"
      )
      attributes.merge(from_character_id: from_character_id)
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/whispers' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      whispers = GameStorage.query(
        "SELECT whisper_id, from_character_id, to_character_id, text FROM play_campaign_whispers " \
        "WHERE campaign_id = #{campaign_sql} ORDER BY rowid"
      )
      unless campaign['owner'] == actor['username']
        character_id = actor_owned_character_id(campaign_sql, actor['username'])
        whispers.select! { |whisper| character_id && [whisper['from_character_id'], whisper['to_character_id']].include?(character_id) }
      end
      { whispers: whispers.map { |whisper| whisper_response(whisper) } }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/sheet' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      character_id_sql = GameStorage.quote(params['character_id'])
      member = GameStorage.query(
        "SELECT character_id, name, class FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'character not found' unless member
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || owner == actor['username']
      {
        character_id: member['character_id'], owner: owner, name: member['name'], class: member['class'],
        level: 1, proficiency_bonus: 2, hp_max: 10, armor_class: 10
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/members' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      character_id = non_empty_string!(payload['character_id'], 'character_id')
      name = non_empty_string!(payload['name'], 'name')
      character_class = non_empty_string!(payload['class'], 'class')
      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'status, max_players')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 409, error: 'campaign is not accepting members' unless campaign['status'] == 'lobby'

      member_count = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = #{campaign_sql}"
      ).first['count']
      halt_json 409, error: 'party is full' if member_count >= campaign['max_players']

      username_sql = GameStorage.quote(actor['username'])
      character_id_sql = GameStorage.quote(character_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND (username = #{username_sql} OR character_id = #{character_id_sql}) LIMIT 1"
      ).any?
      halt_json 409, error: 'membership already exists' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) " \
        "VALUES (#{campaign_sql}, #{username_sql}, #{character_id_sql}, #{GameStorage.quote(name)}, #{GameStorage.quote(character_class)});"
      )
      GameStorage.execute(
        "INSERT INTO play_campaign_member_health (campaign_id, username, hp_current, hp_max) " \
        "VALUES (#{campaign_sql}, #{username_sql}, 20, 20);"
      )
      GameStorage.execute(
        "INSERT INTO play_campaign_member_death_saves (campaign_id, username, successes, failures, status) " \
        "VALUES (#{campaign_sql}, #{username_sql}, 0, 0, 'conscious');"
      )
      GameStorage.execute(
        "INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) " \
        "VALUES (#{campaign_sql}, #{character_id_sql}, 10);"
      )
      { username: actor['username'], character_id: character_id, name: name, class: character_class }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/audit-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      attributes = audit_event_attributes!(json_body)

      correlation_id_sql = GameStorage.quote(attributes[:correlation_id])
      halt_json 409, error: 'correlation_id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_audit_events WHERE campaign_id = #{campaign_sql} " \
        "AND correlation_id = #{correlation_id_sql} LIMIT 1"
      ).any?

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_audit_events " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      role = campaign['owner'] == actor['username'] ? 'DM' : 'player'
      GameStorage.execute(
        'INSERT INTO play_campaign_audit_events (campaign_id, sequence, kind, actor, role, correlation_id) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{GameStorage.quote(attributes[:kind])}, " \
        "#{GameStorage.quote(actor['username'])}, #{GameStorage.quote(role)}, #{correlation_id_sql});"
      )
      {
        kind: attributes[:kind], actor: actor['username'], role: role,
        timestamp: sequence, correlation_id: attributes[:correlation_id]
      }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/audit-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      entries = GameStorage.query(
        "SELECT kind, actor, role, sequence, correlation_id FROM play_campaign_audit_events " \
        "WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map { |entry| audit_event_response(entry) }
      { entries: entries }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/projection-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' if campaign['owner'] == actor['username']
      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).first
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player' && member

      attributes = projection_event_attributes!(json_body)
      event_id_sql = GameStorage.quote(attributes[:event_id])
      halt_json 409, error: 'event_id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_projection_events WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_id_sql} LIMIT 1"
      ).any?

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_projection_events " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      value_sql = attributes.key?(:value) ? GameStorage.quote(attributes[:value]) : 'NULL'
      GameStorage.execute(
        'INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{event_id_sql}, #{GameStorage.quote(attributes[:kind])}, #{value_sql});"
      )
      GameStorage.execute(
        'INSERT INTO play_campaign_service_metrics (campaign_id, projection_events) ' \
        "VALUES (#{campaign_sql}, 1) ON CONFLICT(campaign_id) DO UPDATE SET projection_events = projection_events + 1;"
      )
      projection_from_events(campaign_sql)
      { sequence: sequence, **attributes }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/projection' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      projection_from_events(campaign_sql)
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/projection/rebuild' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      projection_from_events(campaign_sql)
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/metrics' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      metrics = GameStorage.query(
        "SELECT accepted_rate_events, rejected_rate_events, projection_events " \
        "FROM play_campaign_service_metrics WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      {
        accepted_rate_events: metrics ? metrics['accepted_rate_events'] : 0,
        rejected_rate_events: metrics ? metrics['rejected_rate_events'] : 0,
        projection_events: metrics ? metrics['projection_events'] : 0,
        uptime_ticks: 1
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/idempotent-events' do
    created = false
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      idempotency_key = request.env['HTTP_IDEMPOTENCY_KEY']
      halt_json 400, error: 'Idempotency-Key must be a non-empty string' unless idempotency_key.is_a?(String) && !idempotency_key.strip.empty?
      idempotency_key = idempotency_key.strip
      attributes = idempotent_event_attributes!(json_body)
      key_sql = GameStorage.quote(idempotency_key)

      stored = GameStorage.query(
        'SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events ' \
        "WHERE campaign_id = #{campaign_sql} AND idempotency_key = #{key_sql} LIMIT 1"
      ).first
      if stored
        halt_json 409, error: 'idempotency key conflicts with request' unless
          stored['event_id'] == attributes[:event_id] && stored['value'] == attributes[:value]
        next idempotent_event_response(stored)
      end

      event_id_sql = GameStorage.quote(attributes[:event_id])
      halt_json 409, error: 'event_id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_idempotent_events WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_id_sql} LIMIT 1"
      ).any?

      sequence = GameStorage.query(
        'SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_idempotent_events ' \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{event_id_sql}, #{GameStorage.quote(attributes[:value])}, #{key_sql});"
      )
      created = true
      {
        event_id: attributes[:event_id], value: attributes[:value], sequence: sequence,
        idempotency_key: idempotency_key
      }
    end
    status 201 if created
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/idempotent-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      events = GameStorage.query(
        'SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events ' \
        "WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map { |event| idempotent_event_response(event) }
      { events: events }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/safe-turns' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      submission_id = non_empty_string!(payload['submission_id'], 'submission_id')
      expected_turn = integer!(payload['expected_turn'])
      halt_json 400, error: 'expected_turn must be a positive integer' unless expected_turn.positive?
      action = non_empty_string!(payload['action'], 'action')

      submission_sql = GameStorage.quote(submission_id)
      halt_json 409, error: 'submission_id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_safe_turns WHERE campaign_id = #{campaign_sql} " \
        "AND submission_id = #{submission_sql} LIMIT 1"
      ).any?

      current_turn = GameStorage.query(
        "SELECT COALESCE(MAX(accepted_turn), 0) + 1 AS current_turn FROM play_campaign_safe_turns " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['current_turn']
      halt_json 409, current_turn: current_turn unless expected_turn == current_turn

      GameStorage.execute(
        'INSERT INTO play_campaign_safe_turns (campaign_id, submission_id, action, accepted_turn) ' \
        "VALUES (#{campaign_sql}, #{submission_sql}, #{GameStorage.quote(action)}, #{current_turn});"
      )
      { submission_id: submission_id, action: action, accepted_turn: current_turn, next_turn: current_turn + 1 }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/safe-turns' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      accepted = GameStorage.query(
        "SELECT submission_id, action, accepted_turn FROM play_campaign_safe_turns WHERE campaign_id = #{campaign_sql} " \
        'ORDER BY accepted_turn'
      ).map do |turn|
        {
          submission_id: turn['submission_id'], action: turn['action'], accepted_turn: turn['accepted_turn'],
          next_turn: turn['accepted_turn'] + 1
        }
      end
      { current_turn: accepted.length + 1, accepted: accepted }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/delegations' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      attributes = delegation_attributes!(json_body)
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(attributes[:username])} LIMIT 1"
      ).first
      halt_json 400, error: 'username must be a campaign member' unless member

      existing = GameStorage.query(
        "SELECT active FROM play_campaign_delegations WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(attributes[:username])} LIMIT 1"
      ).first
      halt_json 409, error: 'active delegation already exists' if existing && existing['active'] == 1

      powers_json = JSON.generate(attributes[:powers])
      if existing
        GameStorage.execute(
          "UPDATE play_campaign_delegations SET powers = #{GameStorage.quote(powers_json)}, active = 1 " \
          "WHERE campaign_id = #{campaign_sql} AND username = #{GameStorage.quote(attributes[:username])};"
        )
      else
        GameStorage.execute(
          'INSERT INTO play_campaign_delegations (campaign_id, username, powers, active) ' \
          "VALUES (#{campaign_sql}, #{GameStorage.quote(attributes[:username])}, #{GameStorage.quote(powers_json)}, 1);"
        )
      end
      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_delegation_audit " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{GameStorage.quote(attributes[:username])}, 'granted', #{GameStorage.quote(powers_json)});"
      )
      { username: attributes[:username], powers: attributes[:powers], active: true }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/delegations/audit' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      entries = GameStorage.query(
        "SELECT username, action, powers FROM play_campaign_delegation_audit WHERE campaign_id = #{campaign_sql} " \
        'ORDER BY sequence'
      ).map { |entry| { username: entry['username'], action: entry['action'], powers: JSON.parse(entry['powers']) } }
      { entries: entries }
    end
    JSON.generate(response)
  end

  delete '/v1/play/campaigns/:id/delegations/:username' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      username_sql = GameStorage.quote(params['username'])
      delegation = GameStorage.query(
        "SELECT username, powers, active FROM play_campaign_delegations WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{username_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'delegation not found' unless delegation
      GameStorage.execute(
        "UPDATE play_campaign_delegations SET active = 0 WHERE campaign_id = #{campaign_sql} AND username = #{username_sql};"
      )
      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_delegation_audit " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_delegation_audit (campaign_id, sequence, username, action, powers) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{username_sql}, 'revoked', #{GameStorage.quote(delegation['powers'])});"
      )
      { username: delegation['username'], powers: JSON.parse(delegation['powers']), active: false }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/invitations' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      attributes = invitation_attributes!(json_body)
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      target = GameStorage.query(
        "SELECT 1 AS found FROM users WHERE username = #{GameStorage.quote(attributes[:username])} " \
        "AND role = 'player' LIMIT 1"
      ).first
      halt_json 400, error: 'username must be a registered player' unless target

      invitation_id_sql = GameStorage.quote(attributes[:invitation_id])
      halt_json 409, error: 'invitation id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_invitations WHERE campaign_id = #{campaign_sql} " \
        "AND invitation_id = #{invitation_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'pending invitation already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_invitations WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(attributes[:username])} AND status = 'pending' LIMIT 1"
      ).any?

      GameStorage.execute(
        'INSERT INTO play_campaign_invitations (campaign_id, invitation_id, username, character_id, status) ' \
        "VALUES (#{campaign_sql}, #{invitation_id_sql}, #{GameStorage.quote(attributes[:username])}, " \
        "#{GameStorage.quote(attributes[:character_id])}, 'pending');"
      )
      attributes.merge(status: 'pending')
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/invitations/:invitation_id/accept' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'status, max_players')
      halt_json 404, error: 'campaign not found' unless campaign

      invitation_id_sql = GameStorage.quote(params['invitation_id'])
      invitation = GameStorage.query(
        "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations " \
        "WHERE campaign_id = #{campaign_sql} AND invitation_id = #{invitation_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'invitation not found' unless invitation
      halt_json 403, error: 'forbidden' unless invitation['username'] == actor['username']
      halt_json 409, error: 'invitation has already been accepted' unless invitation['status'] == 'pending'
      halt_json 409, error: 'campaign is not accepting members' unless campaign['status'] == 'lobby'

      member_count = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_members WHERE campaign_id = #{campaign_sql}"
      ).first['count']
      halt_json 409, error: 'party is full' if member_count >= campaign['max_players']

      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND (username = #{GameStorage.quote(invitation['username'])} " \
        "OR character_id = #{GameStorage.quote(invitation['character_id'])}) LIMIT 1"
      ).any?
      halt_json 409, error: 'membership already exists' if duplicate

      GameStorage.execute(
        'INSERT INTO play_campaign_members (campaign_id, username, character_id, name, class) ' \
        "VALUES (#{campaign_sql}, #{GameStorage.quote(invitation['username'])}, " \
        "#{GameStorage.quote(invitation['character_id'])}, #{GameStorage.quote(invitation['username'])}, 'fighter');"
      )
      GameStorage.execute(
        'INSERT INTO play_campaign_member_health (campaign_id, username, hp_current, hp_max) ' \
        "VALUES (#{campaign_sql}, #{GameStorage.quote(invitation['username'])}, 20, 20);"
      )
      GameStorage.execute(
        'INSERT INTO play_campaign_member_death_saves (campaign_id, username, successes, failures, status) ' \
        "VALUES (#{campaign_sql}, #{GameStorage.quote(invitation['username'])}, 0, 0, 'conscious');"
      )
      GameStorage.execute(
        'INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) ' \
        "VALUES (#{campaign_sql}, #{GameStorage.quote(invitation['character_id'])}, 10);"
      )
      GameStorage.execute(
        "UPDATE play_campaign_invitations SET status = 'accepted' WHERE campaign_id = #{campaign_sql} " \
        "AND invitation_id = #{invitation_id_sql};"
      )
      invitation['status'] = 'accepted'
      invitation_response(invitation)
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/invitations' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      invitations = GameStorage.query(
        "SELECT invitation_id, username, character_id, status FROM play_campaign_invitations " \
        "WHERE campaign_id = #{campaign_sql} ORDER BY rowid"
      )
      unless campaign['owner'] == actor['username']
        invitations.select! { |invitation| invitation['username'] == actor['username'] }
      end
      { invitations: invitations.map { |invitation| invitation_response(invitation) } }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/damage' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      amount = integer!(payload['amount'])
      halt_json 400, error: 'amount must be positive' unless amount.positive?

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      member = GameStorage.query(
        "SELECT username FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{GameStorage.quote(params['character_id'])} LIMIT 1"
      ).first
      halt_json 404, error: 'character not found' unless member

      username_sql = GameStorage.quote(member['username'])
      health = GameStorage.query(
        "SELECT hp_current, hp_max FROM play_campaign_member_health WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{username_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'character not found' unless health

      hp_after = [health['hp_current'] - amount, 0].max
      GameStorage.execute(
        "UPDATE play_campaign_member_health SET hp_current = #{hp_after} WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{username_sql};"
      )
      if hp_after.zero?
        GameStorage.execute(
          "UPDATE play_campaign_member_death_saves SET successes = 0, failures = 0, status = 'unconscious' " \
          "WHERE campaign_id = #{campaign_sql} AND username = #{username_sql} AND status = 'conscious';"
        )
      end

      { target: params['character_id'], hp_before: health['hp_current'], hp_after: hp_after, damage: amount }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/death-saves' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      outcome = payload['outcome']
      halt_json 400, error: 'outcome must be success or failure' unless %w[success failure].include?(outcome)

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')
      member = GameStorage.query(
        "SELECT username FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{GameStorage.quote(params['character_id'])} LIMIT 1"
      ).first
      halt_json 404, error: 'character not found' unless member
      halt_json 403, error: 'forbidden' unless member['username'] == actor['username']

      username_sql = GameStorage.quote(member['username'])
      death_saves = GameStorage.query(
        "SELECT successes, failures, status FROM play_campaign_member_death_saves WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{username_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'character is not unconscious' unless death_saves && death_saves['status'] == 'unconscious'

      successes = death_saves['successes'] + (outcome == 'success' ? 1 : 0)
      failures = death_saves['failures'] + (outcome == 'failure' ? 1 : 0)
      character_status = successes >= 3 ? 'stable' : (failures >= 3 ? 'dead' : 'unconscious')
      GameStorage.execute(
        "UPDATE play_campaign_member_death_saves SET successes = #{successes}, failures = #{failures}, " \
        "status = #{GameStorage.quote(character_status)} WHERE campaign_id = #{campaign_sql} AND username = #{username_sql};"
      )

      { character_id: params['character_id'], successes: successes, failures: failures, status: character_status }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/status' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      is_member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless is_member

      member = GameStorage.query(
        "SELECT members.character_id, health.hp_current, health.hp_max, saves.status " \
        "FROM play_campaign_members AS members " \
        "JOIN play_campaign_member_health AS health ON health.campaign_id = members.campaign_id " \
        'AND health.username = members.username ' \
        "JOIN play_campaign_member_death_saves AS saves ON saves.campaign_id = members.campaign_id " \
        "AND saves.username = members.username WHERE members.campaign_id = #{campaign_sql} " \
        "AND members.character_id = #{GameStorage.quote(params['character_id'])} LIMIT 1"
      ).first
      halt_json 404, error: 'character not found' unless member

      { character_id: member['character_id'], hp_current: member['hp_current'], hp_max: member['hp_max'], status: member['status'] }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/owner' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner

      { character_id: params['character_id'], owner: owner }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/claim' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 409, error: 'character is already owned' if owner

      GameStorage.execute(
        "INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) " \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{GameStorage.quote(actor['username'])});"
      )
      { character_id: params['character_id'], owner: actor['username'] }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/transfer' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      new_owner = non_empty_string!(payload['new_owner'], 'new_owner')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'only the owner may transfer the character' unless owner == actor['username']

      is_member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(new_owner)} LIMIT 1"
      ).any?
      halt_json 400, error: 'new_owner must be a campaign member' unless is_member

      GameStorage.execute(
        "INSERT INTO play_campaign_character_owners (campaign_id, character_id, owner) " \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{GameStorage.quote(new_owner)}) " \
        'ON CONFLICT(campaign_id, character_id) DO UPDATE SET owner = excluded.owner;'
      )
      { character_id: params['character_id'], owner: new_owner }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/build' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      race = payload['race']
      character_class = payload['class']
      background = payload['background']
      halt_json 400, error: 'invalid race' unless CHARACTER_RACES.include?(race)
      halt_json 400, error: 'invalid class' unless CHARACTER_CLASSES.key?(character_class)
      halt_json 400, error: 'invalid background' unless CHARACTER_BACKGROUNDS.include?(background)

      abilities = payload['abilities']
      halt_json 400, error: 'abilities must be an object' unless abilities.is_a?(Hash)
      ABILITIES.each { |ability| ability_score!(abilities[ability]) }

      level = 1
      hp_max = CHARACTER_CLASSES.fetch(character_class) + ability_modifier(abilities['con'])
      GameStorage.execute(
        "INSERT INTO play_campaign_character_progressions " \
        '(campaign_id, character_id, level, class, con_modifier, hp_max) ' \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{level}, #{GameStorage.quote(character_class)}, " \
        "#{ability_modifier(abilities['con'])}, #{hp_max}) " \
        'ON CONFLICT(campaign_id, character_id) DO NOTHING;'
      )
      GameStorage.execute(
        "INSERT INTO play_campaign_character_abilities " \
        '(campaign_id, character_id, str, dex, con, int, wis, cha) ' \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{abilities['str']}, #{abilities['dex']}, " \
        "#{abilities['con']}, #{abilities['int']}, #{abilities['wis']}, #{abilities['cha']}) " \
        'ON CONFLICT(campaign_id, character_id) DO NOTHING;'
      )
      {
        character_id: params['character_id'],
        race: race,
        class: character_class,
        background: background,
        level: level,
        hp_max: hp_max,
        proficiency_bonus: proficiency_bonus(level)
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/spells' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      spell_id = non_empty_string!(payload['spell_id'], 'spell_id')
      name = non_empty_string!(payload['name'], 'name')
      level = integer!(payload['level'])
      halt_json 400, error: 'spell level must be non-negative' if level.negative?

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      member = GameStorage.query(
        "SELECT class FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'spell is not valid for character class' unless member && member['class'] == 'wizard'

      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_character_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND spell_id = #{GameStorage.quote(spell_id)} LIMIT 1"
      ).any?
      halt_json 409, error: 'spell already known' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_character_spells (campaign_id, character_id, spell_id, name, level) " \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{GameStorage.quote(spell_id)}, " \
        "#{GameStorage.quote(name)}, #{level});"
      )
      { spell_id: spell_id, name: name, level: level }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/spells' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      is_member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless is_member

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)

      spells = GameStorage.query(
        "SELECT spell_id, name, level FROM play_campaign_character_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} ORDER BY rowid"
      ).map { |spell| { spell_id: spell['spell_id'], name: spell['name'], level: spell['level'] } }
      { spells: spells }
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/characters/:character_id/prepared-spells' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      spell_ids = payload['spell_ids']
      halt_json 400, error: 'spell_ids must be an array' unless spell_ids.is_a?(Array)
      spell_ids.each { |spell_id| non_empty_string!(spell_id, 'spell_id') }
      halt_json 400, error: 'spell_ids must not contain duplicates' unless spell_ids.uniq.length == spell_ids.length

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      member = GameStorage.query(
        "SELECT class FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'character class cannot prepare spells' unless member && member['class'] == 'wizard'

      progression = GameStorage.query(
        "SELECT level FROM play_campaign_character_progressions WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      max_prepared = progression ? progression['level'] : 1
      halt_json 400, error: 'too many prepared spells' if spell_ids.length > max_prepared

      known_spells = GameStorage.query(
        "SELECT spell_id FROM play_campaign_character_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql}"
      ).map { |spell| spell['spell_id'] }
      halt_json 400, error: 'unknown spell' unless (spell_ids - known_spells).empty?

      GameStorage.execute(
        "DELETE FROM play_campaign_character_prepared_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql};"
      )
      spell_ids.each_with_index do |spell_id, position|
        GameStorage.execute(
          'INSERT INTO play_campaign_character_prepared_spells ' \
          '(campaign_id, character_id, position, spell_id) ' \
          "VALUES (#{campaign_sql}, #{character_id_sql}, #{position}, #{GameStorage.quote(spell_id)});"
        )
      end

      { character_id: params['character_id'], prepared_spells: spell_ids, max_prepared: max_prepared }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/prepared-spells' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      is_member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless is_member

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)

      member = GameStorage.query(
        "SELECT class FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      progression = GameStorage.query(
        "SELECT level FROM play_campaign_character_progressions WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      max_prepared = member && member['class'] == 'wizard' ? (progression ? progression['level'] : 1) : 0
      prepared_spells = GameStorage.query(
        "SELECT spell_id FROM play_campaign_character_prepared_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} ORDER BY position"
      ).map { |spell| spell['spell_id'] }

      { character_id: params['character_id'], prepared_spells: prepared_spells, max_prepared: max_prepared }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/casts' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      spell_id = non_empty_string!(payload['spell_id'], 'spell_id')
      target = non_empty_string!(payload['target'], 'target')

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      member = GameStorage.query(
        "SELECT class FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'character is not a spellcaster' unless member && member['class'] == 'wizard'

      spell_id_sql = GameStorage.quote(spell_id)
      spell = GameStorage.query(
        "SELECT level FROM play_campaign_character_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND spell_id = #{spell_id_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'spell is not known' unless spell

      prepared = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_character_prepared_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND spell_id = #{spell_id_sql} LIMIT 1"
      ).any?
      halt_json 400, error: 'spell is not currently prepared' unless prepared

      progression = GameStorage.query(
        "SELECT level FROM play_campaign_character_progressions WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      character_level = progression ? progression['level'] : 1
      slot_level = spell['level']
      # The play surface grants one slot at each spell level a wizard has
      # reached. In particular, a first-level wizard has one first-level slot.
      slot_count = slot_level.positive? && slot_level <= character_level ? 1 : 0
      casts_used = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_character_casts WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND slot_level = #{slot_level}"
      ).first['count']
      halt_json 409, error: 'no remaining spell slots' if casts_used >= slot_count

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_character_casts " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql}"
      ).first['sequence']
      slots_remaining = slot_count - casts_used - 1
      GameStorage.execute(
        'INSERT INTO play_campaign_character_casts ' \
        '(campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) ' \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{sequence}, #{spell_id_sql}, " \
        "#{GameStorage.quote(target)}, #{slot_level}, #{slots_remaining});"
      )

      {
        character_id: params['character_id'], spell_id: spell_id, target: target,
        slot_level: slot_level, slots_remaining: slots_remaining, sequence: sequence
      }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/casts' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      is_member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless is_member

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)
      casts = GameStorage.query(
        "SELECT spell_id, target, slot_level, slots_remaining, sequence FROM play_campaign_character_casts " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql} ORDER BY sequence"
      ).map do |cast|
        {
          character_id: params['character_id'], spell_id: cast['spell_id'], target: cast['target'],
          slot_level: cast['slot_level'], slots_remaining: cast['slots_remaining'], sequence: cast['sequence']
        }
      end
      { casts: casts }
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/characters/:character_id/concentration' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      spell_id = non_empty_string!(payload['spell_id'], 'spell_id')
      target = non_empty_string!(payload['target'], 'target')
      duration_turns = payload['duration_turns']
      halt_json 400, error: 'duration_turns must be a positive integer' unless duration_turns.is_a?(Integer) && duration_turns.positive?

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      member = GameStorage.query(
        "SELECT class FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'character is not a spellcaster' unless member && member['class'] == 'wizard'

      spell_id_sql = GameStorage.quote(spell_id)
      known = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_character_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND spell_id = #{spell_id_sql} LIMIT 1"
      ).any?
      halt_json 400, error: 'spell is not known' unless known

      prepared = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_character_prepared_spells WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND spell_id = #{spell_id_sql} LIMIT 1"
      ).any?
      halt_json 400, error: 'spell is not currently prepared' unless prepared

      GameStorage.execute(
        'INSERT INTO play_campaign_character_concentrations ' \
        '(campaign_id, character_id, spell_id, target, remaining_turns) ' \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{spell_id_sql}, #{GameStorage.quote(target)}, #{duration_turns}) " \
        'ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, ' \
        'target = excluded.target, remaining_turns = excluded.remaining_turns;'
      )
      {
        character_id: params['character_id'],
        concentration: { spell_id: spell_id, target: target, remaining_turns: duration_turns }
      }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/concentration' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'id, owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)
      concentration = GameStorage.query(
        "SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentrations " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      {
        character_id: params['character_id'],
        concentration: concentration && {
          spell_id: concentration['spell_id'], target: concentration['target'], remaining_turns: concentration['remaining_turns']
        }
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/concentration/advance-turn' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'id, owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)
      concentration = GameStorage.query(
        "SELECT spell_id, target, remaining_turns FROM play_campaign_character_concentrations " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      if concentration
        remaining_turns = concentration['remaining_turns'] - 1
        if remaining_turns.positive?
          GameStorage.execute(
            "UPDATE play_campaign_character_concentrations SET remaining_turns = #{remaining_turns} " \
            "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql};"
          )
          concentration['remaining_turns'] = remaining_turns
        else
          GameStorage.execute(
            "DELETE FROM play_campaign_character_concentrations WHERE campaign_id = #{campaign_sql} " \
            "AND character_id = #{character_id_sql};"
          )
          concentration = nil
        end
      end
      {
        character_id: params['character_id'],
        concentration: concentration && {
          spell_id: concentration['spell_id'], target: concentration['target'], remaining_turns: concentration['remaining_turns']
        }
      }
    end
    JSON.generate(response)
  end

  delete '/v1/play/campaigns/:id/characters/:character_id/concentration' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']
      GameStorage.execute(
        "DELETE FROM play_campaign_character_concentrations WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql};"
      )
      { character_id: params['character_id'], concentration: nil }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/currency' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)
      balance = GameStorage.query(
        "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      # Currency rows are seeded when joining. The fallback retains that
      # invariant for campaigns created before this table existed.
      unless balance
        GameStorage.execute(
          "INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold) " \
          "VALUES (#{campaign_sql}, #{character_id_sql}, 10);"
        )
        balance = { 'gold' => 10 }
      end
      { character_id: params['character_id'], gold: balance['gold'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/currency/transfers' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      destination_id = non_empty_string!(payload['to_character_id'], 'to_character_id')
      gold = integer!(payload['gold'])
      halt_json 400, error: 'gold must be positive' unless gold.positive?

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')
      source_id = params['character_id']
      source_sql = GameStorage.quote(source_id)
      source_owner = character_owner(campaign_sql, source_sql)
      halt_json 404, error: 'character not found' unless source_owner
      halt_json 403, error: 'forbidden' unless source_owner == actor['username']

      halt_json 400, error: 'destination must be a different campaign character' if destination_id == source_id
      destination_sql = GameStorage.quote(destination_id)
      halt_json 400, error: 'destination must be a campaign character' unless character_owner(campaign_sql, destination_sql)

      source = GameStorage.query(
        "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{source_sql} LIMIT 1"
      ).first
      destination = GameStorage.query(
        "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{destination_sql} LIMIT 1"
      ).first
      # All current joins have a row; seed pre-feature characters deterministically.
      source_gold = source ? source['gold'] : 10
      destination_gold = destination ? destination['gold'] : 10
      halt_json 409, error: 'insufficient gold' if source_gold < gold

      from_gold = source_gold - gold
      to_gold = destination_gold + gold
      transfer_id = GameStorage.query(
        "SELECT COALESCE(MAX(transfer_id), 0) + 1 AS transfer_id FROM play_campaign_currency_transfers " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['transfer_id']
      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
        VALUES (#{campaign_sql}, #{source_sql}, #{source_gold})
        ON CONFLICT(campaign_id, character_id) DO NOTHING;
        INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
        VALUES (#{campaign_sql}, #{destination_sql}, #{destination_gold})
        ON CONFLICT(campaign_id, character_id) DO NOTHING;
        UPDATE play_campaign_character_currency SET gold = #{from_gold}
        WHERE campaign_id = #{campaign_sql} AND character_id = #{source_sql};
        UPDATE play_campaign_character_currency SET gold = #{to_gold}
        WHERE campaign_id = #{campaign_sql} AND character_id = #{destination_sql};
        INSERT INTO play_campaign_currency_transfers
        (campaign_id, transfer_id, from_character_id, to_character_id, gold)
        VALUES (#{campaign_sql}, #{transfer_id}, #{source_sql}, #{destination_sql}, #{gold});
        COMMIT;
      SQL
      {
        from_character_id: source_id, to_character_id: destination_id, gold: gold,
        from_gold: from_gold, to_gold: to_gold, transfer_id: transfer_id
      }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/transactional-transfers' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      from_character_id = non_empty_string!(payload['from_character_id'], 'from_character_id')
      to_character_id = non_empty_string!(payload['to_character_id'], 'to_character_id')
      amount = integer!(payload['amount'])
      halt_json 400, error: 'amount must be positive' unless amount.positive?
      halt_json 400, error: 'simulate_failure must be a boolean' unless payload['simulate_failure'] == true || payload['simulate_failure'] == false

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      from_sql = GameStorage.quote(from_character_id)
      to_sql = GameStorage.quote(to_character_id)
      from_owner = character_owner(campaign_sql, from_sql)
      to_owner = character_owner(campaign_sql, to_sql)
      halt_json 400, error: 'from_character_id must be a campaign character' unless from_owner
      halt_json 400, error: 'to_character_id must be a campaign character' unless to_owner
      halt_json 400, error: 'destination must be a different campaign character' if from_character_id == to_character_id
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player' && from_owner == actor['username']

      from_balance = GameStorage.query(
        "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{from_sql} LIMIT 1"
      ).first
      to_balance = GameStorage.query(
        "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{to_sql} LIMIT 1"
      ).first
      from_gold_before = from_balance ? from_balance['gold'] : 10
      to_gold_before = to_balance ? to_balance['gold'] : 10
      halt_json 409, error: 'insufficient gold' if from_gold_before < amount

      from_gold = from_gold_before - amount
      to_gold = to_gold_before + amount
      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_transactional_transfers " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']

      # Validation and all derived values happen before this point.  A simulated
      # failure deliberately reaches the prepared state without opening a write
      # transaction, so it cannot leave any observable partial mutation.
      halt_json 500, error: 'simulated failure' if payload['simulate_failure']

      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
        VALUES (#{campaign_sql}, #{from_sql}, #{from_gold_before})
        ON CONFLICT(campaign_id, character_id) DO NOTHING;
        INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
        VALUES (#{campaign_sql}, #{to_sql}, #{to_gold_before})
        ON CONFLICT(campaign_id, character_id) DO NOTHING;
        UPDATE play_campaign_character_currency SET gold = #{from_gold}
        WHERE campaign_id = #{campaign_sql} AND character_id = #{from_sql};
        UPDATE play_campaign_character_currency SET gold = #{to_gold}
        WHERE campaign_id = #{campaign_sql} AND character_id = #{to_sql};
        INSERT INTO play_campaign_transactional_transfers
        (campaign_id, sequence, from_character_id, to_character_id, amount, from_gold, to_gold)
        VALUES (#{campaign_sql}, #{sequence}, #{from_sql}, #{to_sql}, #{amount}, #{from_gold}, #{to_gold});
        COMMIT;
      SQL
      {
        from_character_id: from_character_id, to_character_id: to_character_id, amount: amount,
        from_gold: from_gold, to_gold: to_gold, sequence: sequence
      }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/transactional-transfers' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      transfers = GameStorage.query(
        'SELECT from_character_id, to_character_id, amount, from_gold, to_gold, sequence ' \
        "FROM play_campaign_transactional_transfers WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map do |transfer|
        {
          from_character_id: transfer['from_character_id'], to_character_id: transfer['to_character_id'],
          amount: transfer['amount'], from_gold: transfer['from_gold'], to_gold: transfer['to_gold'],
          sequence: transfer['sequence']
        }
      end
      { transfers: transfers }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/loot' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      loot_id = non_empty_string!(payload['loot_id'], 'loot_id')
      item_id = non_empty_string!(payload['item_id'], 'item_id')
      quantity = integer!(payload['quantity'])
      halt_json 400, error: 'invalid item_id' unless INVENTORY_ITEM_IDS.include?(item_id)
      halt_json 400, error: 'quantity must be positive' unless quantity.positive?

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      loot_id_sql = GameStorage.quote(loot_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_loot WHERE campaign_id = #{campaign_sql} " \
        "AND loot_id = #{loot_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'loot id already exists' if duplicate

      GameStorage.execute(
        'INSERT INTO play_campaign_loot (campaign_id, loot_id, item_id, quantity, status) ' \
        "VALUES (#{campaign_sql}, #{loot_id_sql}, #{GameStorage.quote(item_id)}, #{quantity}, 'open');"
      )
      { loot_id: loot_id, item_id: item_id, quantity: quantity, status: 'open' }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/loot/:loot_id/votes' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      recipient_character_id = non_empty_string!(payload['recipient_character_id'], 'recipient_character_id')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      voter_sql = GameStorage.quote(actor['username'])
      is_player = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{voter_sql} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless is_player

      loot_id = params['loot_id']
      loot_id_sql = GameStorage.quote(loot_id)
      loot = GameStorage.query(
        "SELECT status FROM play_campaign_loot WHERE campaign_id = #{campaign_sql} " \
        "AND loot_id = #{loot_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'loot not found' unless loot
      halt_json 409, error: 'loot is not open' unless loot['status'] == 'open'

      recipient_sql = GameStorage.quote(recipient_character_id)
      recipient = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{recipient_sql} LIMIT 1"
      ).any?
      halt_json 400, error: 'recipient must be a campaign character' unless recipient

      prior_vote = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_loot_votes WHERE campaign_id = #{campaign_sql} " \
        "AND loot_id = #{loot_id_sql} AND voter = #{voter_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'vote already exists' if prior_vote

      GameStorage.execute(
        'INSERT INTO play_campaign_loot_votes (campaign_id, loot_id, voter, recipient_character_id) ' \
        "VALUES (#{campaign_sql}, #{loot_id_sql}, #{voter_sql}, #{recipient_sql});"
      )
      votes_for_recipient = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_loot_votes WHERE campaign_id = #{campaign_sql} " \
        "AND loot_id = #{loot_id_sql} AND recipient_character_id = #{recipient_sql}"
      ).first['count']
      {
        loot_id: loot_id, voter: actor['username'], recipient_character_id: recipient_character_id,
        votes_for_recipient: votes_for_recipient
      }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/loot/:loot_id/assign' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      loot_id = params['loot_id']
      loot_id_sql = GameStorage.quote(loot_id)
      loot = GameStorage.query(
        "SELECT item_id, quantity, status FROM play_campaign_loot WHERE campaign_id = #{campaign_sql} " \
        "AND loot_id = #{loot_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'loot not found' unless loot
      halt_json 409, error: 'loot is not open' unless loot['status'] == 'open'

      leaders = GameStorage.query(
        "SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes " \
        "WHERE campaign_id = #{campaign_sql} AND loot_id = #{loot_id_sql} " \
        'GROUP BY recipient_character_id ORDER BY votes DESC, recipient_character_id'
      )
      halt_json 409, error: 'loot has no unambiguous winner' if leaders.empty? ||
        (leaders.length > 1 && leaders[0]['votes'] == leaders[1]['votes'])
      winner = leaders.first
      recipient_sql = GameStorage.quote(winner['recipient_character_id'])
      item_id_sql = GameStorage.quote(loot['item_id'])

      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (#{campaign_sql}, #{recipient_sql}, #{item_id_sql}, #{loot['quantity']})
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity =
        play_campaign_character_inventory_items.quantity + excluded.quantity;
        UPDATE play_campaign_loot SET status = 'assigned', recipient_character_id = #{recipient_sql}, votes = #{winner['votes']}
        WHERE campaign_id = #{campaign_sql} AND loot_id = #{loot_id_sql} AND status = 'open';
        COMMIT;
      SQL
      {
        loot_id: loot_id, recipient_character_id: winner['recipient_character_id'], item_id: loot['item_id'],
        quantity: loot['quantity'], votes: winner['votes'], status: 'assigned'
      }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/loot/:loot_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      loot = GameStorage.query(
        "SELECT loot_id, item_id, quantity, status, recipient_character_id FROM play_campaign_loot " \
        "WHERE campaign_id = #{campaign_sql} AND loot_id = #{GameStorage.quote(params['loot_id'])} LIMIT 1"
      ).first
      halt_json 404, error: 'loot not found' unless loot
      vote_counts = GameStorage.query(
        "SELECT recipient_character_id, COUNT(*) AS votes FROM play_campaign_loot_votes " \
        "WHERE campaign_id = #{campaign_sql} AND loot_id = #{GameStorage.quote(params['loot_id'])} " \
        'GROUP BY recipient_character_id ORDER BY recipient_character_id'
      ).each_with_object({}) { |row, counts| counts[row['recipient_character_id']] = row['votes'] }
      {
        loot_id: loot['loot_id'], item_id: loot['item_id'], quantity: loot['quantity'], status: loot['status'],
        recipient_character_id: loot['recipient_character_id'], votes: vote_counts
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/npcs' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      npc_id = non_empty_string!(payload['npc_id'], 'npc_id')
      name = non_empty_string!(payload['name'], 'name')
      agenda = non_empty_string!(payload['agenda'], 'agenda')
      public_status = non_empty_string!(payload['public_status'], 'public_status')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      npc_id_sql = GameStorage.quote(npc_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_npcs WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{npc_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'npc id already exists' if duplicate

      GameStorage.execute(
        'INSERT INTO play_campaign_npcs (campaign_id, npc_id, name, agenda, public_status) ' \
        "VALUES (#{campaign_sql}, #{npc_id_sql}, #{GameStorage.quote(name)}, " \
        "#{GameStorage.quote(agenda)}, #{GameStorage.quote(public_status)});"
      )
      { npc_id: npc_id, name: name, agenda: agenda, public_status: public_status }
    end
    status 201
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/npcs/:npc_id/agenda' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      agenda = non_empty_string!(payload['agenda'], 'agenda')
      public_status = non_empty_string!(payload['public_status'], 'public_status')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      npc_id_sql = GameStorage.quote(params['npc_id'])
      npc = GameStorage.query(
        "SELECT npc_id, name FROM play_campaign_npcs WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{npc_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'npc not found' unless npc

      GameStorage.execute(
        "UPDATE play_campaign_npcs SET agenda = #{GameStorage.quote(agenda)}, " \
        "public_status = #{GameStorage.quote(public_status)} WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{npc_id_sql};"
      )
      { npc_id: npc['npc_id'], name: npc['name'], agenda: agenda, public_status: public_status }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/npcs/:npc_id/dialogue' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      dialogue_id = non_empty_string!(payload['dialogue_id'], 'dialogue_id')
      speaker = non_empty_string!(payload['speaker'], 'speaker')
      text = non_empty_string!(payload['text'], 'text')
      visibility = payload['visibility']
      halt_json 400, error: 'visibility must be public or private' unless %w[public private].include?(visibility)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      npc_id = params['npc_id']
      npc_id_sql = GameStorage.quote(npc_id)
      npc = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_npcs WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{npc_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'npc not found' unless npc

      dialogue_id_sql = GameStorage.quote(dialogue_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_npc_dialogue WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{npc_id_sql} AND dialogue_id = #{dialogue_id_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'dialogue id already exists' if duplicate

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM play_campaign_npc_dialogue " \
        "WHERE campaign_id = #{campaign_sql} AND npc_id = #{npc_id_sql}"
      ).first['sequence'] + 1
      GameStorage.execute(
        'INSERT INTO play_campaign_npc_dialogue ' \
        '(campaign_id, npc_id, sequence, dialogue_id, speaker, text, visibility) ' \
        "VALUES (#{campaign_sql}, #{npc_id_sql}, #{sequence}, #{dialogue_id_sql}, " \
        "#{GameStorage.quote(speaker)}, #{GameStorage.quote(text)}, #{GameStorage.quote(visibility)});"
      )
      { dialogue_id: dialogue_id, speaker: speaker, text: text, visibility: visibility }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/npcs/:npc_id/dialogue' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      npc_id = params['npc_id']
      npc_id_sql = GameStorage.quote(npc_id)
      npc = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_npcs WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{npc_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'npc not found' unless npc

      visibility_filter = campaign['owner'] == actor['username'] ? '' : " AND visibility = 'public'"
      entries = GameStorage.query(
        "SELECT dialogue_id, speaker, text, visibility FROM play_campaign_npc_dialogue " \
        "WHERE campaign_id = #{campaign_sql} AND npc_id = #{npc_id_sql}#{visibility_filter} ORDER BY sequence"
      ).map do |entry|
        {
          dialogue_id: entry['dialogue_id'], speaker: entry['speaker'], text: entry['text'],
          visibility: entry['visibility']
        }
      end
      { npc_id: npc_id, entries: entries }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/relationships' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      source_id = non_empty_string!(payload['source_id'], 'source_id')
      target_id = non_empty_string!(payload['target_id'], 'target_id')
      kind = non_empty_string!(payload['kind'], 'kind')
      score = integer!(payload['score'])
      halt_json 400, error: 'score must be between -100 and 100' unless (-100..100).cover?(score)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']
      halt_json 400, error: 'source and target must differ' if source_id == target_id
      halt_json 404, error: 'campaign entity not found' unless play_campaign_entity?(campaign_sql, source_id)
      halt_json 404, error: 'campaign entity not found' unless play_campaign_entity?(campaign_sql, target_id)

      source_id_sql = GameStorage.quote(source_id)
      target_id_sql = GameStorage.quote(target_id)
      kind_sql = GameStorage.quote(kind)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_relationships WHERE campaign_id = #{campaign_sql} " \
        "AND source_id = #{source_id_sql} AND target_id = #{target_id_sql} AND kind = #{kind_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'relationship already exists' if duplicate

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_relationships " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_relationships (campaign_id, sequence, source_id, target_id, kind, score) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{source_id_sql}, #{target_id_sql}, #{kind_sql}, #{score});"
      )
      { source_id: source_id, target_id: target_id, kind: kind, score: score }
    end
    status 201
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      score = integer!(payload['score'])
      halt_json 400, error: 'score must be between -100 and 100' unless (-100..100).cover?(score)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      source_id = params['source_id']
      target_id = params['target_id']
      kind = params['kind']
      source_id_sql = GameStorage.quote(source_id)
      target_id_sql = GameStorage.quote(target_id)
      kind_sql = GameStorage.quote(kind)
      relationship = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_relationships WHERE campaign_id = #{campaign_sql} " \
        "AND source_id = #{source_id_sql} AND target_id = #{target_id_sql} AND kind = #{kind_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'relationship not found' unless relationship

      GameStorage.execute(
        "UPDATE play_campaign_relationships SET score = #{score} WHERE campaign_id = #{campaign_sql} " \
        "AND source_id = #{source_id_sql} AND target_id = #{target_id_sql} AND kind = #{kind_sql};"
      )
      { source_id: source_id, target_id: target_id, kind: kind, score: score }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/relationships' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      edges = GameStorage.query(
        "SELECT source_id, target_id, kind, score FROM play_campaign_relationships " \
        "WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map do |edge|
        { source_id: edge['source_id'], target_id: edge['target_id'], kind: edge['kind'], score: edge['score'] }
      end
      { edges: edges }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/clues' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      clue_id = non_empty_string!(payload['clue_id'], 'clue_id')
      text = non_empty_string!(payload['text'], 'text')
      audience = payload['audience']
      halt_json 400, error: 'invalid audience' unless %w[character party hidden].include?(audience)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      character_id = payload['character_id']
      if audience == 'character'
        character_id = non_empty_string!(character_id, 'character_id')
        member = GameStorage.query(
          "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
          "AND character_id = #{GameStorage.quote(character_id)} LIMIT 1"
        ).first
        halt_json 400, error: 'character is not a campaign member' unless member
      else
        halt_json 400, error: 'character_id must be omitted' if payload.key?('character_id')
      end

      clue_id_sql = GameStorage.quote(clue_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_clues WHERE campaign_id = #{campaign_sql} " \
        "AND clue_id = #{clue_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'clue id already exists' if duplicate

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_clues " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_clues (campaign_id, sequence, clue_id, text, audience, character_id) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{clue_id_sql}, #{GameStorage.quote(text)}, " \
        "#{GameStorage.quote(audience)}, #{audience == 'character' ? GameStorage.quote(character_id) : 'NULL'});"
      )

      result = { clue_id: clue_id, text: text, audience: audience }
      result[:character_id] = character_id if audience == 'character'
      result
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/clues' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      member = if campaign['owner'] == actor['username']
                 nil
               else
                 GameStorage.query(
                   "SELECT character_id FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
                   "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
                 ).first
               end
      filter = if campaign['owner'] == actor['username']
                 ''
               else
                 " AND (audience = 'party' OR (audience = 'character' AND character_id = #{GameStorage.quote(member['character_id'])}))"
               end
      clues = GameStorage.query(
        "SELECT clue_id, text, audience, character_id FROM play_campaign_clues " \
        "WHERE campaign_id = #{campaign_sql}#{filter} ORDER BY sequence"
      ).map do |clue|
        result = { clue_id: clue['clue_id'], text: clue['text'], audience: clue['audience'] }
        result[:character_id] = clue['character_id'] if clue['audience'] == 'character'
        result
      end
      { clues: clues }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/quests' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      quest_id = non_empty_string!(payload['quest_id'], 'quest_id')
      title = non_empty_string!(payload['title'], 'title')
      depends_on = payload['depends_on']
      halt_json 400, error: 'invalid depends_on' unless depends_on.is_a?(Array) &&
        depends_on.all? { |dependency| dependency.is_a?(String) && !dependency.empty? } &&
        depends_on.uniq.length == depends_on.length && !depends_on.include?(quest_id)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      quest_id_sql = GameStorage.quote(quest_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_quests WHERE campaign_id = #{campaign_sql} " \
        "AND quest_id = #{quest_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'quest id already exists' if duplicate

      depends_on.each do |dependency|
        existing = GameStorage.query(
          "SELECT 1 AS found FROM play_campaign_quests WHERE campaign_id = #{campaign_sql} " \
          "AND quest_id = #{GameStorage.quote(dependency)} LIMIT 1"
        ).any?
        halt_json 400, error: 'dependency does not exist in campaign' unless existing
      end

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_quests " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_quests (campaign_id, sequence, quest_id, title, depends_on, state) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{quest_id_sql}, #{GameStorage.quote(title)}, " \
        "#{GameStorage.quote(JSON.generate(depends_on))}, 'locked');"
      )
      { quest_id: quest_id, title: title, depends_on: depends_on, state: 'locked' }
    end
    status 201
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/quests/:quest_id/state' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      state = payload['state']
      halt_json 400, error: 'invalid state' unless %w[active completed].include?(state)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      quest_id_sql = GameStorage.quote(params['quest_id'])
      quest = GameStorage.query(
        "SELECT quests.quest_id, quests.title, quests.depends_on, quests.state, rewards.xp AS reward_xp, " \
        "rewards.items AS reward_items FROM play_campaign_quests AS quests " \
        "LEFT JOIN play_campaign_quest_rewards AS rewards ON rewards.campaign_id = quests.campaign_id " \
        "AND rewards.quest_id = quests.quest_id WHERE quests.campaign_id = #{campaign_sql} " \
        "AND quests.quest_id = #{quest_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'quest not found' unless quest

      if quest['state'] == 'locked' && state == 'active'
        dependencies_completed = JSON.parse(quest['depends_on']).all? do |dependency|
          dependency_state = GameStorage.query(
            "SELECT state FROM play_campaign_quests WHERE campaign_id = #{campaign_sql} " \
            "AND quest_id = #{GameStorage.quote(dependency)} LIMIT 1"
          ).first
          dependency_state && dependency_state['state'] == 'completed'
        end
        halt_json 409, error: 'quest dependencies are not completed' unless dependencies_completed
      elsif !(quest['state'] == 'active' && state == 'completed')
        halt_json 409, error: 'invalid quest state transition'
      end

      GameStorage.execute(
        "UPDATE play_campaign_quests SET state = #{GameStorage.quote(state)} WHERE campaign_id = #{campaign_sql} " \
        "AND quest_id = #{quest_id_sql};"
      )
      play_quest_response(quest.merge('state' => state))
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/quests/:quest_id/rewards' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      xp = integer!(payload['xp'])
      halt_json 400, error: 'xp must be nonnegative' if xp.negative?
      items = payload['items']
      halt_json 400, error: 'items must be an object' unless items.is_a?(Hash)
      halt_json 400, error: 'invalid reward items' unless items.all? do |item_id, quantity|
        item_id.is_a?(String) && INVENTORY_ITEM_IDS.include?(item_id) && quantity.is_a?(Integer) && quantity.positive?
      end

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      quest_id = params['quest_id']
      quest_sql = GameStorage.quote(quest_id)
      quest = GameStorage.query(
        "SELECT quest_id, title, depends_on, state FROM play_campaign_quests WHERE campaign_id = #{campaign_sql} " \
        "AND quest_id = #{quest_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'quest not found' unless quest
      halt_json 409, error: 'quest is already completed' unless %w[locked active].include?(quest['state'])

      GameStorage.execute(
        'INSERT INTO play_campaign_quest_rewards (campaign_id, quest_id, xp, items) ' \
        "VALUES (#{campaign_sql}, #{quest_sql}, #{xp}, #{GameStorage.quote(JSON.generate(items))}) " \
        'ON CONFLICT(campaign_id, quest_id) DO UPDATE SET xp = excluded.xp, items = excluded.items;'
      )
      play_quest_response(quest.merge('reward_xp' => xp, 'reward_items' => JSON.generate(items)))
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/quests/:quest_id/rewards/award' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      quest_id = params['quest_id']
      quest_sql = GameStorage.quote(quest_id)
      quest = GameStorage.query(
        "SELECT state FROM play_campaign_quests WHERE campaign_id = #{campaign_sql} AND quest_id = #{quest_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'quest not found' unless quest
      reward = GameStorage.query(
        "SELECT xp, items FROM play_campaign_quest_rewards WHERE campaign_id = #{campaign_sql} AND quest_id = #{quest_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'quest rewards cannot be awarded' unless quest['state'] == 'completed' && reward
      already_awarded = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_quest_reward_awards WHERE campaign_id = #{campaign_sql} AND quest_id = #{quest_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'quest rewards have already been awarded' if already_awarded

      items = JSON.parse(reward['items'])
      grants = ordered_play_members(campaign_sql, 'character_id')
      statements = ["BEGIN IMMEDIATE;", "INSERT INTO play_campaign_quest_reward_awards (campaign_id, quest_id) VALUES (#{campaign_sql}, #{quest_sql});"]
      grants.each do |member|
        statements << 'INSERT INTO play_campaign_quest_reward_grants (campaign_id, quest_id, character_id, xp, items) ' \
          "VALUES (#{campaign_sql}, #{quest_sql}, #{GameStorage.quote(member['character_id'])}, #{reward['xp']}, #{GameStorage.quote(reward['items'])});"
      end
      statements << 'COMMIT;'
      GameStorage.execute(statements.join("\n"))
      { quest_id: quest_id, awarded: true, xp: reward['xp'], items: items }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/rewards' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'id')
      halt_json 404, error: 'campaign not found' unless campaign
      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless member

      character_id = params['character_id']
      character_sql = GameStorage.quote(character_id)
      character = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} LIMIT 1"
      ).any?
      halt_json 404, error: 'character not found' unless character

      grants = GameStorage.query(
        "SELECT xp, items FROM play_campaign_quest_reward_grants WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql}"
      )
      totals = grants.each_with_object({ xp: 0, items: {} }) do |grant, result|
        result[:xp] += grant['xp']
        JSON.parse(grant['items']).each { |item_id, quantity| result[:items][item_id] = (result[:items][item_id] || 0) + quantity }
      end
      { character_id: character_id, xp: totals[:xp], items: totals[:items] }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/quests' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      quests = GameStorage.query(
        "SELECT quests.quest_id, quests.title, quests.depends_on, quests.state, rewards.xp AS reward_xp, " \
        "rewards.items AS reward_items FROM play_campaign_quests AS quests " \
        "LEFT JOIN play_campaign_quest_rewards AS rewards ON rewards.campaign_id = quests.campaign_id " \
        "AND rewards.quest_id = quests.quest_id WHERE quests.campaign_id = #{campaign_sql} ORDER BY quests.sequence"
      ).map { |quest| play_quest_response(quest) }
      { quests: quests }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/world-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      event_id = non_empty_string!(payload['event_id'], 'event_id')
      turn_number = integer!(payload['turn_number'])
      title = non_empty_string!(payload['title'], 'title')
      text = non_empty_string!(payload['text'], 'text')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      halt_json 400, error: 'turn_number must be at or after the current turn' if turn_number < play_campaign_turn_number(campaign_sql)

      event_id_sql = GameStorage.quote(event_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_world_events WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'world event id already exists' if duplicate

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_world_events " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_world_events ' \
        '(campaign_id, sequence, event_id, turn_number, title, text, status) ' \
        "VALUES (#{campaign_sql}, #{sequence}, #{event_id_sql}, #{turn_number}, " \
        "#{GameStorage.quote(title)}, #{GameStorage.quote(text)}, 'scheduled');"
      )
      {
        event_id: event_id,
        turn_number: turn_number,
        title: title,
        text: text,
        status: 'scheduled'
      }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/world-events/:event_id/resolve' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      resolution_text = non_empty_string!(payload['text'], 'text')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      event_sql = GameStorage.quote(params['event_id'])
      event = GameStorage.query(
        "SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text " \
        "FROM play_campaign_world_events WHERE campaign_id = #{campaign_sql} AND event_id = #{event_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'world event not found' unless event
      halt_json 409, error: 'world event is already resolved' if event['status'] == 'resolved'

      current_turn = play_campaign_turn_number(campaign_sql)
      halt_json 409, error: 'world event is not scheduled for the current turn' unless current_turn == event['turn_number']

      GameStorage.execute(
        "UPDATE play_campaign_world_events SET status = 'resolved', resolution_turn_number = #{current_turn}, " \
        "resolution_text = #{GameStorage.quote(resolution_text)} WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_sql} AND status = 'scheduled';"
      )
      play_world_event_response(event.merge(
        'status' => 'resolved',
        'resolution_turn_number' => current_turn,
        'resolution_text' => resolution_text
      ))
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/world-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      events = GameStorage.query(
        "SELECT event_id, turn_number, title, text, status, resolution_turn_number, resolution_text " \
        "FROM play_campaign_world_events WHERE campaign_id = #{campaign_sql} ORDER BY turn_number, sequence"
      ).map { |event| play_world_event_response(event) }
      { events: events }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/npcs/:npc_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      npc = GameStorage.query(
        "SELECT npc_id, name, agenda, public_status FROM play_campaign_npcs WHERE campaign_id = #{campaign_sql} " \
        "AND npc_id = #{GameStorage.quote(params['npc_id'])} LIMIT 1"
      ).first
      halt_json 404, error: 'npc not found' unless npc

      if campaign['owner'] == actor['username']
        { npc_id: npc['npc_id'], name: npc['name'], agenda: npc['agenda'], public_status: npc['public_status'] }
      else
        { npc_id: npc['npc_id'], name: npc['name'], public_status: npc['public_status'] }
      end
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/factions' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      faction_id = non_empty_string!(payload['faction_id'], 'faction_id')
      name = non_empty_string!(payload['name'], 'name')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      faction_sql = GameStorage.quote(faction_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_factions WHERE campaign_id = #{campaign_sql} " \
        "AND faction_id = #{faction_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'faction id already exists' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_factions (campaign_id, faction_id, name) " \
        "VALUES (#{campaign_sql}, #{faction_sql}, #{GameStorage.quote(name)});"
      )
      { faction_id: faction_id, name: name }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/factions/:faction_id/reputation' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      character_id = non_empty_string!(payload['character_id'], 'character_id')
      delta = integer!(payload['delta'])
      halt_json 400, error: 'delta must be nonzero and between -25 and 25' unless delta != 0 && (-25..25).cover?(delta)
      reason = non_empty_string!(payload['reason'], 'reason')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      faction_id = params['faction_id']
      faction_sql = GameStorage.quote(faction_id)
      faction = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_factions WHERE campaign_id = #{campaign_sql} " \
        "AND faction_id = #{faction_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'faction not found' unless faction

      character_sql = GameStorage.quote(character_id)
      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'character must be a campaign member' unless member

      previous = GameStorage.query(
        "SELECT reputation FROM play_campaign_faction_reputation_history WHERE campaign_id = #{campaign_sql} " \
        "AND faction_id = #{faction_sql} AND character_id = #{character_sql} ORDER BY sequence DESC LIMIT 1"
      ).first
      reputation = [[(previous ? previous['reputation'] : 0) + delta, -100].max, 100].min
      sequence_row = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) AS sequence FROM play_campaign_faction_reputation_history " \
        "WHERE campaign_id = #{campaign_sql} AND faction_id = #{faction_sql}"
      ).first
      sequence = sequence_row['sequence'] + 1
      GameStorage.execute(
        'INSERT INTO play_campaign_faction_reputation_history ' \
        '(campaign_id, faction_id, sequence, character_id, reputation, delta, reason) ' \
        "VALUES (#{campaign_sql}, #{faction_sql}, #{sequence}, #{character_sql}, #{reputation}, " \
        "#{delta}, #{GameStorage.quote(reason)});"
      )
      { faction_id: faction_id, character_id: character_id, reputation: reputation, delta: delta, reason: reason }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/factions/:faction_id/reputation' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      faction_id = params['faction_id']
      faction_sql = GameStorage.quote(faction_id)
      faction = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_factions WHERE campaign_id = #{campaign_sql} " \
        "AND faction_id = #{faction_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'faction not found' unless faction

      member_filter = if campaign['owner'] == actor['username']
                        ''
                      else
                        member = GameStorage.query(
                          "SELECT character_id FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
                          "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
                        ).first
                        " AND character_id = #{GameStorage.quote(member['character_id'])}"
                      end
      entries = GameStorage.query(
        "SELECT faction_id, character_id, reputation, delta, reason FROM play_campaign_faction_reputation_history " \
        "WHERE campaign_id = #{campaign_sql} AND faction_id = #{faction_sql}#{member_filter} ORDER BY sequence"
      ).map do |entry|
        {
          faction_id: entry['faction_id'], character_id: entry['character_id'], reputation: entry['reputation'],
          delta: entry['delta'], reason: entry['reason']
        }
      end
      { faction_id: faction_id, entries: entries }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/downtime/activities' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      activity = downtime_activity_attributes!(payload)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm' && campaign['owner'] == actor['username']

      activity_id_sql = GameStorage.quote(activity[:activity_id])
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_downtime_activities WHERE campaign_id = #{campaign_sql} " \
        "AND activity_id = #{activity_id_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'activity id already exists' if duplicate

      GameStorage.execute(
        'INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) ' \
        "VALUES (#{campaign_sql}, #{activity_id_sql}, #{GameStorage.quote(activity[:name])}, " \
        "#{activity[:cycles_required]});"
      )
      activity
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      activity_id = non_empty_string!(payload['activity_id'], 'activity_id')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      character_id = params['character_id']
      character_sql = GameStorage.quote(character_id)
      owner = character_owner(campaign_sql, character_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player' && owner == actor['username'] && campaign['owner'] != actor['username']

      activity_sql = GameStorage.quote(activity_id)
      activity = GameStorage.query(
        "SELECT activity_id FROM play_campaign_downtime_activities WHERE campaign_id = #{campaign_sql} " \
        "AND activity_id = #{activity_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'activity not found' unless activity

      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_downtime_allocations WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} AND activity_id = #{activity_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'downtime allocation already exists' if duplicate

      GameStorage.execute(
        'INSERT INTO play_campaign_downtime_allocations ' \
        '(campaign_id, character_id, activity_id, cycles_completed, completions) ' \
        "VALUES (#{campaign_sql}, #{character_sql}, #{activity_sql}, 0, 0);"
      )
      { character_id: character_id, activity_id: activity_id, cycles_completed: 0, completions: 0 }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      character_id = params['character_id']
      character_sql = GameStorage.quote(character_id)
      owner = character_owner(campaign_sql, character_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player' && owner == actor['username'] && campaign['owner'] != actor['username']

      activity_id = params['activity_id']
      activity_sql = GameStorage.quote(activity_id)
      activity = GameStorage.query(
        "SELECT cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = #{campaign_sql} " \
        "AND activity_id = #{activity_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'activity not found' unless activity
      allocation = GameStorage.query(
        "SELECT cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} AND activity_id = #{activity_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'downtime allocation not found' unless allocation

      cycles_completed = allocation['cycles_completed'] + 1
      completions = allocation['completions']
      if cycles_completed == activity['cycles_required']
        cycles_completed = 0
        completions += 1
      end
      GameStorage.execute(
        "UPDATE play_campaign_downtime_allocations SET cycles_completed = #{cycles_completed}, " \
        "completions = #{completions} WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} AND activity_id = #{activity_sql};"
      )
      { character_id: character_id, activity_id: activity_id, cycles_completed: cycles_completed, completions: completions }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_sql)
      activity_sql = GameStorage.quote(params['activity_id'])
      activity = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_downtime_activities WHERE campaign_id = #{campaign_sql} " \
        "AND activity_id = #{activity_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'activity not found' unless activity
      allocation = GameStorage.query(
        "SELECT character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_sql} " \
        "AND activity_id = #{activity_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'downtime allocation not found' unless allocation
      downtime_allocation_response(allocation)
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/recipes' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      recipe = recipe_attributes!(payload)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      recipe_id_sql = GameStorage.quote(recipe[:recipe_id])
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_recipes WHERE campaign_id = #{campaign_sql} " \
        "AND recipe_id = #{recipe_id_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'recipe id already exists' if duplicate

      GameStorage.execute(
        'INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, ingredients, output_item, output_quantity) ' \
        "VALUES (#{campaign_sql}, #{recipe_id_sql}, #{GameStorage.quote(recipe[:name])}, " \
        "#{GameStorage.quote(JSON.generate(recipe[:ingredients]))}, #{GameStorage.quote(recipe[:output_item])}, " \
        "#{recipe[:output_quantity]});"
      )
      recipe
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/recipes' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      recipes = GameStorage.query(
        "SELECT recipe_id, name, ingredients, output_item, output_quantity FROM play_campaign_recipes " \
        "WHERE campaign_id = #{campaign_sql} ORDER BY rowid"
      ).map { |recipe| recipe_response(recipe) }
      { recipes: recipes }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/recipes/:recipe_id/craft' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      character_id = non_empty_string!(payload['character_id'], 'character_id')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      recipe_sql = GameStorage.quote(params['recipe_id'])
      recipe = GameStorage.query(
        "SELECT recipe_id, ingredients, output_item, output_quantity FROM play_campaign_recipes " \
        "WHERE campaign_id = #{campaign_sql} AND recipe_id = #{recipe_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'recipe not found' unless recipe

      character_sql = GameStorage.quote(character_id)
      owner = character_owner(campaign_sql, character_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player' && campaign['owner'] != actor['username'] && owner == actor['username']

      ingredients = JSON.parse(recipe['ingredients'])
      held = GameStorage.query(
        "SELECT item_id, quantity FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql}"
      ).each_with_object({}) { |item, quantities| quantities[item['item_id']] = item['quantity'] }
      halt_json 409, error: 'insufficient ingredients' unless ingredients.all? { |item_id, quantity| (held[item_id] || 0) >= quantity }

      updates = ingredients.map do |item_id, quantity|
        item_sql = GameStorage.quote(item_id)
        remaining = held[item_id] - quantity
        if remaining.zero?
          "DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} AND character_id = #{character_sql} AND item_id = #{item_sql};"
        else
          "UPDATE play_campaign_character_inventory_items SET quantity = #{remaining} WHERE campaign_id = #{campaign_sql} AND character_id = #{character_sql} AND item_id = #{item_sql};"
        end
      end
      output_sql = GameStorage.quote(recipe['output_item'])
      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        #{updates.join("\n")}
        INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (#{campaign_sql}, #{character_sql}, #{output_sql}, #{recipe['output_quantity']})
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity =
        play_campaign_character_inventory_items.quantity + excluded.quantity;
        COMMIT;
      SQL
      {
        character_id: character_id, recipe_id: recipe['recipe_id'], output_item: recipe['output_item'],
        output_quantity: recipe['output_quantity']
      }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/inventory/items' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      item_id = non_empty_string!(payload['item_id'], 'item_id')
      quantity = integer!(payload['quantity'])
      halt_json 400, error: 'invalid item_id' unless INVENTORY_ITEM_IDS.include?(item_id)
      halt_json 400, error: 'quantity must be positive' unless quantity.positive?

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      item_id_sql = GameStorage.quote(item_id)
      GameStorage.execute(
        'INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity) ' \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{item_id_sql}, #{quantity}) " \
        'ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = ' \
        'play_campaign_character_inventory_items.quantity + excluded.quantity;'
      )
      total_quantity = GameStorage.query(
        "SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql} LIMIT 1"
      ).first['quantity']
      { character_id: params['character_id'], item_id: item_id, quantity: quantity, total_quantity: total_quantity }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/inventory/items' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'id, owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)
      items = GameStorage.query(
        "SELECT item_id, quantity FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} ORDER BY item_id"
      ).map { |item| { item_id: item['item_id'], quantity: item['quantity'] } }
      { character_id: params['character_id'], items: items }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/inventory/items/:item_id/consume' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      item_id = params['item_id']
      halt_json 400, error: 'invalid item_id' unless INVENTORY_ITEM_IDS.include?(item_id)
      halt_json 400, error: 'item is not consumable' unless item_id == 'healing-potion'

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      item_id_sql = GameStorage.quote(item_id)
      held = GameStorage.query(
        "SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql} LIMIT 1"
      ).first
      held_quantity = held ? held['quantity'] : 0
      halt_json 409, error: 'no consumable item held' unless held_quantity.positive?

      total_quantity = held_quantity - 1
      if total_quantity.zero?
        GameStorage.execute(
          "DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
          "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql};"
        )
      else
        GameStorage.execute(
          "UPDATE play_campaign_character_inventory_items SET quantity = #{total_quantity} WHERE campaign_id = #{campaign_sql} " \
          "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql};"
        )
      end

      {
        character_id: params['character_id'], item_id: item_id, quantity_consumed: 1,
        total_quantity: total_quantity, effect: { type: 'healing', hp_restored: 5 }
      }
    end
    JSON.generate(response)
  end

  delete '/v1/play/campaigns/:id/characters/:character_id/inventory/items/:item_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      quantity = integer!(payload['quantity'])
      item_id = params['item_id']
      halt_json 400, error: 'invalid item_id' unless INVENTORY_ITEM_IDS.include?(item_id)
      halt_json 400, error: 'quantity must be positive' unless quantity.positive?

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      item_id_sql = GameStorage.quote(item_id)
      held = GameStorage.query(
        "SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql} LIMIT 1"
      ).first
      held_quantity = held ? held['quantity'] : 0
      halt_json 409, error: 'insufficient item quantity' if quantity > held_quantity

      total_quantity = held_quantity - quantity
      if total_quantity.zero?
        GameStorage.execute(
          "DELETE FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
          "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql};"
        )
      else
        GameStorage.execute(
          "UPDATE play_campaign_character_inventory_items SET quantity = #{total_quantity} WHERE campaign_id = #{campaign_sql} " \
          "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql};"
        )
      end
      { character_id: params['character_id'], item_id: item_id, quantity: quantity, total_quantity: total_quantity }
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      item_id = non_empty_string!(payload['item_id'], 'item_id')
      slot = params['slot']
      halt_json 400, error: 'invalid equipment slot' unless EQUIPMENT_SLOTS.include?(slot)
      halt_json 400, error: 'invalid item_id' unless EQUIPMENT_ITEM_SLOTS.key?(item_id)
      halt_json 400, error: 'item does not match equipment slot' unless EQUIPMENT_ITEM_SLOTS[item_id] == slot

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      item_id_sql = GameStorage.quote(item_id)
      held = GameStorage.query(
        "SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND item_id = #{item_id_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'item is not held' unless held && held['quantity'].positive?

      GameStorage.execute(
        'INSERT INTO play_campaign_character_equipment (campaign_id, character_id, slot, item_id, attuned) ' \
        "VALUES (#{campaign_sql}, #{character_id_sql}, #{GameStorage.quote(slot)}, #{item_id_sql}, 0) " \
        'ON CONFLICT(campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0;'
      )
      { character_id: params['character_id'], slot: slot, item_id: item_id, attuned: false }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      slot = params['slot']
      halt_json 400, error: 'invalid equipment slot' unless EQUIPMENT_SLOTS.include?(slot)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'id, owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      character_id_sql = GameStorage.quote(params['character_id'])
      halt_json 404, error: 'character not found' unless character_owner(campaign_sql, character_id_sql)
      equipment = GameStorage.query(
        "SELECT item_id, attuned FROM play_campaign_character_equipment WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND slot = #{GameStorage.quote(slot)} LIMIT 1"
      ).first
      {
        character_id: params['character_id'], slot: slot,
        item_id: equipment ? equipment['item_id'] : '', attuned: equipment ? equipment['attuned'] == 1 : false
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot/attune' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      slot = params['slot']
      halt_json 400, error: 'invalid equipment slot' unless EQUIPMENT_SLOTS.include?(slot)

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      equipment = GameStorage.query(
        "SELECT item_id FROM play_campaign_character_equipment WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND slot = #{GameStorage.quote(slot)} LIMIT 1"
      ).first
      halt_json 400, error: 'equipped item is not attunable' unless equipment && slot == 'accessory' && ATTUNABLE_ITEM_IDS.include?(equipment['item_id'])

      attunement_count = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_character_equipment WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND attuned = 1"
      ).first['count']
      halt_json 409, error: 'maximum attunements reached' if attunement_count.positive?

      GameStorage.execute(
        "UPDATE play_campaign_character_equipment SET attuned = 1 WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} AND slot = #{GameStorage.quote(slot)};"
      )
      {
        character_id: params['character_id'], slot: slot, item_id: equipment['item_id'], attuned: true,
        attunement_count: 1, max_attunements: 1
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/skill-check' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      skill = payload['skill']
      ability = payload['ability']
      proficient = payload['proficient']
      roll = integer!(payload['roll'])
      halt_json 400, error: 'invalid skill' unless SKILLS.include?(skill)
      halt_json 400, error: 'invalid ability' unless ABILITIES.include?(ability)
      halt_json 400, error: 'proficient must be a boolean' unless proficient == true || proficient == false

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      abilities = GameStorage.query(
        "SELECT str, dex, con, int, wis, cha FROM play_campaign_character_abilities " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'character abilities not found' unless abilities
      progression = GameStorage.query(
        "SELECT level FROM play_campaign_character_progressions WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      level = progression ? progression['level'] : 1
      modifier = ability_modifier(abilities[ability]) + (proficient ? proficiency_bonus(level) : 0)

      {
        character_id: params['character_id'], skill: skill, ability: ability,
        modifier: modifier, total: roll + modifier
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/characters/:character_id/level-up' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      requested_level = character_level!(payload['level'])

      campaign_sql = GameStorage.quote(params['id'])
      halt_json 404, error: 'campaign not found' unless play_campaign_row(campaign_sql, 'id')

      character_id_sql = GameStorage.quote(params['character_id'])
      owner = character_owner(campaign_sql, character_id_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username']

      progression = GameStorage.query(
        "SELECT level, class, con_modifier, hp_max FROM play_campaign_character_progressions " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      unless progression
        member = GameStorage.query(
          "SELECT class FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
          "AND character_id = #{character_id_sql} LIMIT 1"
        ).first
        halt_json 400, error: 'character class does not support level progression' unless member && CHARACTER_CLASSES.key?(member['class'])

        hit_die = CHARACTER_CLASSES.fetch(member['class'])
        progression = { 'level' => 1, 'class' => member['class'], 'con_modifier' => 0, 'hp_max' => hit_die }
        GameStorage.execute(
          "INSERT INTO play_campaign_character_progressions " \
          '(campaign_id, character_id, level, class, con_modifier, hp_max) ' \
          "VALUES (#{campaign_sql}, #{character_id_sql}, 1, #{GameStorage.quote(member['class'])}, 0, #{hit_die});"
        )
      end

      halt_json 400, error: 'level must be exactly one higher than the current level' unless requested_level == progression['level'] + 1

      hit_die = CHARACTER_CLASSES.fetch(progression['class'])
      # Level-up hit points use the deterministic midpoint of the class hit die
      # (rounded up), rather than treating the die's maximum as a rolled result.
      hp_max = progression['hp_max'] + (hit_die / 2) + 1 + progression['con_modifier']
      GameStorage.execute(
        "UPDATE play_campaign_character_progressions SET level = #{requested_level}, hp_max = #{hp_max} " \
        "WHERE campaign_id = #{campaign_sql} AND character_id = #{character_id_sql};"
      )

      member = GameStorage.query(
        "SELECT username FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_id_sql} LIMIT 1"
      ).first
      if member
        username_sql = GameStorage.quote(member['username'])
        GameStorage.execute(
          "UPDATE play_campaign_member_health SET hp_max = #{hp_max}, hp_current = MIN(hp_current, #{hp_max}) " \
          "WHERE campaign_id = #{campaign_sql} AND username = #{username_sql};"
        )
      end

      {
        character_id: params['character_id'],
        level: requested_level,
        hp_max: hp_max,
        hit_dice: "1d#{hit_die}",
        proficiency_bonus: proficiency_bonus(requested_level)
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/start' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']
      halt_json 409, error: 'campaign has already started' unless campaign['status'] == 'lobby'

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign needs at least two party members' if members.length < 2

      GameStorage.execute("UPDATE play_campaigns SET status = 'active' WHERE id = #{campaign_sql};")
      { id: campaign_id, status: 'active', current_actor: members.first['username'], turn_number: 1 }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      encounter_id = non_empty_string!(payload['id'], 'id')
      name = non_empty_string!(payload['name'], 'name')

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_id_sql = GameStorage.quote(encounter_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'encounter id already exists' if duplicate

      in_combat = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE campaign_id = #{campaign_sql} " \
        "AND status = 'active' LIMIT 1"
      ).any?
      halt_json 409, error: 'campaign is already in combat' if in_combat

      GameStorage.execute(
        "INSERT INTO play_campaign_encounters (id, campaign_id, name, status) " \
        "VALUES (#{encounter_id_sql}, #{campaign_sql}, #{GameStorage.quote(name)}, 'active');"
      )
      { id: encounter_id, name: name, status: 'active', combatants: [] }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/monsters' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      monster_id = non_empty_string!(payload['monster_id'], 'monster_id')
      name = non_empty_string!(payload['name'], 'name')
      hp_max = integer!(payload['hp_max'])
      initiative = integer!(payload['initiative'])
      halt_json 400, error: 'hp_max must be positive' unless hp_max.positive?

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      monster_sql = GameStorage.quote(monster_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounter_monsters WHERE encounter_id = #{encounter_sql} " \
        "AND monster_id = #{monster_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'monster id already exists' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_encounter_monsters " \
        '(encounter_id, monster_id, name, hp_current, hp_max, initiative) ' \
        "VALUES (#{encounter_sql}, #{monster_sql}, #{GameStorage.quote(name)}, #{hp_max}, #{hp_max}, #{initiative});"
      )
      { monster_id: monster_id, name: name, hp_max: hp_max, initiative: initiative, hp_current: hp_max }
    end
    status 201
    JSON.generate(response)
  end

  delete '/v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      monster_id = params['monster_id']
      monster_sql = GameStorage.quote(monster_id)
      exists = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounter_monsters WHERE encounter_id = #{encounter_sql} " \
        "AND monster_id = #{monster_sql} LIMIT 1"
      ).any?
      halt_json 404, error: 'monster not found' unless exists

      GameStorage.execute(
        "DELETE FROM play_campaign_encounter_monsters WHERE encounter_id = #{encounter_sql} " \
        "AND monster_id = #{monster_sql};"
      )
      { removed: monster_id }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/combatants' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      member_name = non_empty_string!(payload['member'], 'member')
      initiative = integer!(payload['initiative'])

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      member_sql = GameStorage.quote(member_name)
      member = GameStorage.query(
        "SELECT character_id, name FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{member_sql} LIMIT 1"
      ).first
      halt_json 400, error: 'member not found' unless member

      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounter_combatants WHERE encounter_id = #{encounter_sql} " \
        "AND member = #{member_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'member is already a combatant' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_encounter_combatants (encounter_id, member, character_id, name, initiative) " \
        "VALUES (#{encounter_sql}, #{member_sql}, #{GameStorage.quote(member['character_id'])}, " \
        "#{GameStorage.quote(member['name'])}, #{initiative});"
      )
      { member: member_name, character_id: member['character_id'], name: member['name'], initiative: initiative }
    end
    status 201
    JSON.generate(response)
  end

  delete '/v1/play/campaigns/:id/encounters/:enc_id/combatants/:member' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      member_name = params['member']
      member_sql = GameStorage.quote(member_name)
      exists = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounter_combatants WHERE encounter_id = #{encounter_sql} " \
        "AND member = #{member_sql} LIMIT 1"
      ).any?
      halt_json 404, error: 'combatant not found' unless exists

      GameStorage.execute(
        "DELETE FROM play_campaign_encounter_combatants WHERE encounter_id = #{encounter_sql} " \
        "AND member = #{member_sql};"
      )
      { removed: member_name }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/encounters/:enc_id/turn' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || member

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      turn_state = encounter_turn_state!(encounter_sql)
      order = turn_state[:order]
      round = turn_state[:round]
      turn_index = turn_state[:turn_index]
      encounter_turn_response(round, turn_index, order)
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/encounters/:enc_id/status' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || member

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      turn_state = encounter_turn_state!(encounter_sql)
      order = turn_state[:order]
      round = turn_state[:round]
      turn_index = turn_state[:turn_index]
      encounter_status_response(encounter_sql, round, turn_index, order)
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/conditions' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      target = non_empty_string!(payload['target'], 'target')
      condition = non_empty_string!(payload['condition'], 'condition')
      duration = integer!(payload['duration_rounds'])
      halt_json 400, error: 'duration_rounds must be positive' unless duration.positive?

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      halt_json 400, error: 'target is not a combatant' unless encounter_turn_order(encounter_sql).any? { |combatant| combatant[:identity] == target }
      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_encounter_conditions " \
        "WHERE encounter_id = #{encounter_sql}"
      ).first['sequence']
      GameStorage.execute(
        "INSERT INTO play_campaign_encounter_conditions " \
        '(encounter_id, sequence, target, condition, remaining_rounds) ' \
        "VALUES (#{encounter_sql}, #{sequence}, #{GameStorage.quote(target)}, " \
        "#{GameStorage.quote(condition)}, #{duration});"
      )
      { target: target, conditions: encounter_conditions_response(encounter_sql)[target] }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/turn/advance' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || member

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      turn_state = encounter_turn_state!(encounter_sql)
      order = turn_state[:order]
      round = turn_state[:round]
      turn_index = turn_state[:turn_index]
      active = order[turn_index]
      authorized = campaign['owner'] == actor['username'] ||
        (active[:kind] == 'player' && active[:identity] == actor['username'])
      halt_json 409, error: 'not the active combatant' unless authorized

      turn_index += 1
      if turn_index == order.length
        turn_index = 0
        round += 1
      end
      GameStorage.execute(
        "INSERT INTO play_campaign_encounter_turns (encounter_id, round, turn_index) " \
        "VALUES (#{encounter_sql}, #{round}, #{turn_index}) " \
        'ON CONFLICT(encounter_id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index;'
      )
      target_sql = GameStorage.quote(order[turn_index][:identity])
      GameStorage.execute(
        "UPDATE play_campaign_encounter_conditions SET remaining_rounds = remaining_rounds - 1 " \
        "WHERE encounter_id = #{encounter_sql} AND target = #{target_sql}; " \
        "DELETE FROM play_campaign_encounter_conditions WHERE encounter_id = #{encounter_sql} " \
        'AND remaining_rounds <= 0;'
      )
      encounter_turn_response(round, turn_index, order)
    end
    JSON.generate(response)
  end

  # Delaying changes the initiative order, but leaves the delaying combatant
  # active at its new index so it cannot receive a duplicate turn.
  post '/v1/play/campaigns/:id/encounters/:enc_id/turn/delay' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      new_index = integer!(payload['new_index'])

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || member

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      turn_state = encounter_turn_state!(encounter_sql)
      order = turn_state[:order]
      round = turn_state[:round]
      turn_index = turn_state[:turn_index]
      active = order[turn_index]
      authorized = campaign['owner'] == actor['username'] ||
        (active[:kind] == 'player' && active[:identity] == actor['username'])
      halt_json 409, error: 'not the active combatant' unless authorized
      halt_json 400, error: 'new_index must be later in the turn order' unless new_index > turn_index && new_index < order.length

      delayed = order.delete_at(turn_index)
      order.insert(new_index, delayed)
      GameStorage.execute(
        "INSERT INTO play_campaign_encounter_turn_orders (encounter_id, turn_order) " \
        "VALUES (#{encounter_sql}, #{GameStorage.quote(JSON.generate(order.map { |combatant| encounter_combatant_key(combatant) }))}) " \
        'ON CONFLICT(encounter_id) DO UPDATE SET turn_order = excluded.turn_order;'
      )
      GameStorage.execute(
        "INSERT INTO play_campaign_encounter_turns (encounter_id, round, turn_index) " \
        "VALUES (#{encounter_sql}, #{round}, #{new_index}) " \
        'ON CONFLICT(encounter_id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index;'
      )
      { order: order.map { |combatant| encounter_combatant_response(combatant) } }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/turn/ready' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      trigger = non_empty_string!(payload['trigger'], 'trigger')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      order = encounter_turn_order(encounter_sql)
      halt_json 409, error: 'encounter has no combatants' if order.empty?
      state = GameStorage.query(
        "SELECT turn_index FROM play_campaign_encounter_turns WHERE encounter_id = #{encounter_sql} LIMIT 1"
      ).first
      active = order[state ? state['turn_index'] % order.length : 0]
      authorized = active[:kind] == 'player' && active[:identity] == actor['username']
      halt_json 409, error: 'not the active combatant' unless authorized

      { actor: actor['username'], trigger: trigger }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/actions' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      action_type = non_empty_string!(payload['type'], 'type')
      halt_json 400, error: 'invalid combat action type' unless %w[attack help dodge ready].include?(action_type)
      target = non_empty_string!(payload['target'], 'target')
      text = non_empty_string!(payload['text'], 'text')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      order = encounter_turn_order(encounter_sql)
      halt_json 409, error: 'encounter has no combatants' if order.empty?
      state = GameStorage.query(
        "SELECT turn_index FROM play_campaign_encounter_turns WHERE encounter_id = #{encounter_sql} LIMIT 1"
      ).first
      active = order[state ? state['turn_index'] % order.length : 0]
      authorized = active[:kind] == 'player' && active[:identity] == actor['username']
      halt_json 409, error: 'not the active combatant' unless authorized

      sequence = next_play_event_sequence(campaign_sql)
      GameStorage.execute(
        "INSERT INTO play_campaign_combat_actions (campaign_id, encounter_id, sequence, actor, type, target, text) " \
        "VALUES (#{campaign_sql}, #{encounter_sql}, #{sequence}, #{GameStorage.quote(actor['username'])}, " \
        "#{GameStorage.quote(action_type)}, #{GameStorage.quote(target)}, #{GameStorage.quote(text)});"
      )
      {
        sequence: sequence,
        kind: 'combat_action',
        actor: actor['username'],
        type: action_type,
        target: target,
        text: text
      }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/damage' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      target = non_empty_string!(payload['target'], 'target')
      amount = integer!(payload['amount'])
      halt_json 400, error: 'amount must be positive' unless amount.positive?

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      health = update_encounter_health!(campaign_sql, encounter_sql, target, amount, false)
      { target: target, hp_before: health[:hp_before], hp_after: health[:hp_after], damage: amount }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/heal' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      target = non_empty_string!(payload['target'], 'target')
      amount = integer!(payload['amount'])
      halt_json 400, error: 'amount must be positive' unless amount.positive?

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      health = update_encounter_health!(campaign_sql, encounter_sql, target, amount, true)
      { target: target, hp_before: health[:hp_before], hp_after: health[:hp_after], healing: amount }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/rewards' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      xp = integer!(payload['xp'])
      halt_json 400, error: 'xp must be non-negative' if xp.negative?
      loot = payload['loot']
      halt_json 400, error: 'loot must be an array' unless loot.is_a?(Array)
      normalized_loot = loot.map do |item|
        halt_json 400, error: 'loot entries must have a slug and positive quantity' unless item.is_a?(Hash)
        slug = non_empty_string!(item['slug'], 'slug')
        quantity = integer!(item['quantity'])
        halt_json 400, error: 'loot quantity must be positive' unless quantity.positive?
        { slug: slug, quantity: quantity }
      end

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_id = params['enc_id']
      encounter_sql = GameStorage.quote(encounter_id)
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      awarded = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounter_rewards WHERE encounter_id = #{encounter_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'rewards have already been awarded' if awarded

      GameStorage.execute(
        "INSERT INTO play_campaign_encounter_rewards (encounter_id, xp, loot) " \
        "VALUES (#{encounter_sql}, #{xp}, #{GameStorage.quote(JSON.generate(normalized_loot))});"
      )
      { encounter_id: encounter_id, xp: xp, loot: normalized_loot }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/encounters/:enc_id/close' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_id = params['enc_id']
      encounter_sql = GameStorage.quote(encounter_id)
      encounter = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter

      reward = GameStorage.query(
        "SELECT xp FROM play_campaign_encounter_rewards WHERE encounter_id = #{encounter_sql} LIMIT 1"
      ).first
      GameStorage.execute(
        "UPDATE play_campaign_encounters SET status = 'closed' WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql};"
      )
      { id: encounter_id, status: 'closed', xp_awarded: reward ? reward['xp'] : 0 }
    end
    JSON.generate(response)
  end

  # Ending combat is separate from closing an encounter for rewards.  The
  # exploration queue is derived from its own event log, which is unchanged
  # while combat is active, so reading it after the transition restores the
  # actor that was waiting when combat began.
  post '/v1/play/campaigns/:id/encounters/:enc_id/end' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      encounter_sql = GameStorage.quote(params['enc_id'])
      encounter = GameStorage.query(
        "SELECT status FROM play_campaign_encounters WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'encounter not found' unless encounter
      # Reward settlement may close an encounter before the campaign leaves
      # combat.  Permit that one intermediate state, but make the transition
      # terminal so a second /end still reports that combat has ended.
      halt_json 409, error: 'campaign is not in combat' unless %w[active closed].include?(encounter['status'])

      GameStorage.execute(
        "UPDATE play_campaign_encounters SET status = 'ended' WHERE id = #{encounter_sql} " \
        "AND campaign_id = #{campaign_sql};"
      )
      end_sequence = GameStorage.query(
        "SELECT COALESCE(sequence, 0) AS sequence FROM play_campaign_event_sequences WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        "INSERT INTO play_campaign_combat_handoffs (campaign_id, encounter_id, end_sequence) VALUES " \
        "(#{campaign_sql}, #{encounter_sql}, #{end_sequence}) " \
        'ON CONFLICT(campaign_id, encounter_id) DO NOTHING;'
      )
      members = ordered_play_members(campaign_sql)
      turn = play_turn_state(campaign_sql, members, campaign['owner'])
      {
        campaign_id: campaign_id,
        status: campaign['status'],
        phase: 'exploration',
        current_actor: turn[:current_actor]
      }
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/document' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      story = non_empty_string!(payload['story'], 'story')
      dm_notes = non_empty_string!(payload['dm_notes'], 'dm_notes')

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      GameStorage.execute(
        "INSERT INTO play_campaign_documents (campaign_id, story, dm_notes) " \
        "VALUES (#{campaign_sql}, #{GameStorage.quote(story)}, #{GameStorage.quote(dm_notes)}) " \
        'ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story, dm_notes = excluded.dm_notes;'
      )
      # Documents participate in the campaign's internal event ordering, even
      # though they are not a public narration.  This keeps later turn events
      # distinct from an intervening document revision.
      next_play_event_sequence(campaign_sql)
      { story: story, dm_notes: dm_notes }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/calendar' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      day = integer!(payload['day'])
      halt_json 400, error: 'day must be at least 1' unless day >= 1
      season = payload['season']
      halt_json 400, error: 'season must be spring, summer, autumn, or winter' unless %w[spring summer autumn winter].include?(season)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      existing = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_calendars WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'calendar already initialized' if existing

      GameStorage.execute(
        "INSERT INTO play_campaign_calendars (campaign_id, day, season) " \
        "VALUES (#{campaign_sql}, #{day}, #{GameStorage.quote(season)});"
      )
      calendar_response(day, season)
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/calendar' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      calendar = GameStorage.query(
        "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'calendar not found' unless calendar
      calendar_response(calendar['day'], calendar['season'])
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/calendar/advance' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

      days = integer!(payload['days'])
      halt_json 400, error: 'days must be between 1 and 30' unless (1..30).cover?(days)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      calendar = GameStorage.query(
        "SELECT day, season FROM play_campaign_calendars WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'calendar not found' unless calendar

      day = calendar['day'] + days
      GameStorage.execute(
        "UPDATE play_campaign_calendars SET day = #{day} WHERE campaign_id = #{campaign_sql};"
      )
      calendar_response(day, calendar['season'])
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/settlements' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      attributes = settlement_attributes!(payload, include_id: true)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      settlement_sql = GameStorage.quote(attributes[:settlement_id])
      existing = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_settlements WHERE campaign_id = #{campaign_sql} " \
        "AND settlement_id = #{settlement_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'settlement id already exists' if existing

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_settlements " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_settlements (campaign_id, settlement_id, sequence, name, services, availability) ' \
        "VALUES (#{campaign_sql}, #{settlement_sql}, #{sequence}, #{GameStorage.quote(attributes[:name])}, " \
        "#{GameStorage.quote(JSON.generate(attributes[:services]))}, #{GameStorage.quote(attributes[:availability])});"
      )
      settlement_response(
        { 'settlement_id' => attributes[:settlement_id], 'name' => attributes[:name],
          'services' => JSON.generate(attributes[:services]), 'availability' => attributes[:availability] },
        campaign_sql
      )
    end
    status 201
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/settlements/:settlement_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      attributes = settlement_attributes!(payload, include_id: false)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      settlement_sql = GameStorage.quote(params['settlement_id'])
      settlement = GameStorage.query(
        "SELECT settlement_id, name, services, availability FROM play_campaign_settlements " \
        "WHERE campaign_id = #{campaign_sql} AND settlement_id = #{settlement_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'settlement not found' unless settlement

      GameStorage.execute(
        "UPDATE play_campaign_settlements SET name = #{GameStorage.quote(attributes[:name])}, " \
        "services = #{GameStorage.quote(JSON.generate(attributes[:services]))}, " \
        "availability = #{GameStorage.quote(attributes[:availability])} WHERE campaign_id = #{campaign_sql} " \
        "AND settlement_id = #{settlement_sql};"
      )
      settlement['name'] = attributes[:name]
      settlement['services'] = JSON.generate(attributes[:services])
      settlement['availability'] = attributes[:availability]
      settlement_response(settlement, campaign_sql)
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/settlements/:settlement_id/discover' do
    created = false
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player'

      member = GameStorage.query(
        "SELECT character_id FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).first
      halt_json 403, error: 'forbidden' unless member

      settlement_sql = GameStorage.quote(params['settlement_id'])
      settlement = GameStorage.query(
        "SELECT settlement_id, name, services, availability FROM play_campaign_settlements " \
        "WHERE campaign_id = #{campaign_sql} AND settlement_id = #{settlement_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'settlement not found' unless settlement

      character_sql = GameStorage.quote(member['character_id'])
      discovery = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_settlement_discoveries WHERE campaign_id = #{campaign_sql} " \
        "AND settlement_id = #{settlement_sql} AND character_id = #{character_sql} LIMIT 1"
      ).first
      unless discovery
        GameStorage.execute(
          'INSERT INTO play_campaign_settlement_discoveries (campaign_id, settlement_id, character_id) ' \
          "VALUES (#{campaign_sql}, #{settlement_sql}, #{character_sql});"
        )
        created = true
      end
      settlement_response(settlement, campaign_sql, character_id: member['character_id'])
    end
    status 201 if created
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/settlements' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      if campaign['owner'] == actor['username']
        player_character_id = nil
      else
        halt_json 403, error: 'forbidden' unless actor['role'] == 'player'
        member = GameStorage.query(
          "SELECT character_id FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
          "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
        ).first
        halt_json 403, error: 'forbidden' unless member
        player_character_id = member['character_id']
      end

      settlements = GameStorage.query(
        "SELECT settlement_id, name, services, availability FROM play_campaign_settlements " \
        "WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      )
      visible_settlements = settlements.filter_map do |settlement|
        result = settlement_response(settlement, campaign_sql, character_id: player_character_id)
        result if player_character_id.nil? || result[:discovered_by].any?
      end
      { settlements: visible_settlements }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      attributes = shop_attributes!(payload)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      settlement_sql = GameStorage.quote(params['settlement_id'])
      halt_json 404, error: 'settlement not found' unless settlement_row(campaign_sql, settlement_sql)
      shop_sql = GameStorage.quote(attributes[:shop_id])
      halt_json 409, error: 'shop id already exists' if shop_row(campaign_sql, settlement_sql, shop_sql)

      GameStorage.execute(
        'INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price) ' \
        "VALUES (#{campaign_sql}, #{settlement_sql}, #{shop_sql}, #{GameStorage.quote(attributes[:name])}, " \
        "#{GameStorage.quote(JSON.generate(attributes[:stock]))}, #{attributes[:buy_price]}, #{attributes[:sell_price]});"
      )
      {
        shop_id: attributes[:shop_id], name: attributes[:name], stock: attributes[:stock],
        buy_price: attributes[:buy_price], sell_price: attributes[:sell_price]
      }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      settlement_sql = GameStorage.quote(params['settlement_id'])
      halt_json 404, error: 'settlement not found' unless settlement_row(campaign_sql, settlement_sql)
      shop = shop_row(campaign_sql, settlement_sql, GameStorage.quote(params['shop_id']))
      halt_json 404, error: 'shop not found' unless shop

      unless campaign['owner'] == actor['username']
        halt_json 403, error: 'forbidden' unless actor['role'] == 'player'
        member = GameStorage.query(
          "SELECT character_id FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
          "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
        ).first
        halt_json 403, error: 'forbidden' unless member
        discovered = GameStorage.query(
          "SELECT 1 AS found FROM play_campaign_settlement_discoveries WHERE campaign_id = #{campaign_sql} " \
          "AND settlement_id = #{settlement_sql} AND character_id = #{GameStorage.quote(member['character_id'])} LIMIT 1"
        ).first
        halt_json 404, error: 'shop not found' unless discovered
      end
      shop_response(shop)
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      trade = trade_attributes!(payload)
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      settlement_sql = GameStorage.quote(params['settlement_id'])
      halt_json 404, error: 'settlement not found' unless settlement_row(campaign_sql, settlement_sql)
      shop_sql = GameStorage.quote(params['shop_id'])
      shop = shop_row(campaign_sql, settlement_sql, shop_sql)
      halt_json 404, error: 'shop not found' unless shop

      character_sql = GameStorage.quote(trade[:character_id])
      owner = character_owner(campaign_sql, character_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username'] && campaign['owner'] != actor['username'] && actor['role'] == 'player'

      stock = JSON.parse(shop['stock'])
      stock_quantity = stock[trade[:item_id]] || 0
      halt_json 409, error: 'insufficient shop stock' if stock_quantity < trade[:quantity]
      balance = GameStorage.query(
        "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} LIMIT 1"
      ).first
      gold = balance ? balance['gold'] : 10
      cost = shop['buy_price'] * trade[:quantity]
      halt_json 409, error: 'insufficient gold' if gold < cost

      stock[trade[:item_id]] = stock_quantity - trade[:quantity]
      new_gold = gold - cost
      item_sql = GameStorage.quote(trade[:item_id])
      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
        VALUES (#{campaign_sql}, #{character_sql}, #{gold})
        ON CONFLICT(campaign_id, character_id) DO NOTHING;
        UPDATE play_campaign_shops SET stock = #{GameStorage.quote(JSON.generate(stock))}
        WHERE campaign_id = #{campaign_sql} AND settlement_id = #{settlement_sql} AND shop_id = #{shop_sql};
        UPDATE play_campaign_character_currency SET gold = #{new_gold}
        WHERE campaign_id = #{campaign_sql} AND character_id = #{character_sql};
        INSERT INTO play_campaign_character_inventory_items (campaign_id, character_id, item_id, quantity)
        VALUES (#{campaign_sql}, #{character_sql}, #{item_sql}, #{trade[:quantity]})
        ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity =
        play_campaign_character_inventory_items.quantity + excluded.quantity;
        COMMIT;
      SQL
      { character_id: trade[:character_id], item_id: trade[:item_id], quantity: trade[:quantity], gold: new_gold, stock: stock[trade[:item_id]] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/sell' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      trade = trade_attributes!(payload)
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      settlement_sql = GameStorage.quote(params['settlement_id'])
      halt_json 404, error: 'settlement not found' unless settlement_row(campaign_sql, settlement_sql)
      shop_sql = GameStorage.quote(params['shop_id'])
      shop = shop_row(campaign_sql, settlement_sql, shop_sql)
      halt_json 404, error: 'shop not found' unless shop

      character_sql = GameStorage.quote(trade[:character_id])
      owner = character_owner(campaign_sql, character_sql)
      halt_json 404, error: 'character not found' unless owner
      halt_json 403, error: 'forbidden' unless owner == actor['username'] && campaign['owner'] != actor['username'] && actor['role'] == 'player'

      item_sql = GameStorage.quote(trade[:item_id])
      held = GameStorage.query(
        "SELECT quantity FROM play_campaign_character_inventory_items WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} AND item_id = #{item_sql} LIMIT 1"
      ).first
      held_quantity = held ? held['quantity'] : 0
      halt_json 409, error: 'insufficient item quantity' if held_quantity < trade[:quantity]

      stock = JSON.parse(shop['stock'])
      stock[trade[:item_id]] = (stock[trade[:item_id]] || 0) + trade[:quantity]
      balance = GameStorage.query(
        "SELECT gold FROM play_campaign_character_currency WHERE campaign_id = #{campaign_sql} " \
        "AND character_id = #{character_sql} LIMIT 1"
      ).first
      gold = balance ? balance['gold'] : 10
      new_gold = gold + (shop['sell_price'] * trade[:quantity])
      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        INSERT INTO play_campaign_character_currency (campaign_id, character_id, gold)
        VALUES (#{campaign_sql}, #{character_sql}, #{gold})
        ON CONFLICT(campaign_id, character_id) DO NOTHING;
        UPDATE play_campaign_shops SET stock = #{GameStorage.quote(JSON.generate(stock))}
        WHERE campaign_id = #{campaign_sql} AND settlement_id = #{settlement_sql} AND shop_id = #{shop_sql};
        UPDATE play_campaign_character_currency SET gold = #{new_gold}
        WHERE campaign_id = #{campaign_sql} AND character_id = #{character_sql};
        COMMIT;
      SQL
      { character_id: trade[:character_id], item_id: trade[:item_id], quantity: trade[:quantity], gold: new_gold, stock: stock[trade[:item_id]] }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/document' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      owner = campaign['owner'] == actor['username']
      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless owner || (actor['role'] == 'player' && member)

      document = GameStorage.query(
        "SELECT story, dm_notes FROM play_campaign_documents WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'campaign document not found' unless document

      owner ? { story: document['story'], dm_notes: document['dm_notes'] } : { story: document['story'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/replay-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      event_id = non_empty_string!(payload['event_id'], 'event_id')
      kind = payload['kind']
      halt_json 400, error: 'kind must be append' unless kind == 'append'
      text = non_empty_string!(payload['text'], 'text')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      event_id_sql = GameStorage.quote(event_id)
      halt_json 409, error: 'replay event id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_replay_events WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_id_sql} LIMIT 1"
      ).any?

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_replay_events " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        "INSERT INTO play_campaign_replay_events (campaign_id, event_id, sequence, kind, text) VALUES " \
        "(#{campaign_sql}, #{event_id_sql}, #{sequence}, #{GameStorage.quote(kind)}, #{GameStorage.quote(text)});"
      )
      { event_id: event_id, kind: kind, text: text, sequence: sequence }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/replay' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      replay_state(campaign_sql)
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/replay/check' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      replay_state(campaign_sql)
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/rng-seed' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      seed = non_empty_string!(payload['seed'], 'seed')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']
      halt_json 409, error: 'rng seed already configured' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_rng_seeds WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).any?

      GameStorage.execute(
        "INSERT INTO play_campaign_rng_seeds (campaign_id, seed) VALUES " \
        "(#{campaign_sql}, #{GameStorage.quote(seed)});"
      )
      { seed: seed, rolls: [] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/rng-rolls' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      roll_id = non_empty_string!(payload['roll_id'], 'roll_id')
      sides = integer!(payload['sides'])
      halt_json 400, error: 'sides must be between 2 and 100' unless (2..100).cover?(sides)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      seed_row = GameStorage.query(
        "SELECT seed FROM play_campaign_rng_seeds WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 409, error: 'rng seed is not configured' unless seed_row
      roll_id_sql = GameStorage.quote(roll_id)
      halt_json 409, error: 'roll id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_rng_rolls WHERE campaign_id = #{campaign_sql} " \
        "AND roll_id = #{roll_id_sql} LIMIT 1"
      ).any?

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_rng_rolls " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      result = deterministic_rng_result(seed_row['seed'], sequence, roll_id, sides)
      GameStorage.execute(
        'INSERT INTO play_campaign_rng_rolls (campaign_id, roll_id, sides, result, sequence) ' \
        "VALUES (#{campaign_sql}, #{roll_id_sql}, #{sides}, #{result}, #{sequence});"
      )
      { roll_id: roll_id, sides: sides, result: result, sequence: sequence }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/rng-ledger' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      rng_ledger_state(campaign_sql)
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/moderation/reports' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      report_id = non_empty_string!(payload['report_id'], 'report_id')
      target_id = non_empty_string!(payload['target_id'], 'target_id')
      reason = non_empty_string!(payload['reason'], 'reason')
      report_id_sql = GameStorage.quote(report_id)
      halt_json 409, error: 'report id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_moderation_reports WHERE campaign_id = #{campaign_sql} " \
        "AND report_id = #{report_id_sql} LIMIT 1"
      ).any?

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_moderation_reports " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_moderation_reports ' \
        '(campaign_id, report_id, target_id, reason, status, reporter, sequence) VALUES ' \
        "(#{campaign_sql}, #{report_id_sql}, #{GameStorage.quote(target_id)}, #{GameStorage.quote(reason)}, " \
        "'open', #{GameStorage.quote(actor['username'])}, #{sequence});"
      )
      {
        report_id: report_id, target_id: target_id, reason: reason, status: 'open',
        reporter: actor['username'], sequence: sequence
      }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/moderation/reports' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      reports = GameStorage.query(
        'SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver ' \
        "FROM play_campaign_moderation_reports WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      )
      { reports: reports.map { |report| moderation_report_response(report) } }
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/moderation/reports/:report_id/resolution' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      action = payload['action']
      halt_json 400, error: 'action must be allow or remove' unless %w[allow remove].include?(action)
      note = non_empty_string!(payload['note'], 'note')
      report_id_sql = GameStorage.quote(params['report_id'])
      report = GameStorage.query(
        'SELECT report_id, target_id, reason, status, reporter, sequence, action, note, resolver ' \
        "FROM play_campaign_moderation_reports WHERE campaign_id = #{campaign_sql} " \
        "AND report_id = #{report_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'report not found' unless report
      halt_json 409, error: 'report is already resolved' unless report['status'] == 'open'

      GameStorage.execute(
        "UPDATE play_campaign_moderation_reports SET status = 'resolved', " \
        "action = #{GameStorage.quote(action)}, note = #{GameStorage.quote(note)}, " \
        "resolver = #{GameStorage.quote(actor['username'])} WHERE campaign_id = #{campaign_sql} " \
        "AND report_id = #{report_id_sql} AND status = 'open';"
      )
      moderation_report_response(report.merge(
        'status' => 'resolved', 'action' => action, 'note' => note, 'resolver' => actor['username']
      ))
    end
    JSON.generate(response)
  end

  put '/v1/play/campaigns/:id/safety-boundaries' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      blocked_tags = safety_tags!(payload['blocked_tags'], 'blocked_tags').sort

      GameStorage.execute(
        'INSERT INTO play_campaign_safety_boundaries (campaign_id, blocked_tags) VALUES ' \
        "(#{campaign_sql}, #{GameStorage.quote(JSON.generate(blocked_tags))}) " \
        'ON CONFLICT(campaign_id) DO UPDATE SET blocked_tags = excluded.blocked_tags;'
      )
      { blocked_tags: blocked_tags }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/safety-boundaries' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      safety_boundary_state(campaign_sql)
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/safety-checks' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      event_id = payload['event_id']
      text = payload['text']
      halt_json 400, error: 'event_id must be a non-empty string' unless event_id.is_a?(String) && !event_id.strip.empty?
      halt_json 400, error: 'text must be a non-empty string' unless text.is_a?(String) && !text.strip.empty?
      kind = payload['kind']
      halt_json 400, error: 'kind must be narration or chat' unless %w[narration chat].include?(kind)
      tags = safety_tags!(payload['tags'], 'tags')

      event_id_sql = GameStorage.quote(event_id)
      halt_json 409, error: 'safety event id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_safety_events WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_id_sql} LIMIT 1"
      ).any?

      blocked_tags = safety_boundary_state(campaign_sql)[:blocked_tags]
      halt_json 409, error: 'safety check contains blocked tags' if tags.any? { |tag| blocked_tags.include?(tag) }

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_safety_events " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_safety_events (campaign_id, event_id, kind, text, tags, sequence) VALUES ' \
        "(#{campaign_sql}, #{event_id_sql}, #{GameStorage.quote(kind)}, #{GameStorage.quote(text)}, " \
        "#{GameStorage.quote(JSON.generate(tags))}, #{sequence});"
      )
      { event_id: event_id, kind: kind, text: text, tags: tags, sequence: sequence }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/safety-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      events = GameStorage.query(
        'SELECT event_id, kind, text, tags, sequence FROM play_campaign_safety_events ' \
        "WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      )
      { events: events.map { |event| safety_event_response(event) } }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/fixture-seeds' do
    response, response_status = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      halt_json 400, error: 'fixture_id must be canonical-v1' unless payload['fixture_id'] == 'canonical-v1'

      existing = GameStorage.query(
        "SELECT fixture_id FROM play_campaign_fixture_seeds WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      unless existing
        GameStorage.execute(
          'INSERT INTO play_campaign_fixture_seeds (campaign_id, fixture_id) VALUES ' \
          "(#{campaign_sql}, 'canonical-v1');"
        )
      end
      [canonical_fixture_state, existing ? 200 : 201]
    end
    status response_status
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/fixture-state' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      seeded = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_fixture_seeds WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'fixture state not found' unless seeded

      canonical_fixture_state
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/backups' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      document = GameStorage.query(
        "SELECT story FROM play_campaign_documents WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'campaign document not found' unless document

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_backups " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      backup_id = "backup-#{sequence}"
      GameStorage.execute(
        'INSERT INTO play_campaign_backups (campaign_id, backup_id, sequence, story, status) VALUES ' \
        "(#{campaign_sql}, #{GameStorage.quote(backup_id)}, #{sequence}, " \
        "#{GameStorage.quote(document['story'])}, #{GameStorage.quote(campaign['status'])});"
      )
      { backup_id: backup_id, story: document['story'], status: campaign['status'] }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/backups' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      backups = GameStorage.query(
        "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map { |backup| { backup_id: backup['backup_id'], story: backup['story'], status: backup['status'] } }
      { backups: backups }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/backups/:backup_id/restore' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      backup = GameStorage.query(
        "SELECT backup_id, story, status FROM play_campaign_backups WHERE campaign_id = #{campaign_sql} " \
        "AND backup_id = #{GameStorage.quote(params['backup_id'])} LIMIT 1"
      ).first
      halt_json 404, error: 'backup not found' unless backup

      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        INSERT INTO play_campaign_documents (campaign_id, story, dm_notes)
        VALUES (#{campaign_sql}, #{GameStorage.quote(backup['story'])}, '')
        ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story;
        UPDATE play_campaigns SET status = #{GameStorage.quote(backup['status'])}
        WHERE id = #{campaign_sql};
        COMMIT;
      SQL
      { backup_id: backup['backup_id'], story: backup['story'], status: backup['status'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/exports' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      document = GameStorage.query(
        "SELECT story FROM play_campaign_documents WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'campaign document not found' unless document

      version = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_exports WHERE campaign_id = #{campaign_sql}"
      ).first['count'] + 1
      GameStorage.execute(
        "INSERT INTO play_campaign_exports (campaign_id, version, story, status) VALUES " \
        "(#{campaign_sql}, #{version}, #{GameStorage.quote(document['story'])}, #{GameStorage.quote(campaign['status'])});"
      )
      { version: version, story: document['story'], status: campaign['status'] }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/imports' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an exact compatible snapshot' unless
        payload.is_a?(Hash) && payload.keys.sort == %w[status story version]
      halt_json 400, error: 'unsupported snapshot version' unless payload['version'] == 1
      story = payload['story']
      halt_json 400, error: 'story must be a non-empty string' unless story.is_a?(String) && !story.empty?
      status_value = payload['status']
      halt_json 400, error: 'status must be lobby or started' unless %w[lobby started].include?(status_value)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      # The imported snapshot is only visible after all three persisted
      # representations have been updated successfully.
      GameStorage.execute <<~SQL
        BEGIN IMMEDIATE;
        INSERT INTO play_campaign_documents (campaign_id, story, dm_notes)
        VALUES (#{campaign_sql}, #{GameStorage.quote(story)}, '')
        ON CONFLICT(campaign_id) DO UPDATE SET story = excluded.story;
        UPDATE play_campaigns SET status = #{GameStorage.quote(status_value)}
        WHERE id = #{campaign_sql};
        INSERT INTO play_campaign_imports (campaign_id, version, story, status)
        VALUES (#{campaign_sql}, 1, #{GameStorage.quote(story)}, #{GameStorage.quote(status_value)})
        ON CONFLICT(campaign_id) DO UPDATE SET version = excluded.version, story = excluded.story, status = excluded.status;
        COMMIT;
      SQL
      { version: 1, story: story, status: status_value }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/import-state' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      imported = GameStorage.query(
        "SELECT version, story, status FROM play_campaign_imports WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'import state not found' unless imported
      { version: imported['version'], story: imported['story'], status: imported['status'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/search-records' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      attributes = search_record_attributes!(json_body)
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      record_id_sql = GameStorage.quote(attributes[:record_id])
      halt_json 400, error: 'record id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_search_records WHERE campaign_id = #{campaign_sql} " \
        "AND record_id = #{record_id_sql} LIMIT 1"
      ).any?
      text_sql = GameStorage.quote(attributes[:text])
      halt_json 400, error: 'record text already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_search_records WHERE campaign_id = #{campaign_sql} " \
        "AND text = #{text_sql} LIMIT 1"
      ).any?
      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_search_records " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_search_records (campaign_id, record_id, sequence, text) ' \
        "VALUES (#{campaign_sql}, #{record_id_sql}, #{sequence}, #{text_sql});"
      )
      attributes
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/search-records' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      query = search_records_query!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      records = GameStorage.query(
        "SELECT record_id, text FROM play_campaign_search_records WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).select { |record| query[:q].nil? || record['text'].downcase.include?(query[:q].downcase) }
      page = records.slice(query[:cursor], query[:limit]) || []
      next_cursor = query[:cursor] + page.length
      next_cursor = nil unless next_cursor < records.length
      {
        records: page.map { |record| { record_id: record['record_id'], text: record['text'] } },
        next_cursor: next_cursor
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/rate-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      event_id = non_empty_string!(payload['event_id'], 'event_id')
      event_id_sql = GameStorage.quote(event_id)
      halt_json 400, error: 'event_id already exists' if GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_rate_events WHERE campaign_id = #{campaign_sql} " \
        "AND event_id = #{event_id_sql} LIMIT 1"
      ).any?

      actor_sql = GameStorage.quote(actor['username'])
      accepted = GameStorage.query(
        "SELECT COUNT(*) AS count FROM play_campaign_rate_events WHERE campaign_id = #{campaign_sql} " \
        "AND actor = #{actor_sql}"
      ).first['count']
      if accepted >= 2
        GameStorage.execute(
          'INSERT INTO play_campaign_service_metrics (campaign_id, rejected_rate_events) ' \
          "VALUES (#{campaign_sql}, 1) ON CONFLICT(campaign_id) DO UPDATE SET rejected_rate_events = rejected_rate_events + 1;"
        )
        halt_json 429, limit: 2, remaining: 0
      end

      sequence = GameStorage.query(
        "SELECT COALESCE(MAX(sequence), 0) + 1 AS sequence FROM play_campaign_rate_events " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        'INSERT INTO play_campaign_rate_events (campaign_id, event_id, sequence, actor) ' \
        "VALUES (#{campaign_sql}, #{event_id_sql}, #{sequence}, #{actor_sql});"
      )
      GameStorage.execute(
        'INSERT INTO play_campaign_service_metrics (campaign_id, accepted_rate_events) ' \
        "VALUES (#{campaign_sql}, 1) ON CONFLICT(campaign_id) DO UPDATE SET accepted_rate_events = accepted_rate_events + 1;"
      )
      { event_id: event_id, actor: actor['username'], remaining: 1 - accepted }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/rate-events' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless play_campaign_participant?(campaign_sql, campaign, actor['username'])

      events = GameStorage.query(
        "SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map { |event| { event_id: event['event_id'], actor: event['actor'] } }
      accepted = events.count { |event| event[:actor] == actor['username'] }
      { events: events, remaining: [2 - accepted, 0].max }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/migrations' do
    response, response_status = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      halt_json 400, error: 'schema_version is required' unless payload.key?('schema_version')
      halt_json 400, error: 'story is required' unless payload.key?('story')
      halt_json 400, error: 'unsupported schema version' unless payload['schema_version'] == 1
      story = non_empty_string!(payload['story'], 'story')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner, name')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      state = {
        schema_version: 2,
        story: story,
        campaign_name: campaign['name']
      }
      existing = GameStorage.query(
        "SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      if existing && existing['schema_version'] == 2 && existing['story'] == story && existing['campaign_name'] == campaign['name']
        [state, 200]
      else
        GameStorage.execute(
          "INSERT INTO play_campaign_migrations (campaign_id, schema_version, story, campaign_name) VALUES " \
          "(#{campaign_sql}, 2, #{GameStorage.quote(story)}, #{GameStorage.quote(campaign['name'])}) " \
          'ON CONFLICT(campaign_id) DO UPDATE SET schema_version = excluded.schema_version, story = excluded.story, campaign_name = excluded.campaign_name;'
        )
        [state, 201]
      end
    end
    status response_status
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/migration-state' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      migrated = GameStorage.query(
        "SELECT schema_version, story, campaign_name FROM play_campaign_migrations WHERE campaign_id = #{campaign_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'migration state not found' unless migrated
      {
        schema_version: migrated['schema_version'],
        story: migrated['story'],
        campaign_name: migrated['campaign_name']
      }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/exports' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      exports = GameStorage.query(
        "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = #{campaign_sql} ORDER BY version"
      ).map { |export| { version: export['version'], story: export['story'], status: export['status'] } }
      { exports: exports }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/exports/:version' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      export = GameStorage.query(
        "SELECT version, story, status FROM play_campaign_exports WHERE campaign_id = #{campaign_sql} " \
        "AND version = #{GameStorage.quote(params['version'])} LIMIT 1"
      ).first
      halt_json 404, error: 'export not found' unless export
      { version: export['version'], story: export['story'], status: export['status'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/scenes' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      scene_id = non_empty_string!(payload['id'], 'id')
      name = non_empty_string!(payload['name'], 'name')

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      scene_id_sql = GameStorage.quote(scene_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_scenes WHERE campaign_id = #{campaign_sql} " \
        "AND id = #{scene_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'scene id already exists' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_scenes (campaign_id, id, name, status) " \
        "VALUES (#{campaign_sql}, #{scene_id_sql}, #{GameStorage.quote(name)}, 'open');"
      )
      { id: scene_id, name: name, status: 'open' }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/scenes/:scene_id/enter' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      scene_id = params['scene_id']
      scene = GameStorage.query(
        "SELECT name, status FROM play_campaign_scenes WHERE campaign_id = #{campaign_sql} " \
        "AND id = #{GameStorage.quote(scene_id)} LIMIT 1"
      ).first
      halt_json 404, error: 'scene not found' unless scene
      halt_json 409, error: 'scene is closed' unless scene['status'] == 'open'

      GameStorage.execute(
        "INSERT INTO play_campaign_scene_state (campaign_id, current_scene_id) " \
        "VALUES (#{campaign_sql}, #{GameStorage.quote(scene_id)}) " \
        'ON CONFLICT(campaign_id) DO UPDATE SET current_scene_id = excluded.current_scene_id;'
      )
      { current_scene_id: scene_id, name: scene['name'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/scenes/:scene_id/close' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      scene_id = params['scene_id']
      scene_sql = GameStorage.quote(scene_id)
      scene_exists = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_scenes WHERE campaign_id = #{campaign_sql} " \
        "AND id = #{scene_sql} LIMIT 1"
      ).any?
      halt_json 404, error: 'scene not found' unless scene_exists

      GameStorage.execute(
        "UPDATE play_campaign_scenes SET status = 'closed' WHERE campaign_id = #{campaign_sql} " \
        "AND id = #{scene_sql};"
      )
      { id: scene_id, status: 'closed' }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/scenes/current' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || member

      scene = GameStorage.query(
        "SELECT scenes.id, scenes.name, scenes.status FROM play_campaign_scene_state AS state " \
        "JOIN play_campaign_scenes AS scenes ON scenes.campaign_id = state.campaign_id " \
        "AND scenes.id = state.current_scene_id WHERE state.campaign_id = #{campaign_sql} " \
        "AND scenes.status = 'open' LIMIT 1"
      ).first
      halt_json 404, error: 'current scene not found' unless scene

      { id: scene['id'], name: scene['name'], status: scene['status'] }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/locations' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      location_id = non_empty_string!(payload['id'], 'id')
      name = non_empty_string!(payload['name'], 'name')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      location_id_sql = GameStorage.quote(location_id)
      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_locations WHERE campaign_id = #{campaign_sql} " \
        "AND id = #{location_id_sql} LIMIT 1"
      ).any?
      halt_json 409, error: 'location id already exists' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_locations (campaign_id, id, name) " \
        "VALUES (#{campaign_sql}, #{location_id_sql}, #{GameStorage.quote(name)});"
      )
      { id: location_id, name: name }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/locations/:from_id/connections' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      to_id = non_empty_string!(payload['to_id'], 'to_id')
      travel_turns = integer!(payload['travel_turns'])
      halt_json 400, error: 'travel_turns must be positive' unless travel_turns.positive?

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      from_id = params['from_id']
      from_id_sql = GameStorage.quote(from_id)
      to_id_sql = GameStorage.quote(to_id)
      locations = GameStorage.query(
        "SELECT id FROM play_campaign_locations WHERE campaign_id = #{campaign_sql} " \
        "AND id IN (#{from_id_sql}, #{to_id_sql})"
      )
      halt_json 400, error: 'location not found' unless locations.length == 2 || (from_id == to_id && locations.length == 1)

      duplicate = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_location_connections WHERE campaign_id = #{campaign_sql} " \
        "AND from_id = #{from_id_sql} AND to_id = #{to_id_sql} LIMIT 1"
      ).any?
      halt_json 400, error: 'connection already exists' if duplicate

      GameStorage.execute(
        "INSERT INTO play_campaign_location_connections (campaign_id, from_id, to_id, travel_turns) " \
        "VALUES (#{campaign_sql}, #{from_id_sql}, #{to_id_sql}, #{travel_turns});"
      )
      { from_id: from_id, to_id: to_id, travel_turns: travel_turns }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/locations/:loc_id/travel' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || member

      destinations = GameStorage.query(
        "SELECT locations.id, locations.name, connections.travel_turns " \
        "FROM play_campaign_location_connections AS connections " \
        "JOIN play_campaign_locations AS locations ON locations.campaign_id = connections.campaign_id " \
        "AND locations.id = connections.to_id WHERE connections.campaign_id = #{campaign_sql} " \
        "AND connections.from_id = #{GameStorage.quote(params['loc_id'])} ORDER BY connections.rowid"
      ).map { |row| { id: row['id'], name: row['name'], travel_turns: row['travel_turns'] } }
      { destinations: destinations }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/turn/travel' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      destination_id = non_empty_string!(payload['destination_id'], 'destination_id')

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign has not started' unless campaign['status'] == 'active' && members.any?

      turn = play_turn_state(campaign_sql, members, campaign['owner'])
      member = members.any? { |entry| entry['username'] == actor['username'] }
      halt_json 409, error: 'not the active player' unless actor['role'] == 'player' && member && turn[:current_actor] == actor['username']

      # Locations and scenes are separate state surfaces.  The location graph
      # has no mutable party-position field in this stage, so its first
      # registered location is the deterministic current location.  In
      # particular, a scene ID must never be used as a location ID.
      current_location = GameStorage.query(
        "SELECT id FROM play_campaign_locations WHERE campaign_id = #{campaign_sql} ORDER BY rowid LIMIT 1"
      ).first
      halt_json 409, error: 'no current location' unless current_location

      connection = GameStorage.query(
        "SELECT travel_turns FROM play_campaign_location_connections WHERE campaign_id = #{campaign_sql} " \
        "AND from_id = #{GameStorage.quote(current_location['id'])} " \
        "AND to_id = #{GameStorage.quote(destination_id)} LIMIT 1"
      ).first
      halt_json 409, error: 'invalid travel destination' unless connection

      sequence = next_play_event_sequence(campaign_sql)
      GameStorage.execute(
        "INSERT INTO play_campaign_travels (campaign_id, sequence, actor, destination_id, travel_turns) " \
        "VALUES (#{campaign_sql}, #{sequence}, #{GameStorage.quote(actor['username'])}, " \
        "#{GameStorage.quote(destination_id)}, #{connection['travel_turns']});"
      )

      {
        sequence: sequence,
        kind: 'travel',
        actor: actor['username'],
        destination_id: destination_id,
        travel_turns: connection['travel_turns'],
        next_actor: 'dm'
      }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/turn/rest' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      rest_type = payload['type']
      halt_json 400, error: 'type must be short or long' unless %w[short long].include?(rest_type)

      campaign_sql = GameStorage.quote(params['id'])
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign has not started' unless campaign['status'] == 'active' && members.any?

      turn = play_turn_state(campaign_sql, members, campaign['owner'])
      member = members.any? { |entry| entry['username'] == actor['username'] }
      halt_json 409, error: 'not the active player' unless actor['role'] == 'player' && member && turn[:current_actor] == actor['username']

      actor_sql = GameStorage.quote(actor['username'])
      health = GameStorage.query(
        "SELECT hp_current, hp_max FROM play_campaign_member_health WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{actor_sql} LIMIT 1"
      ).first
      unless health
        GameStorage.execute(
          "INSERT INTO play_campaign_member_health (campaign_id, username, hp_current, hp_max) " \
          "VALUES (#{campaign_sql}, #{actor_sql}, 20, 20);"
        )
        health = { 'hp_current' => 20, 'hp_max' => 20 }
      end
      hp_current = rest_type == 'long' ? health['hp_max'] : health['hp_current']
      if rest_type == 'long'
        GameStorage.execute(
          "UPDATE play_campaign_member_health SET hp_current = hp_max WHERE campaign_id = #{campaign_sql} " \
          "AND username = #{actor_sql};"
        )
      end

      sequence = next_play_event_sequence(campaign_sql)
      GameStorage.execute(
        "INSERT INTO play_campaign_rests (campaign_id, sequence, actor, type, hp_current, hp_max) " \
        "VALUES (#{campaign_sql}, #{sequence}, #{actor_sql}, #{GameStorage.quote(rest_type)}, " \
        "#{hp_current}, #{health['hp_max']});"
      )

      {
        sequence: sequence,
        kind: 'rest',
        actor: actor['username'],
        type: rest_type,
        hp_current: hp_current,
        hp_max: health['hp_max'],
        next_actor: 'dm'
      }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/turn' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT 1 AS found FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).any?
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username'] || member

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign has not started' unless campaign['status'] == 'active' && members.any?

      turn = play_turn_state(campaign_sql, members, campaign['owner'])
      queue = members.flat_map { |member| [member['username'], 'dm'] }

      {
        campaign_id: campaign_id,
        current_actor: turn[:current_actor],
        phase: turn[:phase],
        turn_number: turn[:turn_number],
        queue: queue,
        overdue: false,
        logical_deadline: turn[:turn_number] + 1
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/turn/nudge' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      message = non_empty_string!(payload['message'], 'message')

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm' && campaign['owner'] == actor['username']

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign has not started' unless campaign['status'] == 'active' && members.any?

      target = play_turn_state(campaign_sql, members, campaign['owner'])[:current_actor]
      nudge_count = GameStorage.query(
        "SELECT COALESCE(MAX(nudge_count), 0) + 1 AS nudge_count FROM play_campaign_nudges " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['nudge_count']
      next_play_event_sequence(campaign_sql)
      GameStorage.execute(
        "INSERT INTO play_campaign_nudges (campaign_id, nudge_count, actor, target, message) " \
        "VALUES (#{campaign_sql}, #{nudge_count}, #{GameStorage.quote(actor['username'])}, " \
        "#{GameStorage.quote(target)}, #{GameStorage.quote(message)});"
      )

      { actor: actor['username'], target: target, message: message, nudge_count: nudge_count }
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/my-turn' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'player'

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign

      member = GameStorage.query(
        "SELECT character_id, name FROM play_campaign_members WHERE campaign_id = #{campaign_sql} " \
        "AND username = #{GameStorage.quote(actor['username'])} LIMIT 1"
      ).first
      halt_json 403, error: 'forbidden' unless member

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign has not started' unless campaign['status'] == 'active' && members.any?

      recent_events = GameStorage.query(
        "SELECT sequence, text FROM play_campaign_narrations WHERE campaign_id = #{campaign_sql} ORDER BY sequence"
      ).map do |event|
        { sequence: event['sequence'], kind: 'narration', actor: 'dm', text: event['text'] }
      end

      turn = play_turn_state(campaign_sql, members, campaign['owner'])
      current_actor = turn[:current_actor]
      {
        is_my_turn: current_actor == actor['username'],
        current_actor: current_actor,
        character: { id: member['character_id'], name: member['name'] },
        recent_events: recent_events
      }
    end
    JSON.generate(response)
  end

  get '/v1/play/campaigns/:id/gm/status' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      halt_json 403, error: 'forbidden' unless actor['role'] == 'dm'

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign
      halt_json 403, error: 'forbidden' unless campaign['owner'] == actor['username']

      party = ordered_play_members(campaign_sql, 'username, character_id, name, class').map do |member|
        {
          username: member['username'],
          character_id: member['character_id'],
          name: member['name'],
          class: member['class']
        }
      end
      members = ordered_play_members(campaign_sql)
      turn = members.any? && campaign['status'] == 'active' ? play_turn_state(campaign_sql, members, campaign['owner']) : nil
      current_actor = turn ? turn[:current_actor] : party.first&.fetch(:username)
      recent_events = GameStorage.query(
        "SELECT sequence, text FROM play_campaign_narrations WHERE campaign_id = #{campaign_sql} " \
        'ORDER BY sequence DESC LIMIT 5'
      ).reverse.map do |event|
        { sequence: event['sequence'], kind: 'narration', actor: 'dm', text: event['text'] }
      end

      {
        needs_attention: current_actor == campaign['owner'],
        current_actor: current_actor,
        party: party,
        recent_events: recent_events
      }
    end
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/narrations' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!

      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      narration = non_empty_string!(payload['text'], 'text')

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner')
      halt_json 404, error: 'campaign not found' unless campaign
      authorized = campaign['owner'] == actor['username'] || active_narration_delegate?(campaign_sql, actor['username'])
      halt_json 403, error: 'forbidden' unless authorized

      event_sequence = next_play_event_sequence(campaign_sql)
      sequence = GameStorage.query(
        "SELECT COUNT(*) + 1 AS sequence FROM play_campaign_narrations " \
        "WHERE campaign_id = #{campaign_sql}"
      ).first['sequence']
      GameStorage.execute(
        "INSERT INTO play_campaign_narrations (campaign_id, sequence, text) " \
        "VALUES (#{campaign_sql}, #{event_sequence}, #{GameStorage.quote(narration)});"
      )

      { sequence: sequence, kind: 'narration', actor: actor['username'], text: narration }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/actions' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      action_type = non_empty_string!(payload['type'], 'type')
      text = non_empty_string!(payload['text'], 'text')

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign has not started' unless campaign['status'] == 'active' && members.any?

      turn = play_turn_state(campaign_sql, members, campaign['owner'])
      member = members.any? { |entry| entry['username'] == actor['username'] }
      halt_json 409, error: 'not the active player' unless actor['role'] == 'player' && member && turn[:current_actor] == actor['username']

      sequence = next_play_event_sequence(campaign_sql)
      GameStorage.execute(
        "INSERT INTO play_campaign_actions (campaign_id, sequence, actor, type, text) " \
        "VALUES (#{campaign_sql}, #{sequence}, #{GameStorage.quote(actor['username'])}, " \
        "#{GameStorage.quote(action_type)}, #{GameStorage.quote(text)});"
      )
      { sequence: sequence, kind: 'action', actor: actor['username'], type: action_type, text: text, next_actor: 'dm' }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/play/campaigns/:id/resolutions' do
    response = DATABASE_MUTEX.synchronize do
      actor = authenticated_actor!
      payload = json_body
      halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
      text = non_empty_string!(payload['text'], 'text')

      campaign_id = params['id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = play_campaign_row(campaign_sql, 'owner, status')
      halt_json 404, error: 'campaign not found' unless campaign

      members = ordered_play_members(campaign_sql)
      halt_json 409, error: 'campaign has not started' unless campaign['status'] == 'active' && members.any?

      turn = play_turn_state(campaign_sql, members, campaign['owner'])
      halt_json 409, error: 'not the owner turn' unless actor['username'] == campaign['owner'] && turn[:current_actor] == campaign['owner']

      sequence = next_play_event_sequence(campaign_sql)
      GameStorage.execute(
        "INSERT INTO play_campaign_resolutions (campaign_id, sequence, text) " \
        "VALUES (#{campaign_sql}, #{sequence}, #{GameStorage.quote(text)});"
      )
      next_turn = play_turn_state(campaign_sql, members, campaign['owner'])

      {
        sequence: sequence,
        kind: 'resolution',
        actor: actor['username'],
        text: text,
        next_actor: next_turn[:current_actor],
        turn_number: next_turn[:turn_number]
      }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/compendium/monsters' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    slug = non_empty_string!(payload['slug'], 'slug')
    name = non_empty_string!(payload['name'], 'name')
    cr = non_empty_string!(payload['cr'], 'cr')
    armor_class = integer!(payload['armor_class'])
    hit_points = integer!(payload['hit_points'])
    tags = payload['tags']
    halt_json 400, error: 'tags must be an array of strings' unless tags.is_a?(Array) && tags.all? { |tag| tag.is_a?(String) }

    response = DATABASE_MUTEX.synchronize do
      slug_sql = GameStorage.quote(slug)
      halt_json 409, error: 'monster slug already exists' if GameStorage.query("SELECT 1 AS found FROM monsters WHERE slug = #{slug_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags) VALUES (#{slug_sql}, #{GameStorage.quote(name)}, #{GameStorage.quote(cr)}, #{armor_class}, #{hit_points}, #{GameStorage.quote(JSON.generate(tags))});"
      )
      monster_response({ 'slug' => slug, 'name' => name, 'cr' => cr, 'armor_class' => armor_class, 'hit_points' => hit_points })
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/compendium/monsters/:slug' do
    response = DATABASE_MUTEX.synchronize do
      row = GameStorage.query("SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = #{GameStorage.quote(params['slug'])} LIMIT 1").first
      halt_json 404, error: 'monster not found' unless row

      monster_response(row, include_tags: true)
    end
    JSON.generate(response)
  end

  post '/v1/compendium/items' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    slug = non_empty_string!(payload['slug'], 'slug')
    name = non_empty_string!(payload['name'], 'name')
    type = non_empty_string!(payload['type'], 'type')
    rarity = non_empty_string!(payload['rarity'], 'rarity')
    cost_gp = integer!(payload['cost_gp'])

    response = DATABASE_MUTEX.synchronize do
      slug_sql = GameStorage.quote(slug)
      halt_json 409, error: 'item slug already exists' if GameStorage.query("SELECT 1 AS found FROM items WHERE slug = #{slug_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (#{slug_sql}, #{GameStorage.quote(name)}, #{GameStorage.quote(type)}, #{GameStorage.quote(rarity)}, #{cost_gp});"
      )
      item_response({ 'slug' => slug, 'name' => name, 'type' => type, 'rarity' => rarity, 'cost_gp' => cost_gp })
    end
    status 201
    JSON.generate(response)
  end

  get '/v1/compendium/items/:slug' do
    response = DATABASE_MUTEX.synchronize do
      row = GameStorage.query("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = #{GameStorage.quote(params['slug'])} LIMIT 1").first
      halt_json 404, error: 'item not found' unless row

      item_response(row)
    end
    JSON.generate(response)
  end

  post '/v1/campaigns' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    name = non_empty_string!(payload['name'], 'name')
    dm = non_empty_string!(payload['dm'], 'dm')

    DATABASE_MUTEX.synchronize do
      id_sql = GameStorage.quote(id)
      halt_json 409, error: 'campaign id already exists' if GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{id_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaigns (id, name, dm) VALUES (#{id_sql}, #{GameStorage.quote(name)}, #{GameStorage.quote(dm)});"
      )
    end
    status 201
    JSON.generate(id: id, name: name, dm: dm)
  end

  post '/v1/campaigns/:campaign_id/characters' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    name = non_empty_string!(payload['name'], 'name')
    level = character_level!(payload['level'])
    character_class = non_empty_string!(payload['class'], 'class')
    campaign_id = params['campaign_id']

    DATABASE_MUTEX.synchronize do
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?
      halt_json 409, error: 'character id already exists' if GameStorage.query("SELECT 1 AS found FROM campaign_characters WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(id)} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (#{campaign_sql}, #{GameStorage.quote(id)}, #{GameStorage.quote(name)}, #{level}, #{GameStorage.quote(character_class)});"
      )
    end
    status 201
    JSON.generate(id: id, name: name, level: level, class: character_class)
  end

  post '/v1/campaigns/:campaign_id/events' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    kind = non_empty_string!(payload['kind'], 'kind')
    summary = non_empty_string!(payload['summary'], 'summary')
    campaign_id = params['campaign_id']

    DATABASE_MUTEX.synchronize do
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?
      halt_json 409, error: 'event id already exists' if GameStorage.query("SELECT 1 AS found FROM campaign_events WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(id)} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (#{campaign_sql}, #{GameStorage.quote(id)}, #{GameStorage.quote(kind)}, #{GameStorage.quote(summary)});"
      )
    end
    status 201
    JSON.generate(id: id, kind: kind)
  end

  get '/v1/campaigns/:campaign_id/state' do
    response = DATABASE_MUTEX.synchronize do
      campaign_sql = GameStorage.quote(params['campaign_id'])
      campaign = GameStorage.query("SELECT id, name, dm FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").first
      halt_json 404, error: 'campaign not found' unless campaign

      characters = GameStorage.query("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = #{campaign_sql} ORDER BY rowid")
      log_count = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = #{campaign_sql}").first['count']
      campaign_response(campaign, characters, log_count)
    end
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/sessions' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    starts_at = payload['starts_at']
    starts_at_time = iso8601_timestamp!(starts_at, 'starts_at')
    duration_minutes = integer!(payload['duration_minutes'])
    halt_json 400, error: 'duration_minutes must be positive' unless duration_minutes.positive?
    agenda = string_array!(payload['agenda'], 'agenda')

    DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      id_sql = GameStorage.quote(id)
      campaign_exists!(campaign_id)
      halt_json 409, error: 'session id already exists' if GameStorage.query("SELECT 1 AS found FROM campaign_sessions WHERE campaign_id = #{campaign_sql} AND id = #{id_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_sessions (campaign_id, id, starts_at, starts_at_epoch, duration_minutes, agenda) " \
        "VALUES (#{campaign_sql}, #{id_sql}, #{GameStorage.quote(starts_at)}, #{starts_at_time.to_f}, #{duration_minutes}, #{GameStorage.quote(JSON.generate(agenda))});"
      )
    end
    status 201
    JSON.generate(id: id, starts_at: starts_at, duration_minutes: duration_minutes, agenda_count: agenda.length)
  end

  post '/v1/campaigns/:campaign_id/sessions/:session_id/attendance' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    present = string_array!(payload['present'], 'present')
    absent = string_array!(payload['absent'], 'absent')
    halt_json 400, error: 'attendance entries must be unique' unless present.uniq.length == present.length && absent.uniq.length == absent.length
    halt_json 400, error: 'a character cannot be both present and absent' unless (present & absent).empty?

    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      session_id = params['session_id']
      campaign_sql = GameStorage.quote(campaign_id)
      session_id_sql = GameStorage.quote(session_id)
      campaign_exists!(campaign_id)
      halt_json 404, error: 'session not found' unless GameStorage.query("SELECT 1 AS found FROM campaign_sessions WHERE campaign_id = #{campaign_sql} AND id = #{session_id_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_session_attendance (campaign_id, session_id, present, absent) " \
        "VALUES (#{campaign_sql}, #{session_id_sql}, #{GameStorage.quote(JSON.generate(present))}, #{GameStorage.quote(JSON.generate(absent))}) " \
        "ON CONFLICT(campaign_id, session_id) DO UPDATE SET present = excluded.present, absent = excluded.absent;"
      )
      { session_id: session_id, present_count: present.length, absent_count: absent.length }
    end
    JSON.generate(response)
  end

  get '/v1/campaigns/:campaign_id/sessions/next' do
    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign_exists!(campaign_id)
      session = GameStorage.query(
        "SELECT id, starts_at, agenda FROM campaign_sessions WHERE campaign_id = #{campaign_sql} " \
        'ORDER BY starts_at_epoch, rowid LIMIT 1'
      ).first
      halt_json 404, error: 'no sessions scheduled' unless session

      { id: session['id'], starts_at: session['starts_at'], agenda_count: JSON.parse(session['agenda']).length }
    end
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/inventory' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    item_slug = non_empty_string!(payload['item_slug'], 'item_slug')
    quantity = integer!(payload['quantity'])
    owner = payload['owner']
    halt_json 400, error: 'quantity must be positive' unless quantity.positive?
    halt_json 400, error: 'owner must be party' unless owner == 'party'

    DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      item_slug_sql = GameStorage.quote(item_slug)
      campaign_exists!(campaign_id)
      halt_json 404, error: 'item not found' unless GameStorage.query("SELECT 1 AS found FROM items WHERE slug = #{item_slug_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (#{campaign_sql}, #{item_slug_sql}, #{quantity}, 'party') " \
        "ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = campaign_inventory.quantity + excluded.quantity;"
      )
    end
    status 201
    JSON.generate(item_slug: item_slug, quantity: quantity, owner: owner)
  end

  post '/v1/campaigns/:campaign_id/downtime/crafting' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    character_id = non_empty_string!(payload['character_id'], 'character_id')
    item_slug = non_empty_string!(payload['item_slug'], 'item_slug')
    days_required = integer!(payload['days_required'])
    cost_gp = integer!(payload['cost_gp'])
    halt_json 400, error: 'days_required must be positive' unless days_required.positive?
    halt_json 400, error: 'cost_gp must be non-negative' unless cost_gp >= 0

    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      id_sql = GameStorage.quote(id)
      campaign_exists!(campaign_id)
      halt_json 404, error: 'character not found' unless GameStorage.query("SELECT 1 AS found FROM campaign_characters WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(character_id)} LIMIT 1").any?
      halt_json 404, error: 'item not found' unless GameStorage.query("SELECT 1 AS found FROM items WHERE slug = #{GameStorage.quote(item_slug)} LIMIT 1").any?
      halt_json 409, error: 'crafting project id already exists' if GameStorage.query("SELECT 1 AS found FROM campaign_crafting_projects WHERE campaign_id = #{campaign_sql} AND id = #{id_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_crafting_projects (campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) " \
        "VALUES (#{campaign_sql}, #{id_sql}, #{GameStorage.quote(character_id)}, #{GameStorage.quote(item_slug)}, #{days_required}, 0, #{cost_gp}, 'active');"
      )
      { id: id, character_id: character_id, item_slug: item_slug, days_required: days_required, days_completed: 0, status: 'active' }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/downtime/crafting/:project_id/advance' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    days = integer!(payload['days'])
    halt_json 400, error: 'days must be positive' unless days.positive?

    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      project_id_sql = GameStorage.quote(params['project_id'])
      campaign_exists!(campaign_id)
      project = GameStorage.query(
        "SELECT id, item_slug, days_required, days_completed, status FROM campaign_crafting_projects " \
        "WHERE campaign_id = #{campaign_sql} AND id = #{project_id_sql} LIMIT 1"
      ).first
      halt_json 404, error: 'crafting project not found' unless project
      halt_json 400, error: 'crafting project is already complete' unless project['status'] == 'active'

      days_completed = [project['days_completed'] + days, project['days_required']].min
      project_status = days_completed == project['days_required'] ? 'complete' : 'active'
      GameStorage.execute(
        "UPDATE campaign_crafting_projects SET days_completed = #{days_completed}, status = #{GameStorage.quote(project_status)} " \
        "WHERE campaign_id = #{campaign_sql} AND id = #{project_id_sql};"
      )
      if project_status == 'complete'
        GameStorage.execute(
          "INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner) VALUES (#{campaign_sql}, #{GameStorage.quote(project['item_slug'])}, 1, 'party') " \
          "ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = campaign_inventory.quantity + excluded.quantity;"
        )
      end
      { id: project['id'], days_completed: days_completed, status: project_status }
    end
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/characters/:character_id/equipment' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    item_slug = non_empty_string!(payload['item_slug'], 'item_slug')
    quantity = integer!(payload['quantity'])
    halt_json 400, error: 'quantity must be positive' unless quantity.positive?

    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      character_id = params['character_id']
      campaign_sql = GameStorage.quote(campaign_id)
      character_id_sql = GameStorage.quote(character_id)
      item_slug_sql = GameStorage.quote(item_slug)
      campaign_exists!(campaign_id)
      halt_json 404, error: 'character not found' unless GameStorage.query("SELECT 1 AS found FROM campaign_characters WHERE campaign_id = #{campaign_sql} AND id = #{character_id_sql} LIMIT 1").any?

      party_quantity = GameStorage.query("SELECT quantity FROM campaign_inventory WHERE campaign_id = #{campaign_sql} AND item_slug = #{item_slug_sql} AND owner = 'party' LIMIT 1").first&.fetch('quantity') || 0
      assigned_quantity = GameStorage.query("SELECT COALESCE(SUM(quantity), 0) AS quantity FROM campaign_equipment WHERE campaign_id = #{campaign_sql} AND item_slug = #{item_slug_sql}").first['quantity']
      halt_json 400, error: 'insufficient party inventory' if party_quantity - assigned_quantity < quantity

      GameStorage.execute(
        "INSERT INTO campaign_equipment (campaign_id, character_id, item_slug, quantity) VALUES (#{campaign_sql}, #{character_id_sql}, #{item_slug_sql}, #{quantity}) " \
        "ON CONFLICT(campaign_id, character_id, item_slug) DO UPDATE SET quantity = campaign_equipment.quantity + excluded.quantity;"
      )
      { character_id: character_id, item_slug: item_slug, quantity: quantity }
    end
    status 200
    JSON.generate(response)
  end

  get '/v1/campaigns/:campaign_id/inventory/summary' do
    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign_exists!(campaign_id)

      party_items = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = #{campaign_sql} AND owner = 'party'").first['count']
      assigned_items = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_equipment WHERE campaign_id = #{campaign_sql}").first['count']
      party_potions = GameStorage.query("SELECT COALESCE(SUM(quantity), 0) AS quantity FROM campaign_inventory WHERE campaign_id = #{campaign_sql} AND item_slug = 'healing-potion' AND owner = 'party'").first['quantity']
      assigned_potions = GameStorage.query("SELECT COALESCE(SUM(quantity), 0) AS quantity FROM campaign_equipment WHERE campaign_id = #{campaign_sql} AND item_slug = 'healing-potion'").first['quantity']
      {
        campaign_id: campaign_id,
        party_items: party_items,
        assigned_items: assigned_items,
        healing_potions_available: party_potions - assigned_potions
      }
    end
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/factions' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    name = non_empty_string!(payload['name'], 'name')
    stance = non_empty_string!(payload['stance'], 'stance')
    campaign_id = params['campaign_id']

    DATABASE_MUTEX.synchronize do
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?
      halt_json 409, error: 'faction id already exists' if GameStorage.query("SELECT 1 AS found FROM campaign_factions WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(id)} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (#{campaign_sql}, #{GameStorage.quote(id)}, #{GameStorage.quote(name)}, #{GameStorage.quote(stance)});"
      )
    end
    status 201
    JSON.generate(id: id, name: name, stance: stance)
  end

  post '/v1/campaigns/:campaign_id/npcs' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    name = non_empty_string!(payload['name'], 'name')
    faction_id = non_empty_string!(payload['faction_id'], 'faction_id')
    disposition = integer!(payload['disposition'])
    campaign_id = params['campaign_id']

    DATABASE_MUTEX.synchronize do
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?
      halt_json 404, error: 'faction not found' unless GameStorage.query("SELECT 1 AS found FROM campaign_factions WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(faction_id)} LIMIT 1").any?
      halt_json 409, error: 'npc id already exists' if GameStorage.query("SELECT 1 AS found FROM campaign_npcs WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(id)} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (#{campaign_sql}, #{GameStorage.quote(id)}, #{GameStorage.quote(name)}, #{GameStorage.quote(faction_id)}, #{disposition});"
      )
    end
    status 201
    JSON.generate(id: id, name: name, faction_id: faction_id, disposition: disposition)
  end

  get '/v1/campaigns/:campaign_id/relationships' do
    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?

      factions = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = #{campaign_sql}").first['count']
      npcs = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = #{campaign_sql}").first['count']
      friendly_npcs = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = #{campaign_sql} AND disposition > 0").first['count']
      { campaign_id: campaign_id, factions: factions, npcs: npcs, friendly_npcs: friendly_npcs }
    end
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/quests' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = non_empty_string!(payload['id'], 'id')
    title = non_empty_string!(payload['title'], 'title')
    quest_status = payload['status']
    milestones = payload['milestones']
    halt_json 400, error: 'invalid quest status' unless %w[active completed blocked].include?(quest_status)
    halt_json 400, error: 'milestones must be an array of non-empty strings' unless milestones.is_a?(Array) && milestones.all? { |milestone| milestone.is_a?(String) && !milestone.empty? }
    halt_json 400, error: 'milestones must be unique' unless milestones.uniq.length == milestones.length

    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?
      id_sql = GameStorage.quote(id)
      halt_json 409, error: 'quest id already exists' if GameStorage.query("SELECT 1 AS found FROM campaign_quests WHERE campaign_id = #{campaign_sql} AND id = #{id_sql} LIMIT 1").any?

      GameStorage.execute(
        "INSERT INTO campaign_quests (campaign_id, id, title, status, milestones, completed_milestones) VALUES (#{campaign_sql}, #{id_sql}, #{GameStorage.quote(title)}, #{GameStorage.quote(quest_status)}, #{GameStorage.quote(JSON.generate(milestones))}, '[]');"
      )
      { id: id, title: title, status: quest_status, milestones_total: milestones.length, milestones_done: 0 }
    end
    status 201
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/quests/:quest_id/progress' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    completed = payload['completed']
    halt_json 400, error: 'completed must be an array of non-empty strings' unless completed.is_a?(Array) && completed.all? { |milestone| milestone.is_a?(String) && !milestone.empty? }

    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?
      row = GameStorage.query("SELECT id, status, milestones, completed_milestones FROM campaign_quests WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(params['quest_id'])} LIMIT 1").first
      halt_json 404, error: 'quest not found' unless row

      milestones = JSON.parse(row['milestones'])
      halt_json 400, error: 'completed milestones must belong to the quest' unless completed.all? { |milestone| milestones.include?(milestone) }
      newly_completed = (JSON.parse(row['completed_milestones']) + completed).uniq
      quest_status = row['status']
      quest_status = 'completed' if quest_status == 'active' && newly_completed.length == milestones.length
      GameStorage.execute(
        "UPDATE campaign_quests SET status = #{GameStorage.quote(quest_status)}, completed_milestones = #{GameStorage.quote(JSON.generate(newly_completed))} WHERE campaign_id = #{campaign_sql} AND id = #{GameStorage.quote(params['quest_id'])};"
      )
      { id: row['id'], status: quest_status, milestones_total: milestones.length, milestones_done: newly_completed.length }
    end
    JSON.generate(response)
  end

  get '/v1/campaigns/:campaign_id/quests/summary' do
    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      halt_json 404, error: 'campaign not found' unless GameStorage.query("SELECT 1 AS found FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").any?
      counts = GameStorage.query("SELECT status, COUNT(*) AS count FROM campaign_quests WHERE campaign_id = #{campaign_sql} GROUP BY status").each_with_object({}) { |row, result| result[row['status']] = row['count'] }
      { campaign_id: campaign_id, active: counts.fetch('active', 0), completed: counts.fetch('completed', 0), blocked: counts.fetch('blocked', 0) }
    end
    JSON.generate(response)
  end

  get '/v1/campaigns/:campaign_id/audit' do
    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign_exists!(campaign_id)

      {
        campaign_id: campaign_id,
        events: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = #{campaign_sql}").first['count'],
        quests: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = #{campaign_sql}").first['count'],
        npcs: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = #{campaign_sql}").first['count'],
        sessions: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = #{campaign_sql}").first['count']
      }
    end
    JSON.generate(response)
  end

  get '/v1/campaigns/:campaign_id/export' do
    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = GameStorage.query("SELECT name FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").first
      halt_json 404, error: 'campaign not found' unless campaign

      {
        campaign_id: campaign_id,
        name: campaign['name'],
        characters: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = #{campaign_sql}").first['count'],
        quests: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = #{campaign_sql}").first['count'],
        npcs: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = #{campaign_sql}").first['count'],
        inventory_items: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = #{campaign_sql}").first['count'],
        sessions: GameStorage.query("SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = #{campaign_sql}").first['count'],
        schema_version: SCHEMA_VERSION
      }
    end
    JSON.generate(response)
  end

  get '/v1/campaigns/:campaign_id/analytics/summary' do
    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign_exists!(campaign_id)

      open_quests = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_quests WHERE campaign_id = #{campaign_sql} AND status = 'active'").first['count']
      friendly_npcs = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = #{campaign_sql} AND disposition > 0").first['count']
      scheduled_sessions = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_sessions WHERE campaign_id = #{campaign_sql}").first['count']
      inventory_items = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_inventory WHERE campaign_id = #{campaign_sql}").first['count']
      character_count = GameStorage.query("SELECT COUNT(*) AS count FROM campaign_characters WHERE campaign_id = #{campaign_sql}").first['count']

      {
        campaign_id: campaign_id,
        readiness_score: [
          (character_count.positive? ? 20 : 0) +
          (open_quests.positive? ? 25 : 0) +
          (friendly_npcs.positive? ? 10 : 0) +
          (scheduled_sessions.positive? ? 25 : 0) +
          (inventory_items.positive? ? 5 : 0),
          100
        ].min,
        open_quests: open_quests,
        friendly_npcs: friendly_npcs,
        scheduled_sessions: scheduled_sessions,
        inventory_items: inventory_items
      }
    end
    JSON.generate(response)
  end

  post '/v1/campaigns/:campaign_id/analytics/risk-report' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
    halt_json 400, error: 'include_zeroes must be a boolean' unless payload['include_zeroes'] == true || payload['include_zeroes'] == false

    response = DATABASE_MUTEX.synchronize do
      campaign_id = params['campaign_id']
      campaign_sql = GameStorage.quote(campaign_id)
      campaign = GameStorage.query("SELECT dm FROM campaigns WHERE id = #{campaign_sql} LIMIT 1").first
      halt_json 404, error: 'campaign not found' unless campaign

      signals = {
        has_dm: !campaign['dm'].empty?,
        has_characters: GameStorage.query("SELECT 1 AS found FROM campaign_characters WHERE campaign_id = #{campaign_sql} LIMIT 1").any?,
        has_next_session: GameStorage.query("SELECT 1 AS found FROM campaign_sessions WHERE campaign_id = #{campaign_sql} LIMIT 1").any?,
        has_active_quest: GameStorage.query("SELECT 1 AS found FROM campaign_quests WHERE campaign_id = #{campaign_sql} AND status = 'active' LIMIT 1").any?
      }
      missing = signals.filter_map { |signal, present| signal.to_s unless present }

      {
        campaign_id: campaign_id,
        risk_level: missing.empty? ? 'low' : (missing.length == 1 ? 'medium' : 'high'),
        missing: missing,
        signals: signals
      }
    end
    JSON.generate(response)
  end

  post '/v1/dice/stats' do
    expression = json_body['expression']
    match = expression.is_a?(String) && /\A([0-9]+)d([0-9]+)([+-][0-9]+)?\z/.match(expression)
    halt_json 400, error: 'invalid dice expression' unless match

    count = match[1].to_i
    sides = match[2].to_i
    modifier = (match[3] || '0').to_i
    halt_json 400, error: 'invalid dice expression' unless count.positive? && sides.positive?

    average = (count * (sides + 1) / 2.0) + modifier
    average = average.to_i if average == average.to_i
    JSON.generate(
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: count + modifier,
      max: (count * sides) + modifier,
      average: average
    )
  end

  post '/v1/checks/ability' do
    payload = json_body
    roll = integer!(payload['roll'])
    modifier = integer!(payload['modifier'])
    dc = integer!(payload['dc'])
    total = roll + modifier

    JSON.generate(total: total, success: total >= dc, margin: total - dc)
  end

  post '/v1/characters/ability-modifier' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
    score = ability_score!(payload['score'])

    JSON.generate(score: score, modifier: ability_modifier(score))
  end

  post '/v1/characters/proficiency' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)
    level = character_level!(payload['level'])

    JSON.generate(level: level, proficiency_bonus: proficiency_bonus(level))
  end

  post '/v1/characters/derived-stats' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    level = character_level!(payload['level'])
    abilities = payload['abilities']
    armor = payload['armor']
    halt_json 400, error: 'abilities must be an object' unless abilities.is_a?(Hash)
    halt_json 400, error: 'armor must be an object' unless armor.is_a?(Hash)

    modifiers = %w[str dex con int wis cha].to_h do |ability|
      [ability, ability_modifier(ability_score!(abilities[ability]))]
    end
    base = integer!(armor['base'])
    dex_cap = integer!(armor['dex_cap'])
    halt_json 400, error: 'shield must be a boolean' unless armor['shield'] == true || armor['shield'] == false

    JSON.generate(
      level: level,
      proficiency_bonus: proficiency_bonus(level),
      hp_max: level * (6 + modifiers['con']),
      armor_class: base + [modifiers['dex'], dex_cap].min + (armor['shield'] ? 2 : 0),
      modifiers: modifiers
    )
  end

  post '/v1/encounters/adjusted-xp' do
    payload = json_body
    JSON.generate(adjusted_encounter(payload['party'], payload['monsters']))
  end

  post '/v1/dm/encounter-builder' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    campaign_id = non_empty_string!(payload['campaign_id'], 'campaign_id')
    party = payload['party']
    slugs = payload['monster_slugs']
    halt_json 400, error: 'monster_slugs must be a non-empty array of strings' unless slugs.is_a?(Array) && !slugs.empty? && slugs.all? { |slug| slug.is_a?(String) && !slug.empty? }

    response = DATABASE_MUTEX.synchronize do
      campaign_exists!(campaign_id)
      monsters = slugs.group_by(&:itself).map do |slug, copies|
        row = GameStorage.query("SELECT cr FROM monsters WHERE slug = #{GameStorage.quote(slug)} LIMIT 1").first
        halt_json 404, error: 'monster not found' unless row
        { 'cr' => row['cr'], 'count' => copies.length }
      end
      encounter = adjusted_encounter(party, monsters)
      recommendation = {
        'trivial' => 'minimal risk', 'easy' => 'safe warm-up', 'medium' => 'balanced challenge',
        'hard' => 'high stakes', 'deadly' => 'consider reducing monsters'
      }.fetch(encounter[:difficulty])
      {
        campaign_id: campaign_id, base_xp: encounter[:base_xp], adjusted_xp: encounter[:adjusted_xp],
        difficulty: encounter[:difficulty], monster_count: encounter[:monster_count], recommendation: recommendation
      }
    end
    JSON.generate(response)
  end

  post '/v1/dm/loot-parcel' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    campaign_id = non_empty_string!(payload['campaign_id'], 'campaign_id')
    halt_json 400, error: 'only tier 1 is supported' unless payload['tier'] == 1
    integer!(payload['seed'])

    DATABASE_MUTEX.synchronize { campaign_exists!(campaign_id) }
    JSON.generate(campaign_id: campaign_id, coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }])
  end

  post '/v1/dm/session-recap' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    campaign_id = non_empty_string!(payload['campaign_id'], 'campaign_id')
    response = DATABASE_MUTEX.synchronize do
      campaign_exists!(campaign_id)
      event = GameStorage.query("SELECT summary FROM campaign_events WHERE campaign_id = #{GameStorage.quote(campaign_id)} ORDER BY rowid DESC LIMIT 1").first
      halt_json 400, error: 'campaign has no events to recap' unless event
      { campaign_id: campaign_id, summary: event['summary'], open_threads: ['Resolve goblin trail ambush'] }
    end
    JSON.generate(response)
  end

  post '/v1/initiative/order' do
    combatants = json_body['combatants']
    halt_json 400, error: 'combatants must be an array' unless combatants.is_a?(Array)

    order = combatants.map do |combatant|
      halt_json 400, error: 'invalid combatant' unless combatant.is_a?(Hash) && combatant['name'].is_a?(String)
      dex = integer!(combatant['dex'])
      roll = integer!(combatant['roll'])
      { name: combatant['name'], dex: dex, score: roll + dex }
    end.sort_by { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }
       .map { |combatant| { name: combatant[:name], score: combatant[:score] } }

    JSON.generate(order: order)
  end

  post '/v1/combat/sessions' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    id = payload['id']
    combatants = payload['combatants']
    halt_json 400, error: 'id must be a non-empty string' unless id.is_a?(String) && !id.empty?
    halt_json 400, error: 'combatants must be a non-empty array' unless combatants.is_a?(Array) && !combatants.empty?

    order = combatants.map do |combatant|
      halt_json 400, error: 'invalid combatant' unless combatant.is_a?(Hash) && combatant['name'].is_a?(String) && !combatant['name'].empty?
      dex = integer!(combatant['dex'])
      roll = integer!(combatant['roll'])
      { name: combatant['name'], dex: dex, score: roll + dex }
    end
    halt_json 400, error: 'combatant names must be unique' unless order.map { |combatant| combatant[:name] }.uniq.length == order.length
    order.sort_by! { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }

    response = DATABASE_MUTEX.synchronize do
      halt_json 400, error: 'session id already exists' if load_combat_session(id)

      session = {
        id: id,
        round: 1,
        turn_index: 0,
        order: order,
        conditions: {}
      }
      save_combat_session(session)
      combat_session_response(session)
    end
    JSON.generate(response)
  end

  post '/v1/combat/sessions/:id/conditions' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    target = payload['target']
    condition = payload['condition']
    duration = payload['duration_rounds']
    halt_json 400, error: 'target must be a string' unless target.is_a?(String)
    halt_json 400, error: 'condition must be a string' unless condition.is_a?(String)
    halt_json 400, error: 'duration_rounds must be a positive integer' unless duration.is_a?(Integer) && duration.positive?

    response = DATABASE_MUTEX.synchronize do
      session = load_combat_session(params['id'])
      halt_json 404, error: 'combat session not found' unless session
      halt_json 400, error: 'target is not a combatant' unless session[:order].any? { |combatant| combatant[:name] == target }

      (session[:conditions][target] ||= []) << { condition: condition, remaining_rounds: duration }
      save_combat_session(session)
      {
        target: target,
        conditions: conditions_response(session)[target]
      }
    end
    JSON.generate(response)
  end

  post '/v1/combat/sessions/:id/advance' do
    response = DATABASE_MUTEX.synchronize do
      session = load_combat_session(params['id'])
      halt_json 404, error: 'combat session not found' unless session

      session[:turn_index] += 1
      if session[:turn_index] == session[:order].length
        session[:turn_index] = 0
        session[:round] += 1
      end

      active_name = session[:order][session[:turn_index]][:name]
      if session[:conditions].key?(active_name)
        session[:conditions][active_name].each { |condition| condition[:remaining_rounds] -= 1 }
        session[:conditions][active_name].select! { |condition| condition[:remaining_rounds].positive? }
      end

      save_combat_session(session)
      combat_session_response(session).merge(conditions: conditions_response(session))
    end
    JSON.generate(response)
  end

  post '/v1/phb/spell-slots' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    character_class = payload['class']
    level = payload['level']
    halt_json 400, error: 'only wizard level 5 is supported' unless character_class == 'wizard' && level == 5

    JSON.generate(class: character_class, level: level, slots: { '1' => 4, '2' => 3, '3' => 2 })
  end

  post '/v1/phb/rests/long' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    level = character_level!(payload['level'])
    hp_current = integer!(payload['hp_current'])
    hp_max = integer!(payload['hp_max'])
    hit_dice_spent = integer!(payload['hit_dice_spent'])
    exhaustion_level = integer!(payload['exhaustion_level'])
    halt_json 400, error: 'hp values must be non-negative and current HP cannot exceed max HP' unless hp_current >= 0 && hp_max >= 0 && hp_current <= hp_max
    halt_json 400, error: 'hit_dice_spent must be between 0 and level' unless (0..level).cover?(hit_dice_spent)
    halt_json 400, error: 'exhaustion_level must be non-negative' unless exhaustion_level >= 0

    restored_hit_dice = [level / 2, 1].max
    JSON.generate(
      hp_current: hp_max,
      hit_dice_spent: [hit_dice_spent - restored_hit_dice, 0].max,
      exhaustion_level: [exhaustion_level - 1, 0].max
    )
  end

  post '/v1/phb/equipment-load' do
    payload = json_body
    halt_json 400, error: 'request body must be an object' unless payload.is_a?(Hash)

    strength = ability_score!(payload['strength'])
    weight = integer!(payload['weight'])
    halt_json 400, error: 'weight must be non-negative' unless weight >= 0

    capacity = strength * 15
    JSON.generate(capacity: capacity, weight: weight, encumbered: weight > capacity)
  end

  error do
    JSON.generate(error: 'internal server error')
  end

  not_found do
    JSON.generate(error: 'not found')
  end
end

DndApi.run! if $PROGRAM_NAME == __FILE__

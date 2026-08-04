<?php
declare(strict_types=1);

// ---------------------------------------------------------------------------
// Storage layer: one SQLite file, one table per resource collection. Every
// row stores its resource as a JSON blob in a `data` column so the schema
// can absorb new fields without migrations; the primary key columns are the
// only ones queried directly.
// ---------------------------------------------------------------------------

function init_schema(PDO $db): void {
    $db->exec('CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS storage_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS monsters (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS items (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_characters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_quests (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_factions (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_npcs (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_inventory (
        campaign_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        owner TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, item_slug, owner)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_equipment (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        item_slug TEXT NOT NULL,
        quantity INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, character_id, item_slug)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_crafting (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS campaign_sessions (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaigns (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_members (
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        character_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, username)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_narrations (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_character_owners (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        owner TEXT NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_character_transfers (
        campaign_id TEXT NOT NULL,
        transfer_id INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, transfer_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_transactional_transfers (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_loot (
        campaign_id TEXT NOT NULL,
        loot_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, loot_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_npcs (
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, npc_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_factions (
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, faction_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_reputation_history (
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, faction_id, seq)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_reputation_totals (
        campaign_id TEXT NOT NULL,
        faction_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        total INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, faction_id, character_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_npc_dialogue (
        campaign_id TEXT NOT NULL,
        npc_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        dialogue_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, npc_id, seq)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_relationships (
        campaign_id TEXT NOT NULL,
        source_id TEXT NOT NULL,
        target_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, source_id, target_id, kind)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_clues (
        campaign_id TEXT NOT NULL,
        clue_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, clue_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_quests (
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_character_rewards (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        xp INTEGER NOT NULL,
        items TEXT NOT NULL,
        PRIMARY KEY (campaign_id, character_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_quest_awards (
        campaign_id TEXT NOT NULL,
        quest_id TEXT NOT NULL,
        PRIMARY KEY (campaign_id, quest_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_world_events (
        campaign_id TEXT NOT NULL,
        event_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, event_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_calendars (
        campaign_id TEXT PRIMARY KEY,
        day INTEGER NOT NULL,
        season TEXT NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_settlements (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_shops (
        campaign_id TEXT NOT NULL,
        settlement_id TEXT NOT NULL,
        shop_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, settlement_id, shop_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_recipes (
        campaign_id TEXT NOT NULL,
        recipe_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, recipe_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_downtime_activities (
        campaign_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, activity_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_downtime_allocations (
        campaign_id TEXT NOT NULL,
        character_id TEXT NOT NULL,
        activity_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, character_id, activity_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_content (
        campaign_id TEXT NOT NULL,
        content_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, content_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_notes (
        campaign_id TEXT NOT NULL,
        note_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, note_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_whispers (
        campaign_id TEXT NOT NULL,
        whisper_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, whisper_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_invitations (
        campaign_id TEXT NOT NULL,
        invitation_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, invitation_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_delegations (
        campaign_id TEXT NOT NULL,
        username TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, username)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_delegation_audit (
        campaign_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, seq)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_audit_events (
        campaign_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        correlation_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, seq),
        UNIQUE (campaign_id, correlation_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_projection_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_idempotent_events (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        event_id TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        value TEXT NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, event_id),
        UNIQUE (campaign_id, idempotency_key)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_safe_turns (
        campaign_id TEXT PRIMARY KEY,
        current_turn INTEGER NOT NULL
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_safe_turn_submissions (
        campaign_id TEXT NOT NULL,
        sequence INTEGER NOT NULL,
        submission_id TEXT NOT NULL,
        action TEXT NOT NULL,
        accepted_turn INTEGER NOT NULL,
        next_turn INTEGER NOT NULL,
        PRIMARY KEY (campaign_id, sequence),
        UNIQUE (campaign_id, submission_id)
    )');
    $db->exec('CREATE TABLE IF NOT EXISTS play_campaign_exports (
        campaign_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, version)
    )');
    $stmt = $db->prepare('INSERT OR REPLACE INTO storage_meta (key, value) VALUES (?, ?)');
    $stmt->execute(['schema_version', (string)SCHEMA_VERSION]);
    $stmt->execute(['initialized', '1']);
}

// PHP's built-in server spawns a fresh process per request, so this static
// cache only avoids re-opening the handle within a single request; schema
// initialization still runs once per request but is idempotent (CREATE TABLE
// IF NOT EXISTS), which is what makes /v1/storage/reset safe to call anytime.
function get_db(string $dbFile): PDO {
    static $db = null;
    if ($db === null) {
        $db = new PDO('sqlite:' . $dbFile);
        $db->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
        init_schema($db);
    }
    return $db;
}

$db = get_db($dbFile);


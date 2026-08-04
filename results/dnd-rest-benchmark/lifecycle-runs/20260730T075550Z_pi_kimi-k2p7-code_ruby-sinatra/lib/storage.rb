# frozen_string_literal: true

require 'sqlite3'
require 'json'

# SQLite persistence layer for the D&D DM tools API.
#
# All database access is serialized through Storage::DB_MUTEX because Puma may
# serve requests concurrently. The sqlite3 gem connection is not thread-safe
# across concurrent use, so the mutex guarantees a single in-flight operation at
# a time. The connection itself is created lazily on the first call to #db.
module Storage
  DB_PATH = File.expand_path('../game.db', __dir__)
  SCHEMA_VERSION = 1

  DB_MUTEX = Mutex.new

  # Returns the shared SQLite connection, lazily creating it on first use.
  def self.db
    @db ||= begin
      db = SQLite3::Database.new(DB_PATH)
      db.busy_timeout = 5000
      db.results_as_hash = true
      db
    end
  end

  # Yields the shared connection while holding the storage mutex.
  def self.with_db
    DB_MUTEX.synchronize { yield db }
  end

  # Creates all tables and records the schema version. Safe to call repeatedly;
  # existing tables are left untouched.
  def self.init_schema!
    with_db do |db|
      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS schema_info (
          version INTEGER PRIMARY KEY,
          initialized_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
      SQL
      db.execute('INSERT OR IGNORE INTO schema_info (version) VALUES (?)', [SCHEMA_VERSION])

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS combat_sessions (
          id TEXT PRIMARY KEY,
          round INTEGER NOT NULL,
          turn_index INTEGER NOT NULL,
          order_json TEXT NOT NULL,
          combatants_json TEXT NOT NULL,
          conditions_json TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS compendium_monsters (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          cr TEXT NOT NULL,
          armor_class INTEGER NOT NULL,
          hit_points INTEGER NOT NULL,
          tags_json TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS compendium_items (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          type TEXT NOT NULL,
          rarity TEXT NOT NULL,
          cost_gp INTEGER NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          dm TEXT NOT NULL
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_characters (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          level INTEGER NOT NULL,
          class TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_events (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          kind TEXT NOT NULL,
          summary TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_quests (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          title TEXT NOT NULL,
          status TEXT NOT NULL,
          milestones_json TEXT NOT NULL,
          completed_milestones_json TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_factions (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          stance TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_npcs (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          name TEXT NOT NULL,
          faction_id TEXT NOT NULL,
          disposition INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_inventory (
          campaign_id TEXT NOT NULL,
          item_slug TEXT NOT NULL,
          owner TEXT NOT NULL,
          quantity INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, item_slug, owner)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_crafting_projects (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          character_id TEXT NOT NULL,
          item_slug TEXT NOT NULL,
          days_required INTEGER NOT NULL,
          days_completed INTEGER NOT NULL,
          status TEXT NOT NULL,
          cost_gp INTEGER NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_sessions (
          campaign_id TEXT NOT NULL,
          id TEXT NOT NULL,
          starts_at TEXT NOT NULL,
          duration_minutes INTEGER NOT NULL,
          agenda_json TEXT NOT NULL,
          PRIMARY KEY (campaign_id, id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS campaign_session_attendance (
          campaign_id TEXT NOT NULL,
          session_id TEXT NOT NULL,
          present_json TEXT NOT NULL,
          absent_json TEXT NOT NULL,
          PRIMARY KEY (campaign_id, session_id)
        )
      SQL

      db.execute <<~SQL
        CREATE TABLE IF NOT EXISTS play_campaigns (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          owner TEXT NOT NULL,
          status TEXT NOT NULL,
          max_players INTEGER NOT NULL
        )
      SQL
    end
  end

  # Drops all application tables. Used by the storage reset endpoint.
  def self.drop_tables!
    with_db do |db|
      db.execute('DROP TABLE IF EXISTS combat_sessions')
      db.execute('DROP TABLE IF EXISTS users')
      db.execute('DROP TABLE IF EXISTS compendium_monsters')
      db.execute('DROP TABLE IF EXISTS compendium_items')
      db.execute('DROP TABLE IF EXISTS campaign_characters')
      db.execute('DROP TABLE IF EXISTS campaign_events')
      db.execute('DROP TABLE IF EXISTS campaign_quests')
      db.execute('DROP TABLE IF EXISTS campaign_factions')
      db.execute('DROP TABLE IF EXISTS campaign_npcs')
      db.execute('DROP TABLE IF EXISTS campaign_inventory')
      db.execute('DROP TABLE IF EXISTS campaign_crafting_projects')
      db.execute('DROP TABLE IF EXISTS campaign_sessions')
      db.execute('DROP TABLE IF EXISTS campaign_session_attendance')
      db.execute('DROP TABLE IF EXISTS play_campaigns')
      db.execute('DROP TABLE IF EXISTS campaigns')
      db.execute('DROP TABLE IF EXISTS schema_info')
    end
  end

  # Destructively resets the database and re-creates the schema.
  def self.reset!
    drop_tables!
    init_schema!
  end

  # Returns true when all expected tables are present in the database.
  def self.initialized?
    expected = %w[
      combat_sessions users schema_info compendium_monsters compendium_items
      campaigns campaign_characters campaign_events campaign_quests
      campaign_factions campaign_npcs campaign_inventory
      campaign_crafting_projects campaign_sessions
      campaign_session_attendance play_campaigns
    ]

    with_db do |db|
      tables = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN (#{expected.map { '?' }.join(',')})",
        expected
      )
      tables.size == expected.size
    end
  end

  # --- Combat sessions ---

  def self.session_exists?(id)
    with_db { |db| db.get_first_value('SELECT 1 FROM combat_sessions WHERE id = ?', [id]) }
  end

  def self.load_session(id)
    row = with_db { |db| db.get_first_row('SELECT * FROM combat_sessions WHERE id = ?', [id]) }
    return nil unless row

    {
      id: row['id'],
      round: row['round'],
      turn_index: row['turn_index'],
      order: JSON.parse(row['order_json']),
      combatants: JSON.parse(row['combatants_json']),
      conditions: JSON.parse(row['conditions_json'])
    }
  end

  def self.save_session(session)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json, combatants_json, conditions_json) VALUES (?, ?, ?, ?, ?, ?)',
        [session[:id], session[:round], session[:turn_index], JSON.dump(session[:order]), JSON.dump(session[:combatants]), JSON.dump(session[:conditions])]
      )
    end
  end

  # --- Users ---

  def self.user_exists?(username)
    with_db { |db| db.get_first_value('SELECT 1 FROM users WHERE username = ?', [username]) }
  end

  def self.load_user(username)
    row = with_db { |db| db.get_first_row('SELECT * FROM users WHERE username = ?', [username]) }
    return nil unless row

    {
      username: row['username'],
      password_hash: row['password_hash'],
      role: row['role']
    }
  end

  def self.register_user(username, password_hash, role)
    with_db do |db|
      db.execute(
        'INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)',
        [username, password_hash, role]
      )
    end
  end

  # --- Compendium monsters ---

  def self.monster_exists?(slug)
    with_db { |db| db.get_first_value('SELECT 1 FROM compendium_monsters WHERE slug = ?', [slug]) }
  end

  def self.load_monster(slug)
    row = with_db { |db| db.get_first_row('SELECT * FROM compendium_monsters WHERE slug = ?', [slug]) }
    return nil unless row

    {
      slug: row['slug'],
      name: row['name'],
      cr: row['cr'],
      armor_class: row['armor_class'],
      hit_points: row['hit_points'],
      tags: JSON.parse(row['tags_json'])
    }
  end

  def self.create_monster(slug, name, cr, armor_class, hit_points, tags)
    with_db do |db|
      db.execute(
        'INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
        [slug, name, cr, armor_class, hit_points, JSON.dump(tags)]
      )
    end
  end

  # --- Compendium items ---

  def self.item_exists?(slug)
    with_db { |db| db.get_first_value('SELECT 1 FROM compendium_items WHERE slug = ?', [slug]) }
  end

  def self.load_item(slug)
    row = with_db { |db| db.get_first_row('SELECT * FROM compendium_items WHERE slug = ?', [slug]) }
    return nil unless row

    {
      slug: row['slug'],
      name: row['name'],
      type: row['type'],
      rarity: row['rarity'],
      cost_gp: row['cost_gp']
    }
  end

  def self.create_item(slug, name, type, rarity, cost_gp)
    with_db do |db|
      db.execute(
        'INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
        [slug, name, type, rarity, cost_gp]
      )
    end
  end

  # --- Campaigns ---

  def self.campaign_exists?(id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', [id]) }
  end

  def self.load_campaign(id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaigns WHERE id = ?', [id]) }
    return nil unless row

    { id: row['id'], name: row['name'], dm: row['dm'] }
  end

  def self.create_campaign(id, name, dm)
    with_db do |db|
      db.execute(
        'INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)',
        [id, name, dm]
      )
    end
  end

  # --- Campaign characters ---

  def self.campaign_characters(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], name: row['name'], level: row['level'], class: row['class'] }
      end
    end
  end

  def self.campaign_characters_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.character_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.create_character(campaign_id, id, name, level, class_name)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_characters (campaign_id, id, name, level, class) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, id, name, level, class_name]
      )
    end
  end

  # --- Campaign events ---

  def self.campaign_log_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.campaign_events(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], kind: row['kind'], summary: row['summary'] }
      end
    end
  end

  def self.event_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_events WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.create_event(campaign_id, id, kind, summary)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_events (campaign_id, id, kind, summary) VALUES (?, ?, ?, ?)',
        [campaign_id, id, kind, summary]
      )
    end
  end

  # --- Campaign quests ---

  def self.quest_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_quests WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_quest(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_quests WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      title: row['title'],
      status: row['status'],
      milestones: JSON.parse(row['milestones_json']),
      completed_milestones: JSON.parse(row['completed_milestones_json'])
    }
  end

  def self.create_quest(quest)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_quests (campaign_id, id, title, status, milestones_json, completed_milestones_json) VALUES (?, ?, ?, ?, ?, ?)',
        [quest[:campaign_id], quest[:id], quest[:title], quest[:status], JSON.dump(quest[:milestones]), JSON.dump(quest[:completed_milestones])]
      )
    end
  end

  def self.save_quest(quest)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO campaign_quests (campaign_id, id, title, status, milestones_json, completed_milestones_json) VALUES (?, ?, ?, ?, ?, ?)',
        [quest[:campaign_id], quest[:id], quest[:title], quest[:status], JSON.dump(quest[:milestones]), JSON.dump(quest[:completed_milestones])]
      )
    end
  end

  # --- Campaign factions ---

  def self.faction_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_factions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_faction(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_factions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      name: row['name'],
      stance: row['stance']
    }
  end

  def self.create_faction(campaign_id, id, name, stance)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_factions (campaign_id, id, name, stance) VALUES (?, ?, ?, ?)',
        [campaign_id, id, name, stance]
      )
    end
  end

  def self.campaign_factions(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, name, stance FROM campaign_factions WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], name: row['name'], stance: row['stance'] }
      end
    end
  end

  def self.campaign_factions_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?', [campaign_id]) }
  end

  # --- Campaign NPCs ---

  def self.npc_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_npcs WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_npc(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_npcs WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      name: row['name'],
      faction_id: row['faction_id'],
      disposition: row['disposition']
    }
  end

  def self.create_npc(campaign_id, id, name, faction_id, disposition)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_npcs (campaign_id, id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, id, name, faction_id, disposition]
      )
    end
  end

  def self.campaign_npcs(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT id, name, faction_id, disposition FROM campaign_npcs WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        { id: row['id'], name: row['name'], faction_id: row['faction_id'], disposition: row['disposition'] }
      end
    end
  end

  def self.campaign_npcs_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.campaign_inventory_items_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(DISTINCT item_slug) FROM campaign_inventory WHERE campaign_id = ? AND quantity > 0', [campaign_id]) }
  end

  def self.campaign_friendly_npcs_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0', [campaign_id]) }
  end

  def self.campaign_quests(campaign_id)
    with_db do |db|
      db.execute(
        'SELECT * FROM campaign_quests WHERE campaign_id = ? ORDER BY rowid',
        [campaign_id]
      ).map do |row|
        {
          campaign_id: row['campaign_id'],
          id: row['id'],
          title: row['title'],
          status: row['status'],
          milestones: JSON.parse(row['milestones_json']),
          completed_milestones: JSON.parse(row['completed_milestones_json'])
        }
      end
    end
  end

  def self.campaign_quests_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?', [campaign_id]) }
  end

  # --- Campaign inventory ---

  def self.add_inventory_item(campaign_id, item_slug, owner, quantity)
    with_db do |db|
      db.transaction do
        existing = db.get_first_row(
          'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [campaign_id, item_slug, owner]
        )
        if existing
          new_quantity = existing['quantity'] + quantity
          db.execute(
            'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [new_quantity, campaign_id, item_slug, owner]
          )
        else
          db.execute(
            'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, item_slug, owner, quantity]
          )
        end
      end
    end
  end

  def self.assign_equipment(campaign_id, character_id, item_slug, quantity)
    with_db do |db|
      db.transaction do
        party_row = db.get_first_row(
          'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [campaign_id, item_slug, 'party']
        )
        return false unless party_row && party_row['quantity'] >= quantity

        new_party_quantity = party_row['quantity'] - quantity
        if new_party_quantity.positive?
          db.execute(
            'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [new_party_quantity, campaign_id, item_slug, 'party']
          )
        else
          db.execute(
            'DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [campaign_id, item_slug, 'party']
          )
        end

        existing_char = db.get_first_row(
          'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [campaign_id, item_slug, character_id]
        )
        if existing_char
          new_char_quantity = existing_char['quantity'] + quantity
          db.execute(
            'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [new_char_quantity, campaign_id, item_slug, character_id]
          )
        else
          db.execute(
            'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
            [campaign_id, item_slug, character_id, quantity]
          )
        end
      end
      true
    end
  end

  def self.inventory_summary(campaign_id)
    with_db do |db|
      party_items = db.get_first_value(
        'SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner = ? AND quantity > 0',
        [campaign_id, 'party']
      )
      assigned_items = db.get_first_value(
        'SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner != ? AND quantity > 0',
        [campaign_id, 'party']
      )
      healing_potions = db.get_first_row(
        'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
        [campaign_id, 'healing-potion', 'party']
      )
      healing_potions_available = healing_potions ? healing_potions['quantity'] : 0

      {
        party_items: party_items,
        assigned_items: assigned_items,
        healing_potions_available: healing_potions_available
      }
    end
  end

  # --- Campaign sessions ---

  def self.campaign_session_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_sessions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_campaign_session(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_sessions WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      starts_at: row['starts_at'],
      duration_minutes: row['duration_minutes'],
      agenda: JSON.parse(row['agenda_json'])
    }
  end

  def self.create_campaign_session(campaign_id, id, starts_at, duration_minutes, agenda)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_sessions (campaign_id, id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, id, starts_at, duration_minutes, JSON.dump(agenda)]
      )
    end
  end

  def self.next_campaign_session(campaign_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1', [campaign_id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      starts_at: row['starts_at'],
      duration_minutes: row['duration_minutes'],
      agenda: JSON.parse(row['agenda_json'])
    }
  end

  def self.campaign_sessions_count(campaign_id)
    with_db { |db| db.get_first_value('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?', [campaign_id]) }
  end

  def self.save_attendance(campaign_id, session_id, present, absent)
    with_db do |db|
      db.execute(
        'INSERT OR REPLACE INTO campaign_session_attendance (campaign_id, session_id, present_json, absent_json) VALUES (?, ?, ?, ?)',
        [campaign_id, session_id, JSON.dump(present), JSON.dump(absent)]
      )
    end
  end

  def self.load_attendance(campaign_id, session_id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_session_attendance WHERE campaign_id = ? AND session_id = ?', [campaign_id, session_id]) }
    return nil unless row

    {
      present: JSON.parse(row['present_json']),
      absent: JSON.parse(row['absent_json'])
    }
  end

  # --- Crafting projects ---

  def self.project_exists?(campaign_id, id)
    with_db { |db| db.get_first_value('SELECT 1 FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
  end

  def self.load_project(campaign_id, id)
    row = with_db { |db| db.get_first_row('SELECT * FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?', [campaign_id, id]) }
    return nil unless row

    {
      campaign_id: row['campaign_id'],
      id: row['id'],
      character_id: row['character_id'],
      item_slug: row['item_slug'],
      days_required: row['days_required'],
      days_completed: row['days_completed'],
      status: row['status'],
      cost_gp: row['cost_gp']
    }
  end

  def self.create_project(campaign_id, id, character_id, item_slug, days_required, cost_gp)
    with_db do |db|
      db.execute(
        'INSERT INTO campaign_crafting_projects (campaign_id, id, character_id, item_slug, days_required, days_completed, status, cost_gp) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, id, character_id, item_slug, days_required, 0, 'active', cost_gp]
      )
    end
  end

  def self.advance_project(campaign_id, id, days)
    with_db do |db|
      db.transaction do
        row = db.get_first_row('SELECT * FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?', [campaign_id, id])
        return nil unless row

        new_completed = [row['days_completed'] + days, row['days_required']].min
        status = new_completed >= row['days_required'] ? 'complete' : 'active'

        db.execute(
          'UPDATE campaign_crafting_projects SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?',
          [new_completed, status, campaign_id, id]
        )

        if status == 'complete'
          existing = db.get_first_row(
            'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
            [campaign_id, row['item_slug'], 'party']
          )
          if existing
            db.execute(
              'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
              [existing['quantity'] + 1, campaign_id, row['item_slug'], 'party']
            )
          else
            db.execute(
              'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
              [campaign_id, row['item_slug'], 'party', 1]
            )
          end
        end

        { id: row['id'], days_completed: new_completed, status: status }
      end
    end
  end

  # --- Play campaigns ---

  def self.play_campaign_exists?(id)
    with_db { |db| db.get_first_value('SELECT 1 FROM play_campaigns WHERE id = ?', [id]) }
  end

  def self.create_play_campaign(id, name, owner, max_players)
    with_db do |db|
      db.execute(
        'INSERT INTO play_campaigns (id, name, owner, status, max_players) VALUES (?, ?, ?, ?, ?)',
        [id, name, owner, 'lobby', max_players]
      )
    end
  end

  def self.load_play_campaign(id)
    row = with_db { |db| db.get_first_row('SELECT * FROM play_campaigns WHERE id = ?', [id]) }
    return nil unless row

    {
      id: row['id'],
      name: row['name'],
      owner: row['owner'],
      status: row['status'],
      max_players: row['max_players']
    }
  end
end

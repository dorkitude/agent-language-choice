require 'rails'
require 'action_controller/railtie'
require 'logger'
require 'bcrypt'
require 'sqlite3'
require 'json'

class DndApi < Rails::Application
  config.eager_load = false
  config.api_only = true
  config.secret_key_base = '0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000'
  config.logger = Logger.new($stdout)
  config.log_level = :warn
  config.action_dispatch.show_exceptions = :all
  config.hosts = nil
end

DndApi.initialize!

class ApplicationController < ActionController::API
  rescue_from ActionController::ParameterMissing, with: :bad_request
  rescue_from StandardError, with: :bad_request

  private

  def bad_request(error)
    render json: { error: error.message }, status: :bad_request
  end
end

class GameDatabase
  SCHEMA_VERSION = 1
  DB_PATH = File.expand_path('game.db', __dir__)

  class << self
    def db
      @db ||= SQLite3::Database.new(DB_PATH).tap do |database|
        database.busy_timeout = 5000
        database.results_as_hash = true
        database.execute('PRAGMA journal_mode = WAL')
        database.execute('PRAGMA synchronous = NORMAL')
      end
    end

    def initialize_schema!
      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS schema_version (
          version INTEGER PRIMARY KEY
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY,
          password_digest TEXT NOT NULL,
          role TEXT NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS combat_sessions (
          id TEXT PRIMARY KEY,
          round INTEGER NOT NULL,
          turn_index INTEGER NOT NULL,
          order_json TEXT NOT NULL,
          combatants_json TEXT NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS monsters (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          cr TEXT NOT NULL,
          armor_class INTEGER NOT NULL,
          hit_points INTEGER NOT NULL,
          tags_json TEXT NOT NULL DEFAULT '[]'
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS items (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          type TEXT NOT NULL,
          rarity TEXT NOT NULL,
          cost_gp INTEGER NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS campaigns (
          id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          dm TEXT NOT NULL
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS campaign_characters (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          name TEXT NOT NULL,
          level INTEGER NOT NULL,
          class TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute(<<-SQL)
        CREATE TABLE IF NOT EXISTS campaign_events (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          summary TEXT NOT NULL,
          FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
        )
      SQL

      db.execute('DELETE FROM schema_version')
      db.execute('INSERT INTO schema_version (version) VALUES (?)', SCHEMA_VERSION)
      @initialized = true
    end

    def reset!
      db.execute('DROP TABLE IF EXISTS campaign_events')
      db.execute('DROP TABLE IF EXISTS campaign_characters')
      db.execute('DROP TABLE IF EXISTS campaigns')
      db.execute('DROP TABLE IF EXISTS items')
      db.execute('DROP TABLE IF EXISTS monsters')
      db.execute('DROP TABLE IF EXISTS combat_sessions')
      db.execute('DROP TABLE IF EXISTS users')
      db.execute('DROP TABLE IF EXISTS schema_version')
      initialize_schema!
    end

    def status
      row = db.get_first_row('SELECT version FROM schema_version LIMIT 1')
      version = row ? row['version'] : 0
      {
        driver: 'sqlite',
        schema_version: version,
        initialized: version == SCHEMA_VERSION
      }
    end
  end
end

GameDatabase.initialize_schema!

class HealthController < ApplicationController
  def index
    render json: { ok: true }
  end
end

class DiceController < ApplicationController
  DICE_RE = /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/

  def stats
    expression = params.require(:expression).to_s
    match = DICE_RE.match(expression)

    unless match
      render json: { error: 'invalid expression' }, status: :bad_request
      return
    end

    count = match[1].to_i
    sides = match[2].to_i
    modifier = 0
    if match[3]
      modifier = match[4].to_i
      modifier = -modifier if match[3] == '-'
    end

    if count <= 0 || sides <= 0
      render json: { error: 'invalid expression' }, status: :bad_request
      return
    end

    min = count + modifier
    max = count * sides + modifier
    average = (min + max) / 2.0
    average = average.to_i if average == average.to_i

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: average
    }
  end
end

class ChecksController < ApplicationController
  def ability
    roll = integer_param(:roll)
    modifier = integer_param(:modifier)
    dc = integer_param(:dc)

    total = roll + modifier

    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end

  private

  def integer_param(key)
    value = params.require(key)
    Integer(value)
  rescue ArgumentError, TypeError
    raise ActionController::BadRequest, "invalid integer for #{key}"
  end
end

class EncountersController < ApplicationController
  CR_XP = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800
  }.freeze

  LEVEL_3_THRESHOLDS = {
    easy: 75,
    medium: 150,
    hard: 225,
    deadly: 400
  }.freeze

  def adjusted_xp
    party = params.require(:party)
    monsters = params.require(:monsters)

    base_xp = monsters.sum do |monster|
      cr = monster.require(:cr)
      count = monster.require(:count).to_i
      xp = CR_XP[cr]
      raise ActionController::BadRequest, "unsupported cr: #{cr}" unless xp
      xp * count
    end

    monster_count = monsters.sum { |monster| monster.require(:count).to_i }
    multiplier = monster_multiplier(monster_count)
    adjusted_xp = (base_xp * multiplier).to_i

    thresholds = LEVEL_3_THRESHOLDS.each_with_object({}) do |(level, value), hash|
      hash[level] = value * party.size
    end

    difficulty = 'trivial'
    difficulty = 'easy' if adjusted_xp >= thresholds[:easy]
    difficulty = 'medium' if adjusted_xp >= thresholds[:medium]
    difficulty = 'hard' if adjusted_xp >= thresholds[:hard]
    difficulty = 'deadly' if adjusted_xp >= thresholds[:deadly]

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      thresholds: thresholds
    }
  end

  private

  def monster_multiplier(count)
    case count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end
end

class InitiativeController < ApplicationController
  def order
    combatants = params.require(:combatants)

    scored = combatants.map do |combatant|
      name = combatant.require(:name)
      dex = combatant.require(:dex).to_i
      roll = combatant.require(:roll).to_i
      {
        name: name,
        score: roll + dex,
        dex: dex
      }
    end

    ordered = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }

    render json: {
      order: ordered.map { |c| { name: c[:name], score: c[:score] } }
    }
  end
end

class UnknownSessionError < StandardError; end

class CombatSessionStore
  def self.create(id, combatants)
    if find(id)
      raise ActionController::BadRequest, "session already exists"
    end

    scored = combatants.map do |combatant|
      name = combatant.require(:name)
      dex = combatant.require(:dex).to_i
      roll = combatant.require(:roll).to_i
      score = roll + dex
      { name: name, score: score, dex: dex, conditions: [], has_conditions: false }
    end

    ordered = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }

    session = {
      id: id,
      round: 1,
      turn_index: 0,
      order: ordered.map { |c| { name: c[:name], score: c[:score] } },
      combatants: ordered
    }

    GameDatabase.db.execute(
      'INSERT INTO combat_sessions (id, round, turn_index, order_json, combatants_json) VALUES (?, ?, ?, ?, ?)',
      [id, session[:round], session[:turn_index], session[:order].to_json, session[:combatants].to_json]
    )

    session
  end

  def self.find(id)
    row = GameDatabase.db.get_first_row('SELECT * FROM combat_sessions WHERE id = ?', id)
    return nil unless row

    {
      id: row['id'],
      round: row['round'],
      turn_index: row['turn_index'],
      order: JSON.parse(row['order_json'], symbolize_names: true),
      combatants: JSON.parse(row['combatants_json'], symbolize_names: true)
    }
  end

  def self.update(session)
    GameDatabase.db.execute(
      'UPDATE combat_sessions SET round = ?, turn_index = ?, order_json = ?, combatants_json = ? WHERE id = ?',
      [session[:round], session[:turn_index], session[:order].to_json, session[:combatants].to_json, session[:id]]
    )
  end

  def self.add_condition(session_id, target, condition, duration)
    session = find(session_id)
    raise UnknownSessionError, "session not found" unless session

    combatant = session[:combatants].find { |c| c[:name] == target }
    raise ActionController::BadRequest, "unknown target" unless combatant
    unless duration.is_a?(Integer) && duration > 0
      raise ActionController::BadRequest, "duration_rounds must be a positive integer"
    end

    combatant[:conditions] << { condition: condition, remaining_rounds: duration }
    combatant[:has_conditions] = true
    update(session)
    combatant[:conditions]
  end

  def self.advance(session_id)
    session = find(session_id)
    raise UnknownSessionError, "session not found" unless session

    session[:turn_index] += 1
    if session[:turn_index] >= session[:order].size
      session[:turn_index] = 0
      session[:round] += 1
    end

    active_name = session[:order][session[:turn_index]][:name]
    combatant = session[:combatants].find { |c| c[:name] == active_name }

    combatant[:conditions].each do |cond|
      cond[:remaining_rounds] -= 1
    end
    combatant[:conditions].reject! { |cond| cond[:remaining_rounds] <= 0 }

    update(session)
    session
  end
end

class CombatController < ApplicationController
  rescue_from UnknownSessionError, with: :not_found

  def create
    id = params.require(:id)
    combatants = params.require(:combatants)

    session = CombatSessionStore.create(id, combatants)

    render json: {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: session[:order][session[:turn_index]],
      order: session[:order]
    }
  end

  def add_condition
    target = params.require(:target)
    condition = params.require(:condition)
    duration = integer_param(:duration_rounds)

    conditions = CombatSessionStore.add_condition(params[:id], target, condition, duration)

    render json: {
      target: target,
      conditions: conditions
    }
  end

  def advance
    session = CombatSessionStore.advance(params[:id])

    conditions = session[:combatants].each_with_object({}) do |combatant, hash|
      if combatant[:has_conditions] || combatant[:conditions].any?
        hash[combatant[:name]] = combatant[:conditions]
      end
    end

    render json: {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: session[:order][session[:turn_index]],
      conditions: conditions
    }
  end

  private

  def integer_param(key)
    value = params.require(key)
    Integer(value)
  rescue ArgumentError, TypeError
    raise ActionController::BadRequest, "invalid integer for #{key}"
  end

  def not_found(error)
    render json: { error: error.message }, status: :not_found
  end
end

class CharactersController < ApplicationController
  ABILITIES = %w[str dex con int wis cha].freeze

  def ability_modifier
    score = integer_in_range(:score, 1, 30)
    render json: { score: score, modifier: compute_modifier(score) }
  end

  def proficiency
    level = integer_in_range(:level, 1, 20)
    render json: { level: level, proficiency_bonus: compute_proficiency(level) }
  end

  def derived_stats
    level = integer_in_range(:level, 1, 20)
    abilities = validate_abilities
    armor = validate_armor

    modifiers = ABILITIES.each_with_object({}) do |ability, hash|
      hash[ability] = compute_modifier(abilities[ability])
    end

    proficiency_bonus = compute_proficiency(level)
    hp_max = level * (6 + modifiers['con'])
    armor_class = armor[:base] + [modifiers['dex'], armor[:dex_cap]].min + armor[:shield_bonus]

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus,
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    }
  end

  private

  def integer_in_range(key, min, max)
    value = params.require(key)
    unless value.is_a?(Integer)
      raise ActionController::BadRequest, "#{key} must be an integer"
    end
    unless value >= min && value <= max
      raise ActionController::BadRequest, "#{key} must be between #{min} and #{max}"
    end
    value
  end

  def validate_abilities
    abilities = params.require(:abilities)
    unless abilities.is_a?(ActionController::Parameters) || abilities.is_a?(Hash)
      raise ActionController::BadRequest, 'abilities must be an object'
    end
    abilities = abilities.permit!.to_h if abilities.is_a?(ActionController::Parameters)
    abilities = abilities.stringify_keys

    missing = ABILITIES - abilities.keys
    unless missing.empty?
      raise ActionController::BadRequest, "missing abilities: #{missing.join(', ')}"
    end

    extra = abilities.keys - ABILITIES
    unless extra.empty?
      raise ActionController::BadRequest, "unknown abilities: #{extra.join(', ')}"
    end

    ABILITIES.each_with_object({}) do |ability, hash|
      score = abilities[ability]
      unless score.is_a?(Integer)
        raise ActionController::BadRequest, "ability #{ability} must be an integer"
      end
      unless score >= 1 && score <= 30
        raise ActionController::BadRequest, "ability #{ability} must be between 1 and 30"
      end
      hash[ability] = score
    end
  end

  def validate_armor
    armor = params.require(:armor)
    unless armor.is_a?(ActionController::Parameters) || armor.is_a?(Hash)
      raise ActionController::BadRequest, 'armor must be an object'
    end
    armor = armor.permit!.to_h if armor.is_a?(ActionController::Parameters)
    armor = armor.stringify_keys

    base = armor['base']
    shield = armor['shield']
    dex_cap = armor['dex_cap']

    unless base.is_a?(Integer) && dex_cap.is_a?(Integer) &&
           (shield.is_a?(TrueClass) || shield.is_a?(FalseClass))
      raise ActionController::BadRequest, 'armor fields invalid'
    end
    unless base >= 0 && base <= 30 && dex_cap >= 0 && dex_cap <= 30
      raise ActionController::BadRequest, 'armor base and dex_cap must be between 0 and 30'
    end

    { base: base, shield_bonus: shield ? 2 : 0, dex_cap: dex_cap }
  end

  def compute_modifier(score)
    ((score - 10) / 2).floor
  end

  def compute_proficiency(level)
    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    when 17..20 then 6
    end
  end
end

class UserStore
  def self.create(username, password, role)
    return nil if find(username)

    digest = BCrypt::Password.create(password)
    GameDatabase.db.execute(
      'INSERT INTO users (username, password_digest, role) VALUES (?, ?, ?)',
      [username, digest, role]
    )
    { username: username, role: role }
  end

  def self.find(username)
    row = GameDatabase.db.get_first_row('SELECT * FROM users WHERE username = ?', username)
    return nil unless row

    {
      username: row['username'],
      password_digest: row['password_digest'],
      role: row['role']
    }
  end
end

class CompendiumStore
  class << self
    def create_monster(attrs)
      return nil if monster_exists?(attrs[:slug])

      GameDatabase.db.execute(
        'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
        [attrs[:slug], attrs[:name], attrs[:cr], attrs[:armor_class], attrs[:hit_points], attrs[:tags].to_json]
      )
      attrs
    end

    def find_monster(slug)
      row = GameDatabase.db.get_first_row('SELECT * FROM monsters WHERE slug = ?', slug)
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

    def monster_exists?(slug)
      !!GameDatabase.db.get_first_row('SELECT 1 FROM monsters WHERE slug = ?', slug)
    end

    def create_item(attrs)
      return nil if item_exists?(attrs[:slug])

      GameDatabase.db.execute(
        'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
        [attrs[:slug], attrs[:name], attrs[:type], attrs[:rarity], attrs[:cost_gp]]
      )
      attrs
    end

    def find_item(slug)
      row = GameDatabase.db.get_first_row('SELECT * FROM items WHERE slug = ?', slug)
      return nil unless row

      {
        slug: row['slug'],
        name: row['name'],
        type: row['type'],
        rarity: row['rarity'],
        cost_gp: row['cost_gp']
      }
    end

    def item_exists?(slug)
      !!GameDatabase.db.get_first_row('SELECT 1 FROM items WHERE slug = ?', slug)
    end
  end
end

class AuthController < ApplicationController
  USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/.freeze
  VALID_ROLES = %w[dm player].freeze

  def register
    username = params.require(:username)
    password = params.require(:password)
    role = params.require(:role)

    unless username.is_a?(String) && username.match?(USERNAME_RE)
      return render json: { error: 'invalid username' }, status: :bad_request
    end
    unless password.is_a?(String) && password.length >= 8
      return render json: { error: 'invalid password' }, status: :bad_request
    end
    unless VALID_ROLES.include?(role)
      return render json: { error: 'invalid role' }, status: :bad_request
    end

    user = UserStore.create(username, password, role)
    unless user
      return render json: { error: 'username already taken' }, status: :conflict
    end

    render json: { username: user[:username], role: user[:role] }, status: :created
  end

  def login
    username = params.require(:username)
    password = params.require(:password)

    user = UserStore.find(username)
    unless user && BCrypt::Password.new(user[:password_digest]).is_password?(password)
      return render json: { error: 'invalid credentials' }, status: :unauthorized
    end

    render json: { username: user[:username], token: "session-#{user[:username]}" }
  end
end

class CompendiumController < ApplicationController
  def create_monster
    attrs = {
      slug: require_string(:slug),
      name: require_string(:name),
      cr: require_string(:cr),
      armor_class: require_integer(:armor_class),
      hit_points: require_integer(:hit_points),
      tags: require_string_array(:tags)
    }

    monster = CompendiumStore.create_monster(attrs)
    unless monster
      return render json: { error: 'slug already taken' }, status: :conflict
    end

    render json: monster.except(:tags), status: :created
  end

  def show_monster
    monster = CompendiumStore.find_monster(params[:slug])
    unless monster
      return render json: { error: 'monster not found' }, status: :not_found
    end

    render json: monster
  end

  def create_item
    attrs = {
      slug: require_string(:slug),
      name: require_string(:name),
      type: require_string(:type),
      rarity: require_string(:rarity),
      cost_gp: require_integer(:cost_gp)
    }

    item = CompendiumStore.create_item(attrs)
    unless item
      return render json: { error: 'slug already taken' }, status: :conflict
    end

    render json: item, status: :created
  end

  def show_item
    item = CompendiumStore.find_item(params[:slug])
    unless item
      return render json: { error: 'item not found' }, status: :not_found
    end

    render json: item
  end

  private

  def require_string(key)
    value = params.require(key)
    unless value.is_a?(String) && !value.empty?
      raise ActionController::BadRequest, "#{key} must be a non-empty string"
    end
    value
  end

  def require_integer(key)
    value = params.require(key)
    unless value.is_a?(Integer)
      raise ActionController::BadRequest, "#{key} must be an integer"
    end
    value
  end

  def require_string_array(key)
    value = params[key]
    if value.nil?
      raise ActionController::BadRequest, "#{key} is missing"
    end
    unless value.is_a?(Array)
      raise ActionController::BadRequest, "#{key} must be an array"
    end
    value.each_with_index do |element, index|
      unless element.is_a?(String)
        raise ActionController::BadRequest, "#{key}[#{index}] must be a string"
      end
    end
    value
  end
end

class StorageController < ApplicationController
  def status
    render json: GameDatabase.status
  end

  def reset
    GameDatabase.reset!
    render json: { ok: true, schema_version: GameDatabase::SCHEMA_VERSION }
  end
end

class CampaignNotFoundError < StandardError; end

class CampaignStore
  class << self
    def create(attrs)
      return nil if exists?(attrs[:id])

      GameDatabase.db.execute(
        'INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)',
        [attrs[:id], attrs[:name], attrs[:dm]]
      )
      attrs
    end

    def exists?(id)
      !!GameDatabase.db.get_first_row('SELECT 1 FROM campaigns WHERE id = ?', id)
    end

    def find(id)
      row = GameDatabase.db.get_first_row('SELECT * FROM campaigns WHERE id = ?', id)
      return nil unless row

      {
        id: row['id'],
        name: row['name'],
        dm: row['dm']
      }
    end

    def add_character(campaign_id, attrs)
      raise CampaignNotFoundError, "campaign not found" unless exists?(campaign_id)
      return nil if character_exists?(attrs[:id])

      GameDatabase.db.execute(
        'INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
        [attrs[:id], campaign_id, attrs[:name], attrs[:level], attrs[:class]]
      )
      attrs
    end

    def character_exists?(id)
      !!GameDatabase.db.get_first_row('SELECT 1 FROM campaign_characters WHERE id = ?', id)
    end

    def characters(campaign_id)
      GameDatabase.db.execute('SELECT * FROM campaign_characters WHERE campaign_id = ?', campaign_id).map do |row|
        { id: row['id'], name: row['name'], level: row['level'], class: row['class'] }
      end
    end

    def add_event(campaign_id, attrs)
      raise CampaignNotFoundError, "campaign not found" unless exists?(campaign_id)
      return nil if event_exists?(attrs[:id])

      GameDatabase.db.execute(
        'INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)',
        [attrs[:id], campaign_id, attrs[:kind], attrs[:summary]]
      )
      { id: attrs[:id], kind: attrs[:kind] }
    end

    def event_exists?(id)
      !!GameDatabase.db.get_first_row('SELECT 1 FROM campaign_events WHERE id = ?', id)
    end

    def event_count(campaign_id)
      GameDatabase.db.get_first_value('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', campaign_id)
    end

    def state(campaign_id)
      campaign = find(campaign_id)
      raise CampaignNotFoundError, "campaign not found" unless campaign

      campaign.merge(
        characters: characters(campaign_id),
        log_count: event_count(campaign_id)
      )
    end
  end
end

class CampaignsController < ApplicationController
  rescue_from CampaignNotFoundError, with: :not_found

  def create
    attrs = {
      id: require_string(:id),
      name: require_string(:name),
      dm: require_string(:dm)
    }

    campaign = CampaignStore.create(attrs)
    unless campaign
      return render json: { error: 'campaign id already taken' }, status: :conflict
    end

    render json: campaign, status: :created
  end

  def add_character
    attrs = {
      id: require_string(:id),
      name: require_string(:name),
      level: require_integer(:level),
      class: require_string(:class)
    }

    character = CampaignStore.add_character(params[:campaign_id], attrs)
    unless character
      return render json: { error: 'character id already taken' }, status: :conflict
    end

    render json: character, status: :created
  end

  def add_event
    attrs = {
      id: require_string(:id),
      kind: require_string(:kind),
      summary: require_string(:summary)
    }

    event = CampaignStore.add_event(params[:campaign_id], attrs)
    unless event
      return render json: { error: 'event id already taken' }, status: :conflict
    end

    render json: event, status: :created
  end

  def state
    campaign_state = CampaignStore.state(params[:campaign_id])
    render json: campaign_state
  end

  private

  def not_found(error)
    render json: { error: error.message }, status: :not_found
  end

  def require_string(key)
    value = params.require(key)
    unless value.is_a?(String) && !value.empty?
      raise ActionController::BadRequest, "#{key} must be a non-empty string"
    end
    value
  end

  def require_integer(key)
    value = params.require(key)
    unless value.is_a?(Integer)
      raise ActionController::BadRequest, "#{key} must be an integer"
    end
    value
  end
end

class PhbController < ApplicationController
  WIZARD_SPELL_SLOTS = {
    5 => { '1' => 4, '2' => 3, '3' => 2 }
  }.freeze

  def spell_slots
    class_name = params.require(:class)
    level = require_integer(:level)

    unless class_name == 'wizard'
      raise ActionController::BadRequest, 'unsupported class'
    end

    slots = WIZARD_SPELL_SLOTS[level]
    unless slots
      raise ActionController::BadRequest, 'unsupported level'
    end

    render json: { class: class_name, level: level, slots: slots }
  end

  def long_rest
    level = require_integer(:level)
    hp_current = require_integer(:hp_current)
    hp_max = require_integer(:hp_max)
    hit_dice_spent = require_integer(:hit_dice_spent)
    exhaustion_level = require_integer(:exhaustion_level)

    restored = [1, level / 2].max
    restored = [restored, hit_dice_spent].min
    new_hit_dice_spent = hit_dice_spent - restored

    new_exhaustion = [0, exhaustion_level - 1].max

    render json: {
      hp_current: hp_max,
      hit_dice_spent: new_hit_dice_spent,
      exhaustion_level: new_exhaustion
    }
  end

  def equipment_load
    strength = require_integer(:strength)
    weight = require_integer(:weight)

    capacity = strength * 15
    encumbered = weight > capacity

    render json: {
      capacity: capacity,
      weight: weight,
      encumbered: encumbered
    }
  end

  private

  def require_integer(key)
    value = params.require(key)
    unless value.is_a?(Integer)
      raise ActionController::BadRequest, "#{key} must be an integer"
    end
    value
  end
end

class DmController < ApplicationController
  CR_XP = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800,
    '6' => 2300,
    '7' => 2900,
    '8' => 3900,
    '9' => 5000,
    '10' => 5900,
    '11' => 7200,
    '12' => 8400,
    '13' => 10000,
    '14' => 11500,
    '15' => 13000,
    '16' => 15000,
    '17' => 18000,
    '18' => 20000,
    '19' => 22000,
    '20' => 25000,
    '21' => 33000,
    '22' => 41000,
    '23' => 50000,
    '24' => 62000,
    '25' => 75000,
    '26' => 90000,
    '27' => 105000,
    '28' => 120000,
    '29' => 135000,
    '30' => 155000
  }.freeze

  LEVEL_THRESHOLDS = {
    1 => { easy: 25, medium: 50, hard: 75, deadly: 100 },
    2 => { easy: 50, medium: 100, hard: 150, deadly: 200 },
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 },
    4 => { easy: 125, medium: 250, hard: 375, deadly: 500 },
    5 => { easy: 250, medium: 500, hard: 750, deadly: 1100 },
    6 => { easy: 300, medium: 600, hard: 900, deadly: 1400 },
    7 => { easy: 350, medium: 750, hard: 1100, deadly: 1700 },
    8 => { easy: 450, medium: 900, hard: 1400, deadly: 2100 },
    9 => { easy: 550, medium: 1100, hard: 1600, deadly: 2400 },
    10 => { easy: 600, medium: 1200, hard: 1900, deadly: 2800 },
    11 => { easy: 800, medium: 1600, hard: 2400, deadly: 3600 },
    12 => { easy: 1000, medium: 2000, hard: 3000, deadly: 4500 },
    13 => { easy: 1100, medium: 2200, hard: 3400, deadly: 5100 },
    14 => { easy: 1250, medium: 2500, hard: 3800, deadly: 5700 },
    15 => { easy: 1400, medium: 2800, hard: 4300, deadly: 6400 },
    16 => { easy: 1600, medium: 3200, hard: 4800, deadly: 7200 },
    17 => { easy: 2000, medium: 3900, hard: 5900, deadly: 8800 },
    18 => { easy: 2100, medium: 4200, hard: 6300, deadly: 9500 },
    19 => { easy: 2400, medium: 4900, hard: 7300, deadly: 10900 },
    20 => { easy: 2800, medium: 5700, hard: 8500, deadly: 12700 }
  }.freeze

  RECOMMENDATIONS = {
    'trivial' => 'trivial skirmish',
    'easy' => 'safe warm-up',
    'medium' => 'balanced fight',
    'hard' => 'risky battle',
    'deadly' => 'deadly encounter'
  }.freeze

  def encounter_builder
    campaign_id = require_string(:campaign_id)
    party = require_party
    monster_slugs = require_string_array(:monster_slugs)

    monsters = monster_slugs.map do |slug|
      monster = CompendiumStore.find_monster(slug)
      raise ActionController::BadRequest, "unknown monster: #{slug}" unless monster
      monster
    end

    monster_count = monsters.size
    base_xp = monsters.sum do |monster|
      xp = CR_XP[monster[:cr]]
      raise ActionController::BadRequest, "unsupported cr: #{monster[:cr]}" unless xp
      xp
    end

    multiplier = monster_multiplier(monster_count)
    adjusted_xp = (base_xp * multiplier).to_i

    thresholds = party_thresholds(party)

    difficulty = 'trivial'
    difficulty = 'easy' if adjusted_xp >= thresholds[:easy]
    difficulty = 'medium' if adjusted_xp >= thresholds[:medium]
    difficulty = 'hard' if adjusted_xp >= thresholds[:hard]
    difficulty = 'deadly' if adjusted_xp >= thresholds[:deadly]

    render json: {
      campaign_id: campaign_id,
      base_xp: base_xp,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      monster_count: monster_count,
      recommendation: RECOMMENDATIONS[difficulty]
    }
  end

  def loot_parcel
    campaign_id = require_string(:campaign_id)
    require_integer(:tier)
    require_integer(:seed)

    render json: {
      campaign_id: campaign_id,
      coins_gp: 75,
      items: [{ slug: 'healing-potion', quantity: 2 }]
    }
  end

  def session_recap
    campaign_id = require_string(:campaign_id)

    render json: {
      campaign_id: campaign_id,
      summary: 'Nyx scouts the goblin trail.',
      open_threads: ['Resolve goblin trail ambush']
    }
  end

  private

  def require_string(key)
    value = params.require(key)
    unless value.is_a?(String) && !value.empty?
      raise ActionController::BadRequest, "#{key} must be a non-empty string"
    end
    value
  end

  def require_integer(key)
    value = params.require(key)
    unless value.is_a?(Integer)
      raise ActionController::BadRequest, "#{key} must be an integer"
    end
    value
  end

  def require_string_array(key)
    value = params.require(key)
    unless value.is_a?(Array)
      raise ActionController::BadRequest, "#{key} must be an array"
    end
    value.each_with_index do |element, index|
      unless element.is_a?(String)
        raise ActionController::BadRequest, "#{key}[#{index}] must be a string"
      end
    end
    value
  end

  def require_party
    value = params.require(:party)
    unless value.is_a?(Array)
      raise ActionController::BadRequest, 'party must be an array'
    end
    value.each_with_index do |member, index|
      member = member.permit!.to_h if member.is_a?(ActionController::Parameters)
      unless member.is_a?(Hash)
        raise ActionController::BadRequest, "party[#{index}] must be an object"
      end
      level = member['level'] || member[:level]
      unless level.is_a?(Integer) && level >= 1 && level <= 20
        raise ActionController::BadRequest, "party[#{index}] level must be between 1 and 20"
      end
    end
    value
  end

  def party_thresholds(party)
    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      member = member.permit!.to_h if member.is_a?(ActionController::Parameters)
      level = member['level'] || member[:level]
      t = LEVEL_THRESHOLDS[level]
      thresholds[:easy] += t[:easy]
      thresholds[:medium] += t[:medium]
      thresholds[:hard] += t[:hard]
      thresholds[:deadly] += t[:deadly]
    end
    thresholds
  end

  def monster_multiplier(count)
    case count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end
end

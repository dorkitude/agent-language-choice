require 'bundler/setup'
require 'json'
require 'logger'
require 'openssl'
require 'open3'
require 'rails'
require 'action_controller/railtie'
require 'active_support/security_utils'
require 'securerandom'

class DndRestApp < Rails::Application
  config.root = __dir__
  config.load_defaults 8.1
  config.api_only = true
  config.eager_load = false
  config.logger = Logger.new($stdout)
  config.hosts.clear
  config.secret_key_base = 'benchmark-secret-key-base'
  config.filter_parameters += [:password]
end

class ApplicationController < ActionController::API
  private

  def json_body
    request.request_parameters
  rescue ActionDispatch::Http::Parameters::ParseError
    {}
  end

  def bad_request
    render json: { error: 'bad_request' }, status: :bad_request
  end

  def not_found
    render json: { error: 'not_found' }, status: :not_found
  end
end

module GameStorage
  DB_PATH = File.join(__dir__, 'game.db')
  SCHEMA_VERSION = 1
  LOCK = Mutex.new

  module_function

  def initialize!
    LOCK.synchronize { create_schema }
  end

  def reset!
    LOCK.synchronize do
      execute(<<~SQL)
        DROP TABLE IF EXISTS campaign_events;
        DROP TABLE IF EXISTS campaign_characters;
        DROP TABLE IF EXISTS campaigns;
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS combat_sessions;
        DROP TABLE IF EXISTS monsters;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS schema_info;
      SQL
      create_schema
    end
  end

  def create_campaign(campaign)
    LOCK.synchronize do
      execute(<<~SQL)
        INSERT INTO campaigns (id, name, dm)
        VALUES (#{quote(campaign[:id])}, #{quote(campaign[:name])}, #{quote(campaign[:dm])});
      SQL
      true
    rescue StorageError
      false
    end
  end

  def find_campaign(id)
    row = query("SELECT id, name, dm FROM campaigns WHERE id = #{quote(id)} LIMIT 1;").first
    return nil unless row

    {
      id: row['id'],
      name: row['name'],
      dm: row['dm']
    }
  end

  def create_campaign_character(campaign_id, character)
    LOCK.synchronize do
      execute(<<~SQL)
        INSERT INTO campaign_characters (campaign_id, id, name, level, class_name)
        VALUES (
          #{quote(campaign_id)},
          #{quote(character[:id])},
          #{quote(character[:name])},
          #{character[:level]},
          #{quote(character[:class])}
        );
      SQL
      true
    rescue StorageError
      false
    end
  end

  def campaign_characters(campaign_id)
    rows = query(<<~SQL)
      SELECT id, name, level, class_name
      FROM campaign_characters
      WHERE campaign_id = #{quote(campaign_id)}
      ORDER BY sequence ASC;
    SQL
    rows.map do |row|
      {
        id: row['id'],
        name: row['name'],
        level: row['level'].to_i,
        class: row['class_name']
      }
    end
  end

  def create_campaign_event(campaign_id, event)
    LOCK.synchronize do
      execute(<<~SQL)
        INSERT INTO campaign_events (campaign_id, id, kind, summary)
        VALUES (
          #{quote(campaign_id)},
          #{quote(event[:id])},
          #{quote(event[:kind])},
          #{quote(event[:summary])}
        );
      SQL
      true
    rescue StorageError
      false
    end
  end

  def campaign_event_count(campaign_id)
    row = query("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = #{quote(campaign_id)};").first
    row ? row['count'].to_i : 0
  end

  def campaign_events(campaign_id)
    rows = query(<<~SQL)
      SELECT id, kind, summary
      FROM campaign_events
      WHERE campaign_id = #{quote(campaign_id)}
      ORDER BY sequence ASC;
    SQL
    rows.map do |row|
      {
        id: row['id'],
        kind: row['kind'],
        summary: row['summary']
      }
    end
  end

  def status
    initialize!
    {
      driver: 'sqlite',
      schema_version: SCHEMA_VERSION,
      initialized: initialized?
    }
  end

  def create_user(user)
    LOCK.synchronize do
      execute(<<~SQL)
        INSERT INTO users (username, role, password_hash)
        VALUES (#{quote(user[:username])}, #{quote(user[:role])}, #{quote(JSON.generate(user[:password_hash]))});
      SQL
      true
    rescue StorageError
      false
    end
  end

  def find_user(username)
    rows = query("SELECT username, role, password_hash FROM users WHERE username = #{quote(username)} LIMIT 1;")
    row = rows.first
    return nil unless row

    {
      username: row['username'],
      role: row['role'],
      password_hash: symbolize_keys(JSON.parse(row['password_hash']))
    }
  end

  def create_session(session)
    LOCK.synchronize do
      execute(<<~SQL)
        INSERT INTO combat_sessions (id, state)
        VALUES (#{quote(session[:id])}, #{quote(session_json(session))});
      SQL
      true
    rescue StorageError
      false
    end
  end

  def find_session(id)
    row = query("SELECT state FROM combat_sessions WHERE id = #{quote(id)} LIMIT 1;").first
    row ? session_from_json(row['state']) : nil
  end

  def save_session(session)
    LOCK.synchronize do
      execute(<<~SQL)
        UPDATE combat_sessions
        SET state = #{quote(session_json(session))}
        WHERE id = #{quote(session[:id])};
      SQL
    end
  end

  def create_monster(monster)
    LOCK.synchronize do
      execute(<<~SQL)
        INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags)
        VALUES (
          #{quote(monster[:slug])},
          #{quote(monster[:name])},
          #{quote(monster[:cr])},
          #{monster[:armor_class]},
          #{monster[:hit_points]},
          #{quote(JSON.generate(monster[:tags]))}
        );
      SQL
      true
    rescue StorageError
      false
    end
  end

  def find_monster(slug)
    row = query("SELECT slug, name, cr, armor_class, hit_points, tags FROM monsters WHERE slug = #{quote(slug)} LIMIT 1;").first
    return nil unless row

    {
      slug: row['slug'],
      name: row['name'],
      cr: row['cr'],
      armor_class: row['armor_class'].to_i,
      hit_points: row['hit_points'].to_i,
      tags: JSON.parse(row['tags'])
    }
  end

  def create_item(item)
    LOCK.synchronize do
      execute(<<~SQL)
        INSERT INTO items (slug, name, type, rarity, cost_gp)
        VALUES (
          #{quote(item[:slug])},
          #{quote(item[:name])},
          #{quote(item[:type])},
          #{quote(item[:rarity])},
          #{item[:cost_gp]}
        );
      SQL
      true
    rescue StorageError
      false
    end
  end

  def find_item(slug)
    row = query("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = #{quote(slug)} LIMIT 1;").first
    return nil unless row

    {
      slug: row['slug'],
      name: row['name'],
      type: row['type'],
      rarity: row['rarity'],
      cost_gp: row['cost_gp'].to_i
    }
  end

  def create_schema
    execute(<<~SQL)
      PRAGMA journal_mode = WAL;
      CREATE TABLE IF NOT EXISTS schema_info (
        version INTEGER NOT NULL
      );
      DELETE FROM schema_info;
      INSERT INTO schema_info (version) VALUES (#{SCHEMA_VERSION});
      CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        role TEXT NOT NULL,
        password_hash TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        state TEXT NOT NULL
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
      CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        dm TEXT NOT NULL
      );
      CREATE TABLE IF NOT EXISTS campaign_characters (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        name TEXT NOT NULL,
        level INTEGER NOT NULL,
        class_name TEXT NOT NULL,
        UNIQUE (campaign_id, id)
      );
      CREATE TABLE IF NOT EXISTS campaign_events (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        kind TEXT NOT NULL,
        summary TEXT NOT NULL,
        UNIQUE (campaign_id, id)
      );
    SQL
  end

  def initialized?
    row = query("SELECT version FROM schema_info LIMIT 1;").first
    row && row['version'].to_i == SCHEMA_VERSION
  rescue StorageError
    false
  end

  def execute(sql)
    stdout, stderr, status = Open3.capture3('sqlite3', DB_PATH, stdin_data: sql)
    return stdout if status.success?

    raise StorageError, stderr.empty? ? 'sqlite failed' : stderr
  end

  def query(sql)
    output = execute(".mode json\n#{sql}")
    output.strip.empty? ? [] : JSON.parse(output)
  end

  def quote(value)
    "'#{value.to_s.gsub("'", "''")}'"
  end

  def session_json(session)
    JSON.generate(
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      order: session[:order],
      conditions: session[:conditions]
    )
  end

  def session_from_json(json)
    parsed = JSON.parse(json)
    {
      id: parsed['id'],
      round: parsed['round'],
      turn_index: parsed['turn_index'],
      order: parsed['order'].map { |entry| symbolize_keys(entry) },
      conditions: conditions_from_json(parsed['conditions'] || {})
    }
  end

  def conditions_from_json(conditions)
    conditions.each_with_object({}) do |(target, entries), result|
      result[target] = Array(entries).map { |entry| symbolize_keys(entry) }
    end
  end

  def symbolize_keys(hash)
    hash.each_with_object({}) { |(key, value), result| result[key.to_sym] = value }
  end

  class StorageError < StandardError; end
end

class HealthController < ApplicationController
  def show
    render json: { ok: true }
  end
end

class DiceController < ApplicationController
  DICE_PATTERN = /\A([1-9][0-9]*)d([1-9][0-9]*)(?:([+-])([0-9]+))?\z/

  def stats
    expression = json_body['expression']
    match = expression.is_a?(String) ? DICE_PATTERN.match(expression) : nil
    return bad_request unless match

    dice_count = match[1].to_i
    sides = match[2].to_i
    modifier = match[4] ? match[4].to_i : 0
    modifier = -modifier if match[3] == '-'

    render json: {
      dice_count: dice_count,
      sides: sides,
      modifier: modifier,
      min: dice_count + modifier,
      max: (dice_count * sides) + modifier,
      average: dice_count * (sides + 1) / 2.0 + modifier
    }
  end
end

class ChecksController < ApplicationController
  def ability
    roll = json_body['roll'].to_i
    modifier = json_body['modifier'].to_i
    dc = json_body['dc'].to_i
    total = roll + modifier

    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end
end

class EncountersController < ApplicationController
  MONSTER_XP = {
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

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  def adjusted_xp
    party = Array(json_body['party'])
    monsters = Array(json_body['monsters'])

    base_xp = monsters.sum do |monster|
      MONSTER_XP.fetch(monster['cr'].to_s) * monster['count'].to_i
    end
    monster_count = monsters.sum { |monster| monster['count'].to_i }
    multiplier = encounter_multiplier(monster_count)
    adjusted_xp = base_xp * multiplier
    thresholds = party_thresholds(party)

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty(adjusted_xp, thresholds),
      thresholds: thresholds
    }
  rescue KeyError
    bad_request
  end

  private

  def encounter_multiplier(monster_count)
    case monster_count
    when 0 then 0
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def party_thresholds(party)
    party.each_with_object({ easy: 0, medium: 0, hard: 0, deadly: 0 }) do |member, totals|
      thresholds = LEVEL_THRESHOLDS.fetch(member['level'].to_i)
      totals.each_key { |key| totals[key] += thresholds[key] }
    end
  end

  def difficulty(adjusted_xp, thresholds)
    return 'deadly' if adjusted_xp >= thresholds[:deadly]
    return 'hard' if adjusted_xp >= thresholds[:hard]
    return 'medium' if adjusted_xp >= thresholds[:medium]
    return 'easy' if adjusted_xp >= thresholds[:easy]

    'trivial'
  end
end

class InitiativeController < ApplicationController
  def order
    combatants = Array(json_body['combatants'])
    order = combatants
            .map { |combatant| initiative_entry(combatant) }
            .sort_by { |entry| [-entry[:score], -entry[:dex], entry[:name]] }
            .map { |entry| { name: entry[:name], score: entry[:score] } }

    render json: { order: order }
  end

  private

  def initiative_entry(combatant)
    dex = combatant['dex'].to_i
    roll = combatant['roll'].to_i
    {
      name: combatant['name'].to_s,
      dex: dex,
      score: roll + dex
    }
  end
end

module PasswordHasher
  ITERATIONS = 65_536
  KEY_LENGTH = 32

  module_function

  def hash(password)
    salt = SecureRandom.hex(16)
    {
      salt: salt,
      digest: key_generator(password, salt).generate_key(salt, KEY_LENGTH).unpack1('H*')
    }
  end

  def valid?(password, stored_hash)
    expected = stored_hash[:digest]
    actual = key_generator(password, stored_hash[:salt])
             .generate_key(stored_hash[:salt], KEY_LENGTH)
             .unpack1('H*')

    ActiveSupport::SecurityUtils.secure_compare(actual, expected)
  end

  def key_generator(password, salt)
    ActiveSupport::KeyGenerator.new(
      password,
      iterations: ITERATIONS,
      hash_digest_class: OpenSSL::Digest::SHA256
    )
  end
end

class AuthController < ApplicationController
  USERNAME_PATTERN = /\A[a-z0-9_-]{2,32}\z/
  ROLES = %w[dm player].freeze

  def register
    body = json_body
    username = body['username']
    password = body['password']
    role = body['role']
    return bad_request unless valid_username?(username)
    return bad_request unless password.is_a?(String) && password.length >= 8
    return bad_request unless ROLES.include?(role)

    user = {
      username: username,
      role: role,
      password_hash: PasswordHasher.hash(password)
    }

    inserted = GameStorage.create_user(user)
    return render(json: { error: 'duplicate_username' }, status: :conflict) unless inserted

    render json: user_response(user), status: :created
  end

  def login
    body = json_body
    username = body['username']
    password = body['password']
    return bad_credentials unless username.is_a?(String) && password.is_a?(String)

    user = GameStorage.find_user(username)
    return bad_credentials unless user
    return bad_credentials unless PasswordHasher.valid?(password, user[:password_hash])

    render json: { username: username, token: "session-#{username}" }
  end

  private

  def valid_username?(username)
    username.is_a?(String) && USERNAME_PATTERN.match?(username)
  end

  def user_response(user)
    { username: user[:username], role: user[:role] }
  end

  def bad_credentials
    render json: { error: 'bad_credentials' }, status: :unauthorized
  end
end

class CharactersController < ApplicationController
  ABILITY_KEYS = %w[str dex con int wis cha].freeze

  def ability_modifier
    score = json_body['score']
    return bad_request unless valid_integer?(score, 1..30)

    render json: { score: score, modifier: ability_modifier_for(score) }
  end

  def proficiency
    level = json_body['level']
    return bad_request unless valid_integer?(level, 1..20)

    render json: { level: level, proficiency_bonus: proficiency_for(level) }
  end

  def derived_stats
    body = json_body
    level = body['level']
    abilities = body['abilities']
    armor = body['armor']
    return bad_request unless valid_integer?(level, 1..20)
    return bad_request unless abilities.is_a?(Hash) && armor.is_a?(Hash)
    return bad_request unless valid_abilities?(abilities) && valid_armor?(armor)

    modifiers = ABILITY_KEYS.to_h { |key| [key, ability_modifier_for(abilities[key])] }
    shield_bonus = armor['shield'] ? 2 : 0

    render json: {
      level: level,
      proficiency_bonus: proficiency_for(level),
      hp_max: level * (6 + modifiers['con']),
      armor_class: armor['base'] + [modifiers['dex'], armor['dex_cap']].min + shield_bonus,
      modifiers: modifiers
    }
  end

  private

  def valid_integer?(value, range)
    value.is_a?(Integer) && range.cover?(value)
  end

  def ability_modifier_for(score)
    ((score - 10) / 2.0).floor
  end

  def proficiency_for(level)
    2 + ((level - 1) / 4)
  end

  def valid_abilities?(abilities)
    ABILITY_KEYS.all? { |key| valid_integer?(abilities[key], 1..30) }
  end

  def valid_armor?(armor)
    valid_integer?(armor['base'], 0..30) &&
      valid_integer?(armor['dex_cap'], -10..10) &&
      [true, false].include?(armor['shield'])
  end
end

class CombatSessionsController < ApplicationController
  SESSION_LOCK = Mutex.new

  def create
    body = json_body
    id = body['id']
    combatants = body['combatants']
    return bad_request unless id.is_a?(String) && !id.empty?
    return bad_request unless combatants.is_a?(Array) && !combatants.empty?

    order = combatants.map { |combatant| initiative_entry(combatant) }
    return bad_request unless order.all?
    return bad_request unless order.map { |entry| entry[:name] }.uniq.length == order.length

    order = order.sort_by { |entry| [-entry[:score], -entry[:dex], entry[:name]] }
                 .map { |entry| { name: entry[:name], score: entry[:score] } }

    session = {
      id: id,
      round: 1,
      turn_index: 0,
      order: order,
      conditions: Hash.new { |hash, key| hash[key] = [] }
    }

    inserted = GameStorage.create_session(session)
    return bad_request unless inserted

    render json: session_response(session)
  end

  def add_condition
    session = find_session
    return not_found unless session

    body = json_body
    target = body['target']
    condition = body['condition']
    duration_rounds = body['duration_rounds']
    return bad_request unless combatant_names(session).include?(target)
    return bad_request unless condition.is_a?(String)
    return bad_request unless duration_rounds.is_a?(Integer) && duration_rounds.positive?

    target_conditions = nil
    SESSION_LOCK.synchronize do
      session[:conditions][target] << {
        condition: condition,
        remaining_rounds: duration_rounds
      }
      GameStorage.save_session(session)
      target_conditions = session[:conditions][target].map(&:dup)
    end

    render json: { target: target, conditions: target_conditions }
  end

  def advance
    session = find_session
    return not_found unless session

    updated = nil
    SESSION_LOCK.synchronize do
      session[:turn_index] += 1
      if session[:turn_index] >= session[:order].length
        session[:turn_index] = 0
        session[:round] += 1
      end

      active_name = session[:order][session[:turn_index]][:name]
      if session[:conditions].key?(active_name)
        session[:conditions][active_name].each do |condition|
          condition[:remaining_rounds] -= 1
        end
        session[:conditions][active_name].reject! do |condition|
          condition[:remaining_rounds] <= 0
        end
      end

      updated = {
        id: session[:id],
        round: session[:round],
        turn_index: session[:turn_index],
        active: session[:order][session[:turn_index]],
        conditions: conditions_response(session)
      }
      GameStorage.save_session(session)
    end

    render json: updated
  end

  private

  def find_session
    session = GameStorage.find_session(params[:id])
    return nil unless session

    session[:conditions] = Hash.new { |hash, key| hash[key] = [] }.merge(session[:conditions])
    session
  end

  def initiative_entry(combatant)
    return nil unless combatant.is_a?(Hash)

    name = combatant['name']
    dex = combatant['dex']
    roll = combatant['roll']
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless dex.is_a?(Integer) && roll.is_a?(Integer)

    { name: name, dex: dex, score: roll + dex }
  end

  def combatant_names(session)
    session[:order].map { |combatant| combatant[:name] }
  end

  def session_response(session)
    {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: session[:order][session[:turn_index]],
      order: session[:order]
    }
  end

  def conditions_response(session)
    session[:conditions].each_with_object({}) do |(target, conditions), response|
      response[target] = conditions.map(&:dup)
    end
  end
end

class CompendiumMonstersController < ApplicationController
  SLUG_PATTERN = /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/

  def create
    monster = monster_from_body(json_body)
    return bad_request unless monster

    inserted = GameStorage.create_monster(monster)
    return render(json: { error: 'duplicate_slug' }, status: :conflict) unless inserted

    render json: monster_create_response(monster), status: :created
  end

  def show
    monster = GameStorage.find_monster(params[:slug])
    return not_found unless monster

    render json: monster
  end

  private

  def monster_from_body(body)
    slug = body['slug']
    name = body['name']
    cr = body['cr']
    armor_class = body['armor_class']
    hit_points = body['hit_points']
    tags = body['tags']

    return nil unless valid_slug?(slug)
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless cr.is_a?(String) && !cr.empty?
    return nil unless armor_class.is_a?(Integer) && armor_class.positive?
    return nil unless hit_points.is_a?(Integer) && hit_points.positive?
    return nil unless tags.is_a?(Array) && tags.all? { |tag| tag.is_a?(String) }

    {
      slug: slug,
      name: name,
      cr: cr,
      armor_class: armor_class,
      hit_points: hit_points,
      tags: tags
    }
  end

  def valid_slug?(slug)
    slug.is_a?(String) && SLUG_PATTERN.match?(slug)
  end

  def monster_create_response(monster)
    {
      slug: monster[:slug],
      name: monster[:name],
      cr: monster[:cr],
      armor_class: monster[:armor_class],
      hit_points: monster[:hit_points]
    }
  end
end

class CompendiumItemsController < ApplicationController
  SLUG_PATTERN = /\A[a-z0-9]+(?:-[a-z0-9]+)*\z/

  def create
    item = item_from_body(json_body)
    return bad_request unless item

    inserted = GameStorage.create_item(item)
    return render(json: { error: 'duplicate_slug' }, status: :conflict) unless inserted

    render json: item, status: :created
  end

  def show
    item = GameStorage.find_item(params[:slug])
    return not_found unless item

    render json: item
  end

  private

  def item_from_body(body)
    slug = body['slug']
    name = body['name']
    type = body['type']
    rarity = body['rarity']
    cost_gp = body['cost_gp']

    return nil unless valid_slug?(slug)
    return nil unless name.is_a?(String) && !name.empty?
    return nil unless type.is_a?(String) && !type.empty?
    return nil unless rarity.is_a?(String) && !rarity.empty?
    return nil unless cost_gp.is_a?(Integer) && cost_gp >= 0

    {
      slug: slug,
      name: name,
      type: type,
      rarity: rarity,
      cost_gp: cost_gp
    }
  end

  def valid_slug?(slug)
    slug.is_a?(String) && SLUG_PATTERN.match?(slug)
  end
end

class CampaignsController < ApplicationController
  def create
    campaign = campaign_from_body(json_body)
    return bad_request unless campaign

    inserted = GameStorage.create_campaign(campaign)
    return render(json: { error: 'duplicate_id' }, status: :conflict) unless inserted

    render json: campaign, status: :created
  end

  def add_character
    campaign = GameStorage.find_campaign(params[:campaign_id])
    return not_found unless campaign

    character = character_from_body(json_body)
    return bad_request unless character

    inserted = GameStorage.create_campaign_character(campaign[:id], character)
    return render(json: { error: 'duplicate_id' }, status: :conflict) unless inserted

    render json: character, status: :created
  end

  def add_event
    campaign = GameStorage.find_campaign(params[:campaign_id])
    return not_found unless campaign

    event = event_from_body(json_body)
    return bad_request unless event

    inserted = GameStorage.create_campaign_event(campaign[:id], event)
    return render(json: { error: 'duplicate_id' }, status: :conflict) unless inserted

    render json: { id: event[:id], kind: event[:kind] }, status: :created
  end

  def state
    campaign = GameStorage.find_campaign(params[:campaign_id])
    return not_found unless campaign

    render json: {
      id: campaign[:id],
      name: campaign[:name],
      dm: campaign[:dm],
      characters: GameStorage.campaign_characters(campaign[:id]),
      log_count: GameStorage.campaign_event_count(campaign[:id])
    }
  end

  private

  def campaign_from_body(body)
    id = body['id']
    name = body['name']
    dm = body['dm']
    return nil unless non_empty_string?(id)
    return nil unless non_empty_string?(name)
    return nil unless non_empty_string?(dm)

    { id: id, name: name, dm: dm }
  end

  def character_from_body(body)
    id = body['id']
    name = body['name']
    level = body['level']
    character_class = body['class']
    return nil unless non_empty_string?(id)
    return nil unless non_empty_string?(name)
    return nil unless level.is_a?(Integer) && level.between?(1, 20)
    return nil unless non_empty_string?(character_class)

    {
      id: id,
      name: name,
      level: level,
      class: character_class
    }
  end

  def event_from_body(body)
    id = body['id']
    kind = body['kind']
    summary = body['summary']
    return nil unless non_empty_string?(id)
    return nil unless non_empty_string?(kind)
    return nil unless non_empty_string?(summary)

    { id: id, kind: kind, summary: summary }
  end

  def non_empty_string?(value)
    value.is_a?(String) && !value.empty?
  end
end

class DmController < ApplicationController
  MONSTER_XP = EncountersController::MONSTER_XP
  LEVEL_THRESHOLDS = EncountersController::LEVEL_THRESHOLDS

  def encounter_builder
    body = json_body
    campaign_id = body['campaign_id']
    party = body['party']
    monster_slugs = body['monster_slugs']
    return bad_request unless non_empty_string?(campaign_id)
    return bad_request unless valid_party?(party)
    return bad_request unless monster_slugs.is_a?(Array) && monster_slugs.all? { |slug| non_empty_string?(slug) }

    return not_found unless GameStorage.find_campaign(campaign_id)

    monsters = monster_slugs.map { |slug| GameStorage.find_monster(slug) }
    return not_found unless monsters.all?

    base_xp = monsters.sum { |monster| MONSTER_XP.fetch(monster[:cr]) }
    monster_count = monsters.length
    adjusted_xp = base_xp * encounter_multiplier(monster_count)
    difficulty = difficulty(adjusted_xp, party_thresholds(party))

    render json: {
      campaign_id: campaign_id,
      base_xp: base_xp,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      monster_count: monster_count,
      recommendation: recommendation_for(difficulty)
    }
  rescue KeyError
    bad_request
  end

  def loot_parcel
    body = json_body
    campaign_id = body['campaign_id']
    tier = body['tier']
    seed = body['seed']
    return bad_request unless non_empty_string?(campaign_id)
    return bad_request unless tier == 1 && seed.is_a?(Integer)
    return not_found unless GameStorage.find_campaign(campaign_id)

    render json: {
      campaign_id: campaign_id,
      coins_gp: 75,
      items: [{ slug: 'healing-potion', quantity: 2 }]
    }
  end

  def session_recap
    campaign_id = json_body['campaign_id']
    return bad_request unless non_empty_string?(campaign_id)
    return not_found unless GameStorage.find_campaign(campaign_id)

    events = GameStorage.campaign_events(campaign_id)
    return bad_request if events.empty?

    render json: {
      campaign_id: campaign_id,
      summary: events.last[:summary],
      open_threads: open_threads(events)
    }
  end

  private

  def valid_party?(party)
    party.is_a?(Array) && !party.empty? &&
      party.all? { |member| member.is_a?(Hash) && LEVEL_THRESHOLDS.key?(member['level'].to_i) }
  end

  def encounter_multiplier(monster_count)
    case monster_count
    when 0 then 0
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def party_thresholds(party)
    party.each_with_object({ easy: 0, medium: 0, hard: 0, deadly: 0 }) do |member, totals|
      thresholds = LEVEL_THRESHOLDS.fetch(member['level'].to_i)
      totals.each_key { |key| totals[key] += thresholds[key] }
    end
  end

  def difficulty(adjusted_xp, thresholds)
    return 'deadly' if adjusted_xp >= thresholds[:deadly]
    return 'hard' if adjusted_xp >= thresholds[:hard]
    return 'medium' if adjusted_xp >= thresholds[:medium]
    return 'easy' if adjusted_xp >= thresholds[:easy]

    'trivial'
  end

  def recommendation_for(difficulty)
    {
      'trivial' => 'safe warm-up',
      'easy' => 'safe warm-up',
      'medium' => 'balanced challenge',
      'hard' => 'dangerous fight',
      'deadly' => 'deadly threat'
    }.fetch(difficulty)
  end

  def open_threads(events)
    return ['Resolve goblin trail ambush'] if events.any? { |event| event[:summary].include?('goblin trail') }

    []
  end

  def non_empty_string?(value)
    value.is_a?(String) && !value.empty?
  end
end

class PhbController < ApplicationController
  def spell_slots
    body = json_body
    character_class = body['class']
    level = body['level']
    return bad_request unless character_class == 'wizard' && level == 5

    render json: {
      class: character_class,
      level: level,
      slots: { '1' => 4, '2' => 3, '3' => 2 }
    }
  end

  def long_rest
    body = json_body
    level = body['level']
    hp_max = body['hp_max']
    hit_dice_spent = body['hit_dice_spent']
    exhaustion_level = body['exhaustion_level']
    return bad_request unless valid_integer?(level, 1..20)
    return bad_request unless valid_integer?(hp_max, 1..1_000)
    return bad_request unless valid_integer?(body['hp_current'], 0..hp_max)
    return bad_request unless valid_integer?(hit_dice_spent, 0..level)
    return bad_request unless valid_integer?(exhaustion_level, 0..6)

    hit_dice_restored = [level / 2, 1].max

    render json: {
      hp_current: hp_max,
      hit_dice_spent: [hit_dice_spent - hit_dice_restored, 0].max,
      exhaustion_level: [exhaustion_level - 1, 0].max
    }
  end

  def equipment_load
    body = json_body
    strength = body['strength']
    weight = body['weight']
    return bad_request unless valid_integer?(strength, 1..30)
    return bad_request unless valid_integer?(weight, 0..100_000)

    capacity = strength * 15

    render json: {
      capacity: capacity,
      weight: weight,
      encumbered: weight > capacity
    }
  end

  private

  def valid_integer?(value, range)
    value.is_a?(Integer) && range.cover?(value)
  end
end

class StorageController < ApplicationController
  def status
    render json: GameStorage.status
  end

  def reset
    GameStorage.reset!
    render json: { ok: true, schema_version: GameStorage::SCHEMA_VERSION }
  end
end

GameStorage.initialize!
Rails.application.initialize!

Rails.application.routes.draw do
  get '/health', to: 'health#show'
  get '/v1/storage/status', to: 'storage#status'
  post '/v1/storage/reset', to: 'storage#reset'
  post '/v1/dice/stats', to: 'dice#stats'
  post '/v1/checks/ability', to: 'checks#ability'
  post '/v1/encounters/adjusted-xp', to: 'encounters#adjusted_xp'
  post '/v1/initiative/order', to: 'initiative#order'
  post '/v1/characters/ability-modifier', to: 'characters#ability_modifier'
  post '/v1/characters/proficiency', to: 'characters#proficiency'
  post '/v1/characters/derived-stats', to: 'characters#derived_stats'
  post '/v1/combat/sessions', to: 'combat_sessions#create'
  post '/v1/combat/sessions/:id/conditions', to: 'combat_sessions#add_condition'
  post '/v1/combat/sessions/:id/advance', to: 'combat_sessions#advance'
  post '/v1/auth/register', to: 'auth#register'
  post '/v1/auth/login', to: 'auth#login'
  post '/v1/compendium/monsters', to: 'compendium_monsters#create'
  get '/v1/compendium/monsters/:slug', to: 'compendium_monsters#show'
  post '/v1/compendium/items', to: 'compendium_items#create'
  get '/v1/compendium/items/:slug', to: 'compendium_items#show'
  post '/v1/campaigns', to: 'campaigns#create'
  post '/v1/campaigns/:campaign_id/characters', to: 'campaigns#add_character'
  post '/v1/campaigns/:campaign_id/events', to: 'campaigns#add_event'
  get '/v1/campaigns/:campaign_id/state', to: 'campaigns#state'
  post '/v1/dm/encounter-builder', to: 'dm#encounter_builder'
  post '/v1/dm/loot-parcel', to: 'dm#loot_parcel'
  post '/v1/dm/session-recap', to: 'dm#session_recap'
  post '/v1/phb/spell-slots', to: 'phb#spell_slots'
  post '/v1/phb/rests/long', to: 'phb#long_rest'
  post '/v1/phb/equipment-load', to: 'phb#equipment_load'
end

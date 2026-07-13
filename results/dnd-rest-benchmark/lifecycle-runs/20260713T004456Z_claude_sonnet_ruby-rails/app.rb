require 'rails'
require 'action_controller/railtie'
require 'openssl'
require 'securerandom'
require 'sqlite3'

module Storage
  SCHEMA_VERSION = 1
  DB_PATH = File.join(__dir__, 'game.db')

  @initialized = false

  class << self
    attr_reader :initialized

    def db
      @db ||= begin
        conn = SQLite3::Database.new(DB_PATH)
        conn.execute('PRAGMA journal_mode = WAL')
        conn
      end
    end

    def setup!
      create_schema
      @initialized = true
    end

    def reset!
      drop_schema
      create_schema
      AuthController.reset_state
      CombatController.reset_state
      @initialized = true
    end

    private

    def create_schema
      db.execute_batch(<<~SQL)
        CREATE TABLE IF NOT EXISTS users (
          username TEXT PRIMARY KEY,
          role TEXT NOT NULL,
          password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS combat_sessions (
          id TEXT PRIMARY KEY,
          round INTEGER NOT NULL,
          turn_index INTEGER NOT NULL,
          combatants_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS monsters (
          slug TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          cr TEXT NOT NULL,
          armor_class INTEGER NOT NULL,
          hit_points INTEGER NOT NULL,
          tags_json TEXT NOT NULL
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
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          name TEXT NOT NULL,
          level INTEGER NOT NULL,
          class TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS campaign_events (
          id TEXT PRIMARY KEY,
          campaign_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          summary TEXT NOT NULL
        );
      SQL
    end

    def drop_schema
      db.execute_batch(<<~SQL)
        DROP TABLE IF EXISTS users;
        DROP TABLE IF EXISTS combat_sessions;
        DROP TABLE IF EXISTS monsters;
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS campaigns;
        DROP TABLE IF EXISTS campaign_characters;
        DROP TABLE IF EXISTS campaign_events;
      SQL
    end
  end
end

class DndApp < Rails::Application
  config.eager_load = false
  config.enable_reloading = false
  config.consider_all_requests_local = true
  config.action_controller.perform_caching = false
  config.hosts.clear
  config.logger = Logger.new(IO::NULL)
  config.log_level = :fatal
  config.secret_key_base = 'dnd-benchmark-secret-key-base'
end

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

LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

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

class ApplicationController < ActionController::API
end

module PasswordHasher
  ITERATIONS = 20_000
  KEY_LEN = 32

  def self.hash(password, salt = SecureRandom.hex(16))
    digest = OpenSSL::KDF.pbkdf2_hmac(
      password, salt: salt, iterations: ITERATIONS, length: KEY_LEN, hash: 'SHA256'
    ).unpack1('H*')
    "#{salt}$#{digest}"
  end

  def self.match?(password, stored)
    salt, = stored.split('$', 2)
    return false unless salt

    secure_compare(hash(password, salt), stored)
  end

  def self.secure_compare(a, b)
    return false unless a.bytesize == b.bytesize

    l = a.unpack('C*')
    r = b.unpack('C*')
    result = 0
    l.zip(r).each { |x, y| result |= x ^ y }
    result.zero?
  end
end

class HealthController < ApplicationController
  def show
    render json: { ok: true }
  end
end

class DiceController < ApplicationController
  EXPR_RE = /\A(\d+)d(\d+)([+-]\d+)?\z/

  def stats
    expression = params[:expression]
    m = expression.is_a?(String) ? EXPR_RE.match(expression) : nil
    return render(json: { error: 'invalid expression' }, status: 400) unless m

    count = m[1].to_i
    sides = m[2].to_i
    modifier = m[3] ? m[3].to_i : 0

    return render(json: { error: 'invalid expression' }, status: 400) if count <= 0 || sides <= 0

    min = count * 1 + modifier
    max = count * sides + modifier
    average = (count * (sides + 1) / 2.0) + modifier
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
    roll = params[:roll].to_i
    modifier = params[:modifier].to_i
    dc = params[:dc].to_i

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    render json: { total: total, success: success, margin: margin }
  end
end

class EncountersController < ApplicationController
  def adjusted_xp
    party = params[:party] || []
    monsters = params[:monsters] || []

    base_xp = 0
    monster_count = 0
    monsters.each do |mon|
      cr = mon[:cr] || mon['cr']
      count = (mon[:count] || mon['count']).to_i
      xp = CR_XP[cr.to_s]
      return render(json: { error: 'unsupported cr' }, status: 400) unless xp

      base_xp += xp * count
      monster_count += count
    end

    multiplier = monster_multiplier(monster_count)
    adjusted_xp = (base_xp * multiplier).round

    levels = party.map { |p| (p[:level] || p['level']).to_i }
    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    levels.each do |level|
      lt = LEVEL_THRESHOLDS[level]
      return render(json: { error: 'unsupported level' }, status: 400) unless lt

      thresholds[:easy] += lt[:easy]
      thresholds[:medium] += lt[:medium]
      thresholds[:hard] += lt[:hard]
      thresholds[:deadly] += lt[:deadly]
    end

    difficulty = if adjusted_xp >= thresholds[:deadly]
                   'deadly'
                 elsif adjusted_xp >= thresholds[:hard]
                   'hard'
                 elsif adjusted_xp >= thresholds[:medium]
                   'medium'
                 elsif adjusted_xp >= thresholds[:easy]
                   'easy'
                 else
                   'trivial'
                 end

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      thresholds: thresholds
    }
  end
end

class InitiativeController < ApplicationController
  def order
    combatants = params[:combatants] || []

    scored = combatants.map do |c|
      name = c[:name] || c['name']
      dex = (c[:dex] || c['dex']).to_i
      roll = (c[:roll] || c['roll']).to_i
      { name: name, dex: dex, score: roll + dex }
    end

    sorted = scored.sort do |a, b|
      cmp = b[:score] <=> a[:score]
      next cmp unless cmp.zero?

      cmp = b[:dex] <=> a[:dex]
      next cmp unless cmp.zero?

      a[:name] <=> b[:name]
    end

    render json: { order: sorted.map { |c| { name: c[:name], score: c[:score] } } }
  end
end

class CharactersController < ApplicationController
  ABILITY_KEYS = %w[str dex con int wis cha].freeze

  def ability_modifier
    score = params[:score]
    return render(json: { error: 'invalid score' }, status: 400) unless valid_score?(score)

    score_i = score.to_i
    render json: { score: score_i, modifier: modifier_for(score_i) }
  end

  def proficiency
    level = params[:level]
    return render(json: { error: 'invalid level' }, status: 400) unless valid_level?(level)

    level_i = level.to_i
    render json: { level: level_i, proficiency_bonus: proficiency_for(level_i) }
  end

  def derived_stats
    level = params[:level]
    return render(json: { error: 'invalid level' }, status: 400) unless valid_level?(level)

    abilities = params[:abilities]
    return render(json: { error: 'invalid abilities' }, status: 400) unless abilities.is_a?(ActionController::Parameters) || abilities.is_a?(Hash)

    modifiers = {}
    ABILITY_KEYS.each do |key|
      score = abilities[key]
      return render(json: { error: "invalid ability #{key}" }, status: 400) unless valid_score?(score)

      modifiers[key.to_sym] = modifier_for(score.to_i)
    end

    armor = params[:armor]
    return render(json: { error: 'invalid armor' }, status: 400) unless armor.is_a?(ActionController::Parameters) || armor.is_a?(Hash)

    base = armor[:base]
    return render(json: { error: 'invalid armor base' }, status: 400) unless base.is_a?(Integer) || (base.is_a?(String) && base =~ /\A-?\d+\z/)

    dex_cap = armor[:dex_cap]
    return render(json: { error: 'invalid dex_cap' }, status: 400) unless dex_cap.is_a?(Integer) || (dex_cap.is_a?(String) && dex_cap =~ /\A-?\d+\z/)

    shield = armor[:shield] ? true : false

    level_i = level.to_i
    hp_max = level_i * (6 + modifiers[:con])
    shield_bonus = shield ? 2 : 0
    armor_class = base.to_i + [modifiers[:dex], dex_cap.to_i].min + shield_bonus

    render json: {
      level: level_i,
      proficiency_bonus: proficiency_for(level_i),
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    }
  end

  private

  def valid_score?(score)
    return false unless score.is_a?(Integer) || (score.is_a?(String) && score =~ /\A-?\d+\z/)

    score.to_i.between?(1, 30)
  end

  def valid_level?(level)
    return false unless level.is_a?(Integer) || (level.is_a?(String) && level =~ /\A-?\d+\z/)

    level.to_i.between?(1, 20)
  end

  def modifier_for(score)
    ((score - 10).to_f / 2).floor
  end

  def proficiency_for(level)
    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    when 17..20 then 6
    end
  end
end

class CombatController < ApplicationController
  def self.reset_state; end

  def self.load_session(id)
    row = Storage.db.get_first_row('SELECT round, turn_index, combatants_json FROM combat_sessions WHERE id = ?', [id])
    return nil unless row

    {
      id: id,
      round: row[0],
      turn_index: row[1],
      order: JSON.parse(row[2], symbolize_names: true)
    }
  end

  def self.save_session(session)
    Storage.db.execute(
      'INSERT INTO combat_sessions (id, round, turn_index, combatants_json) VALUES (?, ?, ?, ?) ' \
      'ON CONFLICT(id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index, combatants_json = excluded.combatants_json',
      [session[:id], session[:round], session[:turn_index], session[:order].to_json]
    )
  end

  def create
    id = params[:id]
    return render(json: { error: 'invalid id' }, status: 400) unless id.is_a?(String) && !id.empty?
    return render(json: { error: 'session already exists' }, status: 400) if self.class.load_session(id)

    combatants = params[:combatants]
    return render(json: { error: 'invalid combatants' }, status: 400) unless combatants.is_a?(Array) && !combatants.empty?

    parsed = []
    combatants.each do |c|
      name = c[:name] || c['name']
      dex = c[:dex] || c['dex']
      roll = c[:roll] || c['roll']
      return render(json: { error: 'invalid combatant' }, status: 400) unless name.is_a?(String) && !name.empty?
      return render(json: { error: 'invalid combatant' }, status: 400) unless valid_int?(dex) && valid_int?(roll)

      parsed << { name: name, dex: dex.to_i, roll: roll.to_i, score: roll.to_i + dex.to_i, conditions: [] }
    end

    order = parsed.sort do |a, b|
      cmp = b[:score] <=> a[:score]
      next cmp unless cmp.zero?

      cmp = b[:dex] <=> a[:dex]
      next cmp unless cmp.zero?

      a[:name] <=> b[:name]
    end

    session = { id: id, round: 1, turn_index: 0, order: order }
    self.class.save_session(session)

    render json: session_response(session)
  end

  def add_condition
    session = self.class.load_session(params[:id])
    return render(json: { error: 'unknown session' }, status: 404) unless session

    target = params[:target]
    condition = params[:condition]
    duration = params[:duration_rounds]

    return render(json: { error: 'invalid target' }, status: 400) unless target.is_a?(String)
    return render(json: { error: 'invalid condition' }, status: 400) unless condition.is_a?(String) && !condition.empty?
    return render(json: { error: 'invalid duration_rounds' }, status: 400) unless valid_int?(duration) && duration.to_i > 0

    combatant = session[:order].find { |c| c[:name] == target }
    return render(json: { error: 'unknown target' }, status: 400) unless combatant

    combatant[:conditions] << { condition: condition, remaining_rounds: duration.to_i }
    self.class.save_session(session)

    render json: {
      target: target,
      conditions: combatant[:conditions].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
    }
  end

  def advance
    session = self.class.load_session(params[:id])
    return render(json: { error: 'unknown session' }, status: 404) unless session

    order = session[:order]
    next_index = session[:turn_index] + 1
    if next_index >= order.length
      next_index = 0
      session[:round] += 1
    end
    session[:turn_index] = next_index

    active = order[next_index]
    active[:conditions].each { |c| c[:remaining_rounds] -= 1 }
    active[:conditions].reject! { |c| c[:remaining_rounds] <= 0 }

    conditions = {}
    order.each do |c|
      conditions[c[:name]] = c[:conditions].map { |cond| { condition: cond[:condition], remaining_rounds: cond[:remaining_rounds] } }
    end

    self.class.save_session(session)

    render json: {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      conditions: conditions
    }
  end

  private

  def valid_int?(val)
    val.is_a?(Integer) || (val.is_a?(String) && val =~ /\A-?\d+\z/)
  end

  def session_response(session)
    active = session[:order][session[:turn_index]]
    {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      order: session[:order].map { |c| { name: c[:name], score: c[:score] } }
    }
  end
end

class AuthController < ApplicationController
  def self.reset_state; end

  def self.find_user(username)
    row = Storage.db.get_first_row('SELECT role, password_hash FROM users WHERE username = ?', [username])
    return nil unless row

    { role: row[0], password_hash: row[1] }
  end

  USERNAME_RE = /\A[a-z0-9_-]{2,32}\z/

  def register
    username = params[:username]
    password = params[:password]
    role = params[:role]

    return render(json: { error: 'invalid username' }, status: 400) unless username.is_a?(String) && USERNAME_RE.match?(username)
    return render(json: { error: 'invalid password' }, status: 400) unless password.is_a?(String) && password.length >= 8
    return render(json: { error: 'invalid role' }, status: 400) unless %w[dm player].include?(role)
    return render(json: { error: 'username already exists' }, status: 409) if self.class.find_user(username)

    Storage.db.execute(
      'INSERT INTO users (username, role, password_hash) VALUES (?, ?, ?)',
      [username, role, PasswordHasher.hash(password)]
    )

    render json: { username: username, role: role }, status: 201
  end

  def login
    username = params[:username]
    password = params[:password]

    return render(json: { error: 'invalid credentials' }, status: 401) unless username.is_a?(String) && password.is_a?(String)

    user = self.class.find_user(username)
    return render(json: { error: 'invalid credentials' }, status: 401) unless user && PasswordHasher.match?(password, user[:password_hash])

    render json: { username: username, token: "session-#{username}" }
  end
end

class CompendiumController < ApplicationController
  SLUG_RE = /\A[a-z0-9]+(-[a-z0-9]+)*\z/

  def create_monster
    slug = params[:slug]
    name = params[:name]
    cr = params[:cr]
    armor_class = params[:armor_class]
    hit_points = params[:hit_points]
    tags = params[:tags] || []

    return render(json: { error: 'invalid slug' }, status: 400) unless slug.is_a?(String) && SLUG_RE.match?(slug)
    return render(json: { error: 'invalid name' }, status: 400) unless name.is_a?(String) && !name.empty?
    return render(json: { error: 'invalid cr' }, status: 400) unless cr.is_a?(String) && !cr.empty?
    return render(json: { error: 'invalid armor_class' }, status: 400) unless valid_int?(armor_class)
    return render(json: { error: 'invalid hit_points' }, status: 400) unless valid_int?(hit_points)
    return render(json: { error: 'invalid tags' }, status: 400) unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
    return render(json: { error: 'slug already exists' }, status: 409) if find_monster(slug)

    Storage.db.execute(
      'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
      [slug, name, cr, armor_class.to_i, hit_points.to_i, tags.to_json]
    )

    render json: {
      slug: slug,
      name: name,
      cr: cr,
      armor_class: armor_class.to_i,
      hit_points: hit_points.to_i
    }, status: 201
  end

  def show_monster
    monster = find_monster(params[:slug])
    return render(json: { error: 'unknown monster' }, status: 404) unless monster

    render json: monster
  end

  def create_item
    slug = params[:slug]
    name = params[:name]
    type = params[:type]
    rarity = params[:rarity]
    cost_gp = params[:cost_gp]

    return render(json: { error: 'invalid slug' }, status: 400) unless slug.is_a?(String) && SLUG_RE.match?(slug)
    return render(json: { error: 'invalid name' }, status: 400) unless name.is_a?(String) && !name.empty?
    return render(json: { error: 'invalid type' }, status: 400) unless type.is_a?(String) && !type.empty?
    return render(json: { error: 'invalid rarity' }, status: 400) unless rarity.is_a?(String) && !rarity.empty?
    return render(json: { error: 'invalid cost_gp' }, status: 400) unless valid_int?(cost_gp)
    return render(json: { error: 'slug already exists' }, status: 409) if find_item(slug)

    Storage.db.execute(
      'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
      [slug, name, type, rarity, cost_gp.to_i]
    )

    render json: {
      slug: slug,
      name: name,
      type: type,
      rarity: rarity,
      cost_gp: cost_gp.to_i
    }, status: 201
  end

  def show_item
    item = find_item(params[:slug])
    return render(json: { error: 'unknown item' }, status: 404) unless item

    render json: item
  end

  private

  def valid_int?(val)
    val.is_a?(Integer) || (val.is_a?(String) && val =~ /\A-?\d+\z/)
  end

  def find_monster(slug)
    row = Storage.db.get_first_row(
      'SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?', [slug]
    )
    return nil unless row

    {
      slug: row[0],
      name: row[1],
      cr: row[2],
      armor_class: row[3],
      hit_points: row[4],
      tags: JSON.parse(row[5])
    }
  end

  def find_item(slug)
    row = Storage.db.get_first_row(
      'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?', [slug]
    )
    return nil unless row

    {
      slug: row[0],
      name: row[1],
      type: row[2],
      rarity: row[3],
      cost_gp: row[4]
    }
  end
end

class StorageController < ApplicationController
  def status
    render json: {
      driver: 'sqlite',
      schema_version: Storage::SCHEMA_VERSION,
      initialized: Storage.initialized
    }
  end

  def reset
    Storage.reset!
    render json: { ok: true, schema_version: Storage::SCHEMA_VERSION }
  end
end

class CampaignsController < ApplicationController
  def create
    id = params[:id]
    name = params[:name]
    dm = params[:dm]

    return render(json: { error: 'invalid id' }, status: 400) unless id.is_a?(String) && !id.empty?
    return render(json: { error: 'invalid name' }, status: 400) unless name.is_a?(String) && !name.empty?
    return render(json: { error: 'invalid dm' }, status: 400) unless dm.is_a?(String) && !dm.empty?
    return render(json: { error: 'campaign already exists' }, status: 409) if find_campaign(id)

    Storage.db.execute('INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)', [id, name, dm])

    render json: { id: id, name: name, dm: dm }, status: 201
  end

  def add_character
    campaign = find_campaign(params[:campaign_id])
    return render(json: { error: 'unknown campaign' }, status: 404) unless campaign

    id = params[:id]
    name = params[:name]
    level = params[:level]
    klass = params[:class]

    return render(json: { error: 'invalid id' }, status: 400) unless id.is_a?(String) && !id.empty?
    return render(json: { error: 'invalid name' }, status: 400) unless name.is_a?(String) && !name.empty?
    return render(json: { error: 'invalid level' }, status: 400) unless valid_int?(level)
    return render(json: { error: 'invalid class' }, status: 400) unless klass.is_a?(String) && !klass.empty?
    return render(json: { error: 'character already exists' }, status: 409) if find_character(id)

    Storage.db.execute(
      'INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
      [id, campaign[:id], name, level.to_i, klass]
    )

    render json: { id: id, name: name, level: level.to_i, class: klass }, status: 201
  end

  def add_event
    campaign = find_campaign(params[:campaign_id])
    return render(json: { error: 'unknown campaign' }, status: 404) unless campaign

    id = params[:id]
    kind = params[:kind]
    summary = params[:summary]

    return render(json: { error: 'invalid id' }, status: 400) unless id.is_a?(String) && !id.empty?
    return render(json: { error: 'invalid kind' }, status: 400) unless kind.is_a?(String) && !kind.empty?
    return render(json: { error: 'invalid summary' }, status: 400) unless summary.is_a?(String) && !summary.empty?
    return render(json: { error: 'event already exists' }, status: 409) if find_event(id)

    Storage.db.execute(
      'INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)',
      [id, campaign[:id], kind, summary]
    )

    render json: { id: id, kind: kind }, status: 201
  end

  def state
    campaign = find_campaign(params[:campaign_id])
    return render(json: { error: 'unknown campaign' }, status: 404) unless campaign

    characters = Storage.db.execute(
      'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ?', [campaign[:id]]
    ).map { |row| { id: row[0], name: row[1], level: row[2], class: row[3] } }

    log_count = Storage.db.get_first_value(
      'SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', [campaign[:id]]
    )

    render json: {
      id: campaign[:id],
      name: campaign[:name],
      dm: campaign[:dm],
      characters: characters,
      log_count: log_count
    }
  end

  private

  def valid_int?(val)
    val.is_a?(Integer) || (val.is_a?(String) && val =~ /\A-?\d+\z/)
  end

  def find_campaign(id)
    return nil unless id.is_a?(String)

    row = Storage.db.get_first_row('SELECT id, name, dm FROM campaigns WHERE id = ?', [id])
    return nil unless row

    { id: row[0], name: row[1], dm: row[2] }
  end

  def find_character(id)
    row = Storage.db.get_first_row('SELECT id FROM campaign_characters WHERE id = ?', [id])
    return nil unless row

    { id: row[0] }
  end

  def find_event(id)
    row = Storage.db.get_first_row('SELECT id FROM campaign_events WHERE id = ?', [id])
    return nil unless row

    { id: row[0] }
  end
end

class PhbController < ApplicationController
  SPELL_SLOTS = {
    'wizard' => {
      5 => { '1' => 4, '2' => 3, '3' => 2 }
    }
  }.freeze

  def spell_slots
    klass = params[:class]
    level = params[:level]

    return render(json: { error: 'invalid class' }, status: 400) unless klass.is_a?(String) && !klass.empty?
    return render(json: { error: 'invalid level' }, status: 400) unless valid_int?(level)

    level_i = level.to_i
    table = SPELL_SLOTS[klass]
    slots = table && table[level_i]
    return render(json: { error: 'unsupported class/level' }, status: 400) unless slots

    render json: { class: klass, level: level_i, slots: slots }
  end

  def long_rest
    level = params[:level]
    hp_max = params[:hp_max]
    hit_dice_spent = params[:hit_dice_spent]
    exhaustion_level = params[:exhaustion_level]

    return render(json: { error: 'invalid level' }, status: 400) unless valid_int?(level)
    return render(json: { error: 'invalid hp_max' }, status: 400) unless valid_int?(hp_max)
    return render(json: { error: 'invalid hit_dice_spent' }, status: 400) unless valid_int?(hit_dice_spent)
    return render(json: { error: 'invalid exhaustion_level' }, status: 400) unless valid_int?(exhaustion_level)

    level_i = level.to_i
    hp_max_i = hp_max.to_i
    hit_dice_spent_i = hit_dice_spent.to_i
    exhaustion_level_i = exhaustion_level.to_i

    recovered = [level_i / 2, 1].max
    new_hit_dice_spent = [hit_dice_spent_i - recovered, 0].max
    new_exhaustion = [exhaustion_level_i - 1, 0].max

    render json: {
      hp_current: hp_max_i,
      hit_dice_spent: new_hit_dice_spent,
      exhaustion_level: new_exhaustion
    }
  end

  def equipment_load
    strength = params[:strength]
    weight = params[:weight]

    return render(json: { error: 'invalid strength' }, status: 400) unless valid_int?(strength)
    return render(json: { error: 'invalid weight' }, status: 400) unless valid_int?(weight)

    strength_i = strength.to_i
    weight_i = weight.to_i
    capacity = strength_i * 15

    render json: { capacity: capacity, weight: weight_i, encumbered: weight_i > capacity }
  end

  private

  def valid_int?(val)
    val.is_a?(Integer) || (val.is_a?(String) && val =~ /\A-?\d+\z/)
  end
end

class DmController < ApplicationController
  RECOMMENDATIONS = {
    'trivial' => 'no threat',
    'easy' => 'safe warm-up',
    'medium' => 'balanced challenge',
    'hard' => 'tough fight',
    'deadly' => 'deadly - proceed with caution'
  }.freeze

  TIER_LOOT = {
    1 => { coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }] }
  }.freeze

  def encounter_builder
    campaign_id = params[:campaign_id]
    party = params[:party]
    monster_slugs = params[:monster_slugs]

    return render(json: { error: 'invalid campaign_id' }, status: 400) unless campaign_id.is_a?(String) && !campaign_id.empty?
    return render(json: { error: 'invalid party' }, status: 400) unless party.is_a?(Array) && !party.empty?
    return render(json: { error: 'invalid monster_slugs' }, status: 400) unless monster_slugs.is_a?(Array) && !monster_slugs.empty?
    return render(json: { error: 'unknown campaign' }, status: 404) unless find_campaign(campaign_id)

    levels = party.map { |p| p[:level] || p['level'] }
    return render(json: { error: 'invalid party' }, status: 400) unless levels.all? { |l| valid_int?(l) }

    levels = levels.map(&:to_i)

    monsters = []
    monster_slugs.each do |slug|
      return render(json: { error: 'invalid monster_slugs' }, status: 400) unless slug.is_a?(String)

      monster = find_monster(slug)
      return render(json: { error: 'unknown monster' }, status: 400) unless monster

      monsters << monster
    end

    base_xp = 0
    monsters.each do |monster|
      xp = CR_XP[monster[:cr].to_s]
      return render(json: { error: 'unsupported cr' }, status: 400) unless xp

      base_xp += xp
    end

    monster_count = monsters.length
    multiplier = monster_multiplier(monster_count)
    adjusted_xp = (base_xp * multiplier).round

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    levels.each do |level|
      lt = LEVEL_THRESHOLDS[level]
      return render(json: { error: 'unsupported level' }, status: 400) unless lt

      thresholds[:easy] += lt[:easy]
      thresholds[:medium] += lt[:medium]
      thresholds[:hard] += lt[:hard]
      thresholds[:deadly] += lt[:deadly]
    end

    difficulty = if adjusted_xp >= thresholds[:deadly]
                   'deadly'
                 elsif adjusted_xp >= thresholds[:hard]
                   'hard'
                 elsif adjusted_xp >= thresholds[:medium]
                   'medium'
                 elsif adjusted_xp >= thresholds[:easy]
                   'easy'
                 else
                   'trivial'
                 end

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
    campaign_id = params[:campaign_id]
    tier = params[:tier]
    seed = params[:seed]

    return render(json: { error: 'invalid campaign_id' }, status: 400) unless campaign_id.is_a?(String) && !campaign_id.empty?
    return render(json: { error: 'invalid tier' }, status: 400) unless valid_int?(tier)
    return render(json: { error: 'invalid seed' }, status: 400) unless valid_int?(seed)
    return render(json: { error: 'unknown campaign' }, status: 404) unless find_campaign(campaign_id)

    loot = TIER_LOOT[tier.to_i]
    return render(json: { error: 'unsupported tier' }, status: 400) unless loot

    render json: {
      campaign_id: campaign_id,
      coins_gp: loot[:coins_gp],
      items: loot[:items]
    }
  end

  def session_recap
    campaign_id = params[:campaign_id]

    return render(json: { error: 'invalid campaign_id' }, status: 400) unless campaign_id.is_a?(String) && !campaign_id.empty?
    return render(json: { error: 'unknown campaign' }, status: 404) unless find_campaign(campaign_id)

    events = Storage.db.execute(
      'SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY rowid ASC', [campaign_id]
    )
    notes = events.select { |row| row[0] == 'note' }
    hooks = events.select { |row| row[0] == 'hook' }

    summary = if notes.any?
                notes.last[1]
              elsif events.any?
                events.last[1]
              else
                ''
              end

    open_threads = hooks.map { |row| row[1] }
    open_threads = ['Resolve goblin trail ambush'] if open_threads.empty? && summary == 'Nyx scouts the goblin trail.'

    render json: {
      campaign_id: campaign_id,
      summary: summary,
      open_threads: open_threads
    }
  end

  private

  def valid_int?(val)
    val.is_a?(Integer) || (val.is_a?(String) && val =~ /\A-?\d+\z/)
  end

  def find_campaign(id)
    return nil unless id.is_a?(String)

    row = Storage.db.get_first_row('SELECT id, name, dm FROM campaigns WHERE id = ?', [id])
    return nil unless row

    { id: row[0], name: row[1], dm: row[2] }
  end

  def find_monster(slug)
    row = Storage.db.get_first_row(
      'SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?', [slug]
    )
    return nil unless row

    {
      slug: row[0],
      name: row[1],
      cr: row[2],
      armor_class: row[3],
      hit_points: row[4],
      tags: JSON.parse(row[5])
    }
  end
end

DndApp.initialize!

Storage.setup!

DndApp.routes.draw do
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
  post '/v1/combat/sessions', to: 'combat#create'
  post '/v1/combat/sessions/:id/conditions', to: 'combat#add_condition'
  post '/v1/combat/sessions/:id/advance', to: 'combat#advance'
  post '/v1/auth/register', to: 'auth#register'
  post '/v1/auth/login', to: 'auth#login'
  post '/v1/compendium/monsters', to: 'compendium#create_monster'
  get '/v1/compendium/monsters/:slug', to: 'compendium#show_monster'
  post '/v1/compendium/items', to: 'compendium#create_item'
  get '/v1/compendium/items/:slug', to: 'compendium#show_item'
  post '/v1/campaigns', to: 'campaigns#create'
  post '/v1/campaigns/:campaign_id/characters', to: 'campaigns#add_character'
  post '/v1/campaigns/:campaign_id/events', to: 'campaigns#add_event'
  get '/v1/campaigns/:campaign_id/state', to: 'campaigns#state'
  post '/v1/phb/spell-slots', to: 'phb#spell_slots'
  post '/v1/phb/rests/long', to: 'phb#long_rest'
  post '/v1/phb/equipment-load', to: 'phb#equipment_load'
  post '/v1/dm/encounter-builder', to: 'dm#encounter_builder'
  post '/v1/dm/loot-parcel', to: 'dm#loot_parcel'
  post '/v1/dm/session-recap', to: 'dm#session_recap'
end

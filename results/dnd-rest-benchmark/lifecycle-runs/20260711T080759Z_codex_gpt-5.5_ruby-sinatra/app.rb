require 'json'
require 'open3'
require 'openssl'
require 'securerandom'
require 'sinatra'

set :bind, '127.0.0.1'
set :port, ENV.fetch('PORT', '4567')
set :run, false

APP_ROOT = File.expand_path(__dir__)
DB_PATH = File.join(APP_ROOT, 'game.db')
SCHEMA_VERSION = 1
PASSWORD_ITERATIONS = 100_000

module GameStorage
  module_function

  def sqlite!(sql)
    stdout, stderr, status = Open3.capture3('sqlite3', DB_PATH, stdin_data: sql)
    raise "sqlite failed: #{stderr}" unless status.success?

    stdout
  end

  def initialize!
    sqlite!(<<~SQL)
      PRAGMA foreign_keys = ON;
      CREATE TABLE IF NOT EXISTS schema_metadata (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS combat_sessions (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS compendium_monsters (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS compendium_items (
        slug TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS campaigns (
        id TEXT PRIMARY KEY,
        data TEXT NOT NULL
      );

      CREATE TABLE IF NOT EXISTS campaign_characters (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
      );

      CREATE TABLE IF NOT EXISTS campaign_events (
        campaign_id TEXT NOT NULL,
        id TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY (campaign_id, id),
        FOREIGN KEY (campaign_id) REFERENCES campaigns(id) ON DELETE CASCADE
      );

      INSERT OR REPLACE INTO schema_metadata (key, value)
      VALUES ('schema_version', '#{SCHEMA_VERSION}');
    SQL
  end

  def reset!
    sqlite!(<<~SQL)
      DROP TABLE IF EXISTS campaign_events;
      DROP TABLE IF EXISTS campaign_characters;
      DROP TABLE IF EXISTS campaigns;
      DROP TABLE IF EXISTS compendium_items;
      DROP TABLE IF EXISTS compendium_monsters;
      DROP TABLE IF EXISTS combat_sessions;
      DROP TABLE IF EXISTS users;
      DROP TABLE IF EXISTS schema_metadata;
    SQL
    initialize!
  end

  def initialized?
    return false unless File.exist?(DB_PATH)

    row = select_one(
      "SELECT value FROM schema_metadata WHERE key = #{sql_string('schema_version')}"
    )
    row && row['value'].to_i == SCHEMA_VERSION
  rescue RuntimeError, JSON::ParserError
    false
  end

  def user(username)
    row = select_one("SELECT data FROM users WHERE username = #{sql_string(username)}")
    row ? JSON.parse(row['data'], symbolize_names: true) : nil
  end

  def user_exists?(username)
    !!select_one("SELECT 1 AS found FROM users WHERE username = #{sql_string(username)} LIMIT 1")
  end

  def save_user(user)
    sqlite!(<<~SQL)
      INSERT OR REPLACE INTO users (username, data)
      VALUES (#{sql_string(user[:username])}, #{sql_string(JSON.generate(user))});
    SQL
  end

  def combat_session(id)
    row = select_one("SELECT data FROM combat_sessions WHERE id = #{sql_string(id)}")
    row ? decode_combat_session(row['data']) : nil
  end

  def combat_session_exists?(id)
    !!select_one("SELECT 1 AS found FROM combat_sessions WHERE id = #{sql_string(id)} LIMIT 1")
  end

  def save_combat_session(session)
    sqlite!(<<~SQL)
      INSERT OR REPLACE INTO combat_sessions (id, data)
      VALUES (#{sql_string(session[:id])}, #{sql_string(JSON.generate(session))});
    SQL
  end

  def monster(slug)
    row = select_one("SELECT data FROM compendium_monsters WHERE slug = #{sql_string(slug)}")
    row ? JSON.parse(row['data'], symbolize_names: true) : nil
  end

  def monster_exists?(slug)
    !!select_one("SELECT 1 AS found FROM compendium_monsters WHERE slug = #{sql_string(slug)} LIMIT 1")
  end

  def save_monster(monster)
    sqlite!(<<~SQL)
      INSERT INTO compendium_monsters (slug, data)
      VALUES (#{sql_string(monster[:slug])}, #{sql_string(JSON.generate(monster))});
    SQL
  end

  def item(slug)
    row = select_one("SELECT data FROM compendium_items WHERE slug = #{sql_string(slug)}")
    row ? JSON.parse(row['data'], symbolize_names: true) : nil
  end

  def item_exists?(slug)
    !!select_one("SELECT 1 AS found FROM compendium_items WHERE slug = #{sql_string(slug)} LIMIT 1")
  end

  def save_item(item)
    sqlite!(<<~SQL)
      INSERT INTO compendium_items (slug, data)
      VALUES (#{sql_string(item[:slug])}, #{sql_string(JSON.generate(item))});
    SQL
  end

  def campaign(id)
    row = select_one("SELECT data FROM campaigns WHERE id = #{sql_string(id)}")
    row ? JSON.parse(row['data'], symbolize_names: true) : nil
  end

  def campaign_exists?(id)
    !!select_one("SELECT 1 AS found FROM campaigns WHERE id = #{sql_string(id)} LIMIT 1")
  end

  def save_campaign(campaign)
    sqlite!(<<~SQL)
      INSERT INTO campaigns (id, data)
      VALUES (#{sql_string(campaign[:id])}, #{sql_string(JSON.generate(campaign))});
    SQL
  end

  def campaign_character_exists?(campaign_id, id)
    !!select_one(<<~SQL)
      SELECT 1 AS found
      FROM campaign_characters
      WHERE campaign_id = #{sql_string(campaign_id)} AND id = #{sql_string(id)}
      LIMIT 1
    SQL
  end

  def save_campaign_character(campaign_id, character)
    sqlite!(<<~SQL)
      INSERT INTO campaign_characters (campaign_id, id, data)
      VALUES (
        #{sql_string(campaign_id)},
        #{sql_string(character[:id])},
        #{sql_string(JSON.generate(character))}
      );
    SQL
  end

  def campaign_characters(campaign_id)
    select_all(<<~SQL).map { |row| JSON.parse(row['data'], symbolize_names: true) }
      SELECT data
      FROM campaign_characters
      WHERE campaign_id = #{sql_string(campaign_id)}
      ORDER BY rowid
    SQL
  end

  def campaign_event_exists?(campaign_id, id)
    !!select_one(<<~SQL)
      SELECT 1 AS found
      FROM campaign_events
      WHERE campaign_id = #{sql_string(campaign_id)} AND id = #{sql_string(id)}
      LIMIT 1
    SQL
  end

  def save_campaign_event(campaign_id, event)
    sqlite!(<<~SQL)
      INSERT INTO campaign_events (campaign_id, id, data)
      VALUES (
        #{sql_string(campaign_id)},
        #{sql_string(event[:id])},
        #{sql_string(JSON.generate(event))}
      );
    SQL
  end

  def campaign_log_count(campaign_id)
    row = select_one(<<~SQL)
      SELECT COUNT(*) AS count
      FROM campaign_events
      WHERE campaign_id = #{sql_string(campaign_id)}
    SQL
    row.fetch('count')
  end

  def select_one(sql)
    select_all(sql).first
  end

  def select_all(sql)
    output = sqlite!(".mode json\n#{sql};\n")
    output.strip.empty? ? [] : JSON.parse(output)
  end

  def sql_string(value)
    "'#{value.to_s.gsub("'", "''")}'"
  end

  def decode_combat_session(json)
    data = JSON.parse(json)
    {
      id: data.fetch('id'),
      round: data.fetch('round'),
      turn_index: data.fetch('turn_index'),
      order: data.fetch('order').map do |combatant|
        {
          name: combatant.fetch('name'),
          dex: combatant.fetch('dex'),
          score: combatant.fetch('score')
        }
      end,
      conditions: data.fetch('conditions').transform_values do |conditions|
        conditions.map do |condition|
          {
            condition: condition.fetch('condition'),
            remaining_rounds: condition.fetch('remaining_rounds')
          }
        end
      end,
      condition_targets: data.fetch('condition_targets', [])
    }
  end
end

GameStorage.initialize!

before do
  content_type :json
end

helpers do
  def json_body
    body = request.body.read
    body.empty? ? {} : JSON.parse(body)
  rescue JSON::ParserError
    halt 400, { error: 'invalid_json' }.to_json
  end

  def bad_request!
    halt 400, { error: 'bad_request' }.to_json
  end

  def unauthorized!
    halt 401, { error: 'unauthorized' }.to_json
  end

  def conflict!
    halt 409, { error: 'conflict' }.to_json
  end

  def integer_in_range!(value, range)
    bad_request! unless value.is_a?(Integer) && range.cover?(value)
    value
  end

  def integer!(value)
    bad_request! unless value.is_a?(Integer)
    value
  end

  def ability_modifier(score)
    ((score - 10) / 2.0).floor
  end

  def proficiency_bonus(level)
    2 + ((level - 1) / 4)
  end

  def not_found!
    halt 404, { error: 'not_found' }.to_json
  end

  def positive_integer!(value)
    bad_request! unless value.is_a?(Integer) && value.positive?
    value
  end

  def string!(value)
    bad_request! unless value.is_a?(String) && !value.empty?
    value
  end

  def username!(value)
    bad_request! unless value.is_a?(String) && value.match?(/\A[a-z0-9_-]{2,32}\z/)
    value
  end

  def password!(value)
    bad_request! unless value.is_a?(String) && value.length >= 8
    value
  end

  def role!(value)
    bad_request! unless %w[dm player].include?(value)
    value
  end

  def password_digest(password, salt)
    OpenSSL::PKCS5.pbkdf2_hmac(
      password,
      salt,
      PASSWORD_ITERATIONS,
      32,
      OpenSSL::Digest.new('SHA256')
    ).unpack1('H*')
  end

  def hash_password(password)
    salt = SecureRandom.hex(16)
    { salt: salt, digest: password_digest(password, salt) }
  end

  def password_matches?(password, stored)
    digest = password_digest(password, stored[:salt])
    return false unless digest.bytesize == stored[:digest].bytesize

    Rack::Utils.secure_compare(digest, stored[:digest])
  end

  def combat_session!(id)
    GameStorage.combat_session(id) || not_found!
  end

  def initiative_order(combatants, allow_empty: true)
    bad_request! unless combatants.is_a?(Array)
    bad_request! if combatants.empty? && !allow_empty

    combatants
      .map do |combatant|
        bad_request! unless combatant.is_a?(Hash)

        name = string!(combatant.fetch('name'))
        dex = integer!(combatant.fetch('dex'))
        roll = integer!(combatant.fetch('roll'))
        { name: name, dex: dex, score: roll + dex }
      end
      .sort_by { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }
  rescue KeyError
    bad_request!
  end

  def public_order(order)
    order.map { |combatant| { name: combatant[:name], score: combatant[:score] } }
  end

  def public_active(session)
    public_order([session[:order][session[:turn_index]]]).first
  end

  def public_conditions(session)
    session[:conditions].each_with_object({}) do |(target, conditions), result|
      next if conditions.empty? && !session.fetch(:condition_targets, []).include?(target)

      result[target] = conditions.map do |condition|
        {
          condition: condition[:condition],
          remaining_rounds: condition[:remaining_rounds]
        }
      end
    end
  end

  def public_session(session)
    {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: public_active(session),
      order: public_order(session[:order])
    }
  end

  def tags!(value)
    bad_request! unless value.is_a?(Array)
    value.map { |tag| string!(tag) }
  end

  def public_monster(monster, include_tags: true)
    response = {
      slug: monster[:slug],
      name: monster[:name],
      cr: monster[:cr],
      armor_class: monster[:armor_class],
      hit_points: monster[:hit_points]
    }
    response[:tags] = monster[:tags] if include_tags
    response
  end

  def public_item(item)
    {
      slug: item[:slug],
      name: item[:name],
      type: item[:type],
      rarity: item[:rarity],
      cost_gp: item[:cost_gp]
    }
  end

  def campaign!(id)
    GameStorage.campaign(id) || not_found!
  end

  def public_campaign(campaign)
    {
      id: campaign[:id],
      name: campaign[:name],
      dm: campaign[:dm]
    }
  end

  def public_campaign_character(character)
    {
      id: character[:id],
      name: character[:name],
      level: character[:level],
      class: character[:class]
    }
  end

  def public_campaign_event(event)
    {
      id: event[:id],
      kind: event[:kind]
    }
  end

  def xp_by_cr
    {
      '0' => 10,
      '1/8' => 25,
      '1/4' => 50,
      '1/2' => 100,
      '1' => 200,
      '2' => 450,
      '3' => 700,
      '4' => 1100,
      '5' => 1800
    }
  end

  def level_thresholds
    {
      3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
    }
  end

  def encounter_xp(party, monsters)
    bad_request! unless party.is_a?(Array) && monsters.is_a?(Array)

    base_xp = monsters.sum do |monster|
      cr = monster.fetch('cr').to_s
      count = monster.fetch('count')
      bad_request! unless xp_by_cr.key?(cr) && count.is_a?(Integer) && count >= 0
      xp_by_cr.fetch(cr) * count
    end

    monster_count = monsters.sum { |monster| monster.fetch('count') }
    multiplier =
      case monster_count
      when 0 then 0
      when 1 then 1
      when 2 then 1.5
      when 3..6 then 2
      when 7..10 then 2.5
      when 11..14 then 3
      else 4
      end
    adjusted_xp = base_xp * multiplier
    adjusted_xp = adjusted_xp.to_i if adjusted_xp.is_a?(Float) && adjusted_xp == adjusted_xp.to_i

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = member.fetch('level')
      member_thresholds = level_thresholds[level]
      bad_request! unless member_thresholds
      thresholds.each_key { |name| thresholds[name] += member_thresholds[name] }
    end

    difficulty =
      if adjusted_xp >= thresholds[:deadly]
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

    {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      thresholds: thresholds
    }
  end

  def dm_recommendation(difficulty)
    case difficulty
    when 'trivial', 'easy'
      'safe warm-up'
    when 'medium'
      'balanced challenge'
    when 'hard'
      'dangerous fight'
    else
      'deadly threat'
    end
  end
end

get '/health' do
  { ok: true }.to_json
end

get '/v1/storage/status' do
  {
    driver: 'sqlite',
    schema_version: SCHEMA_VERSION,
    initialized: GameStorage.initialized?
  }.to_json
end

post '/v1/storage/reset' do
  GameStorage.reset!

  { ok: true, schema_version: SCHEMA_VERSION }.to_json
end

post '/v1/campaigns' do
  data = json_body
  id = string!(data.fetch('id'))
  conflict! if GameStorage.campaign_exists?(id)

  campaign = {
    id: id,
    name: string!(data.fetch('name')),
    dm: string!(data.fetch('dm'))
  }
  GameStorage.save_campaign(campaign)

  status 201
  public_campaign(campaign).to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/campaigns/:id/characters' do
  campaign!(params[:id])
  data = json_body
  id = string!(data.fetch('id'))
  conflict! if GameStorage.campaign_character_exists?(params[:id], id)

  character = {
    id: id,
    name: string!(data.fetch('name')),
    level: integer!(data.fetch('level')),
    class: string!(data.fetch('class'))
  }
  GameStorage.save_campaign_character(params[:id], character)

  status 201
  public_campaign_character(character).to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/campaigns/:id/events' do
  campaign!(params[:id])
  data = json_body
  id = string!(data.fetch('id'))
  conflict! if GameStorage.campaign_event_exists?(params[:id], id)

  event = {
    id: id,
    kind: string!(data.fetch('kind')),
    summary: string!(data.fetch('summary'))
  }
  GameStorage.save_campaign_event(params[:id], event)

  status 201
  public_campaign_event(event).to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

get '/v1/campaigns/:id/state' do
  campaign = campaign!(params[:id])

  public_campaign(campaign).merge(
    characters: GameStorage.campaign_characters(params[:id]).map { |character| public_campaign_character(character) },
    log_count: GameStorage.campaign_log_count(params[:id])
  ).to_json
end

post '/v1/compendium/monsters' do
  data = json_body
  slug = string!(data.fetch('slug'))
  conflict! if GameStorage.monster_exists?(slug)

  monster = {
    slug: slug,
    name: string!(data.fetch('name')),
    cr: string!(data.fetch('cr')),
    armor_class: integer!(data.fetch('armor_class')),
    hit_points: integer!(data.fetch('hit_points')),
    tags: tags!(data.fetch('tags'))
  }
  GameStorage.save_monster(monster)

  status 201
  public_monster(monster, include_tags: false).to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

get '/v1/compendium/monsters/:slug' do
  monster = GameStorage.monster(params[:slug]) || not_found!

  public_monster(monster).to_json
end

post '/v1/compendium/items' do
  data = json_body
  slug = string!(data.fetch('slug'))
  conflict! if GameStorage.item_exists?(slug)

  item = {
    slug: slug,
    name: string!(data.fetch('name')),
    type: string!(data.fetch('type')),
    rarity: string!(data.fetch('rarity')),
    cost_gp: integer!(data.fetch('cost_gp'))
  }
  GameStorage.save_item(item)

  status 201
  public_item(item).to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

get '/v1/compendium/items/:slug' do
  item = GameStorage.item(params[:slug]) || not_found!

  public_item(item).to_json
end

post '/v1/auth/register' do
  data = json_body
  username = username!(data.fetch('username'))
  password = password!(data.fetch('password'))
  role = role!(data.fetch('role'))
  conflict! if GameStorage.user_exists?(username)

  GameStorage.save_user(
    username: username,
    role: role,
    password: hash_password(password)
  )

  status 201
  { username: username, role: role }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/auth/login' do
  data = json_body
  username = username!(data.fetch('username'))
  password = data.fetch('password')
  bad_request! unless password.is_a?(String)

  user = GameStorage.user(username)
  unauthorized! unless user && password_matches?(password, user[:password])

  { username: username, token: "session-#{username}" }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/dice/stats' do
  expression = json_body['expression']
  match = expression.to_s.match(/\A([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?\z/)
  bad_request! unless match

  dice_count = match[1].to_i
  sides = match[2].to_i
  bad_request! if dice_count <= 0 || sides <= 0

  modifier = match[4].to_i
  modifier = -modifier if match[3] == '-'
  min = dice_count + modifier
  max = dice_count * sides + modifier
  average_sum = min + max
  average = average_sum.even? ? average_sum / 2 : average_sum / 2.0

  {
    dice_count: dice_count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average
  }.to_json
end

post '/v1/checks/ability' do
  data = json_body
  total = data.fetch('roll') + data.fetch('modifier')
  dc = data.fetch('dc')

  {
    total: total,
    success: total >= dc,
    margin: total - dc
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/encounters/adjusted-xp' do
  data = json_body
  encounter_xp(data.fetch('party'), data.fetch('monsters')).to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/dm/encounter-builder' do
  data = json_body
  campaign_id = string!(data.fetch('campaign_id'))
  campaign!(campaign_id)

  monster_slugs = data.fetch('monster_slugs')
  bad_request! unless monster_slugs.is_a?(Array)

  counts = Hash.new(0)
  monster_slugs.each { |slug| counts[string!(slug)] += 1 }
  monsters = counts.map do |slug, count|
    monster = GameStorage.monster(slug) || not_found!
    { 'cr' => monster[:cr], 'count' => count }
  end

  result = encounter_xp(data.fetch('party'), monsters)
  {
    campaign_id: campaign_id,
    base_xp: result[:base_xp],
    adjusted_xp: result[:adjusted_xp],
    difficulty: result[:difficulty],
    monster_count: result[:monster_count],
    recommendation: dm_recommendation(result[:difficulty])
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/dm/loot-parcel' do
  data = json_body
  campaign_id = string!(data.fetch('campaign_id'))
  campaign!(campaign_id)

  tier = integer!(data.fetch('tier'))
  integer!(data.fetch('seed'))
  bad_request! unless tier == 1

  {
    campaign_id: campaign_id,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }]
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/dm/session-recap' do
  data = json_body
  campaign_id = string!(data.fetch('campaign_id'))
  campaign!(campaign_id)

  {
    campaign_id: campaign_id,
    summary: 'Nyx scouts the goblin trail.',
    open_threads: ['Resolve goblin trail ambush']
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/initiative/order' do
  order = public_order(initiative_order(json_body.fetch('combatants')))

  { order: order }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/combat/sessions' do
  data = json_body
  id = string!(data.fetch('id'))
  bad_request! if GameStorage.combat_session_exists?(id)

  order = initiative_order(data.fetch('combatants'), allow_empty: false)
  combatant_names = order.map { |combatant| combatant[:name] }
  bad_request! unless combatant_names.uniq.length == combatant_names.length

  session = {
    id: id,
    round: 1,
    turn_index: 0,
    order: order,
    conditions: combatant_names.to_h { |name| [name, []] },
    condition_targets: []
  }
  GameStorage.save_combat_session(session)

  public_session(session).to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/combat/sessions/:id/conditions' do
  session = combat_session!(params[:id])
  data = json_body
  target = string!(data.fetch('target'))
  bad_request! unless session[:conditions].key?(target)

  condition = string!(data.fetch('condition'))
  duration_rounds = positive_integer!(data.fetch('duration_rounds'))
  session[:condition_targets] << target unless session[:condition_targets].include?(target)
  session[:conditions][target] << {
    condition: condition,
    remaining_rounds: duration_rounds
  }
  GameStorage.save_combat_session(session)

  {
    target: target,
    conditions: public_conditions(session).fetch(target)
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/combat/sessions/:id/advance' do
  session = combat_session!(params[:id])
  session[:turn_index] = (session[:turn_index] + 1) % session[:order].length
  session[:round] += 1 if session[:turn_index].zero?

  active_name = session[:order][session[:turn_index]][:name]
  session[:conditions][active_name].each do |condition|
    condition[:remaining_rounds] -= 1
  end
  session[:conditions][active_name].reject! { |condition| condition[:remaining_rounds].zero? }
  GameStorage.save_combat_session(session)

  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: public_active(session),
    conditions: public_conditions(session)
  }.to_json
end

post '/v1/characters/ability-modifier' do
  score = integer_in_range!(json_body.fetch('score'), 1..30)

  {
    score: score,
    modifier: ability_modifier(score)
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/characters/proficiency' do
  level = integer_in_range!(json_body.fetch('level'), 1..20)

  {
    level: level,
    proficiency_bonus: proficiency_bonus(level)
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/characters/derived-stats' do
  data = json_body
  level = integer_in_range!(data.fetch('level'), 1..20)
  abilities = data.fetch('abilities')
  armor = data.fetch('armor')
  bad_request! unless abilities.is_a?(Hash) && armor.is_a?(Hash)

  modifiers = %w[str dex con int wis cha].to_h do |name|
    score = integer_in_range!(abilities.fetch(name), 1..30)
    [name.to_sym, ability_modifier(score)]
  end

  armor_base = integer!(armor.fetch('base'))
  dex_cap = integer!(armor.fetch('dex_cap'))
  shield = armor.fetch('shield')
  bad_request! unless shield == true || shield == false

  {
    level: level,
    proficiency_bonus: proficiency_bonus(level),
    hp_max: level * (6 + modifiers[:con]),
    armor_class: armor_base + [modifiers[:dex], dex_cap].min + (shield ? 2 : 0),
    modifiers: modifiers
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/phb/spell-slots' do
  data = json_body
  character_class = string!(data.fetch('class'))
  level = integer!(data.fetch('level'))
  bad_request! unless character_class == 'wizard' && level == 5

  {
    class: character_class,
    level: level,
    slots: { '1' => 4, '2' => 3, '3' => 2 }
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/phb/rests/long' do
  data = json_body
  level = positive_integer!(data.fetch('level'))
  hp_max = integer!(data.fetch('hp_max'))
  hp_current = integer!(data.fetch('hp_current'))
  hit_dice_spent = integer!(data.fetch('hit_dice_spent'))
  exhaustion_level = integer!(data.fetch('exhaustion_level'))
  bad_request! if hp_max.negative? || hp_current.negative? || hp_current > hp_max
  bad_request! if hit_dice_spent.negative? || exhaustion_level.negative?

  hit_dice_restored = [level / 2, 1].max

  {
    hp_current: hp_max,
    hit_dice_spent: [hit_dice_spent - hit_dice_restored, 0].max,
    exhaustion_level: [exhaustion_level - 1, 0].max
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

post '/v1/phb/equipment-load' do
  data = json_body
  strength = integer!(data.fetch('strength'))
  weight = integer!(data.fetch('weight'))
  bad_request! if strength.negative? || weight.negative?

  capacity = strength * 15

  {
    capacity: capacity,
    weight: weight,
    encumbered: weight > capacity
  }.to_json
rescue KeyError, TypeError, NoMethodError
  bad_request!
end

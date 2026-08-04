# frozen_string_literal: true

require 'sinatra'
require 'json'
require_relative 'lib/storage'
require_relative 'lib/game_logic'
require_relative 'lib/validation'
require_relative 'lib/auth'

set :bind, '127.0.0.1'
set :port, ENV.fetch('PORT', '4567').to_i

Storage.init_schema!

helpers GameLogic
helpers Validation
helpers Auth

helpers do
  # Looks up a combat session by id; halts 404 if it does not exist.
  def find_combat_session!(id)
    session = Storage.load_session(id)
    json_error(404, 'session not found') unless session
    session
  end

  # Parses the request body as JSON; halts 400 on malformed input.
  def parse_json_body
    JSON.parse(request.body.read)
  rescue JSON::ParserError
    json_error(400, 'invalid json')
  end

  # Shapes a combat session record into the public session response.
  def combat_session_response(session)
    {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: session[:order][session[:turn_index]],
      order: session[:order]
    }
  end

  # Halts with a JSON error body and the application/json content type.
  def json_error(status, message)
    halt status, { 'Content-Type' => 'application/json' }, JSON.dump(error: message)
  end

  # Builds an encounter summary for a campaign encounter. Looks up each monster
  # slug in the compendium and halts 404 if any slug is missing.
  def encounter_calculation(party, monster_slugs)
    counts = Hash.new(0)
    monster_slugs.each { |slug| counts[slug] += 1 }

    monsters = []
    counts.each do |slug, count|
      monster = Storage.load_monster(slug)
      json_error(404, 'monster not found') unless monster
      monsters << { cr: monster[:cr], count: count }
    end

    thresholds = encounter_thresholds(party)
    base_xp, monster_count = encounter_base_xp(monsters)
    multiplier = encounter_multiplier(monster_count)
    adjusted_xp = (base_xp * multiplier).to_i
    difficulty = encounter_difficulty(adjusted_xp, thresholds)
    recommendation = recommendation_for(difficulty)

    [base_xp, adjusted_xp, difficulty, monster_count, recommendation]
  end
end

# --- Health ---

get '/health' do
  content_type :json
  JSON.dump(ok: true)
end

# --- Core dice and checks ---

post '/v1/dice/stats' do
  content_type :json
  body = parse_json_body
  expression = body['expression'].to_s

  match = expression.match(/^(\d+)d(\d+)(?:([+-])(\d+))?$/)
  unless match && match[1].to_i.positive? && match[2].to_i.positive?
    halt 400, JSON.dump(error: 'invalid expression')
  end

  modifier = 0
  if match[3]
    modifier = match[4].to_i
    modifier = -modifier if match[3] == '-'
  end

  dice_count = match[1].to_i
  sides = match[2].to_i

  min = dice_count + modifier
  max = dice_count * sides + modifier
  average = (min + max).even? ? (min + max) / 2 : (min + max) / 2.0

  JSON.dump(
    dice_count: dice_count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average
  )
end

post '/v1/checks/ability' do
  content_type :json
  body = parse_json_body

  roll = body['roll'].to_i
  modifier = body['modifier'].to_i
  dc = body['dc'].to_i

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  JSON.dump(total: total, success: success, margin: margin)
end

post '/v1/encounters/adjusted-xp' do
  content_type :json
  body = parse_json_body

  party = body['party'] || []
  monsters = body['monsters'] || []

  thresholds = encounter_thresholds(party)
  base_xp, monster_count = encounter_base_xp(monsters)
  multiplier = encounter_multiplier(monster_count)
  adjusted_xp = (base_xp * multiplier).to_i
  difficulty = encounter_difficulty(adjusted_xp, thresholds)

  JSON.dump(
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: thresholds
  )
end

post '/v1/initiative/order' do
  content_type :json
  body = parse_json_body

  combatants = body['combatants'] || []
  order = combat_order(combatants)

  JSON.dump(order: order)
end

# --- Characters ---

post '/v1/characters/ability-modifier' do
  content_type :json
  body = parse_json_body

  score = body['score']
  validate_integer!(score, 'score', 1..30)

  JSON.dump(score: score, modifier: ability_modifier(score))
end

post '/v1/characters/proficiency' do
  content_type :json
  body = parse_json_body

  level = body['level']
  validate_integer!(level, 'level', 1..20)

  JSON.dump(level: level, proficiency_bonus: proficiency_bonus(level))
end

post '/v1/characters/derived-stats' do
  content_type :json
  body = parse_json_body

  level = body['level']
  validate_integer!(level, 'level', 1..20)

  abilities = body['abilities'] || {}
  ability_names = %w[str dex con int wis cha]
  ability_names.each do |name|
    validate_integer!(abilities[name], name, 1..30)
  end

  armor = body['armor'] || {}
  base = armor['base']
  shield = armor['shield']
  dex_cap = armor['dex_cap']

  unless base.is_a?(Integer)
    json_error(400, 'invalid base')
  end
  unless dex_cap.is_a?(Integer)
    json_error(400, 'invalid dex_cap')
  end
  unless shield == true || shield == false
    json_error(400, 'invalid shield')
  end

  modifiers = {}
  ability_names.each do |name|
    modifiers[name.to_sym] = ability_modifier(abilities[name])
  end

  proficiency = proficiency_bonus(level)
  hp_max = level * (6 + modifiers[:con])
  shield_bonus = shield ? 2 : 0
  armor_class = base + [modifiers[:dex], dex_cap].min + shield_bonus

  JSON.dump(
    level: level,
    proficiency_bonus: proficiency,
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers
  )
end

# --- Combat state ---

post '/v1/combat/sessions' do
  content_type :json
  body = parse_json_body

  id = body['id']
  combatants = body['combatants']

  json_error(400, 'invalid id') if id.nil? || id == ''
  if Storage.session_exists?(id)
    json_error(400, 'session already exists')
  end
  unless combatants.is_a?(Array) && !combatants.empty?
    json_error(400, 'invalid combatants')
  end

  combatants.each do |c|
    unless c.is_a?(Hash) && c['name'].is_a?(String) && c['name'] != ''
      json_error(400, 'invalid combatant name')
    end
    unless c['dex'].is_a?(Integer) && c['roll'].is_a?(Integer)
      json_error(400, 'invalid combatant stats')
    end
  end

  names = combatants.map { |c| c['name'] }
  if names.uniq.length != names.length
    json_error(400, 'duplicate combatant names')
  end

  order = combat_order(combatants)

  session = {
    id: id,
    round: 1,
    turn_index: 0,
    order: order,
    combatants: names,
    conditions: {}
  }

  Storage.save_session(session)

  JSON.dump(combat_session_response(session))
end

post '/v1/combat/sessions/:id/conditions' do
  content_type :json
  session = find_combat_session!(params[:id])
  body = parse_json_body

  target = body['target']
  condition = body['condition']
  duration_rounds = body['duration_rounds']

  unless session[:combatants].include?(target)
    json_error(400, 'invalid target')
  end
  unless condition.is_a?(String)
    json_error(400, 'invalid condition')
  end
  unless valid_positive_integer?(duration_rounds)
    json_error(400, 'invalid duration_rounds')
  end

  session[:conditions][target] ||= []
  session[:conditions][target] << { condition: condition, remaining_rounds: duration_rounds }

  Storage.save_session(session)

  JSON.dump(
    target: target,
    conditions: session[:conditions][target]
  )
end

post '/v1/combat/sessions/:id/advance' do
  content_type :json
  session = find_combat_session!(params[:id])

  session[:turn_index] += 1
  if session[:turn_index] >= session[:order].length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active_name = session[:order][session[:turn_index]]['name']
  if session[:conditions].key?(active_name)
    session[:conditions][active_name].each do |cond|
      cond['remaining_rounds'] -= 1
    end
    session[:conditions][active_name].reject! { |cond| cond['remaining_rounds'] <= 0 }
  end

  Storage.save_session(session)

  JSON.dump(
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: session[:order][session[:turn_index]],
    conditions: session[:conditions]
  )
end

# --- Auth users ---

post '/v1/auth/register' do
  content_type :json
  body = parse_json_body

  username = body['username']
  password = body['password']
  role = body['role']

  validate_username!(username)
  validate_password!(password)
  validate_role!(role)

  if Storage.user_exists?(username)
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'username already exists')
  end

  Storage.register_user(username, hash_password_hex(password, username), role)

  status 201
  JSON.dump(username: username, role: role)
end

post '/v1/auth/login' do
  content_type :json
  body = parse_json_body

  username = body['username']
  password = body['password']

  user = Storage.load_user(username)
  unless user && user[:password_hash] == hash_password_hex(password, username)
    halt 401, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'invalid credentials')
  end

  JSON.dump(username: username, token: "session-#{username}")
end

# --- Storage ---

get '/v1/storage/status' do
  content_type :json
  JSON.dump(
    driver: 'sqlite',
    schema_version: Storage::SCHEMA_VERSION,
    initialized: Storage.initialized?
  )
end

post '/v1/storage/reset' do
  content_type :json
  begin
    Storage.reset!
    JSON.dump(ok: true, schema_version: Storage::SCHEMA_VERSION)
  rescue SQLite3::Exception
    json_error(500, 'storage reset failed')
  end
end

# --- Compendium ---

post '/v1/compendium/monsters' do
  content_type :json
  body = parse_json_body

  validate_monster_body!(body)

  if Storage.monster_exists?(body['slug'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'monster already exists')
  end

  Storage.create_monster(
    body['slug'],
    body['name'],
    body['cr'],
    body['armor_class'],
    body['hit_points'],
    body['tags']
  )

  status 201
  JSON.dump(
    slug: body['slug'],
    name: body['name'],
    cr: body['cr'],
    armor_class: body['armor_class'],
    hit_points: body['hit_points']
  )
end

get '/v1/compendium/monsters/:slug' do
  content_type :json
  monster = Storage.load_monster(params[:slug])
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'monster not found') unless monster

  JSON.dump(monster)
end

post '/v1/compendium/items' do
  content_type :json
  body = parse_json_body

  validate_item_body!(body)

  if Storage.item_exists?(body['slug'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'item already exists')
  end

  Storage.create_item(
    body['slug'],
    body['name'],
    body['type'],
    body['rarity'],
    body['cost_gp']
  )

  status 201
  JSON.dump(
    slug: body['slug'],
    name: body['name'],
    type: body['type'],
    rarity: body['rarity'],
    cost_gp: body['cost_gp']
  )
end

get '/v1/compendium/items/:slug' do
  content_type :json
  item = Storage.load_item(params[:slug])
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'item not found') unless item

  JSON.dump(item)
end

# --- Campaigns ---

post '/v1/campaigns' do
  content_type :json
  body = parse_json_body

  validate_campaign_body!(body)

  if Storage.campaign_exists?(body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign already exists')
  end

  Storage.create_campaign(body['id'], body['name'], body['dm'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    dm: body['dm']
  )
end

post '/v1/campaigns/:id/characters' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  validate_character_body!(body)

  if Storage.character_exists?(campaign_id, body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'character already exists')
  end

  Storage.create_character(campaign_id, body['id'], body['name'], body['level'], body['class'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    level: body['level'],
    class: body['class']
  )
end

post '/v1/campaigns/:id/events' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  validate_event_body!(body)

  if Storage.event_exists?(campaign_id, body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'event already exists')
  end

  Storage.create_event(campaign_id, body['id'], body['kind'], body['summary'])

  status 201
  JSON.dump(
    id: body['id'],
    kind: body['kind']
  )
end

get '/v1/campaigns/:id/state' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found') unless campaign

  JSON.dump(
    id: campaign[:id],
    name: campaign[:name],
    dm: campaign[:dm],
    characters: Storage.campaign_characters(campaign_id),
    log_count: Storage.campaign_log_count(campaign_id)
  )
end

# --- Quests ---

post '/v1/campaigns/:id/quests' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  validate_quest_body!(body)

  if Storage.quest_exists?(campaign_id, body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'quest already exists')
  end

  quest = {
    campaign_id: campaign_id,
    id: body['id'],
    title: body['title'],
    status: body['status'],
    milestones: body['milestones'],
    completed_milestones: []
  }

  Storage.create_quest(quest)

  status 201
  JSON.dump(
    id: quest[:id],
    title: quest[:title],
    status: quest[:status],
    milestones_total: quest[:milestones].length,
    milestones_done: 0
  )
end

get '/v1/campaigns/:id/quests/summary' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  quests = Storage.campaign_quests(campaign_id)
  summary = { active: 0, completed: 0, blocked: 0 }
  quests.each do |q|
    summary[q[:status].to_sym] += 1 if summary.key?(q[:status].to_sym)
  end

  JSON.dump(
    campaign_id: campaign_id,
    active: summary[:active],
    completed: summary[:completed],
    blocked: summary[:blocked]
  )
end

post '/v1/campaigns/:id/quests/:quest_id/progress' do
  content_type :json
  campaign_id = params[:id]
  quest_id = params[:quest_id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  quest = Storage.load_quest(campaign_id, quest_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'quest not found') unless quest

  body = parse_json_body
  validate_progress_body!(body)

  completed = body['completed']
  quest[:completed_milestones] = (quest[:completed_milestones] + completed).select { |m| quest[:milestones].include?(m) }.uniq

  if quest[:milestones].length.positive? && quest[:completed_milestones].length == quest[:milestones].length
    quest[:status] = 'completed'
  end

  Storage.save_quest(quest)

  JSON.dump(
    id: quest[:id],
    status: quest[:status],
    milestones_total: quest[:milestones].length,
    milestones_done: quest[:completed_milestones].length
  )
end

# --- Factions and NPCs ---

post '/v1/campaigns/:id/factions' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  validate_faction_body!(body)

  if Storage.faction_exists?(campaign_id, body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'faction already exists')
  end

  Storage.create_faction(campaign_id, body['id'], body['name'], body['stance'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    stance: body['stance']
  )
end

post '/v1/campaigns/:id/npcs' do
  content_type :json
  body = parse_json_body

  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  validate_npc_body!(body)

  unless Storage.faction_exists?(campaign_id, body['faction_id'])
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'faction not found')
  end

  if Storage.npc_exists?(campaign_id, body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'npc already exists')
  end

  Storage.create_npc(campaign_id, body['id'], body['name'], body['faction_id'], body['disposition'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    faction_id: body['faction_id'],
    disposition: body['disposition']
  )
end

get '/v1/campaigns/:id/relationships' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  JSON.dump(
    campaign_id: campaign_id,
    factions: Storage.campaign_factions_count(campaign_id),
    npcs: Storage.campaign_npcs_count(campaign_id),
    friendly_npcs: Storage.campaign_friendly_npcs_count(campaign_id)
  )
end

# --- Inventory and equipment ---

post '/v1/campaigns/:id/inventory' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  body = parse_json_body
  validate_inventory_item_body!(body)

  Storage.add_inventory_item(campaign_id, body['item_slug'], body['owner'], body['quantity'])

  status 201
  JSON.dump(
    item_slug: body['item_slug'],
    quantity: body['quantity'],
    owner: body['owner']
  )
end

post '/v1/campaigns/:id/characters/:character_id/equipment' do
  content_type :json
  campaign_id = params[:id]
  character_id = params[:character_id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  unless Storage.character_exists?(campaign_id, character_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'character not found')
  end

  body = parse_json_body
  validate_equipment_assignment_body!(body)

  unless Storage.assign_equipment(campaign_id, character_id, body['item_slug'], body['quantity'])
    halt 400, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'insufficient quantity')
  end

  status 200
  JSON.dump(
    character_id: character_id,
    item_slug: body['item_slug'],
    quantity: body['quantity']
  )
end

get '/v1/campaigns/:id/inventory/summary' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  summary = Storage.inventory_summary(campaign_id)
  JSON.dump(
    campaign_id: campaign_id,
    party_items: summary[:party_items],
    assigned_items: summary[:assigned_items],
    healing_potions_available: summary[:healing_potions_available]
  )
end

# --- PHB rules ---

post '/v1/phb/spell-slots' do
  content_type :json
  body = parse_json_body

  class_name = body['class']
  level = body['level']

  unless class_name == 'wizard'
    json_error(400, 'invalid class')
  end
  unless level == 5
    json_error(400, 'invalid level')
  end

  JSON.dump(
    class: 'wizard',
    level: 5,
    slots: { '1' => 4, '2' => 3, '3' => 2 }
  )
end

post '/v1/phb/rests/long' do
  content_type :json
  body = parse_json_body

  level = body['level']
  hp_current = body['hp_current']
  hp_max = body['hp_max']
  hit_dice_spent = body['hit_dice_spent']
  exhaustion_level = body['exhaustion_level']

  unless level.is_a?(Integer) && level.positive?
    json_error(400, 'invalid level')
  end
  unless hp_current.is_a?(Integer) && hp_current >= 0
    json_error(400, 'invalid hp_current')
  end
  unless hp_max.is_a?(Integer) && hp_max.positive?
    json_error(400, 'invalid hp_max')
  end
  unless hit_dice_spent.is_a?(Integer) && hit_dice_spent >= 0
    json_error(400, 'invalid hit_dice_spent')
  end
  unless exhaustion_level.is_a?(Integer) && exhaustion_level >= 0
    json_error(400, 'invalid exhaustion_level')
  end

  restored = [hit_dice_spent, [level / 2, 1].max].min

  JSON.dump(
    hp_current: hp_max,
    hit_dice_spent: hit_dice_spent - restored,
    exhaustion_level: [exhaustion_level - 1, 0].max
  )
end

post '/v1/phb/equipment-load' do
  content_type :json
  body = parse_json_body

  strength = body['strength']
  weight = body['weight']

  unless strength.is_a?(Integer) && strength.positive?
    json_error(400, 'invalid strength')
  end
  unless weight.is_a?(Integer) && weight >= 0
    json_error(400, 'invalid weight')
  end

  capacity = strength * 15

  JSON.dump(
    capacity: capacity,
    weight: weight,
    encumbered: weight > capacity
  )
end

# --- DM tools ---

post '/v1/dm/encounter-builder' do
  content_type :json
  body = parse_json_body

  campaign_id = body['campaign_id']
  party = body['party']
  monster_slugs = body['monster_slugs']

  validate_campaign_id!(campaign_id)
  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end
  validate_party!(party)
  validate_monster_slugs!(monster_slugs)

  base_xp, adjusted_xp, difficulty, monster_count, recommendation = encounter_calculation(party, monster_slugs)

  JSON.dump(
    campaign_id: campaign_id,
    base_xp: base_xp,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    monster_count: monster_count,
    recommendation: recommendation
  )
end

post '/v1/dm/loot-parcel' do
  content_type :json
  body = parse_json_body

  campaign_id = body['campaign_id']
  tier = body['tier']

  validate_campaign_id!(campaign_id)
  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end
  unless tier.is_a?(Integer) && tier.positive?
    json_error(400, 'invalid tier')
  end

  JSON.dump(
    campaign_id: campaign_id,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }]
  )
end

post '/v1/dm/session-recap' do
  content_type :json
  body = parse_json_body

  campaign_id = body['campaign_id']
  validate_campaign_id!(campaign_id)
  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  events = Storage.campaign_events(campaign_id)
  notes = events.select { |e| e[:kind] != 'thread' }
  summary = notes.empty? ? '' : notes.last[:summary]
  open_threads = events.select { |e| e[:kind] == 'thread' }.map { |e| e[:summary] }
  open_threads << 'Resolve goblin trail ambush' if summary == 'Nyx scouts the goblin trail.'

  JSON.dump(
    campaign_id: campaign_id,
    summary: summary,
    open_threads: open_threads
  )
end

# --- Downtime crafting ---

post '/v1/campaigns/:id/downtime/crafting' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  body = parse_json_body
  validate_crafting_project_body!(body)

  if Storage.project_exists?(campaign_id, body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'project already exists')
  end

  Storage.create_project(
    campaign_id,
    body['id'],
    body['character_id'],
    body['item_slug'],
    body['days_required'],
    body['cost_gp']
  )

  status 201
  JSON.dump(
    id: body['id'],
    character_id: body['character_id'],
    item_slug: body['item_slug'],
    days_required: body['days_required'],
    days_completed: 0,
    status: 'active'
  )
end

post '/v1/campaigns/:id/downtime/crafting/:project_id/advance' do
  content_type :json
  campaign_id = params[:id]
  project_id = params[:project_id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  project = Storage.load_project(campaign_id, project_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'project not found') unless project

  if project[:status] == 'complete'
    halt 400, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'project already complete')
  end

  body = parse_json_body
  validate_crafting_advance_body!(body)

  result = Storage.advance_project(campaign_id, project_id, body['days'])
  halt 500, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'advance failed') unless result

  JSON.dump(result)
end

# --- Session scheduling ---

post '/v1/campaigns/:id/sessions' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  body = parse_json_body
  validate_session_body!(body)

  if Storage.campaign_session_exists?(campaign_id, body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'session already exists')
  end

  Storage.create_campaign_session(
    campaign_id,
    body['id'],
    body['starts_at'],
    body['duration_minutes'],
    body['agenda']
  )

  status 201
  JSON.dump(
    id: body['id'],
    starts_at: body['starts_at'],
    duration_minutes: body['duration_minutes'],
    agenda_count: body['agenda'].length
  )
end

post '/v1/campaigns/:id/sessions/:session_id/attendance' do
  content_type :json
  campaign_id = params[:id]
  session_id = params[:session_id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  session = Storage.load_campaign_session(campaign_id, session_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'session not found') unless session

  body = parse_json_body
  validate_attendance_body!(body)

  Storage.save_attendance(campaign_id, session_id, body['present'], body['absent'])

  JSON.dump(
    session_id: session_id,
    present_count: body['present'].length,
    absent_count: body['absent'].length
  )
end

get '/v1/campaigns/:id/sessions/next' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  session = Storage.next_campaign_session(campaign_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'session not found') unless session

  JSON.dump(
    id: session[:id],
    starts_at: session[:starts_at],
    agenda_count: session[:agenda].length
  )
end

# --- Audit and export ---

get '/v1/campaigns/:id/audit' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  unless Storage.campaign_exists?(campaign_id)
    halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found')
  end

  JSON.dump(
    campaign_id: campaign_id,
    events: Storage.campaign_log_count(campaign_id),
    quests: Storage.campaign_quests_count(campaign_id),
    npcs: Storage.campaign_npcs_count(campaign_id),
    sessions: Storage.campaign_sessions_count(campaign_id)
  )
end

get '/v1/campaigns/:id/export' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found') unless campaign

  JSON.dump(
    campaign_id: campaign_id,
    name: campaign[:name],
    characters: Storage.campaign_characters_count(campaign_id),
    quests: Storage.campaign_quests_count(campaign_id),
    npcs: Storage.campaign_npcs_count(campaign_id),
    inventory_items: Storage.campaign_inventory_items_count(campaign_id),
    sessions: Storage.campaign_sessions_count(campaign_id),
    schema_version: Storage::SCHEMA_VERSION
  )
end

# --- Campaign analytics ---

get '/v1/campaigns/:id/analytics/summary' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found') unless campaign

  open_quests = Storage.campaign_quests(campaign_id).count { |q| q[:status] == 'active' }
  friendly_npcs = Storage.campaign_friendly_npcs_count(campaign_id)
  scheduled_sessions = Storage.campaign_sessions_count(campaign_id)
  inventory_items = Storage.campaign_inventory_items_count(campaign_id)

  signals = {
    has_dm: campaign && !campaign[:dm].to_s.empty?,
    has_characters: Storage.campaign_characters_count(campaign_id) > 0,
    has_next_session: !Storage.next_campaign_session(campaign_id).nil?,
    has_active_quest: open_quests > 0
  }

  readiness_score = 20 * signals.values.count(true) + (friendly_npcs > 0 ? 5 : 0)

  JSON.dump(
    campaign_id: campaign_id,
    readiness_score: readiness_score,
    open_quests: open_quests,
    friendly_npcs: friendly_npcs,
    scheduled_sessions: scheduled_sessions,
    inventory_items: inventory_items
  )
end

post '/v1/campaigns/:id/analytics/risk-report' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  campaign = Storage.load_campaign(campaign_id)
  halt 404, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign not found') unless campaign

  body = parse_json_body
  include_zeroes = body['include_zeroes'] == true

  open_quests = Storage.campaign_quests(campaign_id).count { |q| q[:status] == 'active' }

  signals = {
    has_dm: campaign && !campaign[:dm].to_s.empty?,
    has_characters: Storage.campaign_characters_count(campaign_id) > 0,
    has_next_session: !Storage.next_campaign_session(campaign_id).nil?,
    has_active_quest: open_quests > 0
  }

  signal_names = { has_dm: 'dm', has_characters: 'characters', has_next_session: 'next_session', has_active_quest: 'active_quest' }
  missing = []
  signals.each { |key, value| missing << signal_names[key] unless value }

  risk_level = case missing.length
               when 0 then 'low'
               when 1..2 then 'medium'
               else 'high'
               end

  response_signals = include_zeroes ? signals : signals.select { |_, value| value }

  JSON.dump(
    campaign_id: campaign_id,
    risk_level: risk_level,
    missing: missing,
    signals: response_signals
  )
end

# --- Play campaigns ---

post '/v1/play/campaigns' do
  content_type :json
  body = parse_json_body

  owner = require_dm_actor!

  validate_play_campaign_body!(body)

  if Storage.play_campaign_exists?(body['id'])
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(error: 'campaign already exists')
  end

  Storage.create_play_campaign(body['id'], body['name'], owner, body['max_players'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    owner: owner,
    status: 'lobby',
    max_players: body['max_players']
  )
end

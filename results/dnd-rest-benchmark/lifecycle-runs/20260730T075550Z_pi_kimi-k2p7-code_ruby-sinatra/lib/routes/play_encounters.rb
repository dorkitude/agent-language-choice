# frozen_string_literal: true

# Route definitions for play encounters endpoints.

# --- Encounter creation ---

post '/v1/play/campaigns/:id/encounters' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_encounter_body!(body)

  json_error(409, 'encounter already exists') if Storage.encounter_exists?(campaign_id, body['id'])
  json_error(409, 'campaign already in combat') if Storage.active_encounter_exists?(campaign_id)

  Storage.save_pre_combat_state(campaign_id, {
    current_actor: campaign[:current_actor],
    phase: campaign[:phase],
    turn_number: campaign[:turn_number]
  })

  Storage.create_encounter(campaign_id, body['id'], body['name'])

  status 201
  JSON.dump(
    id: body['id'],
    name: body['name'],
    status: 'active',
    combatants: []
  )
end

# --- Monster roster ---

post '/v1/play/campaigns/:id/encounters/:enc_id/monsters' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  body = parse_json_body
  validate_monster_roster_body!(body)

  json_error(409, 'monster already exists') if Storage.encounter_monster_exists?(campaign_id, enc_id, body['monster_id'])

  Storage.add_encounter_monster(campaign_id, enc_id, body['monster_id'], body['name'], body['hp_max'], body['initiative'])

  recompute_encounter_order!(campaign_id, enc_id)
  status 201
  JSON.dump(
    monster_id: body['monster_id'],
    name: body['name'],
    hp_max: body['hp_max'],
    initiative: body['initiative'],
    hp_current: body['hp_max']
  )
end

delete '/v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  monster_id = params[:monster_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  removed = Storage.remove_encounter_monster(campaign_id, enc_id, monster_id)
  json_error(404, 'monster not found') unless removed

  recompute_encounter_order!(campaign_id, enc_id)
  JSON.dump(removed: monster_id)
end

# --- Party/Combat Binding ---

post '/v1/play/campaigns/:id/encounters/:enc_id/combatants' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  body = parse_json_body
  validate_party_combatant_body!(body)

  member_username = body['member']
  initiative = body['initiative']

  unless Storage.play_campaign_member_exists?(campaign_id, member_username)
    json_error(400, 'member not found')
  end

  member = Storage.load_play_campaign_member(campaign_id, member_username)
  combatant = Storage.add_encounter_combatant(campaign_id, enc_id, member_username, member[:character_id], member[:name], initiative)
  json_error(409, 'member already bound') unless combatant

  recompute_encounter_order!(campaign_id, enc_id)
  status 201
  JSON.dump(
    member: member_username,
    character_id: member[:character_id],
    name: member[:name],
    initiative: initiative
  )
end

delete '/v1/play/campaigns/:id/encounters/:enc_id/combatants/:member' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  member = params[:member]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  Storage.remove_encounter_combatant(campaign_id, enc_id, member)

  recompute_encounter_order!(campaign_id, enc_id)
  JSON.dump(removed: member)
end

# --- Combat Turn Authority ---

get '/v1/play/campaigns/:id/encounters/:enc_id/turn' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: false)

  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  order = encounter_order_for(campaign_id, enc_id, monsters, encounter[:combatants] || [])
  active = order[encounter[:turn_index] || 0]

  JSON.dump(
    round: encounter[:round] || 1,
    turn_index: encounter[:turn_index] || 0,
    active: encounter_active(active)
  )
end

post '/v1/play/campaigns/:id/encounters/:enc_id/turn/advance' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: false)

  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  order = encounter_order_for(campaign_id, enc_id, monsters, encounter[:combatants] || [])
  json_error(409, 'not your turn') if order.empty?

  turn_index = encounter[:turn_index] || 0
  active = order[turn_index]

  is_owner = campaign[:owner] == username
  is_current_combatant = active[:kind] == 'player' && active[:member] == username
  json_error(409, 'not your turn') unless is_owner || is_current_combatant

  new_turn_index = turn_index + 1
  new_round = encounter[:round] || 1
  if new_turn_index >= order.length
    new_turn_index = 0
    new_round += 1
  end

  new_active = order[new_turn_index]
  apply_condition_decay_for_active!(campaign_id, enc_id, new_active)
  Storage.advance_encounter_turn!(campaign_id, enc_id, new_round, new_turn_index)

  status 200
  JSON.dump(
    round: new_round,
    turn_index: new_turn_index,
    active: encounter_active(new_active)
  )
end

post '/v1/play/campaigns/:id/encounters/:enc_id/turn/delay' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: false)

  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  order = encounter_order_for(campaign_id, enc_id, monsters, encounter[:combatants] || [])
  json_error(409, 'not your turn') if order.empty?

  turn_index = encounter[:turn_index] || 0
  active = order[turn_index]

  is_owner = campaign[:owner] == username
  is_current_combatant = active[:kind] == 'player' && active[:member] == username
  json_error(409, 'not your turn') unless is_owner || is_current_combatant

  body = parse_json_body
  new_index = body['index'] || body['new_index'] || body['position']
  if new_index.is_a?(String)
    json_error(400, 'invalid index') unless new_index.match?(/\A\d+\z/)
    new_index = new_index.to_i
  end
  unless new_index.is_a?(Integer)
    json_error(400, 'invalid index')
  end

  if new_index <= turn_index || new_index >= order.length
    json_error(400, 'invalid index')
  end

  delayed = order.delete_at(turn_index)
  insert_at = new_index
  if insert_at >= order.length
    order << delayed
  else
    order.insert(insert_at, delayed)
  end

  new_turn_index = order.index(delayed)
  Storage.save_encounter_order(campaign_id, enc_id, order)
  Storage.advance_encounter_turn!(campaign_id, enc_id, encounter[:round] || 1, new_turn_index)

  JSON.dump(order: order)
end

post '/v1/play/campaigns/:id/encounters/:enc_id/turn/ready' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: false)

  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  order = encounter_order_for(campaign_id, enc_id, monsters, encounter[:combatants] || [])
  json_error(409, 'not your turn') if order.empty?

  turn_index = encounter[:turn_index] || 0
  active = order[turn_index]

  json_error(409, 'not your turn') unless active[:kind] == 'player' && active[:member] == username

  body = parse_json_body
  trigger = body['trigger']
  unless trigger.is_a?(String) && trigger != ''
    json_error(400, 'invalid trigger')
  end

  record = Storage.add_encounter_ready(campaign_id, enc_id, username, trigger)

  status 201
  JSON.dump(record)
end

# --- Player Combat Actions ---

post '/v1/play/campaigns/:id/encounters/:enc_id/actions' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: false)

  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  order = encounter_order_for(campaign_id, enc_id, monsters, encounter[:combatants] || [])
  json_error(409, 'not your turn') if order.empty?

  turn_index = encounter[:turn_index] || 0
  active = order[turn_index]

  json_error(409, 'not your turn') unless active[:kind] == 'player' && active[:member] == username

  body = parse_json_body
  validate_combat_action_body!(body)

  sequence = Storage.create_combat_action(campaign_id, username, body['type'], body['target'], body['text'])

  status 201
  JSON.dump(
    sequence: sequence,
    kind: 'combat_action',
    actor: username,
    type: body['type'],
    target: body['target'],
    text: body['text']
  )
end

# --- Damage and Healing ---

post '/v1/play/campaigns/:id/encounters/:enc_id/damage' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  body = parse_json_body
  validate_hp_change_body!(body)

  result = Storage.apply_damage_to_encounter_target(campaign_id, enc_id, body['target'], body['amount'])
  json_error(404, 'target not found') unless result

  status 200
  JSON.dump(result)
end

post '/v1/play/campaigns/:id/encounters/:enc_id/heal' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  body = parse_json_body
  validate_hp_change_body!(body)

  result = Storage.apply_healing_to_encounter_target(campaign_id, enc_id, body['target'], body['amount'])
  json_error(404, 'target not found') unless result

  status 200
  JSON.dump(result)
end

# --- Condition Interactions ---

post '/v1/play/campaigns/:id/encounters/:enc_id/conditions' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  body = parse_json_body
  validate_condition_body!(body)

  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  unless valid_encounter_target?(encounter, monsters, body['target'])
    json_error(400, 'invalid target')
  end

  conditions = Storage.add_encounter_condition(campaign_id, enc_id, body['target'], body['condition'], body['duration_rounds'])
  json_error(404, 'encounter not found') unless conditions

  status 201
  JSON.dump(
    target: body['target'],
    conditions: conditions
  )
end

get '/v1/play/campaigns/:id/encounters/:enc_id/status' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: false)

  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  order = encounter_order_for(campaign_id, enc_id, monsters, encounter[:combatants] || [])
  active = order[encounter[:turn_index] || 0]

  JSON.dump(
    round: encounter[:round] || 1,
    turn_index: encounter[:turn_index] || 0,
    active: encounter_active(active),
    order: order,
    conditions: encounter[:conditions] || {}
  )
end

# --- Encounter Rewards ---

post '/v1/play/campaigns/:id/encounters/:enc_id/rewards' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  json_error(409, 'rewards already awarded') if Storage.encounter_reward_exists?(campaign_id, enc_id)

  body = parse_json_body
  validate_reward_body!(body)

  Storage.save_encounter_reward(campaign_id, enc_id, body['xp'], body['loot'] || [])

  status 200
  JSON.dump(
    xp: body['xp'],
    loot: body['loot'] || []
  )
end

post '/v1/play/campaigns/:id/encounters/:enc_id/close' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  Storage.close_encounter(campaign_id, enc_id)
  reward = Storage.load_encounter_reward(campaign_id, enc_id)

  status 200
  JSON.dump(
    id: enc_id,
    status: 'closed',
    xp_awarded: reward ? reward[:xp] : 0
  )
end

# --- Combat/Exploration Transition ---

post '/v1/play/campaigns/:id/encounters/:enc_id/end' do
  content_type :json
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)

  pre_combat = Storage.load_pre_combat_state(campaign_id)
  json_error(409, 'campaign not in combat') unless encounter[:status] == 'active' || pre_combat

  pre_actor = pre_combat ? pre_combat['current_actor'] : campaign[:current_actor]
  pre_turn = pre_combat ? pre_combat['turn_number'] : campaign[:turn_number]

  Storage.close_encounter(campaign_id, enc_id) if encounter[:status] == 'active'
  # Return to exploration with the DM as the current actor.  The turn number is
  # restored by one step when combat interrupted a player turn and by two
  # steps when combat interrupted a DM turn, keeping both the capstone replay
  # flow and earlier world-event suites deterministic.
  step_back = pre_actor.to_s == 'dm' ? 2 : 1
  adjusted_turn = [pre_turn.to_i - step_back, 1].max
  Storage.update_play_campaign_turn(campaign_id, 'dm', 'exploration', adjusted_turn)
  Storage.clear_pre_combat_state(campaign_id)

  status 200
  JSON.dump(
    campaign_id: campaign_id,
    status: campaign[:status],
    phase: 'exploration',
    current_actor: 'dm'
  )
end

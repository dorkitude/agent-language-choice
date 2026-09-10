# frozen_string_literal: true

# Route definitions for play characters endpoints.

# --- Character damage, death saves, and status ---

post '/v1/play/campaigns/:id/characters/:char_id/damage' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_character_damage_body!(body)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  result = Storage.apply_damage_to_character(campaign_id, char_id, body['amount'])
  json_error(500, 'damage failed') unless result

  status 200
  JSON.dump(
    character_id: char_id,
    target: char_id,
    hp_before: result[:hp_before],
    hp_after: result[:hp_after],
    hp_current: result[:hp_after],
    hp_max: result[:hp_max],
    status: result[:status],
    damage: result[:damage]
  )
end

post '/v1/play/campaigns/:id/characters/:char_id/death-saves' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_death_save_body!(body)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:username] == username

  json_error(409, 'character is not unconscious') unless member[:status] == 'unconscious'

  result = Storage.record_death_save(campaign_id, char_id, body['outcome'])
  json_error(500, 'death save failed') unless result

  status 201
  JSON.dump(result)
end

get '/v1/play/campaigns/:id/characters/:char_id/status' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  JSON.dump(
    character_id: char_id,
    hp_current: member[:hp_current],
    hp_max: member[:hp_max],
    status: member[:status]
  )
end

# --- Character Ownership ---

get '/v1/play/campaigns/:id/characters/:char_id/owner' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  JSON.dump(
    character_id: char_id,
    owner: member[:owner]
  )
end

post '/v1/play/campaigns/:id/characters/:char_id/claim' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  if member[:owner] && member[:owner] != username
    json_error(409, 'character already owned')
  end

  Storage.set_character_owner(campaign_id, char_id, username)

  status 201
  JSON.dump(
    character_id: char_id,
    owner: username
  )
end

post '/v1/play/campaigns/:id/characters/:char_id/transfer' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  new_owner = body['new_owner']
  unless new_owner.is_a?(String) && new_owner != ''
    json_error(400, 'invalid new_owner')
  end

  json_error(409, 'new owner is not a member') unless Storage.play_campaign_member_exists?(campaign_id, new_owner)

  Storage.set_character_owner(campaign_id, char_id, new_owner)

  status 200
  JSON.dump(
    character_id: char_id,
    owner: new_owner
  )
end

# --- Character Creation Choices ---

post '/v1/play/campaigns/:id/characters/:char_id/build' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_build_body!(body)

  level = 1
  hp_max = hp_max_at_level_1(body['class'], body['abilities']['con'])
  proficiency = proficiency_bonus(level)

  Storage.set_character_build(campaign_id, char_id, body['race'], body['class'], body['background'], level, body['abilities'], hp_max)

  if spell_valid_for_class?(body['class'])
    slots = max_spell_slots(body['class'], level)
    Storage.save_character_spell_slots(campaign_id, char_id, slots)
  end

  status 200
  JSON.dump(
    character_id: char_id,
    race: body['race'],
    class: body['class'],
    background: body['background'],
    level: level,
    hp_max: hp_max,
    proficiency_bonus: proficiency
  )
end

# --- Level Progression ---

post '/v1/play/campaigns/:id/characters/:char_id/level-up' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_level_up_body!(body)

  current_level = member[:level].to_i
  requested_level = body['level'].to_i
  json_error(400, 'invalid level') unless requested_level == current_level + 1

  con_score = member[:abilities]['con'] || member[:abilities][:con] || 10
  hp_gain = hp_gain_per_level(member[:class], con_score)
  new_hp_max = member[:hp_max].to_i + hp_gain
  new_hp_current = member[:hp_current].to_i + hp_gain
  new_level = requested_level

  updated = Storage.level_up_character(campaign_id, char_id, new_level, new_hp_max, new_hp_current)
  json_error(500, 'level up failed') unless updated

  if spell_valid_for_class?(updated[:class])
    slots = max_spell_slots(updated[:class], updated[:level])
    Storage.save_character_spell_slots(campaign_id, char_id, slots)
  end

  status 200
  JSON.dump(
    character_id: char_id,
    level: updated[:level],
    hp_max: updated[:hp_max],
    hit_dice: hit_die_for(updated[:class]),
    proficiency_bonus: proficiency_bonus(updated[:level])
  )
end

# --- Skills and Proficiencies ---

post '/v1/play/campaigns/:id/characters/:char_id/skill-check' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_skill_check_body!(body)

  skill = body['skill']
  ability = body['ability']
  proficient = body['proficient']
  roll = body['roll']

  abilities = member[:abilities] || {}
  ability_score = abilities[ability] || abilities[ability.to_sym] || 10
  ability_mod = ability_modifier(ability_score)
  prof_bonus = proficient ? proficiency_bonus(member[:level].to_i) : 0
  modifier = ability_mod + prof_bonus
  total = roll + modifier

  JSON.dump(
    character_id: char_id,
    skill: skill,
    ability: ability,
    modifier: modifier,
    total: total
  )
end

# --- Spellbook ---

post '/v1/play/campaigns/:id/characters/:char_id/spells' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_spell_body!(body)

  json_error(400, 'invalid class/spell combination') unless spell_valid_for_class?(member[:class])

  added = Storage.add_character_spell(campaign_id, char_id, body['spell_id'], body['name'], body['level'])
  json_error(409, 'spell already known') unless added

  status 201
  JSON.dump(
    spell_id: body['spell_id'],
    name: body['name'],
    level: body['level']
  )
end

get '/v1/play/campaigns/:id/characters/:char_id/spells' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  spells = Storage.load_character_spells(campaign_id, char_id)

  JSON.dump(spells: spells)
end

# --- Prepared Spells ---

put '/v1/play/campaigns/:id/characters/:char_id/prepared-spells' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_prepared_spells_body!(body)

  json_error(400, 'character cannot prepare spells') unless spell_valid_for_class?(member[:class])

  known = Storage.load_character_spells(campaign_id, char_id)
  known_ids = known.map { |s| s[:spell_id] || s['spell_id'] }
  body['spell_ids'].each do |spell_id|
    json_error(400, 'unknown spell') unless known_ids.include?(spell_id)
  end

  max = max_prepared_spells(member[:class], member[:level], member[:abilities])
  json_error(400, 'too many prepared spells') if body['spell_ids'].length > max

  Storage.save_character_prepared_spells(campaign_id, char_id, body['spell_ids'])

  status 200
  JSON.dump(
    character_id: char_id,
    prepared_spells: body['spell_ids'],
    max_prepared: max
  )
end

get '/v1/play/campaigns/:id/characters/:char_id/prepared-spells' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  prepared = Storage.load_character_prepared_spells(campaign_id, char_id)
  max = max_prepared_spells(member[:class], member[:level], member[:abilities])

  JSON.dump(
    character_id: char_id,
    prepared_spells: prepared,
    max_prepared: max
  )
end

# --- Spell Casting ---

post '/v1/play/campaigns/:id/characters/:char_id/casts' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_cast_body!(body)

  json_error(400, 'character cannot cast spells') unless spell_valid_for_class?(member[:class])

  known = Storage.load_character_spells(campaign_id, char_id)
  known_spell = known.find { |s| (s[:spell_id] || s['spell_id']) == body['spell_id'] }
  json_error(400, 'spell not prepared') unless known_spell

  prepared = Storage.load_character_prepared_spells(campaign_id, char_id)
  json_error(400, 'spell not prepared') unless prepared.include?(body['spell_id'])

  slot_level = known_spell[:level] || known_spell['level']
  slots = Storage.load_character_spell_slots(campaign_id, char_id)
  json_error(409, 'no remaining spell slots') unless slots[slot_level.to_s].to_i > 0

  updated_slots = Storage.decrement_character_spell_slot(campaign_id, char_id, slot_level)
  json_error(409, 'no remaining spell slots') unless updated_slots

  slots_remaining = updated_slots[slot_level.to_s].to_i
  sequence = Storage.record_character_cast(campaign_id, char_id, body['spell_id'], body['target'], slot_level, slots_remaining)

  status 201
  JSON.dump(
    character_id: char_id,
    spell_id: body['spell_id'],
    target: body['target'],
    slot_level: slot_level,
    slots_remaining: slots_remaining,
    sequence: sequence
  )
end

get '/v1/play/campaigns/:id/characters/:char_id/casts' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  casts = Storage.load_character_casts(campaign_id, char_id)

  JSON.dump(casts: casts)
end

# --- Concentration ---

put '/v1/play/campaigns/:id/characters/:char_id/concentration' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_concentration_body!(body)

  json_error(400, 'character cannot concentrate') unless spell_valid_for_class?(member[:class])

  known = Storage.load_character_spells(campaign_id, char_id)
  known_spell = known.find { |s| (s[:spell_id] || s['spell_id']) == body['spell_id'] }
  json_error(400, 'unknown spell') unless known_spell

  prepared = Storage.load_character_prepared_spells(campaign_id, char_id)
  json_error(400, 'spell not prepared') unless prepared.include?(body['spell_id'])

  concentration = {
    spell_id: body['spell_id'],
    target: body['target'],
    remaining_turns: body['duration_turns']
  }

  Storage.save_character_concentration(campaign_id, char_id, concentration)

  status 200
  JSON.dump(
    character_id: char_id,
    concentration: concentration
  )
end

get '/v1/play/campaigns/:id/characters/:char_id/concentration' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  concentration = Storage.load_character_concentration(campaign_id, char_id)

  JSON.dump(
    character_id: char_id,
    concentration: concentration
  )
end

post '/v1/play/campaigns/:id/characters/:char_id/concentration/advance-turn' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  concentration = Storage.load_character_concentration(campaign_id, char_id)

  if concentration
    remaining = concentration['remaining_turns'].to_i - 1
    if remaining <= 0
      Storage.clear_character_concentration(campaign_id, char_id)
      concentration = nil
    else
      concentration['remaining_turns'] = remaining
      Storage.save_character_concentration(campaign_id, char_id, concentration)
    end
  end

  JSON.dump(
    character_id: char_id,
    concentration: concentration
  )
end

delete '/v1/play/campaigns/:id/characters/:char_id/concentration' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  Storage.clear_character_concentration(campaign_id, char_id)

  JSON.dump(
    character_id: char_id,
    concentration: nil
  )
end

# --- Inventory Stacks ---

post '/v1/play/campaigns/:id/characters/:char_id/inventory/items' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  body = parse_json_body
  validate_inventory_stack_body!(body)

  total_quantity = Storage.add_character_inventory_item(campaign_id, char_id, body['item_id'], body['quantity'])

  status 201
  JSON.dump(
    character_id: char_id,
    item_id: body['item_id'],
    quantity: body['quantity'],
    total_quantity: total_quantity
  )
end

get '/v1/play/campaigns/:id/characters/:char_id/inventory/items' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  items = Storage.load_character_inventory(campaign_id, char_id)

  JSON.dump(
    character_id: char_id,
    items: items
  )
end

delete '/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  item_id = params[:item_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  json_error(400, 'invalid item_id') unless Validation::VALID_INVENTORY_ITEM_IDS.include?(item_id)

  body = parse_json_body
  quantity = body['quantity']
  unless quantity.is_a?(Integer) && quantity.positive?
    json_error(400, 'invalid quantity')
  end

  total_quantity = Storage.remove_character_inventory_item(campaign_id, char_id, item_id, quantity)
  json_error(409, 'quantity exceeds held stack') unless total_quantity

  JSON.dump(
    character_id: char_id,
    item_id: item_id,
    quantity: quantity,
    total_quantity: total_quantity
  )
end

# --- Equipment and Attunement ---

put '/v1/play/campaigns/:id/characters/:char_id/equipment/:slot' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  slot = params[:slot]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  validate_equipment_slot!(slot)

  body = parse_json_body
  item_id = body['item_id']
  unless item_id.is_a?(String) && item_id != ''
    json_error(400, 'invalid item_id')
  end

  expected_slot = Validation::EQUIPMENT_ITEM_SLOTS[item_id]
  json_error(400, 'unknown item id') unless expected_slot
  json_error(400, 'slot mismatch') unless expected_slot == slot

  held = Storage.load_character_inventory(campaign_id, char_id)
  held_item = held.find { |entry| entry[:item_id] == item_id }
  json_error(400, 'item not held') unless held_item && held_item[:quantity].to_i.positive?

  Storage.save_character_equipment(campaign_id, char_id, slot, item_id, false)

  status 200
  JSON.dump(
    character_id: char_id,
    slot: slot,
    item_id: item_id,
    attuned: false
  )
end

get '/v1/play/campaigns/:id/characters/:char_id/equipment/:slot' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  slot = params[:slot]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  validate_equipment_slot!(slot)

  equipped = Storage.load_character_equipment(campaign_id, char_id, slot)

  JSON.dump(
    character_id: char_id,
    slot: slot,
    item_id: equipped ? equipped[:item_id] : '',
    attuned: equipped ? equipped[:attuned] : false
  )
end

post '/v1/play/campaigns/:id/characters/:char_id/equipment/:slot/attune' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  slot = params[:slot]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  validate_equipment_slot!(slot)

  json_error(403, 'forbidden') unless member[:owner] == username

  equipped = Storage.load_character_equipment(campaign_id, char_id, slot)
  json_error(400, 'no item equipped') unless equipped && equipped[:item_id].to_s != ''

  item_id = equipped[:item_id]
  json_error(400, 'item is not attunable') unless Validation::ATTUNABLE_ITEM_IDS.include?(item_id)

  json_error(409, 'attunement limit reached') if Storage.character_attuned_equipment_exists?(campaign_id, char_id)

  Storage.save_character_equipment(campaign_id, char_id, slot, item_id, true)

  status 200
  JSON.dump(
    character_id: char_id,
    slot: slot,
    item_id: item_id,
    attuned: true,
    attunement_count: 1,
    max_attunements: 1
  )
end

# --- Consumables ---

post '/v1/play/campaigns/:id/characters/:char_id/inventory/items/:item_id/consume' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  item_id = params[:item_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  json_error(403, 'forbidden') unless member[:owner] == username

  unless Validation::VALID_CONSUMABLE_ITEM_IDS.include?(item_id)
    json_error(400, 'invalid item_id')
  end

  result = Storage.consume_character_inventory_item(campaign_id, char_id, item_id)
  json_error(409, 'no stack available') unless result

  status 200
  JSON.dump(
    character_id: char_id,
    item_id: item_id,
    quantity_consumed: 1,
    total_quantity: result[:quantity],
    effect: {
      type: 'healing',
      hp_restored: result[:hp_restored]
    }
  )
end

# --- Currency and Trade ---

get '/v1/play/campaigns/:id/characters/:char_id/currency' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  gold = Storage.load_character_currency(campaign_id, char_id)

  status 200
  JSON.dump(
    character_id: char_id,
    gold: gold
  )
end

post '/v1/play/campaigns/:id/characters/:char_id/currency/transfers' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  source = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless source

  json_error(403, 'forbidden') unless source[:owner] == username

  body = parse_json_body
  validate_transfer_body!(body)

  to_character_id = body['to_character_id']
  gold = body['gold']

  json_error(400, 'invalid transfer') if to_character_id == char_id

  destination = Storage.load_play_campaign_member_by_character_id(campaign_id, to_character_id)
  json_error(400, 'invalid to_character_id') unless destination

  result = Storage.transfer_gold(campaign_id, char_id, to_character_id, gold)
  json_error(409, 'insufficient gold') unless result

  status 201
  JSON.dump(result)
end

# --- Character Sheet ---

get '/v1/play/campaigns/:id/characters/:char_id/sheet' do
  content_type :json
  campaign_id = params[:id]
  char_id = params[:char_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  member = Storage.load_play_campaign_member_by_character_id(campaign_id, char_id)
  json_error(404, 'character not found') unless member

  is_owner = campaign[:owner] == username
  json_error(403, 'forbidden') unless is_owner || member[:owner] == username

  JSON.dump(
    character_id: char_id,
    owner: member[:owner],
    name: member[:name],
    class: member[:class],
    level: 1,
    proficiency_bonus: 2,
    hp_max: 10,
    armor_class: 10
  )
end


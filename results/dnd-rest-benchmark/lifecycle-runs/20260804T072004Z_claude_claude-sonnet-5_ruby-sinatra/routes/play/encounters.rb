# Combat encounters: roster management (monsters/bound party members),
# initiative-order turns, damage/heal/conditions, and rewards.
#
# Starting an encounter flips the campaign into 'combat' phase and snapshots
# the exploration turn state (pre_combat_actor/turn_index/turn_number) so
# .../encounters/:id/end can resume exploration exactly where it left off.
# encounter_combat_order/tick_encounter_conditions!/apply_encounter_hp_delta!
# live in lib/play_campaigns.rb since both the roster routes and the
# turn-advance routes below need the same initiative math.

post '/v1/play/campaigns/:id/encounters' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  name = body['name']
  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?

  existing = db.execute(
    'SELECT 1 FROM play_encounters WHERE campaign_id = ? AND id = ?',
    [campaign['id'], id]
  ).first
  halt 409, { error: 'encounter id already exists' }.to_json if existing

  already_in_combat = db.execute(
    "SELECT 1 FROM play_encounters WHERE campaign_id = ? AND status = 'active'",
    [campaign['id']]
  ).first
  halt 409, { error: 'campaign already in combat' }.to_json if already_in_combat

  db.execute(
    'INSERT INTO play_encounters (campaign_id, id, name, status, combatants_json) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], id, name, 'active', '[]']
  )

  if campaign['phase'] != 'combat'
    db.execute(
      'UPDATE play_campaigns SET phase = ?, pre_combat_actor = ?, pre_combat_turn_index = ?, pre_combat_turn_number = ? WHERE id = ?',
      ['combat', campaign['current_actor'], campaign['turn_index'], campaign['turn_number'], campaign['id']]
    )
  end

  status 201
  { id: id, name: name, status: 'active', combatants: [] }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/monsters' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  monster_id = body['monster_id']
  name = body['name']
  hp_max = body['hp_max']
  initiative = body['initiative']
  halt 400, { error: 'invalid monster_id' }.to_json unless monster_id.is_a?(String) && !monster_id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid hp_max' }.to_json unless hp_max.is_a?(Integer)
  halt 400, { error: 'invalid initiative' }.to_json unless initiative.is_a?(Integer)

  monsters = JSON.parse(encounter['combatants_json'])
  halt 409, { error: 'monster id already exists' }.to_json if monsters.any? { |m| m['monster_id'] == monster_id }

  monster = {
    'monster_id' => monster_id,
    'name' => name,
    'hp_max' => hp_max,
    'initiative' => initiative,
    'hp_current' => hp_max
  }
  monsters << monster

  db.execute(
    'UPDATE play_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
    [monsters.to_json, campaign['id'], params[:enc_id]]
  )

  status 201
  monster.to_json
end

delete '/v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  monsters = JSON.parse(encounter['combatants_json'])
  halt 404, { error: 'monster not found' }.to_json unless monsters.any? { |m| m['monster_id'] == params[:monster_id] }

  monsters.reject! { |m| m['monster_id'] == params[:monster_id] }

  db.execute(
    'UPDATE play_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
    [monsters.to_json, campaign['id'], params[:enc_id]]
  )

  { removed: params[:monster_id] }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/combatants' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  member = body['member']
  initiative = body['initiative']
  halt 400, { error: 'invalid member' }.to_json unless member.is_a?(String) && !member.empty?
  halt 400, { error: 'invalid initiative' }.to_json unless initiative.is_a?(Integer)

  party_member = db.execute(
    'SELECT * FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
    [campaign['id'], member]
  ).first
  halt 400, { error: 'not a campaign member' }.to_json unless party_member

  combatants = JSON.parse(encounter['combatants_json'])
  halt 409, { error: 'member already bound' }.to_json if combatants.any? { |c| c['member'] == member }

  combatant = {
    'member' => member,
    'character_id' => party_member['character_id'],
    'name' => party_member['name'],
    'initiative' => initiative
  }
  combatants << combatant

  db.execute(
    'UPDATE play_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
    [combatants.to_json, campaign['id'], params[:enc_id]]
  )

  status 201
  combatant.to_json
end

delete '/v1/play/campaigns/:id/encounters/:enc_id/combatants/:member' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  combatants = JSON.parse(encounter['combatants_json'])
  halt 404, { error: 'combatant not found' }.to_json unless combatants.any? { |c| c['member'] == params[:member] }

  combatants.reject! { |c| c['member'] == params[:member] }

  db.execute(
    'UPDATE play_encounters SET combatants_json = ? WHERE campaign_id = ? AND id = ?',
    [combatants.to_json, campaign['id'], params[:enc_id]]
  )

  { removed: params[:member] }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/damage' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  target = body['target']
  amount = body['amount']
  halt 400, { error: 'invalid target' }.to_json unless target.is_a?(String) && !target.empty?
  halt 400, { error: 'invalid amount' }.to_json unless integerish(amount)

  amount = amount.to_i

  hp_before, hp_after = apply_encounter_hp_delta!(campaign['id'], encounter, params[:enc_id], target, -amount)

  { target: target, hp_before: hp_before, hp_after: hp_after, damage: amount }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/heal' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  target = body['target']
  amount = body['amount']
  halt 400, { error: 'invalid target' }.to_json unless target.is_a?(String) && !target.empty?
  halt 400, { error: 'invalid amount' }.to_json unless integerish(amount)

  amount = amount.to_i

  hp_before, hp_after = apply_encounter_hp_delta!(campaign['id'], encounter, params[:enc_id], target, amount)

  { target: target, hp_before: hp_before, hp_after: hp_after, healing: amount }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/end' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  halt 409, { error: 'campaign not in combat' }.to_json unless campaign['phase'] == 'combat'

  if encounter['status'] == 'active'
    db.execute(
      "UPDATE play_encounters SET status = 'closed' WHERE campaign_id = ? AND id = ?",
      [campaign['id'], params[:enc_id]]
    )
  end

  resumed_actor = campaign['pre_combat_actor'] || campaign['owner']

  # If combat interrupted the DM's pending resolution for the active party
  # member's turn, the encounter stands in for that resolution: the queue
  # advances to the next member exactly as a normal /resolutions call would,
  # even though the DM still narrates the handoff before the deadline.
  resumed_turn_index = campaign['pre_combat_turn_index'].to_i
  if resumed_actor == campaign['owner']
    members = play_member_usernames(campaign['id'])
    resumed_turn_index = (resumed_turn_index + 1) % members.length unless members.empty?
  end

  db.execute(
    'UPDATE play_campaigns SET phase = ?, current_actor = ?, turn_index = ?, turn_number = ?, pre_combat_actor = NULL, pre_combat_turn_index = NULL, pre_combat_turn_number = NULL WHERE id = ?',
    ['exploration', resumed_actor, resumed_turn_index, campaign['pre_combat_turn_number'], campaign['id']]
  )

  {
    campaign_id: campaign['id'],
    status: campaign['status'],
    phase: 'exploration',
    current_actor: resumed_actor
  }.to_json
end

get '/v1/play/campaigns/:id/encounters/:enc_id/turn' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  order = encounter_combat_order(encounter)
  halt 409, { error: 'no combatants' }.to_json if order.empty?

  turn_index = encounter['turn_index'].to_i % order.length
  active = order[turn_index]

  {
    round: encounter['round'],
    turn_index: turn_index,
    active: encounter_combatant_payload(active)
  }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/turn/advance' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  order = encounter_combat_order(encounter)
  halt 409, { error: 'no combatants' }.to_json if order.empty?

  turn_index = encounter['turn_index'].to_i % order.length
  active = order[turn_index]

  is_owner = campaign['owner'] == user['username']
  is_current_combatant = active['member'] == user['username']
  halt 409, { error: 'not your turn' }.to_json unless is_owner || is_current_combatant

  next_index = (turn_index + 1) % order.length
  next_round = next_index.zero? ? encounter['round'].to_i + 1 : encounter['round'].to_i

  db.execute(
    'UPDATE play_encounters SET round = ?, turn_index = ? WHERE campaign_id = ? AND id = ?',
    [next_round, next_index, campaign['id'], params[:enc_id]]
  )

  next_active = order[next_index]
  tick_encounter_conditions!(campaign['id'], params[:enc_id], encounter, encounter_combatant_target_key(next_active))

  {
    round: next_round,
    turn_index: next_index,
    active: encounter_combatant_payload(next_active)
  }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/turn/delay' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  order = encounter_combat_order(encounter)
  halt 409, { error: 'no combatants' }.to_json if order.empty?

  turn_index = encounter['turn_index'].to_i % order.length
  active = order[turn_index]

  is_owner = campaign['owner'] == user['username']
  is_current_combatant = active['member'] == user['username']
  halt 409, { error: 'not your turn' }.to_json unless is_owner || is_current_combatant

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  index = body.key?('new_index') ? body['new_index'] : body['index']
  halt 400, { error: 'invalid index' }.to_json unless integerish(index)
  index = index.to_i
  halt 400, { error: 'invalid index' }.to_json unless index > turn_index && index < order.length

  reordered = order.dup
  delayed = reordered.delete_at(turn_index)
  reordered.insert(index, delayed)

  db.execute(
    'UPDATE play_encounters SET turn_order_json = ?, turn_index = ? WHERE campaign_id = ? AND id = ?',
    [reordered.map { |c| encounter_combatant_target_key(c) }.to_json, index, campaign['id'], params[:enc_id]]
  )

  {
    round: encounter['round'],
    turn_index: index,
    order: reordered.map { |c| encounter_combatant_payload(c) }
  }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/turn/ready' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  order = encounter_combat_order(encounter)
  halt 409, { error: 'no combatants' }.to_json if order.empty?

  turn_index = encounter['turn_index'].to_i % order.length
  active = order[turn_index]
  halt 409, { error: 'not your turn' }.to_json unless active['member'] == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  trigger = body['trigger']
  halt 400, { error: 'invalid trigger' }.to_json unless trigger.is_a?(String) && !trigger.empty?

  insert_play_event(campaign['id'], kind: 'ready', actor: user['username'], text: trigger, type: 'ready')

  status 201
  { actor: user['username'], trigger: trigger }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/conditions' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  target = body['target']
  condition = body['condition']
  duration_rounds = body['duration_rounds']
  halt 400, { error: 'invalid target' }.to_json unless target.is_a?(String) && !target.empty?
  halt 400, { error: 'invalid condition' }.to_json unless condition.is_a?(String) && !condition.empty?
  halt 400, { error: 'invalid duration_rounds' }.to_json unless integerish(duration_rounds) && duration_rounds.to_i.positive?

  combatants = JSON.parse(encounter['combatants_json'])
  halt 400, { error: 'invalid target' }.to_json unless combatants.any? { |c| encounter_combatant_target_key(c) == target }

  conditions = JSON.parse(encounter['conditions_json'] || '{}')
  conditions[target] ||= []
  conditions[target] << { 'condition' => condition, 'remaining_rounds' => duration_rounds.to_i }

  db.execute(
    'UPDATE play_encounters SET conditions_json = ? WHERE campaign_id = ? AND id = ?',
    [conditions.to_json, campaign['id'], params[:enc_id]]
  )

  status 201
  {
    target: target,
    conditions: conditions[target].map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
  }.to_json
end

get '/v1/play/campaigns/:id/encounters/:enc_id/status' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  order = encounter_combat_order(encounter)
  turn_index = order.empty? ? encounter['turn_index'].to_i : encounter['turn_index'].to_i % order.length
  active = order.empty? ? nil : encounter_combatant_payload(order[turn_index])

  {
    round: encounter['round'],
    turn_index: turn_index,
    active: active,
    order: order.map { |c| encounter_combatant_payload(c) },
    conditions: encounter_conditions_map(encounter)
  }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/actions' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  order = encounter_combat_order(encounter)
  halt 409, { error: 'no combatants' }.to_json if order.empty?

  turn_index = encounter['turn_index'].to_i % order.length
  active = order[turn_index]
  halt 409, { error: 'not your turn' }.to_json unless active['member'] == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  type = body['type']
  target = body['target']
  text = body['text']
  halt 400, { error: 'invalid type' }.to_json unless %w[attack help dodge ready].include?(type)
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?
  halt 400, { error: 'invalid target' }.to_json unless target.nil? || (target.is_a?(String) && !target.empty?)

  sequence = insert_play_event(
    campaign['id'], kind: 'combat_action', actor: user['username'], text: text, type: type, target: target
  )

  status 201
  {
    sequence: sequence,
    kind: 'combat_action',
    actor: user['username'],
    type: type,
    target: target,
    text: text
  }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/rewards' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  halt 409, { error: 'rewards already awarded' }.to_json unless encounter['rewards_json'].nil?

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  xp = body['xp']
  loot = body['loot']
  halt 400, { error: 'invalid xp' }.to_json unless integerish(xp)
  halt 400, { error: 'invalid loot' }.to_json unless loot.is_a?(Array)

  loot.each do |item|
    halt 400, { error: 'invalid loot' }.to_json unless item.is_a?(Hash)
    halt 400, { error: 'invalid loot' }.to_json unless item['slug'].is_a?(String) && !item['slug'].empty?
    halt 400, { error: 'invalid loot' }.to_json unless integerish(item['quantity'])
  end

  xp = xp.to_i
  loot = loot.map { |item| { 'slug' => item['slug'], 'quantity' => item['quantity'].to_i } }

  db.execute(
    'UPDATE play_encounters SET rewards_json = ?, xp_awarded = ? WHERE campaign_id = ? AND id = ?',
    [{ 'xp' => xp, 'loot' => loot }.to_json, xp, campaign['id'], params[:enc_id]]
  )

  status 200
  { id: params[:enc_id], xp: xp, loot: loot }.to_json
end

post '/v1/play/campaigns/:id/encounters/:enc_id/close' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  encounter = find_play_encounter!(campaign['id'], params[:enc_id])

  db.execute(
    'UPDATE play_encounters SET status = ? WHERE campaign_id = ? AND id = ?',
    ['closed', campaign['id'], params[:enc_id]]
  )

  { id: params[:enc_id], status: 'closed', xp_awarded: encounter['xp_awarded'].to_i }.to_json
end

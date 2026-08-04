# Per-character play state: HP/death saves outside of an encounter,
# ownership/claim/transfer (a character's controlling player can change
# over a campaign's life), build (initial race/class/ability assignment),
# level-up, and ad-hoc skill checks.

post '/v1/play/campaigns/:id/characters/:char_id/damage' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  member = find_play_member_by_character!(campaign['id'], params[:char_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  amount = body['amount']
  halt 400, { error: 'invalid amount' }.to_json unless integerish(amount)
  amount = amount.to_i

  hp_before = member['hp_current']
  hp_after = [hp_before - amount, 0].max

  new_status = member['status']
  new_status = 'unconscious' if hp_after.zero? && member['status'] == 'conscious'

  db.execute(
    'UPDATE play_campaign_members SET hp_current = ?, status = ? WHERE campaign_id = ? AND character_id = ?',
    [hp_after, new_status, campaign['id'], params[:char_id]]
  )

  {
    target: params[:char_id],
    hp_before: hp_before,
    hp_after: hp_after,
    damage: amount,
    status: new_status
  }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/death-saves' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])

  halt 403, { error: 'forbidden' }.to_json unless member['username'] == user['username']
  halt 409, { error: 'character is not unconscious' }.to_json unless member['status'] == 'unconscious'

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  outcome = body['outcome']
  halt 400, { error: 'invalid outcome' }.to_json unless %w[success failure].include?(outcome)

  successes = member['death_save_successes']
  failures = member['death_save_failures']

  outcome == 'success' ? successes += 1 : failures += 1

  new_status = 'unconscious'
  new_status = 'stable' if successes >= 3
  new_status = 'dead' if failures >= 3

  db.execute(
    'UPDATE play_campaign_members SET death_save_successes = ?, death_save_failures = ?, status = ? ' \
    'WHERE campaign_id = ? AND character_id = ?',
    [successes, failures, new_status, campaign['id'], params[:char_id]]
  )

  status 201
  {
    character_id: params[:char_id],
    successes: successes,
    failures: failures,
    status: new_status
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/status' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])

  {
    character_id: params[:char_id],
    hp_current: member['hp_current'],
    hp_max: member['hp_max'],
    status: member['status']
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/owner' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  { character_id: params[:char_id], owner: owner }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/claim' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 409, { error: 'character already owned' }.to_json if owner && owner != user['username']

  db.execute(
    'INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id) DO UPDATE SET owner = excluded.owner',
    [campaign['id'], params[:char_id], user['username']]
  )

  status 201
  { character_id: params[:char_id], owner: user['username'] }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/transfer' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  new_owner = body['new_owner']
  halt 400, { error: 'invalid new_owner' }.to_json unless new_owner.is_a?(String) && !new_owner.empty?
  halt 400, { error: 'new_owner is not a campaign member' }.to_json unless play_campaign_member?(campaign, new_owner)

  db.execute(
    'INSERT INTO play_character_owners (campaign_id, character_id, owner) VALUES (?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id) DO UPDATE SET owner = excluded.owner',
    [campaign['id'], params[:char_id], new_owner]
  )

  { character_id: params[:char_id], owner: new_owner }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/build' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  race = body['race']
  klass = body['class']
  background = body['background']
  abilities = body['abilities']

  halt 400, { error: 'invalid race' }.to_json unless VALID_RACES.include?(race)
  halt 400, { error: 'invalid class' }.to_json unless CLASS_HIT_DICE.key?(klass)
  halt 400, { error: 'invalid background' }.to_json unless VALID_BACKGROUNDS.include?(background)
  halt 400, { error: 'invalid abilities' }.to_json unless abilities.is_a?(Hash)

  ABILITY_KEYS.each do |key|
    score = abilities[key]
    halt 400, { error: "invalid ability score #{key}" }.to_json unless integerish(score) && score.to_i.between?(1, 30)
  end

  level = 1
  modifiers = ABILITY_KEYS.each_with_object({}) { |key, acc| acc[key] = ability_modifier(abilities[key].to_i) }
  con_modifier = modifiers['con']
  hp_max = CLASS_HIT_DICE[klass] + con_modifier
  bonus = proficiency_bonus(level)

  db.execute(
    'UPDATE play_campaign_members SET race = ?, class = ?, background = ?, level = ?, hp_max = ?, ' \
    'hp_current = ?, proficiency_bonus = ?, con_modifier = ?, str_modifier = ?, dex_modifier = ?, ' \
    'int_modifier = ?, wis_modifier = ?, cha_modifier = ? WHERE campaign_id = ? AND character_id = ?',
    [race, klass, background, level, hp_max, hp_max, bonus, con_modifier, modifiers['str'], modifiers['dex'],
     modifiers['int'], modifiers['wis'], modifiers['cha'], campaign['id'], params[:char_id]]
  )

  {
    character_id: params[:char_id],
    race: race,
    class: klass,
    background: background,
    level: level,
    hp_max: hp_max,
    proficiency_bonus: bonus
  }.to_json
end

# Fixed (non-random) average hit-point gain for a class's hit die when
# leveling up, per the PHB's "take the average instead of rolling" option:
# floor(die / 2) + 1. All hit dice in CLASS_HIT_DICE are even, so this is
# exact (e.g. d8 -> 5, d10 -> 6).
def average_hit_die_gain(klass)
  (CLASS_HIT_DICE[klass] / 2) + 1
end

post '/v1/play/campaigns/:id/characters/:char_id/level-up' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  new_level = body['level']
  halt 400, { error: 'invalid level' }.to_json unless integerish(new_level)

  current_level = member['level']
  halt 400, { error: 'level must be exactly one higher than the current level' }.to_json unless new_level.to_i == current_level + 1

  klass = member['class']
  halt 400, { error: 'invalid class' }.to_json unless CLASS_HIT_DICE.key?(klass)

  con_modifier = member['con_modifier']
  hp_gain = average_hit_die_gain(klass) + con_modifier
  hp_max = member['hp_max'] + hp_gain
  hp_current = [member['hp_current'] + hp_gain, hp_max].min
  bonus = proficiency_bonus(new_level.to_i)

  db.execute(
    'UPDATE play_campaign_members SET level = ?, hp_max = ?, hp_current = ?, proficiency_bonus = ? ' \
    'WHERE campaign_id = ? AND character_id = ?',
    [new_level.to_i, hp_max, hp_current, bonus, campaign['id'], params[:char_id]]
  )

  {
    character_id: params[:char_id],
    level: new_level.to_i,
    hp_max: hp_max,
    hit_dice: "1d#{CLASS_HIT_DICE[klass]}",
    proficiency_bonus: bonus
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/sheet' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'forbidden' }.to_json unless is_owner || owner == user['username']

  {
    character_id: params[:char_id],
    owner: owner,
    name: member['name'],
    class: member['class'],
    level: 1,
    proficiency_bonus: 2,
    hp_max: 10,
    armor_class: 10
  }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/skill-check' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  skill = body['skill']
  ability = body['ability']
  proficient = body['proficient']
  roll = body['roll']

  halt 400, { error: 'unsupported skill' }.to_json unless SKILL_ABILITIES.key?(skill)
  halt 400, { error: 'unsupported ability' }.to_json unless ability == SKILL_ABILITIES[skill]
  halt 400, { error: 'invalid proficient' }.to_json unless [true, false].include?(proficient)
  halt 400, { error: 'invalid roll' }.to_json unless integerish(roll)

  ability_mod = member["#{ability}_modifier"]
  modifier = ability_mod + (proficient ? member['proficiency_bonus'] : 0)
  total = roll.to_i + modifier

  {
    character_id: params[:char_id],
    skill: skill,
    ability: ability,
    modifier: modifier,
    total: total
  }.to_json
end

# A character's known-spells list: learning a new spell (validated against
# SPELL_COMPENDIUM and the character's class) and listing what's known.

post '/v1/play/campaigns/:id/characters/:char_id/spells' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  spell_id = body['spell_id']
  name = body['name']
  level = body['level']

  halt 400, { error: 'invalid spell_id' }.to_json unless valid_slug?(spell_id)
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid level' }.to_json unless integerish(level)

  spell = SPELL_COMPENDIUM[spell_id]
  valid = spell && spell[:name] == name && spell[:level] == level.to_i && spell[:classes].include?(member['class'])
  halt 400, { error: 'invalid class/spell combination' }.to_json unless valid

  existing = db.execute(
    'SELECT 1 FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
    [campaign['id'], params[:char_id], spell_id]
  ).first
  halt 409, { error: 'spell already known' }.to_json if existing

  db.execute(
    'INSERT INTO play_character_spells (campaign_id, character_id, spell_id, name, level) VALUES (?, ?, ?, ?, ?)',
    [campaign['id'], params[:char_id], spell_id, name, level.to_i]
  )

  status 201
  { spell_id: spell_id, name: name, level: level.to_i }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/spells' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:char_id])

  spells = db.execute(
    'SELECT spell_id, name, level FROM play_character_spells WHERE campaign_id = ? AND character_id = ? ORDER BY rowid ASC',
    [campaign['id'], params[:char_id]]
  ).map { |row| { spell_id: row['spell_id'], name: row['name'], level: row['level'] } }

  { spells: spells }.to_json
end

# A character's prepared-spells list: which known spells are currently
# readied for casting, capped by the class level's max-prepared count.

put '/v1/play/campaigns/:id/characters/:char_id/prepared-spells' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  halt 400, { error: 'invalid class/spell combination' }.to_json unless SPELLCASTING_CLASSES.include?(member['class'])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  spell_ids = body['spell_ids']
  halt 400, { error: 'invalid spell_ids' }.to_json unless spell_ids.is_a?(Array) && spell_ids.all? { |id| id.is_a?(String) }

  known_spell_ids = db.execute(
    'SELECT spell_id FROM play_character_spells WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  ).map { |row| row['spell_id'] }
  halt 400, { error: 'unknown spell' }.to_json unless spell_ids.all? { |id| known_spell_ids.include?(id) }

  max_prepared = member['level']
  halt 400, { error: 'too many prepared spells' }.to_json if spell_ids.length > max_prepared

  db.execute(
    'INSERT INTO play_character_prepared_spells (campaign_id, character_id, spell_ids_json) VALUES (?, ?, ?) ' \
    'ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_ids_json = excluded.spell_ids_json',
    [campaign['id'], params[:char_id], spell_ids.to_json]
  )

  {
    character_id: params[:char_id],
    prepared_spells: spell_ids,
    max_prepared: max_prepared
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/prepared-spells' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  member = find_play_member_by_character!(campaign['id'], params[:char_id])

  row = db.execute(
    'SELECT spell_ids_json FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  ).first
  prepared_spells = row ? JSON.parse(row['spell_ids_json']) : []

  {
    character_id: params[:char_id],
    prepared_spells: prepared_spells,
    max_prepared: member['level']
  }.to_json
end

# Casting a spell: consumes one of the character's remaining spell slots of
# the spell's level (cantrips, level 0, are unlimited and never consume a
# slot) and records the cast in the character's history.

post '/v1/play/campaigns/:id/characters/:char_id/casts' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  spell_id = body['spell_id']
  target = body['target']

  halt 400, { error: 'invalid spell_id' }.to_json unless valid_slug?(spell_id)
  halt 400, { error: 'invalid target' }.to_json unless target.is_a?(String) && !target.empty?

  halt 400, { error: 'not a spellcaster' }.to_json unless SPELLCASTING_CLASSES.include?(member['class'])

  row = db.execute(
    'SELECT spell_ids_json FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  ).first
  prepared_spells = row ? JSON.parse(row['spell_ids_json']) : []
  halt 400, { error: 'spell not prepared' }.to_json unless prepared_spells.include?(spell_id)

  spell = SPELL_COMPENDIUM[spell_id]
  halt 400, { error: 'spell not prepared' }.to_json unless spell

  slot_level = spell[:level]

  if slot_level.zero?
    slots_remaining = nil
  else
    total_slots = PLAY_SPELL_SLOTS.dig(member['level'], slot_level) || 0
    used_slots = db.execute(
      'SELECT COUNT(*) AS n FROM play_character_casts WHERE campaign_id = ? AND character_id = ? AND slot_level = ?',
      [campaign['id'], params[:char_id], slot_level]
    ).first['n']
    halt 409, { error: 'no remaining spell slots' }.to_json if used_slots >= total_slots
    slots_remaining = total_slots - used_slots - 1
  end

  sequence = db.execute(
    'SELECT COUNT(*) AS n FROM play_character_casts WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  ).first['n'] + 1

  db.execute(
    'INSERT INTO play_character_casts (campaign_id, character_id, sequence, spell_id, target, slot_level, slots_remaining) ' \
    'VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign['id'], params[:char_id], sequence, spell_id, target, slot_level, slots_remaining]
  )

  status 201
  {
    character_id: params[:char_id],
    spell_id: spell_id,
    target: target,
    slot_level: slot_level,
    slots_remaining: slots_remaining,
    sequence: sequence
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/casts' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:char_id])

  casts = db.execute(
    'SELECT sequence, spell_id, target, slot_level, slots_remaining FROM play_character_casts ' \
    'WHERE campaign_id = ? AND character_id = ? ORDER BY sequence ASC',
    [campaign['id'], params[:char_id]]
  ).map do |row|
    {
      character_id: params[:char_id],
      spell_id: row['spell_id'],
      target: row['target'],
      slot_level: row['slot_level'],
      slots_remaining: row['slots_remaining'],
      sequence: row['sequence']
    }
  end

  { casts: casts }.to_json
end

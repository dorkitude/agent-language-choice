# A character's current concentration state: setting/replacing it when
# casting a concentration spell, reading it, advancing it by one turn, and
# clearing it.

def play_concentration_row(campaign_id, character_id)
  db.execute(
    'SELECT spell_id, target, remaining_turns FROM play_character_concentration ' \
    'WHERE campaign_id = ? AND character_id = ?',
    [campaign_id, character_id]
  ).first
end

def play_concentration_json(row)
  return nil unless row
  { spell_id: row['spell_id'], target: row['target'], remaining_turns: row['remaining_turns'] }
end

put '/v1/play/campaigns/:id/characters/:char_id/concentration' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  spell_id = body['spell_id']
  target = body['target']
  duration_turns = body['duration_turns']

  halt 400, { error: 'invalid spell_id' }.to_json unless valid_slug?(spell_id)
  halt 400, { error: 'invalid target' }.to_json unless target.is_a?(String) && !target.empty?
  halt 400, { error: 'invalid duration_turns' }.to_json unless integerish(duration_turns) && duration_turns.to_i >= 1

  halt 400, { error: 'not a spellcaster' }.to_json unless SPELLCASTING_CLASSES.include?(member['class'])

  known = db.execute(
    'SELECT 1 FROM play_character_spells WHERE campaign_id = ? AND character_id = ? AND spell_id = ?',
    [campaign['id'], params[:char_id], spell_id]
  ).first
  halt 400, { error: 'unknown spell' }.to_json unless known

  row = db.execute(
    'SELECT spell_ids_json FROM play_character_prepared_spells WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  ).first
  prepared_spells = row ? JSON.parse(row['spell_ids_json']) : []
  halt 400, { error: 'spell not prepared' }.to_json unless prepared_spells.include?(spell_id)

  db.execute(
    'INSERT INTO play_character_concentration (campaign_id, character_id, spell_id, target, remaining_turns) ' \
    'VALUES (?, ?, ?, ?, ?) ' \
    'ON CONFLICT(campaign_id, character_id) DO UPDATE SET spell_id = excluded.spell_id, target = excluded.target, remaining_turns = excluded.remaining_turns',
    [campaign['id'], params[:char_id], spell_id, target, duration_turns.to_i]
  )

  {
    character_id: params[:char_id],
    concentration: { spell_id: spell_id, target: target, remaining_turns: duration_turns.to_i }
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/concentration' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:char_id])

  row = play_concentration_row(campaign['id'], params[:char_id])

  { character_id: params[:char_id], concentration: play_concentration_json(row) }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/concentration/advance-turn' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:char_id])

  row = play_concentration_row(campaign['id'], params[:char_id])

  if row
    remaining = row['remaining_turns'] - 1
    if remaining <= 0
      db.execute(
        'DELETE FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?',
        [campaign['id'], params[:char_id]]
      )
      row = nil
    else
      db.execute(
        'UPDATE play_character_concentration SET remaining_turns = ? WHERE campaign_id = ? AND character_id = ?',
        [remaining, campaign['id'], params[:char_id]]
      )
      row = play_concentration_row(campaign['id'], params[:char_id])
    end
  end

  { character_id: params[:char_id], concentration: play_concentration_json(row) }.to_json
end

delete '/v1/play/campaigns/:id/characters/:char_id/concentration' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  db.execute(
    'DELETE FROM play_character_concentration WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:char_id]]
  )

  { character_id: params[:char_id], concentration: nil }.to_json
end

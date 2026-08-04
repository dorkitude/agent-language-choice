# Campaign quest records whose activation is gated by completed
# prerequisite quests. Quest IDs are unique per campaign.

def play_quest_payload(quest)
  payload = {
    quest_id: quest['quest_id'],
    title: quest['title'],
    depends_on: JSON.parse(quest['depends_on_json']),
    state: quest['state']
  }
  payload[:rewards] = JSON.parse(quest['rewards_json']).transform_keys(&:to_sym) if quest['rewards_json']
  payload
end

post '/v1/play/campaigns/:id/quests' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  quest_id = body['quest_id']
  title = body['title']
  depends_on = body['depends_on']

  halt 400, { error: 'invalid quest_id' }.to_json unless quest_id.is_a?(String) && !quest_id.empty?
  halt 400, { error: 'invalid title' }.to_json unless title.is_a?(String) && !title.empty?
  halt 400, { error: 'invalid depends_on' }.to_json unless depends_on.is_a?(Array) && depends_on.all? { |d| d.is_a?(String) }
  halt 400, { error: 'duplicate dependency ids' }.to_json if depends_on.uniq.length != depends_on.length
  halt 400, { error: 'quest cannot depend on itself' }.to_json if depends_on.include?(quest_id)

  depends_on.each do |dep_id|
    halt 400, { error: 'unknown dependency' }.to_json unless db.execute(
      'SELECT 1 FROM play_quests WHERE campaign_id = ? AND quest_id = ?',
      [campaign['id'], dep_id]
    ).first
  end

  existing = db.execute(
    'SELECT 1 FROM play_quests WHERE campaign_id = ? AND quest_id = ?',
    [campaign['id'], quest_id]
  ).first
  halt 409, { error: 'quest already exists' }.to_json if existing

  sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), -1) + 1 AS seq FROM play_quests WHERE campaign_id = ?',
    [campaign['id']]
  ).first['seq']

  db.execute(
    'INSERT INTO play_quests (campaign_id, sequence, quest_id, title, depends_on_json, state) VALUES (?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, quest_id, title, depends_on.to_json, 'locked']
  )

  status 201
  { quest_id: quest_id, title: title, depends_on: depends_on, state: 'locked' }.to_json
end

put '/v1/play/campaigns/:id/quests/:quest_id/state' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  quest = db.execute(
    'SELECT * FROM play_quests WHERE campaign_id = ? AND quest_id = ?',
    [campaign['id'], params[:quest_id]]
  ).first
  halt 404, { error: 'quest not found' }.to_json unless quest

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  new_state = body['state']
  halt 400, { error: 'invalid state' }.to_json unless %w[active completed].include?(new_state)

  current_state = quest['state']

  if new_state == 'active'
    halt 409, { error: 'invalid transition' }.to_json unless current_state == 'locked'

    depends_on = JSON.parse(quest['depends_on_json'])
    all_completed = depends_on.all? do |dep_id|
      dep = db.execute(
        'SELECT state FROM play_quests WHERE campaign_id = ? AND quest_id = ?',
        [campaign['id'], dep_id]
      ).first
      dep && dep['state'] == 'completed'
    end
    halt 409, { error: 'dependencies not completed' }.to_json unless all_completed
  else
    halt 409, { error: 'invalid transition' }.to_json unless current_state == 'active'
  end

  db.execute(
    'UPDATE play_quests SET state = ? WHERE campaign_id = ? AND quest_id = ?',
    [new_state, campaign['id'], params[:quest_id]]
  )

  quest['state'] = new_state
  play_quest_payload(quest).to_json
end

get '/v1/play/campaigns/:id/quests' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  quests = db.execute(
    'SELECT * FROM play_quests WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  { quests: quests.map { |quest| play_quest_payload(quest) } }.to_json
end

put '/v1/play/campaigns/:id/quests/:quest_id/rewards' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  quest = db.execute(
    'SELECT * FROM play_quests WHERE campaign_id = ? AND quest_id = ?',
    [campaign['id'], params[:quest_id]]
  ).first
  halt 404, { error: 'quest not found' }.to_json unless quest

  halt 409, { error: 'quest already completed' }.to_json if quest['state'] == 'completed'

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  xp = body['xp']
  items = body['items']

  halt 400, { error: 'invalid xp' }.to_json unless integerish(xp) && xp.to_i >= 0
  halt 400, { error: 'invalid items' }.to_json unless items.is_a?(Hash)

  items.each do |item_id, quantity|
    halt 400, { error: 'invalid items' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
    halt 400, { error: 'invalid items' }.to_json unless integerish(quantity) && quantity.to_i.positive?
  end

  xp = xp.to_i
  items = items.each_with_object({}) { |(item_id, quantity), acc| acc[item_id] = quantity.to_i }

  db.execute(
    'UPDATE play_quests SET rewards_json = ? WHERE campaign_id = ? AND quest_id = ?',
    [{ 'xp' => xp, 'items' => items }.to_json, campaign['id'], params[:quest_id]]
  )

  quest['rewards_json'] = { 'xp' => xp, 'items' => items }.to_json
  play_quest_payload(quest).to_json
end

post '/v1/play/campaigns/:id/quests/:quest_id/rewards/award' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  quest = db.execute(
    'SELECT * FROM play_quests WHERE campaign_id = ? AND quest_id = ?',
    [campaign['id'], params[:quest_id]]
  ).first
  halt 404, { error: 'quest not found' }.to_json unless quest

  halt 409, { error: 'quest not completed or rewards not configured' }.to_json unless quest['state'] == 'completed' && quest['rewards_json']
  halt 409, { error: 'rewards already awarded' }.to_json if quest['rewards_awarded'] == 1

  rewards = JSON.parse(quest['rewards_json'])
  xp = rewards['xp']
  items = rewards['items']

  members = db.execute(
    'SELECT character_id FROM play_campaign_members WHERE campaign_id = ?',
    [campaign['id']]
  )

  members.each do |member|
    db.execute(
      'INSERT INTO play_quest_reward_grants (campaign_id, quest_id, character_id, xp, items_json) VALUES (?, ?, ?, ?, ?)',
      [campaign['id'], params[:quest_id], member['character_id'], xp, items.to_json]
    )

    items.each do |item_id, quantity|
      existing_item = db.execute(
        'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign['id'], member['character_id'], item_id]
      ).first
      item_total = (existing_item ? existing_item['quantity'] : 0) + quantity

      db.execute(
        'INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ' \
        'ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity',
        [campaign['id'], member['character_id'], item_id, item_total]
      )
    end
  end

  db.execute(
    'UPDATE play_quests SET rewards_awarded = 1 WHERE campaign_id = ? AND quest_id = ?',
    [campaign['id'], params[:quest_id]]
  )

  status 201
  { quest_id: quest['quest_id'], awarded: true, xp: xp, items: items }.to_json
end

get '/v1/play/campaigns/:id/characters/:character_id/rewards' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:character_id])

  grants = db.execute(
    'SELECT xp, items_json FROM play_quest_reward_grants WHERE campaign_id = ? AND character_id = ?',
    [campaign['id'], params[:character_id]]
  )

  total_xp = 0
  total_items = {}

  grants.each do |grant|
    total_xp += grant['xp']
    JSON.parse(grant['items_json']).each do |item_id, quantity|
      total_items[item_id] = (total_items[item_id] || 0) + quantity
    end
  end

  { character_id: params[:character_id], xp: total_xp, items: total_items }.to_json
end

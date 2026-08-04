# Per-character equipment slots and attunement for the /v1/play surface.

EQUIPMENT_SLOT_ITEMS = {
  'armor' => %w[leather-armor],
  'accessory' => %w[ring-of-protection amulet-of-health]
}.freeze

ATTUNABLE_ITEM_IDS = %w[ring-of-protection amulet-of-health].freeze

MAX_ATTUNEMENTS = 1

def equipment_row(campaign_id, character_id, slot)
  db.execute(
    'SELECT * FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND slot = ?',
    [campaign_id, character_id, slot]
  ).first
end

def character_attunement_count(campaign_id, character_id)
  db.execute(
    'SELECT COUNT(*) AS n FROM play_character_equipment WHERE campaign_id = ? AND character_id = ? AND attuned = 1',
    [campaign_id, character_id]
  ).first['n']
end

put '/v1/play/campaigns/:id/characters/:char_id/equipment/:slot' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  slot = params[:slot]
  halt 400, { error: 'invalid slot' }.to_json unless EQUIPMENT_SLOT_ITEMS.key?(slot)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  item_id = body['item_id']
  halt 400, { error: 'invalid item_id' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
  halt 400, { error: 'item does not fit that slot' }.to_json unless EQUIPMENT_SLOT_ITEMS[slot].include?(item_id)

  held = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], params[:char_id], item_id]
  ).first
  halt 400, { error: 'item not held' }.to_json unless held && held['quantity'].positive?

  db.execute(
    'INSERT INTO play_character_equipment (campaign_id, character_id, slot, item_id, attuned) VALUES (?, ?, ?, ?, 0) ' \
    'ON CONFLICT (campaign_id, character_id, slot) DO UPDATE SET item_id = excluded.item_id, attuned = 0',
    [campaign['id'], params[:char_id], slot, item_id]
  )

  {
    character_id: params[:char_id],
    slot: slot,
    item_id: item_id,
    attuned: false
  }.to_json
end

get '/v1/play/campaigns/:id/characters/:char_id/equipment/:slot' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  find_play_member_by_character!(campaign['id'], params[:char_id])

  slot = params[:slot]
  halt 400, { error: 'invalid slot' }.to_json unless EQUIPMENT_SLOT_ITEMS.key?(slot)

  row = equipment_row(campaign['id'], params[:char_id], slot)

  {
    character_id: params[:char_id],
    slot: slot,
    item_id: row ? row['item_id'] : '',
    attuned: row ? row['attuned'] == 1 : false
  }.to_json
end

post '/v1/play/campaigns/:id/characters/:char_id/equipment/:slot/attune' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  member = find_play_member_by_character!(campaign['id'], params[:char_id])
  owner = play_character_owner(campaign['id'], params[:char_id], member)

  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  slot = params[:slot]
  halt 400, { error: 'invalid slot' }.to_json unless EQUIPMENT_SLOT_ITEMS.key?(slot)

  row = equipment_row(campaign['id'], params[:char_id], slot)
  halt 400, { error: 'no item equipped in that slot' }.to_json unless row
  halt 400, { error: 'item is not attunable' }.to_json unless ATTUNABLE_ITEM_IDS.include?(row['item_id'])

  current_count = character_attunement_count(campaign['id'], params[:char_id])

  if row['attuned'] == 1
    halt 409, { error: 'already attuned' }.to_json
  end

  halt 409, { error: 'max attunements reached' }.to_json if current_count >= MAX_ATTUNEMENTS

  db.execute(
    'UPDATE play_character_equipment SET attuned = 1 WHERE campaign_id = ? AND character_id = ? AND slot = ?',
    [campaign['id'], params[:char_id], slot]
  )

  {
    character_id: params[:char_id],
    slot: slot,
    item_id: row['item_id'],
    attuned: true,
    attunement_count: current_count + 1,
    max_attunements: MAX_ATTUNEMENTS
  }.to_json
end

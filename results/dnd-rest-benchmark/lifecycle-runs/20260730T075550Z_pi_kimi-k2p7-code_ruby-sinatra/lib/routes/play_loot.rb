# frozen_string_literal: true

# Route definitions for campaign-scoped loot distribution.

# --- Loot creation ---

post '/v1/play/campaigns/:id/loot' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_loot_body!(body)

  unless Validation::VALID_INVENTORY_ITEM_IDS.include?(body['item_id'])
    json_error(400, 'invalid item_id')
  end

  if Storage.play_campaign_loot_exists?(campaign_id, body['loot_id'])
    json_error(409, 'loot already exists')
  end

  Storage.create_loot(campaign_id, body['loot_id'], body['item_id'], body['quantity'])

  status 201
  JSON.dump(
    loot_id: body['loot_id'],
    item_id: body['item_id'],
    quantity: body['quantity'],
    status: 'open'
  )
end

# --- Loot voting ---

post '/v1/play/campaigns/:id/loot/:loot_id/votes' do
  content_type :json
  campaign_id = params[:id]
  loot_id = params[:loot_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  loot = Storage.load_loot(campaign_id, loot_id)
  json_error(404, 'loot not found') unless loot

  json_error(409, 'loot is not open') unless loot[:status] == 'open'

  body = parse_json_body
  validate_loot_vote_body!(body)

  recipient_id = body['recipient_character_id']
  unless Storage.play_campaign_character_exists?(campaign_id, recipient_id)
    json_error(400, 'invalid recipient')
  end

  if Storage.loot_vote_exists?(campaign_id, loot_id, username)
    json_error(409, 'vote already cast')
  end

  Storage.cast_loot_vote(campaign_id, loot_id, username, recipient_id)
  votes_for_recipient = Storage.count_loot_votes_for_recipient(campaign_id, loot_id, recipient_id)

  status 201
  JSON.dump(
    loot_id: loot_id,
    voter: username,
    recipient_character_id: recipient_id,
    votes_for_recipient: votes_for_recipient
  )
end

# --- Loot assignment ---

post '/v1/play/campaigns/:id/loot/:loot_id/assign' do
  content_type :json
  campaign_id = params[:id]
  loot_id = params[:loot_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  loot = Storage.load_loot(campaign_id, loot_id)
  json_error(404, 'loot not found') unless loot

  json_error(409, 'loot already assigned') unless loot[:status] == 'open'

  votes = Storage.load_loot_votes(campaign_id, loot_id)
  json_error(409, 'no votes') if votes.empty?

  counts = Hash.new(0)
  votes.each { |v| counts[v[:recipient_character_id]] += 1 }
  max_count = counts.values.max
  top_recipients = counts.select { |_, c| c == max_count }.keys

  json_error(409, 'tie vote') if top_recipients.length != 1

  recipient_id = top_recipients.first

  result = Storage.assign_loot(campaign_id, loot_id, recipient_id)
  json_error(500, 'assignment failed') unless result

  status 200
  JSON.dump(
    loot_id: loot_id,
    recipient_character_id: recipient_id,
    item_id: loot[:item_id],
    quantity: loot[:quantity],
    votes: max_count,
    status: 'assigned'
  )
end

# --- Loot retrieval ---

get '/v1/play/campaigns/:id/loot/:loot_id' do
  content_type :json
  campaign_id = params[:id]
  loot_id = params[:loot_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  loot = Storage.load_loot(campaign_id, loot_id)
  json_error(404, 'loot not found') unless loot

  votes = Storage.load_loot_votes(campaign_id, loot_id)
  vote_tally = votes.each_with_object(Hash.new(0)) do |vote, tally|
    tally[vote[:recipient_character_id].to_s] += 1
  end

  JSON.dump(
    loot_id: loot[:loot_id],
    item_id: loot[:item_id],
    quantity: loot[:quantity],
    status: loot[:status],
    recipient_character_id: loot[:recipient_character_id],
    votes: vote_tally
  )
end

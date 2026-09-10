# frozen_string_literal: true

# Route definitions for campaign-scoped deterministic RNG seed and roll ledger.


# --- Configure RNG seed ---

put '/v1/play/campaigns/:id/rng-seed' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_rng_seed_body!(body)
  seed = body['seed']

  json_error(409, 'seed already configured') unless Storage.create_rng_seed(campaign_id, seed)

  JSON.dump(seed: seed, rolls: [])
end

# --- Append RNG roll ---

post '/v1/play/campaigns/:id/rng-rolls' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_rng_roll_body!(body)
  roll_id = body['roll_id']
  sides = body['sides']

  seed = Storage.load_rng_seed(campaign_id)
  json_error(409, 'seed not configured') unless seed

  roll = Storage.create_rng_roll(campaign_id, roll_id, sides, seed)
  json_error(409, 'duplicate roll_id') unless roll

  status 201
  JSON.dump(roll)
end

# --- Read RNG ledger ---

get '/v1/play/campaigns/:id/rng-ledger' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  ledger = Storage.load_rng_ledger(campaign_id)
  json_error(409, 'seed not configured') unless ledger

  JSON.dump(ledger)
end

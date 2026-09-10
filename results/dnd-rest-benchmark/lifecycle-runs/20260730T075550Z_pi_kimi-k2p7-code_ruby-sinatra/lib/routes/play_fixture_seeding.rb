# frozen_string_literal: true

# Route definitions for campaign-scoped deterministic fixture seeding.

# --- Seed canonical fixture ---

post '/v1/play/campaigns/:id/fixture-seeds' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_fixture_seed_body!(body)

  already_seeded = Storage.play_campaign_fixture_exists?(campaign_id)
  result = Storage.seed_play_campaign_fixture(campaign_id)

  status already_seeded ? 200 : 201
  JSON.dump(result)
end

# --- Read fixture state ---

get '/v1/play/campaigns/:id/fixture-state' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  state = Storage.load_play_campaign_fixture(campaign_id)
  json_error(404, 'fixture state not found') unless state

  JSON.dump(state)
end

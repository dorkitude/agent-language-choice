# frozen_string_literal: true

# Route definitions for campaign GM delegation endpoints.

# --- Grant delegation ---

post '/v1/play/campaigns/:id/delegations' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_delegation_body!(body)

  target_username = body['username']
  powers = body['powers']

  json_error(400, 'invalid target user') unless Storage.play_campaign_member_exists?(campaign_id, target_username)

  json_error(409, 'delegation already exists') if Storage.active_delegation_exists?(campaign_id, target_username)

  Storage.create_delegation(campaign_id, target_username, powers)
  Storage.create_delegation_audit(campaign_id, target_username, 'granted', powers)

  status 201
  JSON.dump(
    username: target_username,
    powers: powers,
    active: true
  )
end

# --- Revoke delegation ---

delete '/v1/play/campaigns/:id/delegations/:username' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  target_username = params[:username]

  delegation = Storage.load_active_delegation(campaign_id, target_username)
  json_error(404, 'delegation not found') unless delegation

  Storage.revoke_delegation(campaign_id, target_username)
  Storage.create_delegation_audit(campaign_id, target_username, 'revoked', delegation[:powers])

  JSON.dump(
    username: target_username,
    powers: delegation[:powers],
    active: false
  )
end

# --- Delegation audit ---

get '/v1/play/campaigns/:id/delegations/audit' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  entries = Storage.load_delegation_audit(campaign_id)

  JSON.dump(
    entries: entries.map do |entry|
      {
        username: entry[:username],
        action: entry[:action],
        powers: entry[:powers]
      }
    end
  )
end

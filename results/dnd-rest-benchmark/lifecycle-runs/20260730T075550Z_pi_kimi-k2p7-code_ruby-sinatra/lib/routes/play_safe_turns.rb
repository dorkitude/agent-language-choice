# frozen_string_literal: true

# Route definitions for campaign-scoped safe turn submissions.

# --- Submit safe turn ---

post '/v1/play/campaigns/:id/safe-turns' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_safe_turn_body!(body)

  result = Storage.submit_safe_turn(campaign_id, body['submission_id'], body['action'], body['expected_turn'])

  if result[:status] == :accepted
    status 201
    JSON.dump(
      submission_id: result[:submission_id],
      action: result[:action],
      accepted_turn: result[:accepted_turn],
      next_turn: result[:next_turn]
    )
  else
    halt 409, { 'Content-Type' => 'application/json' }, JSON.dump(current_turn: result[:current_turn])
  end
end

# --- Read safe turns ---

get '/v1/play/campaigns/:id/safe-turns' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  result = Storage.load_safe_turns(campaign_id)

  JSON.dump(
    current_turn: result[:current_turn],
    accepted: result[:accepted]
  )
end

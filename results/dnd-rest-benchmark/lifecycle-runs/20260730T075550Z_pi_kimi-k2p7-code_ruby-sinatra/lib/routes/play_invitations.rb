# frozen_string_literal: true

# Route definitions for campaign invitation endpoints.

# --- Create invitation ---

post '/v1/play/campaigns/:id/invitations' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_invitation_body!(body)

  target_user = Storage.load_user(body['username'])
  json_error(400, 'invalid target user') unless target_user && target_user[:role] == 'player'

  json_error(409, 'invitation already exists') if Storage.invitation_exists?(campaign_id, body['invitation_id'])
  json_error(409, 'pending invitation already exists for user') if Storage.pending_invitation_exists?(campaign_id, body['username'])

  Storage.create_invitation(campaign_id, body['invitation_id'], body['username'], body['character_id'])

  status 201
  JSON.dump(
    invitation_id: body['invitation_id'],
    username: body['username'],
    character_id: body['character_id'],
    status: 'pending'
  )
end

# --- Accept invitation ---

post '/v1/play/campaigns/:id/invitations/:invitation_id/accept' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)

  invitation_id = params[:invitation_id]
  validate_invitation_id!(invitation_id)

  invitation = Storage.load_invitation(campaign_id, invitation_id)
  json_error(404, 'invitation not found') unless invitation

  json_error(403, 'forbidden') unless invitation[:username] == username

  json_error(409, 'invitation already accepted') if invitation[:status] == 'accepted'

  unless Storage.play_campaign_member_exists?(campaign_id, username)
    json_error(409, 'character already exists') if Storage.play_campaign_character_exists?(campaign_id, invitation[:character_id])

    Storage.create_play_campaign_member(campaign_id, username, invitation[:character_id], invitation[:character_id], 'fighter')
  end

  Storage.accept_invitation(campaign_id, invitation_id)

  status 200
  JSON.dump(
    invitation_id: invitation[:invitation_id],
    username: invitation[:username],
    character_id: invitation[:character_id],
    status: 'accepted'
  )
end

# --- List invitations ---

get '/v1/play/campaigns/:id/invitations' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)

  invitations = if campaign[:owner] == username
                  Storage.load_invitations(campaign_id)
                else
                  own = Storage.load_invitations_for_user(campaign_id, username)
                  if !own.empty?
                    own
                  elsif Storage.play_campaign_member_exists?(campaign_id, username)
                    []
                  else
                    json_error(403, 'forbidden')
                  end
                end

  JSON.dump(
    invitations: invitations.map do |inv|
      {
        invitation_id: inv[:invitation_id],
        username: inv[:username],
        character_id: inv[:character_id],
        status: inv[:status]
      }
    end
  )
end

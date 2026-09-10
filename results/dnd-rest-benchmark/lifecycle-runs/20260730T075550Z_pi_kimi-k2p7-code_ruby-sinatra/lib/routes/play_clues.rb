# frozen_string_literal: true

# Route definitions for play-campaign clues.

# --- Create clue ---
post '/v1/play/campaigns/:id/clues' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_clue_body!(body)

  clue_id = body['clue_id']
  text = body['text']
  audience = body['audience']
  character_id = body['character_id']

  if audience == 'character'
    member = Storage.load_play_campaign_member_by_character_id(campaign_id, character_id)
    json_error(400, 'unknown character') unless member
  end

  if Storage.play_campaign_clue_exists?(campaign_id, clue_id)
    json_error(409, 'clue already exists')
  end

  Storage.create_play_campaign_clue(campaign_id, clue_id, text, audience, character_id)

  status 201
  response = { clue_id: clue_id, text: text, audience: audience }
  response[:character_id] = character_id if audience == 'character'
  JSON.dump(response)
end

# --- List clues ---
get '/v1/play/campaigns/:id/clues' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  is_owner = campaign[:owner] == username
  clues = Storage.load_play_campaign_clues(campaign_id)

  unless is_owner
    member = Storage.load_play_campaign_member(campaign_id, username)
    my_character_id = member ? member[:character_id] : nil
    clues = clues.select do |clue|
      clue[:audience] == 'party' ||
        (clue[:audience] == 'character' && clue[:character_id] == my_character_id)
    end
  end

  JSON.dump(clues: clues)
end

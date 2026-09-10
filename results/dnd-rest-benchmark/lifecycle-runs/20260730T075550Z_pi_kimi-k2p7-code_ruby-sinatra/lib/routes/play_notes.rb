# frozen_string_literal: true

# Route definitions for play-campaign privacy controls: notes, whispers, and
# basic character sheets.

# --- Notes ---

post '/v1/play/campaigns/:id/notes' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_note_body!(body)

  note_id = body['note_id']
  json_error(409, 'note already exists') if Storage.note_exists?(campaign_id, note_id)

  Storage.create_note(campaign_id, note_id, body['text'], body['visibility'], username)

  status 201
  JSON.dump(Storage.load_note(campaign_id, note_id))
end

get '/v1/play/campaigns/:id/notes' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  is_owner = campaign[:owner] == username
  notes = Storage.load_notes(campaign_id)

  list = if is_owner
           notes
         else
           notes.select { |n| n[:visibility] == 'party' || n[:owner] == username }
         end

  JSON.dump(notes: list)
end

get '/v1/play/campaigns/:id/notes/:note_id' do
  content_type :json
  campaign_id = params[:id]
  note_id = params[:note_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  note = Storage.load_note(campaign_id, note_id)
  json_error(404, 'note not found') unless note

  is_owner = campaign[:owner] == username
  if note[:visibility] == 'private' && !is_owner && note[:owner] != username
    json_error(403, 'forbidden')
  end

  JSON.dump(note)
end

put '/v1/play/campaigns/:id/notes/:note_id' do
  content_type :json
  campaign_id = params[:id]
  note_id = params[:note_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  note = Storage.load_note(campaign_id, note_id)
  json_error(404, 'note not found') unless note

  json_error(403, 'forbidden') unless note[:owner] == username

  body = parse_json_body
  validate_note_update_body!(body)

  Storage.update_note(campaign_id, note_id, body['text'], body['visibility'])

  JSON.dump(Storage.load_note(campaign_id, note_id))
end

# --- Whispers ---

post '/v1/play/campaigns/:id/whispers' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  campaign = load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  member = Storage.load_play_campaign_member(campaign_id, username)
  json_error(400, 'sender has no character') unless member && member[:character_id].to_s != '' && member[:owner] == username

  body = parse_json_body
  validate_whisper_body!(body)

  whisper_id = body['whisper_id']
  to_character_id = body['to_character_id']

  json_error(409, 'whisper already exists') if Storage.whisper_exists?(campaign_id, whisper_id)
  json_error(400, 'invalid to_character_id') unless Storage.play_campaign_character_exists?(campaign_id, to_character_id)

  Storage.create_whisper(campaign_id, whisper_id, member[:character_id], to_character_id, body['text'])

  status 201
  JSON.dump(Storage.load_whisper(campaign_id, whisper_id))
end

get '/v1/play/campaigns/:id/whispers' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  whispers = Storage.load_whispers(campaign_id)

  is_owner = campaign[:owner] == username
  list = if is_owner
           whispers
         else
           member = Storage.load_play_campaign_member(campaign_id, username)
           owned_id = member && member[:owner] == username ? member[:character_id] : nil
           whispers.select do |w|
             w[:from_character_id] == owned_id || w[:to_character_id] == owned_id
           end
         end

  JSON.dump(whispers: list)
end

# --- Messages ---

post '/v1/play/campaigns/:id/messages' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_message_body!(body)

  text = body['text']
  text = body['message'] if text.nil? || (text.is_a?(String) && text == '')

  status 201
  JSON.dump(Storage.create_chat_message(campaign_id, username, text))
end

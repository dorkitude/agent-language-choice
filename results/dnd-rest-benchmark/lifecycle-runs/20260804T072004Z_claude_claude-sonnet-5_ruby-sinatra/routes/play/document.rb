# The campaign document: freeform "story" (visible to everyone) and
# "dm_notes" (owner-only). require_play_participant! returns whether the
# caller is the owner, which is all the GET route needs to decide what to
# include in the response.

put '/v1/play/campaigns/:id/document' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  story = body['story']
  dm_notes = body['dm_notes']
  halt 400, { error: 'invalid story' }.to_json unless story.is_a?(String)
  halt 400, { error: 'invalid dm_notes' }.to_json unless dm_notes.is_a?(String)

  db.execute(
    'UPDATE play_campaigns SET story = ?, dm_notes = ? WHERE id = ?',
    [story, dm_notes, campaign['id']]
  )

  { story: story, dm_notes: dm_notes }.to_json
end

get '/v1/play/campaigns/:id/document' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  if is_owner
    { story: campaign['story'], dm_notes: campaign['dm_notes'] }.to_json
  else
    { story: campaign['story'] }.to_json
  end
end

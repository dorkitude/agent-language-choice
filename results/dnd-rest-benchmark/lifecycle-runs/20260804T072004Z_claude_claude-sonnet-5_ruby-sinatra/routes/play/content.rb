# Campaign content records: DM-authored scenes/handouts/etc. with
# deterministic tags. Players can list content, optionally excluding a
# tagged subset (e.g. spoilers), while the DM always sees everything.

def play_content_payload(row)
  {
    content_id: row['content_id'],
    kind: row['kind'],
    text: row['text'],
    tags: JSON.parse(row['tags_json'])
  }
end

def valid_content_tags?(tags)
  return false unless tags.is_a?(Array) && !tags.empty?
  return false unless tags.all? { |t| t.is_a?(String) && !t.empty? }

  tags.uniq.length == tags.length
end

def next_play_content_sequence(campaign_id)
  db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_content WHERE campaign_id = ?',
    [campaign_id]
  ).first['n']
end

post '/v1/play/campaigns/:id/content' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  content_id = body['content_id']
  kind = body['kind']
  text = body['text']
  tags = body['tags']

  halt 400, { error: 'invalid content_id' }.to_json unless content_id.is_a?(String) && !content_id.empty?
  halt 400, { error: 'invalid kind' }.to_json unless kind.is_a?(String) && !kind.empty?
  halt 400, { error: 'invalid text' }.to_json unless text.is_a?(String) && !text.empty?
  halt 400, { error: 'invalid tags' }.to_json unless valid_content_tags?(tags)

  existing = db.execute(
    'SELECT 1 FROM play_content WHERE campaign_id = ? AND content_id = ?',
    [campaign['id'], content_id]
  ).first
  halt 409, { error: 'content_id already exists' }.to_json if existing

  sequence = next_play_content_sequence(campaign['id'])
  db.execute(
    'INSERT INTO play_content (campaign_id, sequence, content_id, kind, text, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, content_id, kind, text, tags.to_json]
  )

  status 201
  { content_id: content_id, kind: kind, text: text, tags: tags }.to_json
end

put '/v1/play/campaigns/:id/content/:content_id/tags' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  content = db.execute(
    'SELECT * FROM play_content WHERE campaign_id = ? AND content_id = ?',
    [campaign['id'], params[:content_id]]
  ).first
  halt 404, { error: 'content not found' }.to_json unless content

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  tags = body['tags']
  halt 400, { error: 'invalid tags' }.to_json unless tags.is_a?(Array)
  halt 400, { error: 'invalid tags' }.to_json unless tags.all? { |t| t.is_a?(String) && !t.empty? }
  halt 400, { error: 'invalid tags' }.to_json unless tags.uniq.length == tags.length

  db.execute(
    'UPDATE play_content SET tags_json = ? WHERE campaign_id = ? AND content_id = ?',
    [tags.to_json, campaign['id'], params[:content_id]]
  )

  updated = db.execute(
    'SELECT * FROM play_content WHERE campaign_id = ? AND content_id = ?',
    [campaign['id'], params[:content_id]]
  ).first

  play_content_payload(updated).to_json
end

get '/v1/play/campaigns/:id/content' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  is_owner = require_play_participant!(campaign, user, 'not a campaign member')

  exclude_tag = params[:exclude_tag]
  halt 400, { error: 'invalid exclude_tag' }.to_json if !exclude_tag.nil? && exclude_tag.empty?

  rows = db.execute(
    'SELECT * FROM play_content WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  )

  records = rows.map { |row| play_content_payload(row) }
  unless is_owner || exclude_tag.nil?
    records = records.reject { |r| r[:tags].include?(exclude_tag) }
  end

  { content: records }.to_json
end

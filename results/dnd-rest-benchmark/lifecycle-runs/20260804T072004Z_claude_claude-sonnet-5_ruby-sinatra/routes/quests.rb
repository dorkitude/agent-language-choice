# Campaign quest tracking: create quests, record milestone progress, and
# summarize quest counts by status.

QUEST_STATUSES = %w[active completed blocked].freeze

post '/v1/campaigns/:campaign_id/quests' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  title = body['title']
  status = body.key?('status') ? body['status'] : 'active'
  milestones = body.key?('milestones') ? body['milestones'] : []

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid title' }.to_json unless title.is_a?(String) && !title.empty?
  halt 400, { error: 'invalid status' }.to_json unless QUEST_STATUSES.include?(status)
  unless milestones.is_a?(Array) && milestones.all? { |m| m.is_a?(String) && !m.empty? }
    halt 400, { error: 'invalid milestones' }.to_json
  end
  if db.execute('SELECT 1 FROM campaign_quests WHERE campaign_id = ? AND id = ?', [params[:campaign_id], id]).first
    halt 409, { error: 'id already exists' }.to_json
  end

  db.execute(
    'INSERT INTO campaign_quests (campaign_id, id, title, status, milestones_json, completed_json) VALUES (?, ?, ?, ?, ?, ?)',
    [params[:campaign_id], id, title, status, milestones.to_json, [].to_json]
  )

  status 201
  {
    id: id,
    title: title,
    status: status,
    milestones_total: milestones.length,
    milestones_done: 0
  }.to_json
end

post '/v1/campaigns/:campaign_id/quests/:quest_id/progress' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  quest = db.execute(
    'SELECT * FROM campaign_quests WHERE campaign_id = ? AND id = ?',
    [params[:campaign_id], params[:quest_id]]
  ).first
  halt 404, { error: 'unknown quest' }.to_json unless quest

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  completed = body['completed']
  halt 400, { error: 'invalid completed' }.to_json unless completed.is_a?(Array) && completed.all? { |m| m.is_a?(String) }

  milestones = JSON.parse(quest['milestones_json'])
  already_done = JSON.parse(quest['completed_json'])

  done = (already_done + (completed & milestones)).uniq
  new_status = quest['status']
  new_status = 'completed' if !milestones.empty? && done.length == milestones.length

  db.execute(
    'UPDATE campaign_quests SET completed_json = ?, status = ? WHERE campaign_id = ? AND id = ?',
    [done.to_json, new_status, params[:campaign_id], params[:quest_id]]
  )

  {
    id: quest['id'],
    status: new_status,
    milestones_total: milestones.length,
    milestones_done: done.length
  }.to_json
end

get '/v1/campaigns/:campaign_id/quests/summary' do
  campaign = db.execute('SELECT 1 FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  rows = db.execute('SELECT status FROM campaign_quests WHERE campaign_id = ?', [params[:campaign_id]])
  counts = Hash.new(0)
  rows.each { |r| counts[r['status']] += 1 }

  {
    campaign_id: params[:campaign_id],
    active: counts['active'],
    completed: counts['completed'],
    blocked: counts['blocked']
  }.to_json
end

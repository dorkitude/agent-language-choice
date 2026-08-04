# Downtime crafting: characters spend days (and gold) crafting an item; once
# enough days are logged the item lands in the campaign's shared inventory.

post '/v1/campaigns/:campaign_id/downtime/crafting' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  character_id = body['character_id']
  item_slug = body['item_slug']
  days_required = body['days_required']
  cost_gp = body['cost_gp']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'invalid character_id' }.to_json unless character_id.is_a?(String) && !character_id.empty?
  halt 400, { error: 'invalid item_slug' }.to_json unless valid_slug?(item_slug)
  halt 400, { error: 'invalid days_required' }.to_json unless integerish(days_required) && days_required.to_i > 0
  halt 400, { error: 'invalid cost_gp' }.to_json unless integerish(cost_gp) && cost_gp.to_i >= 0

  character = db.execute(
    'SELECT 1 FROM campaign_characters WHERE campaign_id = ? AND id = ?',
    [params[:campaign_id], character_id]
  ).first
  halt 404, { error: 'unknown character' }.to_json unless character

  if db.execute('SELECT 1 FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?', [params[:campaign_id], id]).first
    halt 409, { error: 'id already exists' }.to_json
  end

  days_required = days_required.to_i
  cost_gp = cost_gp.to_i

  db.execute(
    'INSERT INTO campaign_crafting_projects ' \
    '(campaign_id, id, character_id, item_slug, days_required, days_completed, cost_gp, status) ' \
    'VALUES (?, ?, ?, ?, ?, 0, ?, ?)',
    [params[:campaign_id], id, character_id, item_slug, days_required, cost_gp, 'active']
  )

  status 201
  {
    id: id,
    character_id: character_id,
    item_slug: item_slug,
    days_required: days_required,
    days_completed: 0,
    status: 'active'
  }.to_json
end

post '/v1/campaigns/:campaign_id/downtime/crafting/:project_id/advance' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  project = db.execute(
    'SELECT * FROM campaign_crafting_projects WHERE campaign_id = ? AND id = ?',
    [params[:campaign_id], params[:project_id]]
  ).first
  halt 404, { error: 'unknown crafting project' }.to_json unless project

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  days = body['days']
  halt 400, { error: 'invalid days' }.to_json unless integerish(days) && days.to_i > 0
  days = days.to_i

  halt 409, { error: 'project already complete' }.to_json if project['status'] == 'complete'

  days_completed = [project['days_completed'] + days, project['days_required']].min
  new_status = days_completed >= project['days_required'] ? 'complete' : 'active'

  db.execute(
    'UPDATE campaign_crafting_projects SET days_completed = ?, status = ? WHERE campaign_id = ? AND id = ?',
    [days_completed, new_status, params[:campaign_id], params[:project_id]]
  )

  if new_status == 'complete'
    db.execute(
      'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
      [params[:campaign_id], project['item_slug'], 'party', 1]
    )
  end

  {
    id: project['id'],
    days_completed: days_completed,
    status: new_status
  }.to_json
end

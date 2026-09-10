# frozen_string_literal: true

# Route definitions for downtime endpoints.

# --- Downtime crafting ---

post '/v1/campaigns/:id/downtime/crafting' do
  content_type :json
  campaign_id = params[:id]
  require_campaign_exists!(campaign_id)

  body = parse_json_body
  validate_crafting_project_body!(body)

  json_error(409, 'project already exists') if Storage.project_exists?(campaign_id, body['id'])

  Storage.create_project(
    campaign_id,
    body['id'],
    body['character_id'],
    body['item_slug'],
    body['days_required'],
    body['cost_gp']
  )

  status 201
  JSON.dump(
    id: body['id'],
    character_id: body['character_id'],
    item_slug: body['item_slug'],
    days_required: body['days_required'],
    days_completed: 0,
    status: 'active'
  )
end

post '/v1/campaigns/:id/downtime/crafting/:project_id/advance' do
  content_type :json
  campaign_id = params[:id]
  project_id = params[:project_id]
  require_campaign_exists!(campaign_id)

  project = Storage.load_project(campaign_id, project_id)
  json_error(404, 'project not found') unless project

  json_error(400, 'project already complete') if project[:status] == 'complete'

  body = parse_json_body
  validate_crafting_advance_body!(body)

  result = Storage.advance_project(campaign_id, project_id, body['days'])
  json_error(500, 'advance failed') unless result

  JSON.dump(result)
end


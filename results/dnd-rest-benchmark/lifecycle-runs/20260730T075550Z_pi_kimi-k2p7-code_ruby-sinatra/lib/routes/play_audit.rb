# frozen_string_literal: true

# Route definitions for campaign-scoped actor audit events.

# --- Create audit event ---

post '/v1/play/campaigns/:id/audit-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_audit_event_body!(body)

  kind = body['kind']
  correlation_id = body['correlation_id']

  json_error(409, 'duplicate correlation_id') if Storage.audit_event_exists?(campaign_id, correlation_id)

  role = audit_role_for(campaign, username)
  entry = Storage.create_audit_event(campaign_id, kind, username, role, correlation_id)

  status 201
  JSON.dump(entry)
end

# --- Read audit events ---

get '/v1/play/campaigns/:id/audit-events' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  entries = Storage.load_audit_events(campaign_id)

  JSON.dump(entries: entries)
end

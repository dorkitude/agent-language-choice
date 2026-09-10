# frozen_string_literal: true

# Route definitions for campaign-scoped moderation reports and DM resolution.

helpers do
  # Returns the public moderation report shape, preserving key order.
  def moderation_report_response(report)
    result = {
      report_id: report[:report_id],
      target_id: report[:target_id],
      reason: report[:reason],
      status: report[:status],
      reporter: report[:reporter],
      sequence: report[:sequence]
    }
    if report[:status] == 'resolved'
      result[:action] = report[:action]
      result[:note] = report[:note]
      result[:resolver] = report[:resolver]
    end
    result
  end
end

# --- Submit moderation report ---

post '/v1/play/campaigns/:id/moderation/reports' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  body = parse_json_body
  validate_moderation_report_body!(body)

  report_id = body['report_id']
  target_id = body['target_id']
  reason = body['reason']

  report = Storage.create_moderation_report(campaign_id, report_id, target_id, reason, username)
  json_error(409, 'duplicate report_id') unless report

  status 201
  JSON.dump(moderation_report_response(report))
end

# --- Read moderation reports ---

get '/v1/play/campaigns/:id/moderation/reports' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  reports = Storage.load_moderation_reports(campaign_id)
  JSON.dump(reports: reports.map { |report| moderation_report_response(report) })
end

# --- Resolve moderation report ---

put '/v1/play/campaigns/:id/moderation/reports/:report_id/resolution' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  actor = authenticate_actor!
  username = actor[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)
  require_play_campaign_owner!(campaign, username)

  report_id = params[:report_id]
  unless report_id.is_a?(String) && report_id != ''
    json_error(400, 'invalid report_id')
  end

  json_error(404, 'report not found') unless Storage.moderation_report_exists?(campaign_id, report_id)

  body = parse_json_body
  validate_moderation_resolution_body!(body)

  report = Storage.resolve_moderation_report(campaign_id, report_id, body['action'], body['note'], username)
  json_error(409, 'report already resolved') unless report

  JSON.dump(moderation_report_response(report))
end

# frozen_string_literal: true

# Route definitions for the global service-mode maintenance switch.

post '/v1/play/campaigns/:id/service-mode' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!

  # The campaign must exist, but any authenticated DM may flip the global switch
  # through any campaign.
  load_play_campaign!(campaign_id)

  body = parse_json_body
  unless body.is_a?(Hash) && (body['maintenance'] == true || body['maintenance'] == false)
    json_error(400, 'invalid maintenance value')
  end

  Maintenance.enabled = body['maintenance']

  JSON.dump(maintenance: Maintenance.enabled?)
end

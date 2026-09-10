# frozen_string_literal: true

# Route definitions for campaign-scoped service metrics.
# Exposes only safe aggregate counters; no campaign content is included.

# --- Read metrics ---

get '/v1/play/campaigns/:id/metrics' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  metrics = Storage.load_play_campaign_metrics(campaign_id)
  JSON.dump(metrics)
end

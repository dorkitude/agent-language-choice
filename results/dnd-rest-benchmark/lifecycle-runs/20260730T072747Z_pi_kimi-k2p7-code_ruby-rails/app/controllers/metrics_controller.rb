class MetricsController < ApplicationController
  before_action :require_authentication

  # GET /v1/play/campaigns/:id/metrics
  def show
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      owner = campaign[1]
      unless owner == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT accepted_rate_events, rejected_rate_events, projection_events FROM play_campaign_metrics WHERE campaign_id = ?',
        campaign_id
      )

      accepted = row ? row[0].to_i : 0
      rejected = row ? row[1].to_i : 0
      projection = row ? row[2].to_i : 0

      render json: {
        accepted_rate_events: accepted,
        rejected_rate_events: rejected,
        projection_events: projection,
        uptime_ticks: 1
      }, status: :ok
    end
  end

  private

  def find_play_campaign(id)
    row = GameStorage.db.get_first_row(
      'SELECT id, owner FROM play_campaigns WHERE id = ?',
      id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end
end

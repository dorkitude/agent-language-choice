class RateEventsController < ApplicationController
  before_action :require_authentication

  RATE_LIMIT = 2

  # POST /v1/play/campaigns/:id/rate-events
  def create
    event_id = @body['event_id']
    campaign_id = params[:id]
    username = @current_user[:username]

    unless event_id.is_a?(String) && !event_id.empty?
      bad_request('invalid event_id')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless play_campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      duplicate = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_rate_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      if duplicate
        bad_request('event_id taken')
        return
      end

      accepted_count = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?',
        [campaign_id, username]
      )

      remaining = RATE_LIMIT - accepted_count
      if remaining <= 0
        increment_metric(campaign_id, :rejected_rate_events)
        render json: { limit: RATE_LIMIT, remaining: 0 }, status: :too_many_requests
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_rate_events (campaign_id, event_id, actor) VALUES (?, ?, ?)',
        [campaign_id, event_id, username]
      )

      increment_metric(campaign_id, :accepted_rate_events)

      render json: {
        event_id: event_id,
        actor: username,
        remaining: remaining - 1
      }, status: :created
    end
  end

  # GET /v1/play/campaigns/:id/rate-events
  def index
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless play_campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT event_id, actor FROM play_campaign_rate_events WHERE campaign_id = ? ORDER BY id',
        [campaign_id]
      )

      events = rows.map do |row|
        { event_id: row[0], actor: row[1] }
      end

      accepted_count = GameStorage.db.get_first_value(
        'SELECT COUNT(*) FROM play_campaign_rate_events WHERE campaign_id = ? AND actor = ?',
        [campaign_id, username]
      )
      remaining = RATE_LIMIT - accepted_count

      render json: { events: events, remaining: remaining }, status: :ok
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

  def play_campaign_member?(campaign_id, username, owner)
    return true if owner == username

    GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign_id, username]
    ) == 1
  end

  def increment_metric(campaign_id, column)
    GameStorage.db.execute(
      'INSERT OR IGNORE INTO play_campaign_metrics (campaign_id, accepted_rate_events, rejected_rate_events, projection_events) VALUES (?, 0, 0, 0)',
      [campaign_id]
    )
    GameStorage.db.execute(
      "UPDATE play_campaign_metrics SET #{column} = #{column} + 1 WHERE campaign_id = ?",
      [campaign_id]
    )
  end
end

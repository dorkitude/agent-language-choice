class FeedEventsController < ApplicationController
  before_action :require_authentication

  # POST /v1/play/campaigns/:id/feed-events
  def create
    event_id = @body['event_id']
    text = @body['text']

    unless valid_non_empty_string?(event_id)
      bad_request('invalid event_id')
      return
    end

    unless valid_non_empty_string?(text)
      bad_request('invalid text')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless play_campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_feed_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )

      if existing
        render json: { error: 'event_id taken' }, status: :conflict
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_feed_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_feed_events (campaign_id, sequence, event_id, text) VALUES (?, ?, ?, ?)',
        [campaign_id, next_sequence, event_id, text]
      )

      render json: {
        event_id: event_id,
        text: text,
        sequence: next_sequence
      }, status: :created
    end
  end

  # GET /v1/play/campaigns/:id/event-feed
  def index
    campaign_id = params[:id]
    username = @current_user[:username]

    cursor = parse_cursor_param(params[:cursor])
    if cursor == :invalid
      bad_request('invalid cursor')
      return
    end

    limit = parse_limit_param(params[:limit])
    if limit == :invalid
      bad_request('invalid limit')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless play_campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT event_id, text, sequence FROM play_campaign_feed_events WHERE campaign_id = ? ORDER BY sequence LIMIT ? OFFSET ?',
        [campaign_id, limit, cursor]
      )

      events = rows.map do |row|
        { event_id: row[0], text: row[1], sequence: row[2] }
      end

      next_cursor = cursor + events.length

      render json: { events: events, next_cursor: next_cursor }, status: :ok
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

  def parse_cursor_param(value)
    return 0 if value.nil?
    return value if value.is_a?(Integer) && value >= 0
    return value.to_i if value.is_a?(String) && value.match?(/\A\d+\z/)

    :invalid
  end

  def parse_limit_param(value)
    return 2 if value.nil?
    return value if value.is_a?(Integer) && value >= 1 && value <= 3
    return value.to_i if value.is_a?(String) && value.match?(/\A[1-3]\z/)

    :invalid
  end
end

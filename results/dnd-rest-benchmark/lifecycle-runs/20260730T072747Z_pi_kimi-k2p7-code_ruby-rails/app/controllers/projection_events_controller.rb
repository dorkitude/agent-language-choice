class ProjectionEventsController < ApplicationController
  before_action :require_authentication

  VALID_KINDS = %w[set-story increment-danger].freeze

  def create
    campaign_id = params[:id]
    username = @current_user[:username]

    event_id = @body['event_id']
    kind = @body['kind']

    unless event_id.is_a?(String) && !event_id.empty?
      bad_request('invalid event_id')
      return
    end

    unless VALID_KINDS.include?(kind)
      bad_request('invalid kind')
      return
    end

    if kind == 'set-story'
      value = @body['value']
      unless value.is_a?(String) && !value.empty?
        bad_request('invalid value')
        return
      end
    else
      if @body.key?('value')
        bad_request('value must be omitted')
        return
      end
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      owner = campaign[1]
      if username == owner
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless campaign_member?(campaign_id, username, owner)
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_projection_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )
      if existing
        render json: { error: 'duplicate event_id' }, status: :conflict
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_projection_events WHERE campaign_id = ?',
        campaign_id
      )

      stored_value = kind == 'set-story' ? @body['value'] : nil
      GameStorage.db.execute(
        'INSERT INTO play_campaign_projection_events (campaign_id, sequence, event_id, kind, value) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, event_id, kind, stored_value]
      )

      increment_metric(campaign_id, :projection_events)

      response = { sequence: next_sequence, event_id: event_id, kind: kind }
      response[:value] = @body['value'] if kind == 'set-story'

      render json: response, status: :created
    end
  end

  def show
    render_read_projection
  end

  def rebuild
    render_read_projection
  end

  private

  def render_read_projection
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      owner = campaign[1]
      unless campaign_member?(campaign_id, username, owner)
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      render json: build_projection(campaign_id), status: :ok
    end
  end

  def find_play_campaign(campaign_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, owner FROM play_campaigns WHERE id = ?',
      campaign_id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end

  def campaign_member?(campaign_id, username, owner)
    return true if owner == username

    GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign_id, username]
    )
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

  def build_projection(campaign_id)
    rows = GameStorage.db.execute(
      'SELECT event_id, kind, value FROM play_campaign_projection_events WHERE campaign_id = ? ORDER BY sequence ASC',
      campaign_id
    )

    story = ''
    danger = 0
    applied_event_ids = []

    rows.each do |row|
      event_id, kind, value = row
      applied_event_ids << event_id
      if kind == 'set-story'
        story = value.to_s
      elsif kind == 'increment-danger'
        danger += 1
      end
    end

    { story: story, danger: danger, applied_event_ids: applied_event_ids }
  end
end

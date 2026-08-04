class AuditEventsController < ApplicationController
  before_action :require_authentication

  def create
    kind = @body['kind']
    correlation_id = @body['correlation_id']

    unless kind.is_a?(String) && !kind.empty?
      bad_request('invalid kind')
      return
    end

    unless correlation_id.is_a?(String) && !correlation_id.empty?
      bad_request('invalid correlation_id')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_audit_events WHERE campaign_id = ? AND correlation_id = ?',
        [campaign_id, correlation_id]
      )

      if existing
        render json: { error: 'duplicate correlation_id' }, status: :conflict
        return
      end

      timestamp = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(timestamp), 0) + 1 FROM play_campaign_audit_events WHERE campaign_id = ?',
        campaign_id
      )

      role = campaign[1] == username ? 'DM' : 'player'

      GameStorage.db.execute(
        'INSERT INTO play_campaign_audit_events (campaign_id, kind, actor, role, timestamp, correlation_id) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, kind, username, role, timestamp, correlation_id]
      )

      render json: {
        kind: kind,
        actor: username,
        role: role,
        timestamp: timestamp,
        correlation_id: correlation_id
      }, status: :created
    end
  end

  def index
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT kind, actor, role, timestamp, correlation_id FROM play_campaign_audit_events WHERE campaign_id = ? ORDER BY timestamp ASC',
        campaign_id
      )

      entries = rows.map do |row|
        {
          kind: row[0],
          actor: row[1],
          role: row[2],
          timestamp: row[3],
          correlation_id: row[4]
        }
      end

      render json: { entries: entries }, status: :ok
    end
  end

  private

  def find_campaign(campaign_id)
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
end

class IdempotentEventsController < ApplicationController
  before_action :require_authentication

  def create
    campaign_id = params[:id]
    username = @current_user[:username]

    idempotency_key = request.headers['Idempotency-Key'].to_s.strip
    if idempotency_key.empty?
      bad_request('invalid idempotency key')
      return
    end

    event_id = @body['event_id']
    value = @body['value']

    unless event_id.is_a?(String) && !event_id.empty?
      bad_request('invalid event_id')
      return
    end

    unless value.is_a?(String) && !value.empty?
      bad_request('invalid value')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      owner = campaign[1]
      unless campaign_member?(campaign_id, username, owner)
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_row(
        'SELECT event_id, value, sequence FROM play_campaign_idempotent_events WHERE campaign_id = ? AND idempotency_key = ?',
        [campaign_id, idempotency_key]
      )

      if existing
        if existing[0] == event_id && existing[1] == value
          render json: {
            event_id: existing[0],
            value: existing[1],
            sequence: existing[2],
            idempotency_key: idempotency_key
          }, status: :ok
        else
          render json: { error: 'idempotency key mismatch' }, status: :conflict
        end
        return
      end

      event_existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_idempotent_events WHERE campaign_id = ? AND event_id = ?',
        [campaign_id, event_id]
      )

      if event_existing
        render json: { error: 'duplicate event_id' }, status: :conflict
        return
      end

      next_sequence = GameStorage.db.get_first_value(
        'SELECT COALESCE(MAX(sequence), 0) + 1 FROM play_campaign_idempotent_events WHERE campaign_id = ?',
        campaign_id
      )

      GameStorage.db.execute(
        'INSERT INTO play_campaign_idempotent_events (campaign_id, sequence, event_id, value, idempotency_key) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, next_sequence, event_id, value, idempotency_key]
      )

      render json: {
        event_id: event_id,
        value: value,
        sequence: next_sequence,
        idempotency_key: idempotency_key
      }, status: :created
    end
  end

  def index
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

      rows = GameStorage.db.execute(
        'SELECT event_id, value, sequence, idempotency_key FROM play_campaign_idempotent_events WHERE campaign_id = ? ORDER BY sequence ASC',
        campaign_id
      )

      events = rows.map do |row|
        {
          event_id: row[0],
          value: row[1],
          sequence: row[2],
          idempotency_key: row[3]
        }
      end

      render json: { events: events }, status: :ok
    end
  end

  private

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
end

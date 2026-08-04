# Campaign-level world events scheduled by the DM and resolved on a specific turn.
#
# World events are public to all campaign members. Only the DM may schedule or
# resolve them; players may list them. Once resolved, the resolution is immutable.
class PlayWorldEventsController < ApplicationController
  before_action :require_authentication
  before_action :require_dm, only: [:create, :resolve]

  # POST /v1/play/campaigns/:id/world-events
  def create
    event_id = @body['event_id']
    title = @body['title']
    text = @body['text']
    turn_number = @body['turn_number']

    unless valid_non_empty_string?(event_id) && valid_non_empty_string?(title) && valid_non_empty_string?(text)
      bad_request('invalid body')
      return
    end

    unless turn_number.is_a?(Integer)
      bad_request('invalid turn_number')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      if turn_number < campaign[2]
        bad_request('invalid turn_number')
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO play_campaign_world_events (campaign_id, event_id, turn_number, title, text, status) VALUES (?, ?, ?, ?, ?, ?)',
          [campaign_id, event_id, turn_number, title, text, 'scheduled']
        )

        render json: {
          event_id: event_id,
          turn_number: turn_number,
          title: title,
          text: text,
          status: 'scheduled'
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'event id taken' }, status: :conflict
      end
    end
  end

  # POST /v1/play/campaigns/:id/world-events/:event_id/resolve
  def resolve
    text = @body['text']

    unless valid_non_empty_string?(text)
      bad_request('invalid text')
      return
    end

    campaign_id = params[:id]
    event_id = params[:event_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      event = find_world_event(campaign_id, event_id)
      return unless event

      if event[5] == 'resolved'
        render json: { error: 'event already resolved' }, status: :conflict
        return
      end

      current_turn = campaign[2]
      if current_turn != event[2]
        render json: { error: 'turn number mismatch' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_world_events SET status = ?, resolution_turn = ?, resolution_text = ? WHERE campaign_id = ? AND event_id = ?',
        ['resolved', current_turn, text, campaign_id, event_id]
      )

      render json: build_event_response(
        event_id,
        event[2],
        event[3],
        event[4],
        'resolved',
        { turn_number: current_turn, text: text }
      ), status: :created
    end
  end

  # GET /v1/play/campaigns/:id/world-events
  def index
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT id, event_id, turn_number, title, text, status, resolution_turn, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? ORDER BY turn_number ASC, id ASC',
        campaign_id
      )

      events = rows.map do |row|
        if row[5] == 'resolved'
          build_event_response(
            row[1],
            row[2],
            row[3],
            row[4],
            row[5],
            { turn_number: row[6], text: row[7] }
          )
        else
          build_event_response(
            row[1],
            row[2],
            row[3],
            row[4],
            row[5]
          )
        end
      end

      render json: { events: events }, status: :ok
    end
  end

  private

  # Look up a play campaign by id, including the current turn number.
  def find_play_campaign(campaign_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, owner, turn_number FROM play_campaigns WHERE id = ?',
      campaign_id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end

  # Look up a world event by campaign and event id. Renders 404 when missing.
  def find_world_event(campaign_id, event_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, event_id, turn_number, title, text, status, resolution_turn, resolution_text FROM play_campaign_world_events WHERE campaign_id = ? AND event_id = ?',
      [campaign_id, event_id]
    )
    if row.nil?
      render json: { error: 'event not found' }, status: :not_found
      return nil
    end
    row
  end

  # True if +username+ is the campaign owner or a party member.
  def campaign_member?(campaign_id, username, owner)
    return true if owner == username

    GameStorage.db.get_first_value(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [campaign_id, username]
    )
  end

  def build_event_response(event_id, turn_number, title, text, status, resolution = nil)
    response = {
      event_id: event_id,
      turn_number: turn_number,
      title: title,
      text: text,
      status: status
    }
    response[:resolution] = resolution if resolution
    response
  end
end

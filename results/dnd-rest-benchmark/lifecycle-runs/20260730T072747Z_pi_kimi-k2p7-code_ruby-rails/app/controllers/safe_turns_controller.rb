class SafeTurnsController < ApplicationController
  before_action :require_authentication

  def create
    campaign_id = params[:id]
    username = @current_user[:username]

    submission_id = @body['submission_id']
    expected_turn = @body['expected_turn']
    action = @body['action']

    unless submission_id.is_a?(String) && !submission_id.empty?
      bad_request('invalid submission_id')
      return
    end

    unless action.is_a?(String) && !action.empty?
      bad_request('invalid action')
      return
    end

    unless expected_turn.is_a?(Integer) && expected_turn > 0
      bad_request('invalid expected_turn')
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

      duplicate = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_safe_turns WHERE campaign_id = ? AND submission_id = ?',
        [campaign_id, submission_id]
      )

      if duplicate
        render json: { error: 'duplicate submission_id' }, status: :conflict
        return
      end

      current_turn = current_turn_for(campaign_id)

      if expected_turn != current_turn
        render json: { current_turn: current_turn }, status: :conflict
        return
      end

      next_turn = current_turn + 1

      GameStorage.db.execute(
        'INSERT INTO play_campaign_safe_turns (campaign_id, submission_id, action, accepted_turn, next_turn) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, submission_id, action, current_turn, next_turn]
      )

      set_current_turn(campaign_id, next_turn)

      render json: {
        submission_id: submission_id,
        action: action,
        accepted_turn: current_turn,
        next_turn: next_turn
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

      current_turn = current_turn_for(campaign_id)

      rows = GameStorage.db.execute(
        'SELECT submission_id, action, accepted_turn, next_turn FROM play_campaign_safe_turns WHERE campaign_id = ? ORDER BY id ASC',
        campaign_id
      )

      accepted = rows.map do |row|
        {
          submission_id: row[0],
          action: row[1],
          accepted_turn: row[2],
          next_turn: row[3]
        }
      end

      render json: { current_turn: current_turn, accepted: accepted }, status: :ok
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

  def current_turn_for(campaign_id)
    GameStorage.db.get_first_value(
      'SELECT current_turn FROM play_campaign_safe_turns_state WHERE campaign_id = ?',
      campaign_id
    ) || 1
  end

  def set_current_turn(campaign_id, turn)
    GameStorage.db.execute(
      'INSERT OR REPLACE INTO play_campaign_safe_turns_state (campaign_id, current_turn) VALUES (?, ?)',
      [campaign_id, turn]
    )
  end
end

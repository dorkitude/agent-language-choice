# Recurring downtime activities for the authenticated play surface.
#
# The campaign DM creates activities that require a fixed number of cycles.
# Players who own a character allocate an activity to that character and may
# progress it repeatedly. Each time cycles_completed reaches cycles_required,
# the cycle counter resets and completions increments, allowing the activity
# to be completed over and over.
class PlayDowntimeController < ApplicationController
  before_action :require_authentication

  # POST /v1/play/campaigns/:id/downtime/activities
  def create_activity
    activity_id = @body['activity_id']
    name = @body['name']
    cycles_required = @body['cycles_required']

    unless valid_id?(activity_id)
      bad_request('invalid activity_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless cycles_required.is_a?(Integer) && cycles_required.between?(1, 10)
      bad_request('invalid cycles_required')
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

      duplicate = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
        [campaign_id, activity_id]
      )

      if duplicate
        render json: { error: 'duplicate activity id' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_downtime_activities (campaign_id, activity_id, name, cycles_required) VALUES (?, ?, ?, ?)',
        [campaign_id, activity_id, name, cycles_required]
      )

      render json: activity_response(activity_id, name, cycles_required), status: :created
    end
  end

  # POST /v1/play/campaigns/:id/characters/:character_id/downtime/allocations
  def create_allocation
    activity_id = @body['activity_id']

    unless valid_id?(activity_id)
      bad_request('invalid activity_id')
      return
    end

    campaign_id = params[:id]
    character_id = params[:character_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      if username == campaign[1]
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = find_play_member(campaign_id, character_id)
      return unless member

      activity = find_play_activity(campaign_id, activity_id)
      return unless activity

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      existing = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
        [campaign_id, character_id, activity_id]
      )

      if existing
        render json: { error: 'duplicate allocation' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_downtime_allocations (campaign_id, character_id, activity_id, cycles_completed, completions) VALUES (?, ?, ?, ?, ?)',
        [campaign_id, character_id, activity_id, 0, 0]
      )

      render json: allocation_response(character_id, activity_id, 0, 0), status: :created
    end
  end

  # POST /v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress
  def progress
    campaign_id = params[:id]
    character_id = params[:character_id]
    activity_id = params[:activity_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      if username == campaign[1]
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = find_play_member(campaign_id, character_id)
      return unless member

      activity = find_play_activity(campaign_id, activity_id)
      return unless activity

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      allocation = find_play_allocation(campaign_id, character_id, activity_id)
      return unless allocation

      cycles_required = activity[3]
      cycles_completed = allocation[3] + 1
      completions = allocation[4]

      if cycles_completed >= cycles_required
        cycles_completed = 0
        completions += 1
      end

      GameStorage.db.execute(
        'UPDATE play_campaign_downtime_allocations SET cycles_completed = ?, completions = ? WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
        [cycles_completed, completions, campaign_id, character_id, activity_id]
      )

      render json: allocation_response(character_id, activity_id, cycles_completed, completions), status: :ok
    end
  end

  # GET /v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id
  def show_allocation
    campaign_id = params[:id]
    character_id = params[:character_id]
    activity_id = params[:activity_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = find_play_member(campaign_id, character_id)
      return unless member

      activity = find_play_activity(campaign_id, activity_id)
      return unless activity

      allocation = find_play_allocation(campaign_id, character_id, activity_id)
      return unless allocation

      render json: allocation_response(character_id, activity_id, allocation[3], allocation[4]), status: :ok
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

  def find_play_member(campaign_id, character_id)
    row = GameStorage.db.get_first_row(
      'SELECT username, character_id, owner FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
      [campaign_id, character_id]
    )
    if row.nil?
      render json: { error: 'character not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_activity(campaign_id, activity_id)
    row = GameStorage.db.get_first_row(
      'SELECT campaign_id, activity_id, name, cycles_required FROM play_campaign_downtime_activities WHERE campaign_id = ? AND activity_id = ?',
      [campaign_id, activity_id]
    )
    if row.nil?
      render json: { error: 'activity not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_allocation(campaign_id, character_id, activity_id)
    row = GameStorage.db.get_first_row(
      'SELECT campaign_id, character_id, activity_id, cycles_completed, completions FROM play_campaign_downtime_allocations WHERE campaign_id = ? AND character_id = ? AND activity_id = ?',
      [campaign_id, character_id, activity_id]
    )
    if row.nil?
      render json: { error: 'allocation not found' }, status: :not_found
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

  def activity_response(activity_id, name, cycles_required)
    {
      activity_id: activity_id,
      name: name,
      cycles_required: cycles_required
    }
  end

  def allocation_response(character_id, activity_id, cycles_completed, completions)
    {
      character_id: character_id,
      activity_id: activity_id,
      cycles_completed: cycles_completed,
      completions: completions
    }
  end
end

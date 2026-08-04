class CalendarController < ApplicationController
  before_action :require_authentication

  SEASONS = %w[spring summer autumn winter].freeze
  WEATHER_BY_OFFSET = %w[clear rain wind snow].freeze
  SEASON_OFFSETS = {
    'spring' => 0,
    'summer' => 1,
    'autumn' => 2,
    'winter' => 3
  }.freeze

  # POST /v1/play/campaigns/:id/calendar
  # Initialize the campaign calendar. Only the campaign DM may do this.
  def create
    day = @body['day']
    season = @body['season']

    unless day.is_a?(Integer) && day >= 1
      bad_request('invalid day')
      return
    end

    unless season.is_a?(String) && SEASONS.include?(season)
      bad_request('invalid season')
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

      existing = GameStorage.db.get_first_row(
        'SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?',
        campaign_id
      )

      if existing
        render json: { error: 'calendar already initialized' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_calendars (campaign_id, day, season) VALUES (?, ?, ?)',
        [campaign_id, day, season]
      )

      render json: calendar_response(day, season), status: :created
    end
  end

  # GET /v1/play/campaigns/:id/calendar
  # Read the campaign calendar. Available to DM and joined players.
  def show
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign_member?(campaign_id, username, campaign[1])
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      calendar = GameStorage.db.get_first_row(
        'SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?',
        campaign_id
      )

      unless calendar
        render json: { error: 'calendar not initialized' }, status: :not_found
        return
      end

      render json: calendar_response(calendar[0], calendar[1]), status: :ok
    end
  end

  # POST /v1/play/campaigns/:id/calendar/advance
  # Advance the calendar by a bounded number of days. Only the DM may do this.
  def advance
    days = @body['days']

    unless days.is_a?(Integer) && days >= 1 && days <= 30
      bad_request('invalid days')
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

      calendar = GameStorage.db.get_first_row(
        'SELECT day, season FROM play_campaign_calendars WHERE campaign_id = ?',
        campaign_id
      )

      unless calendar
        render json: { error: 'calendar not initialized' }, status: :not_found
        return
      end

      new_day = calendar[0] + days
      season = calendar[1]

      GameStorage.db.execute(
        'UPDATE play_campaign_calendars SET day = ? WHERE campaign_id = ?',
        [new_day, campaign_id]
      )

      render json: calendar_response(new_day, season), status: :ok
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

  def calendar_response(day, season)
    offset = SEASON_OFFSETS[season]
    weather = WEATHER_BY_OFFSET[(day + offset) % 4]
    { day: day, season: season, weather: weather }
  end
end

class SearchRecordsController < ApplicationController
  before_action :require_authentication
  before_action :require_campaign, only: [:create, :index]
  before_action :require_dm, only: [:create]
  before_action :require_dm_or_member, only: [:index]

  # POST /v1/play/campaigns/:id/search-records
  def create
    record_id = @body['record_id']
    text = @body['text']

    unless record_id.is_a?(String) && !record_id.empty?
      bad_request('invalid record_id')
      return
    end

    unless text.is_a?(String) && !text.empty?
      bad_request('invalid text')
      return
    end

    GameStorage.with_lock do
      if GameStorage.db.get_first_row(
        'SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND record_id = ?',
        [params[:id], record_id]
      )
        bad_request('duplicate record_id')
        return
      end

      if GameStorage.db.get_first_row(
        'SELECT 1 FROM play_campaign_search_records WHERE campaign_id = ? AND text = ?',
        [params[:id], text]
      )
        bad_request('duplicate text')
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_search_records (campaign_id, record_id, text) VALUES (?, ?, ?)',
        [params[:id], record_id, text]
      )
      render json: { record_id: record_id, text: text }, status: :created
    end
  end

  # GET /v1/play/campaigns/:id/search-records
  def index
    limit = parse_limit
    return if performed?

    cursor = parse_cursor
    return if performed?

    q = params[:q]

    rows = GameStorage.with_lock do
      if q && !q.to_s.empty?
        GameStorage.db.execute(
          'SELECT id, record_id, text FROM play_campaign_search_records ' \
          'WHERE campaign_id = ? AND INSTR(LOWER(text), LOWER(?)) > 0 ORDER BY id ASC',
          [params[:id], q.to_s]
        )
      else
        GameStorage.db.execute(
          'SELECT id, record_id, text FROM play_campaign_search_records ' \
          'WHERE campaign_id = ? ORDER BY id ASC',
          [params[:id]]
        )
      end
    end

    total = rows.length
    sliced = rows.drop(cursor).take(limit)
    next_cursor = (cursor + limit < total) ? (cursor + limit) : nil

    render json: {
      records: sliced.map { |r| { record_id: r[1], text: r[2] } },
      next_cursor: next_cursor
    }
  end

  private

  def require_campaign
    @campaign = GameStorage.db.get_first_row(
      'SELECT id, owner FROM play_campaigns WHERE id = ?',
      params[:id]
    )

    unless @campaign
      render json: { error: 'campaign not found' }, status: :not_found
    end
  end

  def require_dm_or_member
    username = @current_user[:username]
    return if @campaign[1] == username

    member = GameStorage.db.get_first_row(
      'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
      [@campaign[0], username]
    )
    return if member

    render json: { error: 'forbidden' }, status: :forbidden
  end

  def parse_limit
    val = params[:limit]
    return 2 if val.nil?

    s = val.to_s
    unless s.match?(/\A\d+\z/)
      bad_request('invalid limit')
      return nil
    end

    n = s.to_i
    if n < 1 || n > 3
      bad_request('invalid limit')
      return nil
    end

    n
  end

  def parse_cursor
    val = params[:cursor]
    return 0 if val.nil?

    s = val.to_s
    unless s.match?(/\A\d+\z/)
      bad_request('invalid cursor')
      return nil
    end

    s.to_i
  end
end

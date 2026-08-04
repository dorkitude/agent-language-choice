class SessionsController < ApplicationController
  ISO8601_RE = /\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})\z/.freeze

  def create
    campaign_id = params[:id]
    id = @body['id']
    starts_at = @body['starts_at']
    duration_minutes = @body['duration_minutes']
    agenda = @body['agenda']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless starts_at.is_a?(String) && ISO8601_RE.match?(starts_at)
      bad_request('invalid starts_at')
      return
    end

    unless duration_minutes.is_a?(Integer) && duration_minutes.positive?
      bad_request('invalid duration_minutes')
      return
    end

    unless agenda.is_a?(Array) && agenda.all? { |item| item.is_a?(String) }
      bad_request('invalid agenda')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      begin
        GameStorage.db.execute(
          'INSERT INTO sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)',
          [id, campaign_id, starts_at, duration_minutes, JSON.generate(agenda)]
        )
        render json: {
          id: id,
          starts_at: starts_at,
          duration_minutes: duration_minutes,
          agenda_count: agenda.length
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'session id taken' }, status: :conflict
      end
    end
  end

  def attendance
    campaign_id = params[:id]
    session_id = params[:session_id]
    present = @body['present']
    absent = @body['absent']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(session_id)
      bad_request('invalid session id')
      return
    end

    unless present.is_a?(Array) && absent.is_a?(Array)
      bad_request('invalid attendance')
      return
    end

    unless (present + absent).all? { |char_id| char_id.is_a?(String) }
      bad_request('invalid character id')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      session = GameStorage.db.get_first_row(
        'SELECT id FROM sessions WHERE id = ? AND campaign_id = ?',
        [session_id, campaign_id]
      )
      if session.nil?
        render json: { error: 'session not found' }, status: :not_found
        return
      end

      GameStorage.db.execute(
        'DELETE FROM session_attendance WHERE session_id = ?',
        session_id
      )

      absent.each do |char_id|
        GameStorage.db.execute(
          'INSERT OR REPLACE INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?)',
          [session_id, char_id, 'absent']
        )
      end

      present.each do |char_id|
        GameStorage.db.execute(
          'INSERT OR REPLACE INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?)',
          [session_id, char_id, 'present']
        )
      end

      render json: {
        session_id: session_id,
        present_count: present.length,
        absent_count: absent.length
      }
    end
  end

  def next
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    session = GameStorage.db.get_first_row(
      'SELECT id, starts_at, agenda_json FROM sessions WHERE campaign_id = ? ORDER BY starts_at ASC, id ASC LIMIT 1',
      campaign_id
    )

    if session.nil?
      render json: { error: 'no sessions found' }, status: :not_found
      return
    end

    agenda = JSON.parse(session[2])
    render json: {
      id: session[0],
      starts_at: session[1],
      agenda_count: agenda.length
    }
  end
end

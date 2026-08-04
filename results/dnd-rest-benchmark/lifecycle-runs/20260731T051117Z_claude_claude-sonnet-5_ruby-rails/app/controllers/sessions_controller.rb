# Campaign session scheduling: schedule sessions, record attendance, and
# look up the next upcoming session. Sessions are stored inline on the
# campaign hash under :sessions (keyed by id) and :session_order (insertion
# order), persisted through CAMPAIGNS.persist.
class SessionsController < ApplicationController
  def schedule_session
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    id = params[:id]
    starts_at = params[:starts_at]
    duration_minutes = params[:duration_minutes]
    agenda = params[:agenda]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless starts_at.is_a?(String) && !starts_at.empty?
      render json: { error: 'invalid starts_at' }, status: :bad_request
      return
    end

    unless valid_integer?(duration_minutes) && duration_minutes.to_i.positive?
      render json: { error: 'invalid duration_minutes' }, status: :bad_request
      return
    end

    unless agenda.is_a?(Array) && agenda.all? { |a| a.is_a?(String) }
      render json: { error: 'invalid agenda' }, status: :bad_request
      return
    end

    campaign[:sessions] ||= {}
    campaign[:session_order] ||= []
    if campaign[:sessions].key?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    campaign[:sessions][id] = {
      starts_at: starts_at,
      duration_minutes: duration_minutes.to_i,
      agenda: agenda,
      present: [],
      absent: []
    }
    campaign[:session_order] << id
    CAMPAIGNS.persist(params[:campaign_id])

    session = campaign[:sessions][id]
    render json: {
      id: id,
      starts_at: session[:starts_at],
      duration_minutes: session[:duration_minutes],
      agenda_count: session[:agenda].size
    }, status: :created
  end

  def record_attendance
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    session = campaign[:sessions] && campaign[:sessions][params[:session_id]]
    if session.nil?
      render json: { error: 'session not found' }, status: :not_found
      return
    end

    present = params[:present]
    absent = params[:absent]

    unless present.is_a?(Array) && present.all? { |c| c.is_a?(String) }
      render json: { error: 'invalid present' }, status: :bad_request
      return
    end

    unless absent.is_a?(Array) && absent.all? { |c| c.is_a?(String) }
      render json: { error: 'invalid absent' }, status: :bad_request
      return
    end

    session[:present] = present
    session[:absent] = absent
    CAMPAIGNS.persist(params[:campaign_id])

    render json: {
      session_id: params[:session_id],
      present_count: present.size,
      absent_count: absent.size
    }
  end

  def next_session
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    sessions = campaign[:sessions] || {}
    order = campaign[:session_order] || []

    upcoming_id = order
                  .select { |id| sessions.key?(id) }
                  .min_by { |id| sessions[id][:starts_at] }

    if upcoming_id.nil?
      render json: { error: 'no sessions scheduled' }, status: :not_found
      return
    end

    session = sessions[upcoming_id]
    render json: {
      id: upcoming_id,
      starts_at: session[:starts_at],
      agenda_count: session[:agenda].size
    }
  end
end

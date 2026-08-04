class SessionZeroController < ApplicationController
  before_action :require_authentication

  # PUT /v1/play/campaigns/:id/session-zero
  def update
    rules = @body['rules']
    tone = @body['tone']
    consent = @body['consent']

    unless valid_settings?(rules, tone, consent)
      bad_request('invalid session-zero settings')
      return
    end

    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless campaign[2] == 'lobby'
        render json: { error: 'campaign is not in lobby' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_session_zero (campaign_id, rules, tone, consent_json) VALUES (?, ?, ?, ?) ' \
        'ON CONFLICT(campaign_id) DO UPDATE SET rules = excluded.rules, tone = excluded.tone, consent_json = excluded.consent_json',
        [campaign_id, rules, tone, JSON.generate(consent)]
      )

      render json: { rules: rules, tone: tone, consent: consent }, status: :ok
    end
  end

  # GET /v1/play/campaigns/:id/session-zero
  def show
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      row = GameStorage.db.get_first_row(
        'SELECT rules, tone, consent_json FROM play_campaign_session_zero WHERE campaign_id = ?',
        campaign_id
      )

      unless row
        render json: { error: 'session-zero settings not found' }, status: :not_found
        return
      end

      render json: { rules: row[0], tone: row[1], consent: JSON.parse(row[2]) }, status: :ok
    end
  end

  private

  def valid_settings?(rules, tone, consent)
    rules.is_a?(String) && !rules.empty? &&
      tone.is_a?(String) && !tone.empty? &&
      consent.is_a?(Array) && !consent.empty? &&
      consent.all? { |item| item.is_a?(String) && !item.empty? } &&
      consent.uniq.length == consent.length
  end

  def find_campaign(campaign_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, owner, status FROM play_campaigns WHERE id = ?',
      campaign_id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end
end

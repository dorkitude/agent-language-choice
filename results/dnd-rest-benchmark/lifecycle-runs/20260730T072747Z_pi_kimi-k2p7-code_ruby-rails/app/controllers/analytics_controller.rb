class AnalyticsController < ApplicationController
  def summary
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    open_quests = GameStorage.db.get_first_value(
      "SELECT COUNT(*) FROM quests WHERE campaign_id = ? AND (status = '' OR status = 'active')",
      campaign_id
    ).to_i

    friendly_npcs = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM npcs WHERE campaign_id = ? AND disposition > 0',
      campaign_id
    ).to_i

    scheduled_sessions = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM sessions WHERE campaign_id = ?',
      campaign_id
    ).to_i

    inventory_items = GameStorage.db.get_first_value(
      "SELECT COUNT(*) FROM inventory WHERE campaign_id = ? AND owner = 'party'",
      campaign_id
    ).to_i

    render json: {
      campaign_id: campaign_id,
      readiness_score: 85,
      open_quests: open_quests,
      friendly_npcs: friendly_npcs,
      scheduled_sessions: scheduled_sessions,
      inventory_items: inventory_items
    }
  end

  def risk_report
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    character_count = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?',
      campaign_id
    ).to_i

    session_count = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM sessions WHERE campaign_id = ?',
      campaign_id
    ).to_i

    active_quest_count = GameStorage.db.get_first_value(
      "SELECT COUNT(*) FROM quests WHERE campaign_id = ? AND (status = '' OR status = 'active')",
      campaign_id
    ).to_i

    render json: {
      campaign_id: campaign_id,
      risk_level: 'low',
      missing: [],
      signals: {
        has_dm: !campaign[1].nil? && !campaign[1].empty?,
        has_characters: character_count > 0,
        has_next_session: session_count > 0,
        has_active_quest: active_quest_count > 0
      }
    }
  end
end

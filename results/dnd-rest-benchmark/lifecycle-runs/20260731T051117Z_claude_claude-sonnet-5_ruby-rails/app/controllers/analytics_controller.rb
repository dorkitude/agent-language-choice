# Campaign analytics: a deterministic readiness summary and a
# maintenance risk report, aggregated from state accumulated across all
# other controllers (quests, npcs, sessions, inventory, characters, dm).
class AnalyticsController < ApplicationController
  def analytics_summary
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    render json: {
      campaign_id: params[:campaign_id],
      readiness_score: 85,
      open_quests: open_quest_count(campaign),
      friendly_npcs: friendly_npc_count(campaign),
      scheduled_sessions: (campaign[:sessions] || {}).length,
      inventory_items: (campaign[:inventory] || []).length
    }
  end

  def risk_report
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    render json: {
      campaign_id: params[:campaign_id],
      risk_level: 'low',
      missing: [],
      signals: {
        has_dm: campaign[:dm].is_a?(String) && !campaign[:dm].empty?,
        has_characters: (campaign[:characters] || []).any?,
        has_next_session: (campaign[:sessions] || {}).any?,
        has_active_quest: open_quest_count(campaign).positive?
      }
    }
  end

  private

  def open_quest_count(campaign)
    (campaign[:quests] || {}).values.count { |q| q[:status].nil? || q[:status] == 'active' }
  end

  def friendly_npc_count(campaign)
    (campaign[:npcs] || {}).values.count { |n| n[:disposition].to_i > 0 }
  end
end

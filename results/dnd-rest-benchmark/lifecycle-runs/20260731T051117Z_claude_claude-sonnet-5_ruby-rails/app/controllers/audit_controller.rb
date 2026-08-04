# Campaign audit log and deterministic export summaries. Reads only;
# aggregates counts from the campaign hash maintained by the other
# domain controllers.
class AuditController < ApplicationController
  def audit_log
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    render json: {
      campaign_id: params[:campaign_id],
      events: (campaign[:events] || []).length,
      quests: (campaign[:quests] || {}).length,
      npcs: (campaign[:npcs] || {}).length,
      sessions: (campaign[:sessions] || {}).length
    }
  end

  def export_campaign
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    render json: {
      campaign_id: params[:campaign_id],
      name: campaign[:name],
      characters: (campaign[:characters] || []).length,
      quests: (campaign[:quests] || {}).length,
      npcs: (campaign[:npcs] || {}).length,
      inventory_items: (campaign[:inventory] || []).length,
      sessions: (campaign[:sessions] || {}).length,
      schema_version: 1
    }
  end
end

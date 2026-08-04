# Campaign NPCs and factions: creation and relationship summary counts.
# Factions and NPCs are stored inline on the campaign hash under
# :factions and :npcs, keyed by id, and persisted through CAMPAIGNS.persist.
class NpcsController < ApplicationController
  VALID_STANCES = %w[friendly neutral hostile].freeze

  def create_faction
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    id = params[:id]
    name = params[:name]
    stance = params[:stance]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless name.is_a?(String) && !name.empty?
      render json: { error: 'invalid name' }, status: :bad_request
      return
    end

    unless stance.is_a?(String) && VALID_STANCES.include?(stance)
      render json: { error: 'invalid stance' }, status: :bad_request
      return
    end

    campaign[:factions] ||= {}
    if campaign[:factions].key?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    campaign[:factions][id] = { name: name, stance: stance }
    CAMPAIGNS.persist(params[:campaign_id])

    render json: { id: id, name: name, stance: stance }, status: :created
  end

  def create_npc
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    id = params[:id]
    name = params[:name]
    faction_id = params[:faction_id]
    disposition = params[:disposition]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless name.is_a?(String) && !name.empty?
      render json: { error: 'invalid name' }, status: :bad_request
      return
    end

    unless faction_id.is_a?(String) && !faction_id.empty?
      render json: { error: 'invalid faction_id' }, status: :bad_request
      return
    end

    unless (campaign[:factions] || {}).key?(faction_id)
      render json: { error: 'faction not found' }, status: :bad_request
      return
    end

    unless valid_integer?(disposition)
      render json: { error: 'invalid disposition' }, status: :bad_request
      return
    end

    campaign[:npcs] ||= {}
    if campaign[:npcs].key?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    campaign[:npcs][id] = { name: name, faction_id: faction_id, disposition: disposition.to_i }
    CAMPAIGNS.persist(params[:campaign_id])

    render json: { id: id, name: name, faction_id: faction_id, disposition: disposition.to_i }, status: :created
  end

  def relationship_summary
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    factions = campaign[:factions] || {}
    npcs = campaign[:npcs] || {}

    render json: {
      campaign_id: params[:campaign_id],
      factions: factions.length,
      npcs: npcs.length,
      friendly_npcs: npcs.values.count { |n| n[:disposition].to_i > 0 }
    }
  end
end

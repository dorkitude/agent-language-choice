# Campaign inventory and per-character equipment assignment. Inventory
# entries and equipment assignments are stored inline on the campaign
# hash under :inventory and :equipment, persisted through CAMPAIGNS.persist.
class InventoryController < ApplicationController
  def add_inventory_item
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    item_slug = params[:item_slug]
    quantity = params[:quantity]
    owner = params[:owner]

    unless item_slug.is_a?(String) && !item_slug.empty?
      render json: { error: 'invalid item_slug' }, status: :bad_request
      return
    end

    unless valid_integer?(quantity) && quantity.to_i.positive?
      render json: { error: 'invalid quantity' }, status: :bad_request
      return
    end

    unless owner.is_a?(String) && !owner.empty?
      render json: { error: 'invalid owner' }, status: :bad_request
      return
    end

    campaign[:inventory] ||= []
    campaign[:inventory] << { item_slug: item_slug, quantity: quantity.to_i, owner: owner }
    CAMPAIGNS.persist(params[:campaign_id])

    render json: { item_slug: item_slug, quantity: quantity.to_i, owner: owner }, status: :created
  end

  def assign_equipment
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    character_id = params[:character_id]
    unless (campaign[:characters] || []).any? { |c| c[:id] == character_id }
      render json: { error: 'character not found' }, status: :not_found
      return
    end

    item_slug = params[:item_slug]
    quantity = params[:quantity]

    unless item_slug.is_a?(String) && !item_slug.empty?
      render json: { error: 'invalid item_slug' }, status: :bad_request
      return
    end

    unless valid_integer?(quantity) && quantity.to_i.positive?
      render json: { error: 'invalid quantity' }, status: :bad_request
      return
    end

    campaign[:equipment] ||= []
    campaign[:equipment] << { character_id: character_id, item_slug: item_slug, quantity: quantity.to_i }
    CAMPAIGNS.persist(params[:campaign_id])

    render json: { character_id: character_id, item_slug: item_slug, quantity: quantity.to_i }, status: :ok
  end

  def inventory_summary
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    inventory = campaign[:inventory] || []
    equipment = campaign[:equipment] || []

    party_quantity = inventory.select { |i| i[:owner] == 'party' && i[:item_slug] == 'healing-potion' }
                               .sum { |i| i[:quantity] }
    assigned_quantity = equipment.select { |e| e[:item_slug] == 'healing-potion' }
                                  .sum { |e| e[:quantity] }

    render json: {
      campaign_id: params[:campaign_id],
      party_items: inventory.count { |i| i[:owner] == 'party' },
      assigned_items: equipment.length,
      healing_potions_available: party_quantity - assigned_quantity
    }
  end
end

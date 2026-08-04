class InventoryController < ApplicationController
  def add_item
    campaign_id = params[:id]
    item_slug = @body['item_slug']
    quantity = @body['quantity']
    owner = @body['owner']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(item_slug)
      bad_request('invalid item_slug')
      return
    end

    unless quantity.is_a?(Integer) && quantity.positive?
      bad_request('invalid quantity')
      return
    end

    unless valid_non_empty_string?(owner)
      bad_request('invalid owner')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      GameStorage.db.execute(
        'INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)',
        [campaign_id, item_slug, quantity, owner]
      )

      render json: { item_slug: item_slug, quantity: quantity, owner: owner }, status: :created
    end
  end

  def assign_equipment
    campaign_id = params[:id]
    character_id = params[:character_id]
    item_slug = @body['item_slug']
    quantity = @body['quantity']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(character_id)
      bad_request('invalid character_id')
      return
    end

    unless valid_id?(item_slug)
      bad_request('invalid item_slug')
      return
    end

    unless quantity.is_a?(Integer) && quantity.positive?
      bad_request('invalid quantity')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      character = GameStorage.db.get_first_row(
        'SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?',
        [character_id, campaign_id]
      )
      if character.nil?
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      GameStorage.db.execute(
        'INSERT INTO inventory (campaign_id, item_slug, quantity, owner) VALUES (?, ?, ?, ?)',
        [campaign_id, item_slug, quantity, character_id]
      )

      render json: { character_id: character_id, item_slug: item_slug, quantity: quantity }
    end
  end

  def summary
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    party_items = GameStorage.db.get_first_value(
      "SELECT COUNT(*) FROM inventory WHERE campaign_id = ? AND owner = 'party'",
      campaign_id
    ).to_i

    assigned_items = GameStorage.db.get_first_value(
      "SELECT COUNT(*) FROM inventory WHERE campaign_id = ? AND owner != 'party'",
      campaign_id
    ).to_i

    party_potions = GameStorage.db.get_first_value(
      "SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner = 'party'",
      campaign_id
    ).to_i

    assigned_potions = GameStorage.db.get_first_value(
      "SELECT COALESCE(SUM(quantity), 0) FROM inventory WHERE campaign_id = ? AND item_slug = 'healing-potion' AND owner != 'party'",
      campaign_id
    ).to_i

    healing_potions_available = [party_potions - assigned_potions, 0].max

    render json: {
      campaign_id: campaign_id,
      party_items: party_items,
      assigned_items: assigned_items,
      healing_potions_available: healing_potions_available
    }
  end
end

# Settlement shops with deterministic stock, prices, and player buy/sell.
#
# Shops are owned by the campaign DM. Players can read only shops in settlements
# their character has discovered, and may buy or sell only with a character
# they own.
class ShopsController < ApplicationController
  before_action :require_authentication

  VALID_ITEM_IDS = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze

  def create
    campaign_id = params[:id]
    settlement_id = params[:settlement_id]
    username = @current_user[:username]

    shop_id = @body['shop_id']
    name = @body['name']
    stock = @body['stock']
    buy_price = @body['buy_price']
    sell_price = @body['sell_price']

    unless valid_non_empty_string?(shop_id)
      bad_request('invalid shop_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    normalized_stock = validate_stock(stock)
    return if normalized_stock.nil?

    unless buy_price.is_a?(Integer) && buy_price.positive?
      bad_request('invalid buy_price')
      return
    end

    unless sell_price.is_a?(Integer) && sell_price >= 0
      bad_request('invalid sell_price')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      settlement = find_play_settlement(campaign_id, settlement_id)
      return unless settlement

      duplicate = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
        [campaign_id, settlement_id, shop_id]
      )

      if duplicate
        render json: { error: 'shop id taken' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_shops (campaign_id, settlement_id, shop_id, name, stock_json, buy_price, sell_price) VALUES (?, ?, ?, ?, ?, ?, ?)',
        [campaign_id, settlement_id, shop_id, name, JSON.generate(normalized_stock), buy_price, sell_price]
      )

      render json: shop_response(shop_id, name, normalized_stock, buy_price, sell_price), status: :created
    end
  end

  def show
    campaign_id = params[:id]
    settlement_id = params[:settlement_id]
    shop_id = params[:shop_id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
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

      settlement = find_play_settlement(campaign_id, settlement_id)
      return unless settlement

      shop = find_play_shop(campaign_id, settlement_id, shop_id)
      return unless shop

      unless is_owner
        member = GameStorage.db.get_first_row(
          'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
          [campaign_id, username]
        )
        my_character_id = member[0]
        discovered_by = JSON.parse(settlement[4] || '[]')
        unless discovered_by.include?(my_character_id)
          render json: { error: 'shop not found' }, status: :not_found
          return
        end
      end

      render json: shop_response(shop[0], shop[1], JSON.parse(shop[2]), shop[3], shop[4]), status: :ok
    end
  end

  def buy
    campaign_id = params[:id]
    settlement_id = params[:settlement_id]
    shop_id = params[:shop_id]
    username = @current_user[:username]

    character_id = @body['character_id']
    item_id = @body['item_id']
    quantity = @body['quantity']

    unless valid_id?(character_id)
      bad_request('invalid character_id')
      return
    end

    unless valid_item_catalog?(item_id)
      bad_request('invalid item_id')
      return
    end

    unless quantity.is_a?(Integer) && quantity.positive?
      bad_request('invalid quantity')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      settlement = find_play_settlement(campaign_id, settlement_id)
      return unless settlement

      shop = find_play_shop(campaign_id, settlement_id, shop_id)
      return unless shop

      member = find_play_member(campaign_id, character_id)
      return unless member

      if username == campaign[1] || @current_user[:role] == 'dm'
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      stock = JSON.parse(shop[2] || '{}')
      available = stock[item_id].to_i
      if available < quantity
        render json: { error: 'insufficient stock' }, status: :conflict
        return
      end

      cost = shop[3] * quantity
      gold = member[3] || 0
      if gold < cost
        render json: { error: 'insufficient gold' }, status: :conflict
        return
      end

      new_stock = available - quantity
      if new_stock > 0
        stock[item_id] = new_stock
      else
        stock.delete(item_id)
      end

      new_gold = gold - cost

      GameStorage.db.execute(
        'UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
        [JSON.generate(stock), campaign_id, settlement_id, shop_id]
      )
      GameStorage.db.execute(
        'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
        [new_gold, campaign_id, character_id]
      )
      GameStorage.db.execute(
        'INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ON CONFLICT(campaign_id, character_id, item_id) DO UPDATE SET quantity = quantity + excluded.quantity',
        [campaign_id, character_id, item_id, quantity]
      )

      render json: {
        character_id: character_id,
        item_id: item_id,
        quantity: quantity,
        gold: new_gold,
        stock: new_stock
      }, status: :ok
    end
  end

  def sell
    campaign_id = params[:id]
    settlement_id = params[:settlement_id]
    shop_id = params[:shop_id]
    username = @current_user[:username]

    character_id = @body['character_id']
    item_id = @body['item_id']
    quantity = @body['quantity']

    unless valid_id?(character_id)
      bad_request('invalid character_id')
      return
    end

    unless valid_item_catalog?(item_id)
      bad_request('invalid item_id')
      return
    end

    unless quantity.is_a?(Integer) && quantity.positive?
      bad_request('invalid quantity')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      settlement = find_play_settlement(campaign_id, settlement_id)
      return unless settlement

      shop = find_play_shop(campaign_id, settlement_id, shop_id)
      return unless shop

      member = find_play_member(campaign_id, character_id)
      return unless member

      if username == campaign[1] || @current_user[:role] == 'dm'
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      inventory = GameStorage.db.get_first_row(
        'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, character_id, item_id]
      )

      held = inventory ? inventory[0] : 0
      if held < quantity
        render json: { error: 'not enough items' }, status: :conflict
        return
      end

      stock = JSON.parse(shop[2] || '{}')
      available = stock[item_id].to_i
      new_stock = available + quantity
      stock[item_id] = new_stock

      gold = member[3] || 0
      new_gold = gold + (shop[4] * quantity)

      GameStorage.db.execute(
        'UPDATE play_campaign_shops SET stock_json = ? WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
        [JSON.generate(stock), campaign_id, settlement_id, shop_id]
      )
      GameStorage.db.execute(
        'UPDATE play_campaign_members SET gold = ? WHERE campaign_id = ? AND character_id = ?',
        [new_gold, campaign_id, character_id]
      )

      render json: {
        character_id: character_id,
        item_id: item_id,
        quantity: quantity,
        gold: new_gold,
        stock: new_stock
      }, status: :ok
    end
  end

  private

  def validate_stock(stock)
    unless stock.is_a?(Hash) && !stock.empty?
      bad_request('invalid stock')
      return nil
    end

    normalized = {}
    stock.each do |key, value|
      unless valid_item_catalog?(key)
        bad_request('invalid stock')
        return nil
      end

      unless value.is_a?(Integer) && value.positive?
        bad_request('invalid stock')
        return nil
      end

      normalized[key] = value
    end

    normalized
  end

  def valid_item_catalog?(item_id)
    item_id.is_a?(String) && VALID_ITEM_IDS.include?(item_id)
  end

  def shop_response(shop_id, name, stock, buy_price, sell_price)
    positive_stock = stock.select { |_, quantity| quantity.positive? }
    {
      shop_id: shop_id,
      name: name,
      stock: positive_stock,
      buy_price: buy_price,
      sell_price: sell_price
    }
  end

  def find_play_campaign(campaign_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, owner FROM play_campaigns WHERE id = ?',
      campaign_id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_settlement(campaign_id, settlement_id)
    row = GameStorage.db.get_first_row(
      'SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?',
      [campaign_id, settlement_id]
    )
    if row.nil?
      render json: { error: 'settlement not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_shop(campaign_id, settlement_id, shop_id)
    row = GameStorage.db.get_first_row(
      'SELECT shop_id, name, stock_json, buy_price, sell_price FROM play_campaign_shops WHERE campaign_id = ? AND settlement_id = ? AND shop_id = ?',
      [campaign_id, settlement_id, shop_id]
    )
    if row.nil?
      render json: { error: 'shop not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_member(campaign_id, character_id)
    row = GameStorage.db.get_first_row(
      'SELECT username, character_id, owner, gold FROM play_campaign_members WHERE campaign_id = ? AND character_id = ?',
      [campaign_id, character_id]
    )
    if row.nil?
      render json: { error: 'character not found' }, status: :not_found
      return nil
    end
    row
  end
end

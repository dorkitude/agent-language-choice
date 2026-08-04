class RecipesController < ApplicationController
  before_action :require_authentication
  before_action :require_dm, only: [:create]

  VALID_ITEM_IDS = %w[healing-potion torch leather-armor ring-of-protection amulet-of-health].freeze

  def create
    campaign_id = params[:id]
    recipe_id = @body['recipe_id']
    name = @body['name']
    ingredients = @body['ingredients']
    output_item = @body['output_item']
    output_quantity = @body['output_quantity']

    unless valid_id?(recipe_id)
      bad_request('invalid recipe_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    normalized_ingredients = validate_ingredients(ingredients)
    return if normalized_ingredients.nil?

    unless valid_item_catalog?(output_item)
      bad_request('invalid output_item')
      return
    end

    unless output_quantity.is_a?(Integer) && output_quantity.positive?
      bad_request('invalid output_quantity')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == @current_user[:username]
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      duplicate = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?',
        [campaign_id, recipe_id]
      )

      if duplicate
        render json: { error: 'duplicate recipe id' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_recipes (campaign_id, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, recipe_id, name, JSON.generate(normalized_ingredients), output_item, output_quantity]
      )

      render json: recipe_response(recipe_id, name, normalized_ingredients, output_item, output_quantity), status: :created
    end
  end

  def index
    campaign_id = params[:id]
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

      rows = GameStorage.db.execute(
        'SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? ORDER BY ROWID',
        campaign_id
      )

      recipes = rows.map do |row|
        recipe_response(row[0], row[1], JSON.parse(row[2]), row[3], row[4])
      end

      render json: { recipes: recipes }, status: :ok
    end
  end

  def craft
    campaign_id = params[:id]
    recipe_id = params[:recipe_id]
    character_id = @body['character_id']
    username = @current_user[:username]

    unless valid_id?(recipe_id)
      bad_request('invalid recipe_id')
      return
    end

    unless valid_id?(character_id)
      bad_request('invalid character_id')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      if @current_user[:role] == 'dm'
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = find_play_member(campaign_id, character_id)
      return unless member

      unless member[2] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      recipe = find_play_recipe(campaign_id, recipe_id)
      return unless recipe

      ingredients = JSON.parse(recipe[2])

      ingredients.each do |item_id, required|
        row = GameStorage.db.get_first_row(
          'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
        if row.nil? || row[0] < required
          render json: { error: 'insufficient ingredients' }, status: :conflict
          return
        end
      end

      ingredients.each do |item_id, required|
        current = GameStorage.db.get_first_value(
          'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [campaign_id, character_id, item_id]
        )
        new_quantity = current - required
        if new_quantity > 0
          GameStorage.db.execute(
            'UPDATE play_campaign_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [new_quantity, campaign_id, character_id, item_id]
          )
        else
          GameStorage.db.execute(
            'DELETE FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
            [campaign_id, character_id, item_id]
          )
        end
      end

      existing_output = GameStorage.db.get_first_value(
        'SELECT quantity FROM play_campaign_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign_id, character_id, recipe[3]]
      )

      if existing_output
        GameStorage.db.execute(
          'UPDATE play_campaign_inventory_items SET quantity = quantity + ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
          [recipe[4], campaign_id, character_id, recipe[3]]
        )
      else
        GameStorage.db.execute(
          'INSERT INTO play_campaign_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?)',
          [campaign_id, character_id, recipe[3], recipe[4]]
        )
      end

      render json: {
        character_id: character_id,
        recipe_id: recipe_id,
        output_item: recipe[3],
        output_quantity: recipe[4]
      }, status: :created
    end
  end

  private

  def validate_ingredients(ingredients)
    unless ingredients.is_a?(Hash) && !ingredients.empty?
      bad_request('invalid ingredients')
      return nil
    end

    normalized = {}
    ingredients.each do |key, value|
      unless valid_item_catalog?(key)
        bad_request('invalid ingredients')
        return nil
      end

      unless value.is_a?(Integer) && value.positive?
        bad_request('invalid ingredients')
        return nil
      end

      normalized[key] = value
    end

    normalized
  end

  def valid_item_catalog?(item_id)
    item_id.is_a?(String) && VALID_ITEM_IDS.include?(item_id)
  end

  def recipe_response(recipe_id, name, ingredients, output_item, output_quantity)
    {
      recipe_id: recipe_id,
      name: name,
      ingredients: ingredients,
      output_item: output_item,
      output_quantity: output_quantity
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

  def find_play_recipe(campaign_id, recipe_id)
    row = GameStorage.db.get_first_row(
      'SELECT recipe_id, name, ingredients_json, output_item, output_quantity FROM play_campaign_recipes WHERE campaign_id = ? AND recipe_id = ?',
      [campaign_id, recipe_id]
    )
    if row.nil?
      render json: { error: 'recipe not found' }, status: :not_found
      return nil
    end
    row
  end
end

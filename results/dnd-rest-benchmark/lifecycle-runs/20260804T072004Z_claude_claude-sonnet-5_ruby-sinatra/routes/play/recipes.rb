# DM-defined crafting recipes with deterministic ingredient requirements,
# backed by the public campaign inventory item catalog, and player crafting
# that atomically consumes ingredients and grants the output item.

def play_recipe_payload(recipe)
  {
    recipe_id: recipe['recipe_id'],
    name: recipe['name'],
    ingredients: JSON.parse(recipe['ingredients_json']),
    output_item: recipe['output_item'],
    output_quantity: recipe['output_quantity']
  }
end

# Validates the create payload and returns the normalized
# [recipe_id, name, ingredients, output_item, output_quantity] tuple.
def validate_recipe_fields!(body)
  recipe_id = body['recipe_id']
  name = body['name']
  ingredients = body['ingredients']
  output_item = body['output_item']
  output_quantity = body['output_quantity']

  halt 400, { error: 'invalid recipe_id' }.to_json unless recipe_id.is_a?(String) && !recipe_id.empty?
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid ingredients' }.to_json unless ingredients.is_a?(Hash) && !ingredients.empty?

  normalized_ingredients = {}
  ingredients.each do |item_id, quantity|
    halt 400, { error: 'invalid ingredients' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(item_id)
    halt 400, { error: 'invalid ingredients' }.to_json unless integerish(quantity) && quantity.to_i.positive?

    normalized_ingredients[item_id] = quantity.to_i
  end

  halt 400, { error: 'invalid output_item' }.to_json unless VALID_INVENTORY_ITEM_IDS.include?(output_item)
  halt 400, { error: 'invalid output_quantity' }.to_json unless integerish(output_quantity) && output_quantity.to_i.positive?

  [recipe_id, name, normalized_ingredients, output_item, output_quantity.to_i]
end

def find_play_recipe!(campaign_id, recipe_id)
  recipe = db.execute(
    'SELECT * FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?',
    [campaign_id, recipe_id]
  ).first
  halt 404, { error: 'recipe not found' }.to_json unless recipe
  recipe
end

post '/v1/play/campaigns/:id/recipes' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_owner!(campaign, user)

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  recipe_id, name, ingredients, output_item, output_quantity = validate_recipe_fields!(body)

  existing = db.execute(
    'SELECT 1 FROM play_recipes WHERE campaign_id = ? AND recipe_id = ?',
    [campaign['id'], recipe_id]
  ).first
  halt 409, { error: 'recipe already exists' }.to_json if existing

  sequence = db.execute(
    'SELECT COALESCE(MAX(sequence), 0) + 1 AS n FROM play_recipes WHERE campaign_id = ?',
    [campaign['id']]
  ).first['n']

  db.execute(
    'INSERT INTO play_recipes (campaign_id, sequence, recipe_id, name, ingredients_json, output_item, output_quantity) VALUES (?, ?, ?, ?, ?, ?, ?)',
    [campaign['id'], sequence, recipe_id, name, ingredients.to_json, output_item, output_quantity]
  )

  status 201
  play_recipe_payload(find_play_recipe!(campaign['id'], recipe_id)).to_json
end

get '/v1/play/campaigns/:id/recipes' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  require_play_participant!(campaign, user, 'not a campaign member')

  recipes = db.execute(
    'SELECT * FROM play_recipes WHERE campaign_id = ? ORDER BY sequence ASC',
    [campaign['id']]
  ).map { |recipe| play_recipe_payload(recipe) }

  { recipes: recipes }.to_json
end

post '/v1/play/campaigns/:id/recipes/:recipe_id/craft' do
  user = authenticate_play_request!

  campaign = find_play_campaign!(params[:id])
  recipe = find_play_recipe!(campaign['id'], params[:recipe_id])

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  character_id = body['character_id']
  halt 400, { error: 'invalid character_id' }.to_json unless character_id.is_a?(String) && !character_id.empty?

  member = find_play_member_by_character!(campaign['id'], character_id)
  owner = play_character_owner(campaign['id'], character_id, member)
  halt 403, { error: 'not the character owner' }.to_json unless owner == user['username']

  ingredients = JSON.parse(recipe['ingredients_json'])

  held = {}
  ingredients.each do |item_id, required_quantity|
    existing_item = db.execute(
      'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
      [campaign['id'], character_id, item_id]
    ).first
    held[item_id] = existing_item ? existing_item['quantity'] : 0
    halt 409, { error: 'insufficient ingredients' }.to_json if held[item_id] < required_quantity
  end

  ingredients.each do |item_id, required_quantity|
    held_after = held[item_id] - required_quantity

    if held_after.zero?
      db.execute(
        'DELETE FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [campaign['id'], character_id, item_id]
      )
    else
      db.execute(
        'UPDATE play_character_inventory_items SET quantity = ? WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
        [held_after, campaign['id'], character_id, item_id]
      )
    end
  end

  existing_output = db.execute(
    'SELECT quantity FROM play_character_inventory_items WHERE campaign_id = ? AND character_id = ? AND item_id = ?',
    [campaign['id'], character_id, recipe['output_item']]
  ).first
  output_total = (existing_output ? existing_output['quantity'] : 0) + recipe['output_quantity']

  db.execute(
    'INSERT INTO play_character_inventory_items (campaign_id, character_id, item_id, quantity) VALUES (?, ?, ?, ?) ' \
    'ON CONFLICT (campaign_id, character_id, item_id) DO UPDATE SET quantity = excluded.quantity',
    [campaign['id'], character_id, recipe['output_item'], output_total]
  )

  status 201
  {
    character_id: character_id,
    recipe_id: recipe['recipe_id'],
    output_item: recipe['output_item'],
    output_quantity: recipe['output_quantity']
  }.to_json
end

# frozen_string_literal: true

# Route definitions for campaign crafting recipes.

# Returns the public recipe shape.
def recipe_response(recipe)
  {
    recipe_id: recipe[:recipe_id],
    name: recipe[:name],
    ingredients: recipe[:ingredients],
    output_item: recipe[:output_item],
    output_quantity: recipe[:output_quantity]
  }
end

# --- Create recipe ---
post '/v1/play/campaigns/:id/recipes' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_recipe_body!(body)

  json_error(409, 'recipe already exists') if Storage.recipe_exists?(campaign_id, body['recipe_id'])

  Storage.create_recipe(
    campaign_id,
    body['recipe_id'],
    body['name'],
    body['ingredients'],
    body['output_item'],
    body['output_quantity']
  )

  status 201
  JSON.dump(recipe_response(Storage.load_recipe(campaign_id, body['recipe_id'])))
end

# --- List recipes ---
get '/v1/play/campaigns/:id/recipes' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  recipes = Storage.load_recipes(campaign_id).map { |r| recipe_response(r) }
  JSON.dump(recipes: recipes)
end

# --- Craft recipe ---
post '/v1/play/campaigns/:id/recipes/:recipe_id/craft' do
  content_type :json
  campaign_id = params[:id]
  recipe_id = params[:recipe_id]
  validate_campaign_id!(campaign_id)

  username = require_player_actor!

  load_play_campaign!(campaign_id)
  json_error(403, 'forbidden') unless Storage.play_campaign_member_exists?(campaign_id, username)

  body = parse_json_body
  validate_craft_body!(body)

  character_id = body['character_id']
  character = Storage.load_play_campaign_member_by_character_id(campaign_id, character_id)
  json_error(404, 'character not found') unless character

  json_error(403, 'forbidden') unless character[:owner] == username

  recipe = Storage.load_recipe(campaign_id, recipe_id)
  json_error(404, 'recipe not found') unless recipe

  result = Storage.craft_recipe(campaign_id, recipe_id, character_id)
  json_error(409, 'insufficient ingredients') unless result

  status 201
  JSON.dump(
    character_id: character_id,
    recipe_id: recipe_id,
    output_item: recipe[:output_item],
    output_quantity: recipe[:output_quantity]
  )
end

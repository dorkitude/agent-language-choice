# frozen_string_literal: true

# Route definitions for compendium endpoints.

# --- Compendium ---

post '/v1/compendium/monsters' do
  content_type :json
  body = parse_json_body

  validate_monster_body!(body)

  json_error(409, 'monster already exists') if Storage.monster_exists?(body['slug'])

  Storage.create_monster(
    body['slug'],
    body['name'],
    body['cr'],
    body['armor_class'],
    body['hit_points'],
    body['tags']
  )

  status 201
  JSON.dump(
    slug: body['slug'],
    name: body['name'],
    cr: body['cr'],
    armor_class: body['armor_class'],
    hit_points: body['hit_points']
  )
end

get '/v1/compendium/monsters/:slug' do
  content_type :json
  monster = Storage.load_monster(params[:slug])
  json_error(404, 'monster not found') unless monster

  JSON.dump(monster)
end

post '/v1/compendium/items' do
  content_type :json
  body = parse_json_body

  validate_item_body!(body)

  json_error(409, 'item already exists') if Storage.item_exists?(body['slug'])

  Storage.create_item(
    body['slug'],
    body['name'],
    body['type'],
    body['rarity'],
    body['cost_gp']
  )

  status 201
  JSON.dump(
    slug: body['slug'],
    name: body['name'],
    type: body['type'],
    rarity: body['rarity'],
    cost_gp: body['cost_gp']
  )
end

get '/v1/compendium/items/:slug' do
  content_type :json
  item = Storage.load_item(params[:slug])
  json_error(404, 'item not found') unless item

  JSON.dump(item)
end


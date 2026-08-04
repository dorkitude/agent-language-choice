# Reference data catalogs: monsters and items. Create-then-read only, keyed
# by a caller-supplied slug; no update/delete endpoints exist.

post '/v1/compendium/monsters' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  slug = body['slug']
  name = body['name']
  cr = body['cr']
  armor_class = body['armor_class']
  hit_points = body['hit_points']
  tags = body['tags']
  tags = [] if tags.nil?

  halt 400, { error: 'invalid slug' }.to_json unless valid_slug?(slug)
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid cr' }.to_json unless cr.is_a?(String) && !cr.empty?
  halt 400, { error: 'invalid armor_class' }.to_json unless integerish(armor_class)
  halt 400, { error: 'invalid hit_points' }.to_json unless integerish(hit_points)
  halt 400, { error: 'invalid tags' }.to_json unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
  halt 409, { error: 'slug already exists' }.to_json if db.execute('SELECT 1 FROM monsters WHERE slug = ?', [slug]).first

  armor_class = armor_class.to_i
  hit_points = hit_points.to_i

  db.execute(
    'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
    [slug, name, cr, armor_class, hit_points, tags.to_json]
  )

  status 201
  {
    slug: slug,
    name: name,
    cr: cr,
    armor_class: armor_class,
    hit_points: hit_points
  }.to_json
end

get '/v1/compendium/monsters/:slug' do
  row = db.execute('SELECT * FROM monsters WHERE slug = ?', [params[:slug]]).first
  halt 404, { error: 'unknown monster' }.to_json unless row

  {
    slug: row['slug'],
    name: row['name'],
    cr: row['cr'],
    armor_class: row['armor_class'],
    hit_points: row['hit_points'],
    tags: JSON.parse(row['tags_json'])
  }.to_json
end

post '/v1/compendium/items' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  slug = body['slug']
  name = body['name']
  type = body['type']
  rarity = body['rarity']
  cost_gp = body['cost_gp']

  halt 400, { error: 'invalid slug' }.to_json unless valid_slug?(slug)
  halt 400, { error: 'invalid name' }.to_json unless name.is_a?(String) && !name.empty?
  halt 400, { error: 'invalid type' }.to_json unless type.is_a?(String) && !type.empty?
  halt 400, { error: 'invalid rarity' }.to_json unless rarity.is_a?(String) && !rarity.empty?
  halt 400, { error: 'invalid cost_gp' }.to_json unless integerish(cost_gp)
  halt 409, { error: 'slug already exists' }.to_json if db.execute('SELECT 1 FROM items WHERE slug = ?', [slug]).first

  cost_gp = cost_gp.to_i

  db.execute(
    'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
    [slug, name, type, rarity, cost_gp]
  )

  status 201
  {
    slug: slug,
    name: name,
    type: type,
    rarity: rarity,
    cost_gp: cost_gp
  }.to_json
end

get '/v1/compendium/items/:slug' do
  row = db.execute('SELECT * FROM items WHERE slug = ?', [params[:slug]]).first
  halt 404, { error: 'unknown item' }.to_json unless row

  {
    slug: row['slug'],
    name: row['name'],
    type: row['type'],
    rarity: row['rarity'],
    cost_gp: row['cost_gp']
  }.to_json
end

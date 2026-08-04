class CompendiumController < ApplicationController
  def create_monster
    slug = @body['slug']
    name = @body['name']
    cr = @body['cr']
    armor_class = @body['armor_class']
    hit_points = @body['hit_points']
    tags = @body['tags']

    unless valid_id?(slug)
      bad_request('invalid slug')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless valid_non_empty_string?(cr)
      bad_request('invalid cr')
      return
    end

    unless armor_class.is_a?(Integer)
      bad_request('invalid armor_class')
      return
    end

    unless hit_points.is_a?(Integer)
      bad_request('invalid hit_points')
      return
    end

    unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
      bad_request('invalid tags')
      return
    end

    GameStorage.with_lock do
      begin
        GameStorage.db.execute(
          'INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
          [slug, name, cr, armor_class, hit_points, JSON.generate(tags)]
        )
        render json: {
          slug: slug,
          name: name,
          cr: cr,
          armor_class: armor_class,
          hit_points: hit_points
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'slug taken' }, status: :conflict
      end
    end
  end

  def read_monster
    slug = params[:slug]
    row = GameStorage.db.get_first_row(
      'SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = ?',
      slug
    )

    if row.nil?
      render json: { error: 'monster not found' }, status: :not_found
      return
    end

    render json: {
      slug: row[0],
      name: row[1],
      cr: row[2],
      armor_class: row[3],
      hit_points: row[4],
      tags: JSON.parse(row[5])
    }
  end

  def create_item
    slug = @body['slug']
    name = @body['name']
    type = @body['type']
    rarity = @body['rarity']
    cost_gp = @body['cost_gp']

    unless valid_id?(slug)
      bad_request('invalid slug')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless valid_non_empty_string?(type)
      bad_request('invalid type')
      return
    end

    unless valid_non_empty_string?(rarity)
      bad_request('invalid rarity')
      return
    end

    unless cost_gp.is_a?(Integer)
      bad_request('invalid cost_gp')
      return
    end

    GameStorage.with_lock do
      begin
        GameStorage.db.execute(
          'INSERT INTO items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
          [slug, name, type, rarity, cost_gp]
        )
        render json: {
          slug: slug,
          name: name,
          type: type,
          rarity: rarity,
          cost_gp: cost_gp
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'slug taken' }, status: :conflict
      end
    end
  end

  def read_item
    slug = params[:slug]
    row = GameStorage.db.get_first_row(
      'SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = ?',
      slug
    )

    if row.nil?
      render json: { error: 'item not found' }, status: :not_found
      return
    end

    render json: {
      slug: row[0],
      name: row[1],
      type: row[2],
      rarity: row[3],
      cost_gp: row[4]
    }
  end
end

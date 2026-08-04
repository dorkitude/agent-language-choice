# Read/write access to the shared monster and item compendium tables.
class CompendiumController < ApplicationController
  def create_monster
    slug = params[:slug]
    name = params[:name]
    cr = params[:cr]
    armor_class = params[:armor_class]
    hit_points = params[:hit_points]
    tags = params[:tags] || []

    unless slug.is_a?(String) && slug.match?(/\A[a-z0-9-]{1,64}\z/)
      render json: { error: 'invalid slug' }, status: :bad_request
      return
    end

    unless name.is_a?(String) && !name.empty?
      render json: { error: 'invalid name' }, status: :bad_request
      return
    end

    unless cr.is_a?(String) && !cr.empty?
      render json: { error: 'invalid cr' }, status: :bad_request
      return
    end

    unless valid_integer?(armor_class)
      render json: { error: 'invalid armor_class' }, status: :bad_request
      return
    end

    unless valid_integer?(hit_points)
      render json: { error: 'invalid hit_points' }, status: :bad_request
      return
    end

    unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
      render json: { error: 'invalid tags' }, status: :bad_request
      return
    end

    if MONSTERS.key?(slug)
      render json: { error: 'duplicate slug' }, status: :conflict
      return
    end

    monster = {
      slug: slug,
      name: name,
      cr: cr,
      armor_class: armor_class.to_i,
      hit_points: hit_points.to_i,
      tags: tags
    }
    MONSTERS[slug] = monster

    render json: {
      slug: monster[:slug],
      name: monster[:name],
      cr: monster[:cr],
      armor_class: monster[:armor_class],
      hit_points: monster[:hit_points]
    }, status: :created
  end

  def show_monster
    monster = MONSTERS[params[:slug]]
    if monster.nil?
      render json: { error: 'monster not found' }, status: :not_found
      return
    end

    render json: monster
  end

  def create_item
    slug = params[:slug]
    name = params[:name]
    type = params[:type]
    rarity = params[:rarity]
    cost_gp = params[:cost_gp]

    unless slug.is_a?(String) && slug.match?(/\A[a-z0-9-]{1,64}\z/)
      render json: { error: 'invalid slug' }, status: :bad_request
      return
    end

    unless name.is_a?(String) && !name.empty?
      render json: { error: 'invalid name' }, status: :bad_request
      return
    end

    unless type.is_a?(String) && !type.empty?
      render json: { error: 'invalid type' }, status: :bad_request
      return
    end

    unless rarity.is_a?(String) && !rarity.empty?
      render json: { error: 'invalid rarity' }, status: :bad_request
      return
    end

    unless valid_integer?(cost_gp)
      render json: { error: 'invalid cost_gp' }, status: :bad_request
      return
    end

    if ITEMS.key?(slug)
      render json: { error: 'duplicate slug' }, status: :conflict
      return
    end

    item = {
      slug: slug,
      name: name,
      type: type,
      rarity: rarity,
      cost_gp: cost_gp.to_i
    }
    ITEMS[slug] = item

    render json: item, status: :created
  end

  def show_item
    item = ITEMS[params[:slug]]
    if item.nil?
      render json: { error: 'item not found' }, status: :not_found
      return
    end

    render json: item
  end
end

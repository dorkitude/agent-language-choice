# frozen_string_literal: true

require 'json'
require_relative 'persistence'

# Compendium: monsters and items.
module Compendium
  def self.create_monster(payload)
    data = validate_monster(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      existing = d.get_first_value('SELECT 1 FROM compendium_monsters WHERE slug = ?', data[:slug])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO compendium_monsters (slug, name, cr, armor_class, hit_points, tags_json) VALUES (?, ?, ?, ?, ?, ?)',
        [data[:slug], data[:name], data[:cr], data[:armor_class], data[:hit_points], JSON.generate(data[:tags])]
      )

      [:ok, {
        'slug' => data[:slug],
        'name' => data[:name],
        'cr' => data[:cr],
        'armor_class' => data[:armor_class],
        'hit_points' => data[:hit_points]
      }]
    end
  end

  def self.read_monster(slug)
    return [:invalid] unless slug.is_a?(String) && !slug.empty?

    Persistence.db do |d|
      row = d.get_first_row(
        'SELECT name, cr, armor_class, hit_points, tags_json FROM compendium_monsters WHERE slug = ?',
        slug
      )
      next [:not_found] unless row

      name, cr, armor_class, hit_points, tags_json = row
      tags = JSON.parse(tags_json) rescue []

      [:ok, {
        'slug' => slug,
        'name' => name,
        'cr' => cr,
        'armor_class' => armor_class,
        'hit_points' => hit_points,
        'tags' => tags
      }]
    end
  end

  def self.create_item(payload)
    data = validate_item(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      existing = d.get_first_value('SELECT 1 FROM compendium_items WHERE slug = ?', data[:slug])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO compendium_items (slug, name, type, rarity, cost_gp) VALUES (?, ?, ?, ?, ?)',
        [data[:slug], data[:name], data[:type], data[:rarity], data[:cost_gp]]
      )

      [:ok, {
        'slug' => data[:slug],
        'name' => data[:name],
        'type' => data[:type],
        'rarity' => data[:rarity],
        'cost_gp' => data[:cost_gp]
      }]
    end
  end

  def self.read_item(slug)
    return [:invalid] unless slug.is_a?(String) && !slug.empty?

    Persistence.db do |d|
      row = d.get_first_row(
        'SELECT name, type, rarity, cost_gp FROM compendium_items WHERE slug = ?',
        slug
      )
      next [:not_found] unless row

      name, type, rarity, cost_gp = row

      [:ok, {
        'slug' => slug,
        'name' => name,
        'type' => type,
        'rarity' => rarity,
        'cost_gp' => cost_gp
      }]
    end
  end

  def self.validate_monster(payload)
    return nil unless payload.is_a?(Hash)

    slug = payload['slug']
    name = payload['name']
    cr = payload['cr']
    armor_class = payload['armor_class']
    hit_points = payload['hit_points']
    tags = payload['tags']

    return nil unless slug.is_a?(String) && !slug.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      cr.is_a?(String) && !cr.empty? &&
                      armor_class.is_a?(Integer) &&
                      hit_points.is_a?(Integer) &&
                      tags.is_a?(Array) &&
                      tags.all? { |t| t.is_a?(String) }

    {
      slug: slug,
      name: name,
      cr: cr,
      armor_class: armor_class,
      hit_points: hit_points,
      tags: tags
    }
  end
  private_class_method :validate_monster

  def self.validate_item(payload)
    return nil unless payload.is_a?(Hash)

    slug = payload['slug']
    name = payload['name']
    type = payload['type']
    rarity = payload['rarity']
    cost_gp = payload['cost_gp']

    return nil unless slug.is_a?(String) && !slug.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      type.is_a?(String) && !type.empty? &&
                      rarity.is_a?(String) && !rarity.empty? &&
                      cost_gp.is_a?(Integer)

    {
      slug: slug,
      name: name,
      type: type,
      rarity: rarity,
      cost_gp: cost_gp
    }
  end
  private_class_method :validate_item
end

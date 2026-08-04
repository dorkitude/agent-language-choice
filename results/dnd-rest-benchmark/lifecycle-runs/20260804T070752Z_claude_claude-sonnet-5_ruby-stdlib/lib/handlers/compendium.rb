# frozen_string_literal: true

require 'json'
require_relative '../errors'
require_relative '../database'

module Handlers
  # Read/write access to the shared monster and magic-item compendium.
  # Entries are keyed by a URL-safe slug chosen by the caller.
  module Compendium
    SLUG_PATTERN = /\A[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\z/

    module_function

    def create_monster(body)
      slug = body['slug']
      name = body['name']
      cr = body['cr']
      armor_class = body['armor_class']
      hit_points = body['hit_points']
      tags = body['tags']

      raise HttpError.new(400, 'slug must be a valid slug string') unless slug.is_a?(String) && SLUG_PATTERN.match?(slug)
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'cr must be a string') unless cr.is_a?(String) && !cr.empty?
      raise HttpError.new(400, 'armor_class must be an integer') unless armor_class.is_a?(Integer)
      raise HttpError.new(400, 'hit_points must be an integer') unless hit_points.is_a?(Integer)
      raise HttpError.new(400, 'tags must be an array of strings') unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
      raise HttpError.new(409, 'slug already exists') unless Database.query("SELECT slug FROM monsters WHERE slug = #{Database.escape(slug)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO monsters (slug, name, cr, armor_class, hit_points, tags_json)
        VALUES (
          #{Database.escape(slug)},
          #{Database.escape(name)},
          #{Database.escape(cr)},
          #{Database.int(armor_class)},
          #{Database.int(hit_points)},
          #{Database.escape(JSON.generate(tags))}
        );
      SQL

      [201, {
        slug: slug,
        name: name,
        cr: cr,
        armor_class: armor_class,
        hit_points: hit_points
      }]
    end

    def get_monster(slug, _body)
      row = Database.query("SELECT slug, name, cr, armor_class, hit_points, tags_json FROM monsters WHERE slug = #{Database.escape(slug)};").first
      raise HttpError.new(404, 'unknown monster slug') unless row

      [200, {
        slug: row['slug'],
        name: row['name'],
        cr: row['cr'],
        armor_class: row['armor_class'].to_i,
        hit_points: row['hit_points'].to_i,
        tags: JSON.parse(row['tags_json'])
      }]
    end

    def create_item(body)
      slug = body['slug']
      name = body['name']
      type = body['type']
      rarity = body['rarity']
      cost_gp = body['cost_gp']

      raise HttpError.new(400, 'slug must be a valid slug string') unless slug.is_a?(String) && SLUG_PATTERN.match?(slug)
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'type must be a string') unless type.is_a?(String) && !type.empty?
      raise HttpError.new(400, 'rarity must be a string') unless rarity.is_a?(String) && !rarity.empty?
      raise HttpError.new(400, 'cost_gp must be an integer') unless cost_gp.is_a?(Integer)
      raise HttpError.new(409, 'slug already exists') unless Database.query("SELECT slug FROM items WHERE slug = #{Database.escape(slug)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO items (slug, name, type, rarity, cost_gp)
        VALUES (
          #{Database.escape(slug)},
          #{Database.escape(name)},
          #{Database.escape(type)},
          #{Database.escape(rarity)},
          #{Database.int(cost_gp)}
        );
      SQL

      [201, {
        slug: slug,
        name: name,
        type: type,
        rarity: rarity,
        cost_gp: cost_gp
      }]
    end

    def get_item(slug, _body)
      row = Database.query("SELECT slug, name, type, rarity, cost_gp FROM items WHERE slug = #{Database.escape(slug)};").first
      raise HttpError.new(404, 'unknown item slug') unless row

      [200, {
        slug: row['slug'],
        name: row['name'],
        type: row['type'],
        rarity: row['rarity'],
        cost_gp: row['cost_gp'].to_i
      }]
    end
  end
end

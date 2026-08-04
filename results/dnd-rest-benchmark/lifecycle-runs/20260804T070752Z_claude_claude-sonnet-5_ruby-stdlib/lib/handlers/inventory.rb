# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'
require_relative 'campaigns'

module Handlers
  # Campaign inventory and per-character equipment assignment.
  # `healing-potion` availability in the summary is the party's on-hand
  # quantity minus whatever has been assigned out to characters.
  module Inventory
    HEALING_POTION_SLUG = 'healing-potion'

    module_function

    def find_character(campaign_id, character_id)
      row = Database.query(<<~SQL).first
        SELECT id FROM campaign_characters
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(character_id)};
      SQL
      raise HttpError.new(404, 'unknown character id') unless row

      row
    end

    def add_inventory_item(campaign_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)

      item_slug = body['item_slug']
      quantity = body['quantity']
      owner = body['owner']

      raise HttpError.new(400, 'item_slug must be a string') unless item_slug.is_a?(String) && !item_slug.empty?
      raise HttpError.new(400, 'quantity must be a positive integer') unless quantity.is_a?(Integer) && quantity.positive?
      raise HttpError.new(400, 'owner must be a string') unless owner.is_a?(String) && !owner.empty?

      Database.exec(<<~SQL)
        INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(item_slug)},
          #{Database.int(quantity)},
          #{Database.escape(owner)}
        );
      SQL

      [201, { item_slug: item_slug, quantity: quantity, owner: owner }]
    end

    def assign_equipment(campaign_id, character_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)
      find_character(campaign_id, character_id)

      item_slug = body['item_slug']
      quantity = body['quantity']

      raise HttpError.new(400, 'item_slug must be a string') unless item_slug.is_a?(String) && !item_slug.empty?
      raise HttpError.new(400, 'quantity must be a positive integer') unless quantity.is_a?(Integer) && quantity.positive?

      Database.exec(<<~SQL)
        INSERT INTO character_equipment (campaign_id, character_id, item_slug, quantity)
        VALUES (
          #{Database.escape(campaign_id)},
          #{Database.escape(character_id)},
          #{Database.escape(item_slug)},
          #{Database.int(quantity)}
        );
      SQL

      [200, { character_id: character_id, item_slug: item_slug, quantity: quantity }]
    end

    def summary(campaign_id, _body)
      Handlers::Campaigns.find_campaign(campaign_id)

      party_items_row = Database.query(<<~SQL).first
        SELECT COUNT(*) AS count FROM campaign_inventory
        WHERE campaign_id = #{Database.escape(campaign_id)} AND owner = 'party';
      SQL
      party_items = party_items_row ? party_items_row['count'].to_i : 0

      assigned_items_row = Database.query(<<~SQL).first
        SELECT COUNT(*) AS count FROM character_equipment
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      assigned_items = assigned_items_row ? assigned_items_row['count'].to_i : 0

      party_potions_row = Database.query(<<~SQL).first
        SELECT COALESCE(SUM(quantity), 0) AS total FROM campaign_inventory
        WHERE campaign_id = #{Database.escape(campaign_id)}
          AND owner = 'party'
          AND item_slug = #{Database.escape(HEALING_POTION_SLUG)};
      SQL
      party_potions = party_potions_row ? party_potions_row['total'].to_i : 0

      assigned_potions_row = Database.query(<<~SQL).first
        SELECT COALESCE(SUM(quantity), 0) AS total FROM character_equipment
        WHERE campaign_id = #{Database.escape(campaign_id)}
          AND item_slug = #{Database.escape(HEALING_POTION_SLUG)};
      SQL
      assigned_potions = assigned_potions_row ? assigned_potions_row['total'].to_i : 0

      [200, {
        campaign_id: campaign_id,
        party_items: party_items,
        assigned_items: assigned_items,
        healing_potions_available: party_potions - assigned_potions
      }]
    end
  end
end

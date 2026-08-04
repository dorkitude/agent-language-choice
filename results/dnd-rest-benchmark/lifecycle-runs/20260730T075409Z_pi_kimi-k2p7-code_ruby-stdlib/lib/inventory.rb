# frozen_string_literal: true

require_relative 'persistence'

# Inventory and equipment: campaign inventory and character assignments.
module Inventory
  def self.add_item(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    item_slug = payload['item_slug']
    quantity = payload['quantity']
    owner = payload['owner']

    return [:invalid] unless item_slug.is_a?(String) && !item_slug.empty? &&
                             owner.is_a?(String) && !owner.empty? &&
                             quantity.is_a?(Integer) && quantity > 0

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      d.execute(
        'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)
         ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity',
        [campaign_id, item_slug, owner, quantity]
      )

      [:ok, {
        'item_slug' => item_slug,
        'quantity' => quantity,
        'owner' => owner
      }]
    end
  end

  def self.assign_equipment(campaign_id, character_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                             character_id.is_a?(String) && !character_id.empty?

    item_slug = payload['item_slug']
    quantity = payload['quantity']

    return [:invalid] unless item_slug.is_a?(String) && !item_slug.empty? &&
                             quantity.is_a?(Integer) && quantity > 0

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      character_exists = d.get_first_value(
        'SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?',
        [character_id, campaign_id]
      )
      next [:not_found] unless character_exists

      party_qty = d.get_first_value(
        'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
        [campaign_id, item_slug, 'party']
      )
      next [:invalid] unless party_qty.is_a?(Integer) && party_qty >= quantity

      new_party_qty = party_qty - quantity
      if new_party_qty == 0
        d.execute(
          'DELETE FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [campaign_id, item_slug, 'party']
        )
      else
        d.execute(
          'UPDATE campaign_inventory SET quantity = ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [new_party_qty, campaign_id, item_slug, 'party']
        )
      end

      existing_assigned = d.get_first_value(
        'SELECT quantity FROM campaign_inventory WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
        [campaign_id, item_slug, character_id]
      )
      if existing_assigned
        d.execute(
          'UPDATE campaign_inventory SET quantity = quantity + ? WHERE campaign_id = ? AND item_slug = ? AND owner = ?',
          [quantity, campaign_id, item_slug, character_id]
        )
      else
        d.execute(
          'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)',
          [campaign_id, item_slug, character_id, quantity]
        )
      end

      [:ok, {
        'character_id' => character_id,
        'item_slug' => item_slug,
        'quantity' => quantity
      }]
    end
  end

  # Summary exposes the count of party/assigned items and, for each party item,
  # a dynamic "<plural>_available" key derived from the slug. This preserves
  # the shape expected by the cumulative inventory suite.
  def self.summary(campaign_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      party_rows = d.execute(
        'SELECT item_slug, quantity FROM campaign_inventory WHERE campaign_id = ? AND owner = ?',
        [campaign_id, 'party']
      )

      assigned_count = d.get_first_value(
        'SELECT COUNT(*) FROM campaign_inventory WHERE campaign_id = ? AND owner != ?',
        [campaign_id, 'party']
      )

      result = {
        'campaign_id' => campaign_id,
        'party_items' => party_rows.length,
        'assigned_items' => assigned_count
      }

      party_rows.each do |slug, qty|
        base = slug.to_s
        plural = base.end_with?('s') ? base : base + 's'
        result[plural.gsub('-', '_') + '_available'] = qty
      end

      [:ok, result]
    end
  end
end

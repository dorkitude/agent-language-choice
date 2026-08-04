# frozen_string_literal: true

require_relative 'persistence'

# Downtime crafting: long-term item crafting projects.
module Crafting
  VALID_STATUSES = %w[active complete].freeze

  def self.create_project(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_project(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      character_exists = d.get_first_value(
        'SELECT 1 FROM campaign_characters WHERE id = ? AND campaign_id = ?',
        [data[:character_id], campaign_id]
      )
      next [:not_found] unless character_exists

      existing = d.get_first_value('SELECT 1 FROM campaign_crafting_projects WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaign_crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
        [data[:id], campaign_id, data[:character_id], data[:item_slug], data[:days_required], 0, data[:cost_gp], 'active']
      )

      [:ok, {
        'id' => data[:id],
        'character_id' => data[:character_id],
        'item_slug' => data[:item_slug],
        'days_required' => data[:days_required],
        'days_completed' => 0,
        'status' => 'active'
      }]
    end
  end

  def self.advance_project(campaign_id, project_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                             project_id.is_a?(String) && !project_id.empty?

    days = payload['days']
    return [:invalid] unless days.is_a?(Integer) && days > 0

    Persistence.db do |d|
      row = d.get_first_row(
        'SELECT id, days_required, days_completed, status, item_slug FROM campaign_crafting_projects WHERE id = ? AND campaign_id = ?',
        [project_id, campaign_id]
      )
      next [:not_found] unless row

      project_id, days_required, days_completed, status, item_slug = row

      if status == 'complete'
        next [:ok, {
          'id' => project_id,
          'days_completed' => days_completed,
          'status' => 'complete'
        }]
      end

      new_days_completed = [days_completed + days, days_required].min
      new_status = new_days_completed >= days_required ? 'complete' : 'active'

      if new_status == 'complete'
        d.execute(
          'INSERT INTO campaign_inventory (campaign_id, item_slug, owner, quantity) VALUES (?, ?, ?, ?)
           ON CONFLICT(campaign_id, item_slug, owner) DO UPDATE SET quantity = quantity + excluded.quantity',
          [campaign_id, item_slug, 'party', 1]
        )
      end

      d.execute(
        'UPDATE campaign_crafting_projects SET days_completed = ?, status = ? WHERE id = ?',
        [new_days_completed, new_status, project_id]
      )

      [:ok, {
        'id' => project_id,
        'days_completed' => new_days_completed,
        'status' => new_status
      }]
    end
  end

  def self.validate_project(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    character_id = payload['character_id']
    item_slug = payload['item_slug']
    days_required = payload['days_required']
    cost_gp = payload['cost_gp']

    return nil unless id.is_a?(String) && !id.empty? &&
                      character_id.is_a?(String) && !character_id.empty? &&
                      item_slug.is_a?(String) && !item_slug.empty? &&
                      days_required.is_a?(Integer) && days_required > 0 &&
                      cost_gp.is_a?(Integer)

    {
      id: id,
      character_id: character_id,
      item_slug: item_slug,
      days_required: days_required,
      cost_gp: cost_gp
    }
  end
  private_class_method :validate_project
end

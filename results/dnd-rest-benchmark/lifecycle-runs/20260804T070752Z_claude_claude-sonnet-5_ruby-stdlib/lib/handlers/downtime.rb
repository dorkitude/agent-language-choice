# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'
require_relative 'campaigns'
require_relative 'inventory'

module Handlers
  # Downtime crafting projects: a character spends days_required in-game
  # days (advanced in arbitrary increments) crafting an item. Once
  # days_completed reaches days_required, the project is marked complete
  # and the crafted item is added to the campaign's party inventory.
  module Downtime
    module_function

    def find_project(campaign_id, project_id)
      row = Database.query(<<~SQL).first
        SELECT id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status
        FROM campaign_crafting_projects
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(project_id)};
      SQL
      raise HttpError.new(404, 'unknown crafting project id') unless row

      row
    end

    def create_crafting_project(campaign_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)

      id = body['id']
      character_id = body['character_id']
      item_slug = body['item_slug']
      days_required = body['days_required']
      cost_gp = body['cost_gp']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'character_id must be a string') unless character_id.is_a?(String) && !character_id.empty?
      raise HttpError.new(400, 'item_slug must be a string') unless item_slug.is_a?(String) && !item_slug.empty?
      raise HttpError.new(400, 'days_required must be a positive integer') unless days_required.is_a?(Integer) && days_required.positive?
      raise HttpError.new(400, 'cost_gp must be a non-negative integer') unless cost_gp.is_a?(Integer) && !cost_gp.negative?

      Handlers::Inventory.find_character(campaign_id, character_id)

      raise HttpError.new(409, 'id already exists') unless Database.query(<<~SQL).empty?
        SELECT id FROM campaign_crafting_projects WHERE id = #{Database.escape(id)};
      SQL

      Database.exec(<<~SQL)
        INSERT INTO campaign_crafting_projects
          (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(campaign_id)},
          #{Database.escape(character_id)},
          #{Database.escape(item_slug)},
          #{Database.int(days_required)},
          0,
          #{Database.int(cost_gp)},
          'active'
        );
      SQL

      [201, {
        id: id,
        character_id: character_id,
        item_slug: item_slug,
        days_required: days_required,
        days_completed: 0,
        status: 'active'
      }]
    end

    def advance(campaign_id, project_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)
      project = find_project(campaign_id, project_id)

      days = body['days']
      raise HttpError.new(400, 'days must be a positive integer') unless days.is_a?(Integer) && days.positive?
      raise HttpError.new(409, 'crafting project is already complete') if project['status'] == 'complete'

      days_required = project['days_required'].to_i
      days_completed = [project['days_completed'].to_i + days, days_required].min
      status = days_completed >= days_required ? 'complete' : 'active'

      Database.exec(<<~SQL)
        UPDATE campaign_crafting_projects
        SET days_completed = #{Database.int(days_completed)}, status = #{Database.escape(status)}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(project_id)};
      SQL

      if status == 'complete'
        existing = Database.query(<<~SQL).first
          SELECT rowid FROM campaign_inventory
          WHERE campaign_id = #{Database.escape(campaign_id)}
            AND item_slug = #{Database.escape(project['item_slug'])}
            AND owner = 'party';
        SQL

        if existing
          Database.exec(<<~SQL)
            UPDATE campaign_inventory
            SET quantity = quantity + 1
            WHERE rowid = #{Database.int(existing['rowid'].to_i)};
          SQL
        else
          Database.exec(<<~SQL)
            INSERT INTO campaign_inventory (campaign_id, item_slug, quantity, owner)
            VALUES (
              #{Database.escape(campaign_id)},
              #{Database.escape(project['item_slug'])},
              1,
              'party'
            );
          SQL
        end
      end

      [200, {
        id: project['id'],
        days_completed: days_completed,
        status: status
      }]
    end
  end
end

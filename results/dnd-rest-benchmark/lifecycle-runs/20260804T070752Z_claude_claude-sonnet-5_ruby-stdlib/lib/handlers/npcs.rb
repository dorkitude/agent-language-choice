# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'
require_relative 'campaigns'

module Handlers
  # Campaign NPCs, factions, and a relationship summary derived from them.
  module Npcs
    STANCES = %w[friendly neutral hostile].freeze

    module_function

    def create_faction(campaign_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)

      id = body['id']
      name = body['name']
      stance = body['stance']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'stance must be one of friendly, neutral, hostile') unless STANCES.include?(stance)
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM campaign_factions WHERE id = #{Database.escape(id)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO campaign_factions (id, campaign_id, name, stance)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(campaign_id)},
          #{Database.escape(name)},
          #{Database.escape(stance)}
        );
      SQL

      [201, { id: id, name: name, stance: stance }]
    end

    def create_npc(campaign_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)

      id = body['id']
      name = body['name']
      faction_id = body['faction_id']
      disposition = body['disposition']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'disposition must be an integer') unless disposition.is_a?(Integer)
      unless faction_id.nil? || (faction_id.is_a?(String) && !faction_id.empty?)
        raise HttpError.new(400, 'faction_id must be a string')
      end
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM campaign_npcs WHERE id = #{Database.escape(id)};").empty?

      unless faction_id.nil?
        raise HttpError.new(400, 'unknown faction id') if Database.query(
          "SELECT id FROM campaign_factions WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(faction_id)};"
        ).empty?
      end

      Database.exec(<<~SQL)
        INSERT INTO campaign_npcs (id, campaign_id, name, faction_id, disposition)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(campaign_id)},
          #{Database.escape(name)},
          #{faction_id.nil? ? 'NULL' : Database.escape(faction_id)},
          #{Database.int(disposition)}
        );
      SQL

      [201, { id: id, name: name, faction_id: faction_id, disposition: disposition }]
    end

    def relationships(campaign_id, _body)
      Handlers::Campaigns.find_campaign(campaign_id)

      faction_count_row = Database.query("SELECT COUNT(*) AS count FROM campaign_factions WHERE campaign_id = #{Database.escape(campaign_id)};").first
      npc_count_row = Database.query("SELECT COUNT(*) AS count FROM campaign_npcs WHERE campaign_id = #{Database.escape(campaign_id)};").first
      friendly_row = Database.query(<<~SQL).first
        SELECT COUNT(*) AS count
        FROM campaign_npcs n
        JOIN campaign_factions f ON f.id = n.faction_id AND f.campaign_id = n.campaign_id
        WHERE n.campaign_id = #{Database.escape(campaign_id)} AND f.stance = 'friendly';
      SQL

      [200, {
        campaign_id: campaign_id,
        factions: faction_count_row ? faction_count_row['count'].to_i : 0,
        npcs: npc_count_row ? npc_count_row['count'].to_i : 0,
        friendly_npcs: friendly_row ? friendly_row['count'].to_i : 0
      }]
    end
  end
end

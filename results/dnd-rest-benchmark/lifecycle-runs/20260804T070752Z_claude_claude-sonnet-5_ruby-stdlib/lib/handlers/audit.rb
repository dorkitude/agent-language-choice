# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'
require_relative 'campaigns'

module Handlers
  # Deterministic audit log and export summaries for campaign state.
  module Audit
    module_function

    def count(table, campaign_id)
      row = Database.query(<<~SQL).first
        SELECT COUNT(*) AS count FROM #{table}
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
      row ? row['count'].to_i : 0
    end

    def audit(campaign_id, _body)
      Handlers::Campaigns.find_campaign(campaign_id)

      [200, {
        campaign_id: campaign_id,
        events: count('campaign_events', campaign_id),
        quests: count('campaign_quests', campaign_id),
        npcs: count('campaign_npcs', campaign_id),
        sessions: count('campaign_sessions', campaign_id)
      }]
    end

    def export(campaign_id, _body)
      campaign = Handlers::Campaigns.find_campaign(campaign_id)

      [200, {
        campaign_id: campaign_id,
        name: campaign[:name],
        characters: count('campaign_characters', campaign_id),
        quests: count('campaign_quests', campaign_id),
        npcs: count('campaign_npcs', campaign_id),
        inventory_items: count('campaign_inventory', campaign_id),
        sessions: count('campaign_sessions', campaign_id),
        schema_version: Database::SCHEMA_VERSION
      }]
    end
  end
end

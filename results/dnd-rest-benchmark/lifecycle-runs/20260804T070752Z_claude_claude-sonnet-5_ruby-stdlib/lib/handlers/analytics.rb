# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'
require_relative 'campaigns'

module Handlers
  # Deterministic campaign analytics derived from state accumulated across
  # all prior stages: quests, npcs/factions, sessions, and inventory.
  module Analytics
    module_function

    def count(sql)
      row = Database.query(sql).first
      row ? row['count'].to_i : 0
    end

    def open_quests(campaign_id)
      count(<<~SQL)
        SELECT COUNT(*) AS count FROM campaign_quests
        WHERE campaign_id = #{Database.escape(campaign_id)} AND status = 'active';
      SQL
    end

    def friendly_npcs(campaign_id)
      count(<<~SQL)
        SELECT COUNT(*) AS count
        FROM campaign_npcs n
        JOIN campaign_factions f ON f.id = n.faction_id AND f.campaign_id = n.campaign_id
        WHERE n.campaign_id = #{Database.escape(campaign_id)} AND f.stance = 'friendly';
      SQL
    end

    def scheduled_sessions(campaign_id)
      count(<<~SQL)
        SELECT COUNT(*) AS count FROM campaign_sessions
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    def inventory_items(campaign_id)
      count(<<~SQL)
        SELECT COUNT(*) AS count FROM campaign_inventory
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    def has_characters(campaign_id)
      count(<<~SQL).positive?
        SELECT COUNT(*) AS count FROM campaign_characters
        WHERE campaign_id = #{Database.escape(campaign_id)};
      SQL
    end

    def readiness_score(open_quests, friendly_npcs, scheduled_sessions, inventory_items)
      raw = 10 + (open_quests * 20) + (friendly_npcs * 15) + (scheduled_sessions * 30) + (inventory_items * 10)
      raw.clamp(0, 100)
    end

    def summary(campaign_id, _body)
      Handlers::Campaigns.find_campaign(campaign_id)

      quests = open_quests(campaign_id)
      npcs = friendly_npcs(campaign_id)
      sessions = scheduled_sessions(campaign_id)
      items = inventory_items(campaign_id)

      [200, {
        campaign_id: campaign_id,
        readiness_score: readiness_score(quests, npcs, sessions, items),
        open_quests: quests,
        friendly_npcs: npcs,
        scheduled_sessions: sessions,
        inventory_items: items
      }]
    end

    def risk_report(campaign_id, body)
      campaign = Handlers::Campaigns.find_campaign(campaign_id)

      include_zeroes = body.key?('include_zeroes') ? body['include_zeroes'] : true
      raise HttpError.new(400, 'include_zeroes must be a boolean') unless [true, false].include?(include_zeroes)

      has_dm = campaign[:dm].is_a?(String) && !campaign[:dm].empty?
      has_chars = has_characters(campaign_id)
      has_next_session = scheduled_sessions(campaign_id).positive?
      has_active_quest = open_quests(campaign_id).positive?

      signals = {
        has_dm: has_dm,
        has_characters: has_chars,
        has_next_session: has_next_session,
        has_active_quest: has_active_quest
      }

      missing = []
      missing << 'dm' unless has_dm
      missing << 'characters' unless has_chars
      missing << 'next_session' unless has_next_session
      missing << 'active_quest' unless has_active_quest

      risk_level = case missing.size
                   when 0 then 'low'
                   when 1, 2 then 'medium'
                   else 'high'
                   end

      [200, {
        campaign_id: campaign_id,
        risk_level: risk_level,
        missing: include_zeroes ? missing : [],
        signals: signals
      }]
    end
  end
end

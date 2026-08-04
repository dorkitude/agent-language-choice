# frozen_string_literal: true

require_relative 'persistence'

# Campaign analytics: readiness and risk summaries.
module Analytics
  def self.summary(campaign_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      row = d.get_first_row('SELECT dm FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless row

      dm = row[0]
      characters = d.get_first_value('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?', campaign_id)
      active_quests = d.get_first_value(
        "SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active'",
        campaign_id
      )
      friendly_npcs = d.get_first_value(
        'SELECT COUNT(*) FROM campaign_npcs n JOIN campaign_factions f ON n.faction_id = f.id WHERE n.campaign_id = ? AND f.stance = ?',
        [campaign_id, 'friendly']
      )
      sessions = d.get_first_value('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?', campaign_id)
      inventory_items = d.get_first_value(
        'SELECT COUNT(DISTINCT item_slug) FROM campaign_inventory WHERE campaign_id = ?',
        campaign_id
      )

      has_dm = dm.is_a?(String) && !dm.empty?
      has_characters = characters > 0
      has_next_session = sessions > 0
      has_active_quest = active_quests > 0

      readiness_score = 0
      readiness_score += 25 if has_dm
      readiness_score += 25 if has_characters
      readiness_score += 20 if has_next_session
      readiness_score += 15 if has_active_quest

      [:ok, {
        'campaign_id' => campaign_id,
        'readiness_score' => readiness_score,
        'open_quests' => active_quests,
        'friendly_npcs' => friendly_npcs,
        'scheduled_sessions' => sessions,
        'inventory_items' => inventory_items
      }]
    end
  end

  def self.risk_report(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?
    return [:invalid] unless payload.is_a?(Hash)

    include_zeroes = payload.fetch('include_zeroes', false)
    return [:invalid] unless [true, false].include?(include_zeroes)

    Persistence.db do |d|
      row = d.get_first_row('SELECT dm FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless row

      dm = row[0]
      characters = d.get_first_value('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?', campaign_id)
      sessions = d.get_first_value('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?', campaign_id)
      active_quests = d.get_first_value(
        "SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ? AND status = 'active'",
        campaign_id
      )

      signals = {
        'has_dm' => dm.is_a?(String) && !dm.empty?,
        'has_characters' => characters > 0,
        'has_next_session' => sessions > 0,
        'has_active_quest' => active_quests > 0
      }

      missing = signals.select { |_, present| !present }.keys
      true_count = signals.count { |_, present| present }

      risk_level = case true_count
                   when 4 then 'low'
                   when 3 then 'medium'
                   else 'high'
                   end

      [:ok, {
        'campaign_id' => campaign_id,
        'risk_level' => risk_level,
        'missing' => missing,
        'signals' => signals
      }]
    end
  end
end

# frozen_string_literal: true

require_relative 'persistence'

# Factions and NPCs: campaign relationship tracking.
module Factions
  def self.create_faction(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_faction(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      existing = d.get_first_value('SELECT 1 FROM campaign_factions WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaign_factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)',
        [data[:id], campaign_id, data[:name], data[:stance]]
      )

      [:ok, {
        'id' => data[:id],
        'name' => data[:name],
        'stance' => data[:stance]
      }]
    end
  end

  def self.create_npc(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_npc(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      faction_exists = d.get_first_value(
        'SELECT 1 FROM campaign_factions WHERE id = ? AND campaign_id = ?',
        [data[:faction_id], campaign_id]
      )
      next [:not_found] unless faction_exists

      existing = d.get_first_value('SELECT 1 FROM campaign_npcs WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaign_npcs (id, campaign_id, faction_id, name, disposition) VALUES (?, ?, ?, ?, ?)',
        [data[:id], campaign_id, data[:faction_id], data[:name], data[:disposition]]
      )

      [:ok, {
        'id' => data[:id],
        'name' => data[:name],
        'faction_id' => data[:faction_id],
        'disposition' => data[:disposition]
      }]
    end
  end

  def self.relationships(campaign_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      factions = d.get_first_value('SELECT COUNT(*) FROM campaign_factions WHERE campaign_id = ?', campaign_id)
      npcs = d.get_first_value('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?', campaign_id)
      friendly_npcs = d.get_first_value(
        'SELECT COUNT(*) FROM campaign_npcs n JOIN campaign_factions f ON n.faction_id = f.id WHERE n.campaign_id = ? AND f.stance = ?',
        [campaign_id, 'friendly']
      )

      [:ok, {
        'campaign_id' => campaign_id,
        'factions' => factions,
        'npcs' => npcs,
        'friendly_npcs' => friendly_npcs
      }]
    end
  end

  def self.validate_faction(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']
    stance = payload['stance']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      stance.is_a?(String) && !stance.empty?

    { id: id, name: name, stance: stance }
  end
  private_class_method :validate_faction

  def self.validate_npc(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']
    faction_id = payload['faction_id']
    disposition = payload['disposition']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      faction_id.is_a?(String) && !faction_id.empty? &&
                      disposition.is_a?(Integer)

    { id: id, name: name, faction_id: faction_id, disposition: disposition }
  end
  private_class_method :validate_npc
end

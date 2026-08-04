# frozen_string_literal: true

require_relative 'config'
require_relative 'persistence'

# Campaigns: state, characters, and session logs.
module Campaigns
  def self.create(payload)
    data = validate_campaign(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      existing = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)',
        [data[:id], data[:name], data[:dm]]
      )

      [:ok, {
        'id' => data[:id],
        'name' => data[:name],
        'dm' => data[:dm]
      }]
    end
  end

  def self.create_character(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_character(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      existing = d.get_first_value('SELECT 1 FROM campaign_characters WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
        [data[:id], campaign_id, data[:name], data[:level], data[:class]]
      )

      [:ok, {
        'id' => data[:id],
        'name' => data[:name],
        'level' => data[:level],
        'class' => data[:class]
      }]
    end
  end

  def self.create_event(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_event(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      existing = d.get_first_value('SELECT 1 FROM campaign_events WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)',
        [data[:id], campaign_id, data[:kind], data[:summary]]
      )

      [:ok, {
        'id' => data[:id],
        'kind' => data[:kind]
      }]
    end
  end

  def self.state(campaign_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      row = d.get_first_row('SELECT name, dm FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless row

      name, dm = row

      characters = d.execute(
        'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id',
        campaign_id
      ).map do |id, char_name, level, klass|
        { 'id' => id, 'name' => char_name, 'level' => level, 'class' => klass }
      end

      log_count = d.get_first_value('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', campaign_id)

      [:ok, {
        'id' => campaign_id,
        'name' => name,
        'dm' => dm,
        'characters' => characters,
        'log_count' => log_count
      }]
    end
  end

  def self.audit(campaign_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      events = d.get_first_value('SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?', campaign_id)
      quests = d.get_first_value('SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?', campaign_id)
      npcs = d.get_first_value('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?', campaign_id)
      sessions = d.get_first_value('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?', campaign_id)

      [:ok, {
        'campaign_id' => campaign_id,
        'events' => events,
        'quests' => quests,
        'npcs' => npcs,
        'sessions' => sessions
      }]
    end
  end

  def self.export(campaign_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      row = d.get_first_row('SELECT name FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless row

      name = row[0]
      characters = d.get_first_value('SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?', campaign_id)
      quests = d.get_first_value('SELECT COUNT(*) FROM campaign_quests WHERE campaign_id = ?', campaign_id)
      npcs = d.get_first_value('SELECT COUNT(*) FROM campaign_npcs WHERE campaign_id = ?', campaign_id)
      inventory_items = d.get_first_value('SELECT COUNT(DISTINCT item_slug) FROM campaign_inventory WHERE campaign_id = ?', campaign_id)
      sessions = d.get_first_value('SELECT COUNT(*) FROM campaign_sessions WHERE campaign_id = ?', campaign_id)

      [:ok, {
        'campaign_id' => campaign_id,
        'name' => name,
        'characters' => characters,
        'quests' => quests,
        'npcs' => npcs,
        'inventory_items' => inventory_items,
        'sessions' => sessions,
        'schema_version' => Config::SCHEMA_VERSION
      }]
    end
  end

  def self.validate_campaign(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']
    dm = payload['dm']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      dm.is_a?(String) && !dm.empty?

    { id: id, name: name, dm: dm }
  end
  private_class_method :validate_campaign

  def self.validate_character(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    name = payload['name']
    level = payload['level']
    klass = payload['class']

    return nil unless id.is_a?(String) && !id.empty? &&
                      name.is_a?(String) && !name.empty? &&
                      level.is_a?(Integer) && level >= 1 && level <= 20 &&
                      klass.is_a?(String) && !klass.empty?

    { id: id, name: name, level: level, class: klass }
  end
  private_class_method :validate_character

  def self.validate_event(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    kind = payload['kind']
    summary = payload['summary']

    return nil unless id.is_a?(String) && !id.empty? &&
                      kind.is_a?(String) && !kind.empty? &&
                      (summary.nil? || summary.is_a?(String))

    { id: id, kind: kind, summary: summary }
  end
  private_class_method :validate_event
end

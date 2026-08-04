# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'

module Handlers
  # Campaigns and their nested characters/event log. `find_campaign` is
  # reused by Handlers::DmTools since DM tools always operate within the
  # context of an existing campaign.
  module Campaigns
    module_function

    def find_campaign(id)
      row = Database.query("SELECT id, name, dm FROM campaigns WHERE id = #{Database.escape(id)};").first
      raise HttpError.new(404, 'unknown campaign id') unless row

      { id: row['id'], name: row['name'], dm: row['dm'] }
    end

    def create_campaign(body)
      id = body['id']
      name = body['name']
      dm = body['dm']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'dm must be a string') unless dm.is_a?(String) && !dm.empty?
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM campaigns WHERE id = #{Database.escape(id)};").empty?

      Database.exec("INSERT INTO campaigns (id, name, dm) VALUES (#{Database.escape(id)}, #{Database.escape(name)}, #{Database.escape(dm)});")

      [201, { id: id, name: name, dm: dm }]
    end

    def add_character(campaign_id, body)
      find_campaign(campaign_id)

      id = body['id']
      name = body['name']
      level = body['level']
      klass = body['class']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'name must be a string') unless name.is_a?(String) && !name.empty?
      raise HttpError.new(400, 'level must be an integer') unless level.is_a?(Integer)
      raise HttpError.new(400, 'class must be a string') unless klass.is_a?(String) && !klass.empty?
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM campaign_characters WHERE id = #{Database.escape(id)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO campaign_characters (id, campaign_id, name, level, class)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(campaign_id)},
          #{Database.escape(name)},
          #{Database.int(level)},
          #{Database.escape(klass)}
        );
      SQL

      [201, { id: id, name: name, level: level, class: klass }]
    end

    def add_event(campaign_id, body)
      find_campaign(campaign_id)

      id = body['id']
      kind = body['kind']
      summary = body['summary']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'kind must be a string') unless kind.is_a?(String) && !kind.empty?
      raise HttpError.new(400, 'summary must be a string') unless summary.is_a?(String)
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM campaign_events WHERE id = #{Database.escape(id)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO campaign_events (id, campaign_id, kind, summary)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(campaign_id)},
          #{Database.escape(kind)},
          #{Database.escape(summary)}
        );
      SQL

      [201, { id: id, kind: kind }]
    end

    def state(campaign_id, _body)
      campaign = find_campaign(campaign_id)

      character_rows = Database.query("SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = #{Database.escape(campaign_id)} ORDER BY rowid;")
      characters = character_rows.map do |row|
        { id: row['id'], name: row['name'], level: row['level'].to_i, class: row['class'] }
      end

      log_count_row = Database.query("SELECT COUNT(*) AS count FROM campaign_events WHERE campaign_id = #{Database.escape(campaign_id)};").first
      log_count = log_count_row ? log_count_row['count'].to_i : 0

      [200, {
        id: campaign[:id],
        name: campaign[:name],
        dm: campaign[:dm],
        characters: characters,
        log_count: log_count
      }]
    end
  end
end

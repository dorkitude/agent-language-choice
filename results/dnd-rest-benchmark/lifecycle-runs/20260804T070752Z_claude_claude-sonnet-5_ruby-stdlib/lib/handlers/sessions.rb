# frozen_string_literal: true

require 'json'
require_relative '../errors'
require_relative '../database'
require_relative 'campaigns'

module Handlers
  # Campaign session scheduling: schedule sessions, record attendance, and
  # look up the next upcoming session by start time.
  module Sessions
    module_function

    def find_session(campaign_id, session_id)
      row = Database.query(<<~SQL).first
        SELECT id, campaign_id, starts_at, duration_minutes, agenda_json, present_json, absent_json
        FROM campaign_sessions
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(session_id)};
      SQL
      raise HttpError.new(404, 'unknown session id') unless row

      row
    end

    def create_session(campaign_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)

      id = body['id']
      starts_at = body['starts_at']
      duration_minutes = body['duration_minutes']
      agenda = body['agenda']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'starts_at must be a string') unless starts_at.is_a?(String) && !starts_at.empty?
      raise HttpError.new(400, 'duration_minutes must be a positive integer') unless duration_minutes.is_a?(Integer) && duration_minutes.positive?
      raise HttpError.new(400, 'agenda must be an array of strings') unless agenda.is_a?(Array) && agenda.all? { |a| a.is_a?(String) }
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM campaign_sessions WHERE id = #{Database.escape(id)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json, present_json, absent_json)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(campaign_id)},
          #{Database.escape(starts_at)},
          #{Database.int(duration_minutes)},
          #{Database.escape(JSON.generate(agenda))},
          #{Database.escape(JSON.generate([]))},
          #{Database.escape(JSON.generate([]))}
        );
      SQL

      [201, {
        id: id,
        starts_at: starts_at,
        duration_minutes: duration_minutes,
        agenda_count: agenda.size
      }]
    end

    def record_attendance(campaign_id, session_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)
      find_session(campaign_id, session_id)

      present = body['present']
      absent = body['absent']

      raise HttpError.new(400, 'present must be an array of strings') unless present.is_a?(Array) && present.all? { |c| c.is_a?(String) }
      raise HttpError.new(400, 'absent must be an array of strings') unless absent.is_a?(Array) && absent.all? { |c| c.is_a?(String) }

      Database.exec(<<~SQL)
        UPDATE campaign_sessions
        SET present_json = #{Database.escape(JSON.generate(present))},
            absent_json = #{Database.escape(JSON.generate(absent))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(session_id)};
      SQL

      [200, {
        session_id: session_id,
        present_count: present.size,
        absent_count: absent.size
      }]
    end

    def next_session(campaign_id, _body)
      Handlers::Campaigns.find_campaign(campaign_id)

      rows = Database.query(<<~SQL)
        SELECT id, starts_at, agenda_json
        FROM campaign_sessions
        WHERE campaign_id = #{Database.escape(campaign_id)}
        ORDER BY starts_at ASC;
      SQL
      raise HttpError.new(404, 'no sessions scheduled') if rows.empty?

      row = rows.first
      agenda = JSON.parse(row['agenda_json'])

      [200, {
        id: row['id'],
        starts_at: row['starts_at'],
        agenda_count: agenda.size
      }]
    end
  end
end

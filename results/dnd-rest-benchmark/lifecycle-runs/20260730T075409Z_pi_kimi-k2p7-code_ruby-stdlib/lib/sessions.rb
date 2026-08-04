# frozen_string_literal: true

require 'json'
require_relative 'persistence'

# Session scheduling: campaign sessions and attendance.
module Sessions
  ISO8601_RE = /\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\z/.freeze

  def self.create(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_session(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      existing = d.get_first_value('SELECT 1 FROM campaign_sessions WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaign_sessions (id, campaign_id, starts_at, duration_minutes, agenda_json) VALUES (?, ?, ?, ?, ?)',
        [data[:id], campaign_id, data[:starts_at], data[:duration_minutes], JSON.generate(data[:agenda])]
      )

      [:ok, {
        'id' => data[:id],
        'starts_at' => data[:starts_at],
        'duration_minutes' => data[:duration_minutes],
        'agenda_count' => data[:agenda].length
      }]
    end
  end

  def self.record_attendance(campaign_id, session_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                             session_id.is_a?(String) && !session_id.empty?

    present = payload['present']
    absent = payload['absent']
    return [:invalid] unless present.is_a?(Array) && absent.is_a?(Array) &&
                             present.all? { |c| c.is_a?(String) && !c.empty? } &&
                             absent.all? { |c| c.is_a?(String) && !c.empty? }

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      session_exists = d.get_first_value(
        'SELECT 1 FROM campaign_sessions WHERE id = ? AND campaign_id = ?',
        [session_id, campaign_id]
      )
      next [:not_found] unless session_exists

      d.execute('DELETE FROM session_attendance WHERE session_id = ?', session_id)

      records = {}
      present.each { |c| records[c] = 'present' }
      absent.each { |c| records[c] = 'absent' }
      records.each do |character_id, status|
        d.execute(
          'INSERT INTO session_attendance (session_id, character_id, status) VALUES (?, ?, ?)',
          [session_id, character_id, status]
        )
      end

      [:ok, {
        'session_id' => session_id,
        'present_count' => present.length,
        'absent_count' => absent.length
      }]
    end
  end

  # Note: returns :not_found (not :invalid) for malformed IDs. This preserves
  # the behavior exercised by the cumulative session-scheduling suite.
  def self.next_session(campaign_id)
    return [:not_found] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      row = d.get_first_row(
        'SELECT id, starts_at, agenda_json FROM campaign_sessions WHERE campaign_id = ? ORDER BY starts_at ASC LIMIT 1',
        campaign_id
      )
      next [:not_found] unless row

      id, starts_at, agenda_json = row
      agenda = JSON.parse(agenda_json) rescue []

      [:ok, {
        'id' => id,
        'starts_at' => starts_at,
        'agenda_count' => agenda.length
      }]
    end
  end

  def self.validate_session(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    starts_at = payload['starts_at']
    duration_minutes = payload['duration_minutes']
    agenda = payload['agenda']

    return nil unless id.is_a?(String) && !id.empty? &&
                      starts_at.is_a?(String) && !starts_at.empty? && starts_at.match?(ISO8601_RE) &&
                      duration_minutes.is_a?(Integer) && duration_minutes > 0 &&
                      agenda.is_a?(Array) &&
                      agenda.all? { |a| a.is_a?(String) && !a.empty? }

    {
      id: id,
      starts_at: starts_at,
      duration_minutes: duration_minutes,
      agenda: agenda
    }
  end
  private_class_method :validate_session
end

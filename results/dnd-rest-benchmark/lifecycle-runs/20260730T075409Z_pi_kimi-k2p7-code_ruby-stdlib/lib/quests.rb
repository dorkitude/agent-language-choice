# frozen_string_literal: true

require 'json'
require_relative 'persistence'

# Quest tracking for a campaign.
module Quests
  VALID_STATUSES = %w[active completed blocked].freeze

  def self.create(campaign_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    data = validate_quest(payload)
    return [:invalid] unless data

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      existing = d.get_first_value('SELECT 1 FROM campaign_quests WHERE id = ?', data[:id])
      next [:conflict] if existing

      d.execute(
        'INSERT INTO campaign_quests (id, campaign_id, title, status, milestones_json, completed_json) VALUES (?, ?, ?, ?, ?, ?)',
        [data[:id], campaign_id, data[:title], data[:status], JSON.generate(data[:milestones]), JSON.generate(data[:completed])]
      )

      [:ok, {
        'id' => data[:id],
        'title' => data[:title],
        'status' => data[:status],
        'milestones_total' => data[:milestones].length,
        'milestones_done' => 0
      }]
    end
  end

  def self.update_progress(campaign_id, quest_id, payload)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty? &&
                           quest_id.is_a?(String) && !quest_id.empty?

    completed = payload['completed']
    return [:invalid] unless completed.is_a?(Array) && completed.all? { |m| m.is_a?(String) }

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      row = d.get_first_row(
        'SELECT id, status, milestones_json, completed_json FROM campaign_quests WHERE id = ? AND campaign_id = ?',
        [quest_id, campaign_id]
      )
      next [:not_found] unless row

      _, status, milestones_json, completed_json = row
      milestones = JSON.parse(milestones_json)
      done = JSON.parse(completed_json)

      completed.each do |m|
        done << m if milestones.include?(m) && !done.include?(m)
      end

      milestones_done = milestones.count { |m| done.include?(m) }
      new_status = (milestones_done == milestones.length && milestones.length > 0) ? 'completed' : status

      d.execute(
        'UPDATE campaign_quests SET status = ?, completed_json = ? WHERE id = ?',
        [new_status, JSON.generate(done), quest_id]
      )

      [:ok, {
        'id' => quest_id,
        'status' => new_status,
        'milestones_total' => milestones.length,
        'milestones_done' => milestones_done
      }]
    end
  end

  def self.summary(campaign_id)
    return [:invalid] unless campaign_id.is_a?(String) && !campaign_id.empty?

    Persistence.db do |d|
      campaign_exists = d.get_first_value('SELECT 1 FROM campaigns WHERE id = ?', campaign_id)
      next [:not_found] unless campaign_exists

      active = 0
      completed = 0
      blocked = 0

      d.execute('SELECT status FROM campaign_quests WHERE campaign_id = ?', campaign_id).each do |row|
        status = row[0]
        case status
        when 'active' then active += 1
        when 'completed' then completed += 1
        when 'blocked' then blocked += 1
        end
      end

      [:ok, {
        'campaign_id' => campaign_id,
        'active' => active,
        'completed' => completed,
        'blocked' => blocked
      }]
    end
  end

  def self.validate_quest(payload)
    return nil unless payload.is_a?(Hash)

    id = payload['id']
    title = payload['title']
    status = payload['status']
    milestones = payload['milestones']

    return nil unless id.is_a?(String) && !id.empty? &&
                      title.is_a?(String) && !title.empty? &&
                      status.is_a?(String) && VALID_STATUSES.include?(status) &&
                      milestones.is_a?(Array) &&
                      milestones.all? { |m| m.is_a?(String) && !m.empty? }

    {
      id: id,
      title: title,
      status: status,
      milestones: milestones,
      completed: []
    }
  end
  private_class_method :validate_quest
end

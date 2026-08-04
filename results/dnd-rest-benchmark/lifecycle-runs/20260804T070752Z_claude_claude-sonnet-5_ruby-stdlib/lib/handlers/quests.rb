# frozen_string_literal: true

require 'json'
require_relative '../errors'
require_relative '../database'
require_relative 'campaigns'

module Handlers
  # Campaign quest tracking: create quests with milestones, mark milestones
  # complete, and summarize quest status counts per campaign.
  module Quests
    STATUSES = %w[active completed blocked].freeze

    module_function

    def find_quest(campaign_id, quest_id)
      row = Database.query(<<~SQL).first
        SELECT id, campaign_id, title, status, milestones_json, completed_json
        FROM campaign_quests
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(quest_id)};
      SQL
      raise HttpError.new(404, 'unknown quest id') unless row

      row
    end

    def create_quest(campaign_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)

      id = body['id']
      title = body['title']
      status = body['status']
      milestones = body['milestones']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'title must be a string') unless title.is_a?(String) && !title.empty?
      raise HttpError.new(400, 'status must be one of active, completed, blocked') unless STATUSES.include?(status)
      raise HttpError.new(400, 'milestones must be an array of strings') unless milestones.is_a?(Array) && milestones.all? { |m| m.is_a?(String) }
      raise HttpError.new(409, 'id already exists') unless Database.query("SELECT id FROM campaign_quests WHERE id = #{Database.escape(id)};").empty?

      Database.exec(<<~SQL)
        INSERT INTO campaign_quests (id, campaign_id, title, status, milestones_json, completed_json)
        VALUES (
          #{Database.escape(id)},
          #{Database.escape(campaign_id)},
          #{Database.escape(title)},
          #{Database.escape(status)},
          #{Database.escape(JSON.generate(milestones))},
          #{Database.escape(JSON.generate([]))}
        );
      SQL

      [201, {
        id: id,
        title: title,
        status: status,
        milestones_total: milestones.size,
        milestones_done: 0
      }]
    end

    def update_progress(campaign_id, quest_id, body)
      Handlers::Campaigns.find_campaign(campaign_id)
      quest = find_quest(campaign_id, quest_id)

      completed_arg = body['completed']
      raise HttpError.new(400, 'completed must be an array of strings') unless completed_arg.is_a?(Array) && completed_arg.all? { |m| m.is_a?(String) }

      milestones = JSON.parse(quest['milestones_json'])
      completed = JSON.parse(quest['completed_json'])

      invalid = completed_arg - milestones
      raise HttpError.new(400, "unknown milestone(s): #{invalid.join(', ')}") unless invalid.empty?

      completed = (completed + completed_arg).uniq

      Database.exec(<<~SQL)
        UPDATE campaign_quests
        SET completed_json = #{Database.escape(JSON.generate(completed))}
        WHERE campaign_id = #{Database.escape(campaign_id)} AND id = #{Database.escape(quest_id)};
      SQL

      [200, {
        id: quest_id,
        status: quest['status'],
        milestones_total: milestones.size,
        milestones_done: completed.size
      }]
    end

    def summary(campaign_id, _body)
      Handlers::Campaigns.find_campaign(campaign_id)

      rows = Database.query("SELECT status FROM campaign_quests WHERE campaign_id = #{Database.escape(campaign_id)};")

      counts = { 'active' => 0, 'completed' => 0, 'blocked' => 0 }
      rows.each { |row| counts[row['status']] += 1 if counts.key?(row['status']) }

      [200, {
        campaign_id: campaign_id,
        active: counts['active'],
        completed: counts['completed'],
        blocked: counts['blocked']
      }]
    end
  end
end

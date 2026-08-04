class QuestsController < ApplicationController
  VALID_STATUSES = %w[active completed blocked].freeze

  def create
    campaign_id = params[:id]
    id = @body['id']
    title = @body['title']
    status = @body['status']
    milestones = @body['milestones']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless title.is_a?(String) && !title.empty?
      bad_request('invalid title')
      return
    end

    unless VALID_STATUSES.include?(status)
      bad_request('invalid status')
      return
    end

    unless milestones.is_a?(Array) && milestones.all? { |m| m.is_a?(String) && !m.empty? }
      bad_request('invalid milestones')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      begin
        GameStorage.db.execute(
          'INSERT INTO quests (id, campaign_id, title, status, milestones_json, completed_milestones_json) VALUES (?, ?, ?, ?, ?, ?)',
          [id, campaign_id, title, status, JSON.generate(milestones), '[]']
        )
        render json: {
          id: id,
          title: title,
          status: status,
          milestones_total: milestones.length,
          milestones_done: 0
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'quest id taken' }, status: :conflict
      end
    end
  end

  def progress
    campaign_id = params[:id]
    quest_id = params[:quest_id]
    completed = @body['completed']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(quest_id)
      bad_request('invalid quest id')
      return
    end

    unless completed.is_a?(Array) && completed.all? { |c| c.is_a?(String) }
      bad_request('invalid completed')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      quest = GameStorage.db.get_first_row(
        'SELECT id, status, milestones_json, completed_milestones_json FROM quests WHERE id = ? AND campaign_id = ?',
        [quest_id, campaign_id]
      )
      if quest.nil?
        render json: { error: 'quest not found' }, status: :not_found
        return
      end

      milestones = JSON.parse(quest[2])
      existing_completed = JSON.parse(quest[3])
      new_completed = (existing_completed + completed.select { |c| milestones.include?(c) }).uniq
      new_status = new_completed.length == milestones.length ? 'completed' : quest[1]

      GameStorage.db.execute(
        'UPDATE quests SET status = ?, completed_milestones_json = ? WHERE id = ?',
        [new_status, JSON.generate(new_completed), quest_id]
      )

      render json: {
        id: quest_id,
        status: new_status,
        milestones_total: milestones.length,
        milestones_done: new_completed.length
      }
    end
  end

  def summary
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    counts = GameStorage.db.execute(
      'SELECT status, COUNT(*) FROM quests WHERE campaign_id = ? GROUP BY status',
      campaign_id
    ).each_with_object({}) { |row, h| h[row[0]] = row[1] }

    render json: {
      campaign_id: campaign_id,
      active: counts['active'].to_i,
      completed: counts['completed'].to_i,
      blocked: counts['blocked'].to_i
    }
  end
end

# Campaign quest tracking: creation, milestone progress, and summary
# counts. Quests are stored inline on the campaign hash under :quests,
# keyed by quest id, and persisted through CAMPAIGNS.persist.
class QuestsController < ApplicationController
  VALID_STATUSES = %w[active completed blocked].freeze

  def create_quest
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    id = params[:id]
    title = params[:title]
    status = params[:status]
    milestones = params[:milestones]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless title.is_a?(String) && !title.empty?
      render json: { error: 'invalid title' }, status: :bad_request
      return
    end

    unless status.is_a?(String) && VALID_STATUSES.include?(status)
      render json: { error: 'invalid status' }, status: :bad_request
      return
    end

    unless milestones.is_a?(Array) && !milestones.empty? && milestones.all? { |m| m.is_a?(String) && !m.empty? }
      render json: { error: 'invalid milestones' }, status: :bad_request
      return
    end

    campaign[:quests] ||= {}
    if campaign[:quests].key?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    campaign[:quests][id] = {
      title: title,
      status: status,
      milestones: milestones,
      done: []
    }
    CAMPAIGNS.persist(params[:campaign_id])

    render json: quest_payload(id, campaign[:quests][id], include_title: true), status: :created
  end

  def update_quest_progress
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    quest = campaign[:quests] && campaign[:quests][params[:quest_id]]
    if quest.nil?
      render json: { error: 'quest not found' }, status: :not_found
      return
    end

    completed = params[:completed] || []
    unless completed.is_a?(Array) && completed.all? { |m| m.is_a?(String) }
      render json: { error: 'invalid completed' }, status: :bad_request
      return
    end

    unless completed.all? { |m| quest[:milestones].include?(m) }
      render json: { error: 'unknown milestone' }, status: :bad_request
      return
    end

    status = params[:status]
    if status && !VALID_STATUSES.include?(status)
      render json: { error: 'invalid status' }, status: :bad_request
      return
    end

    quest[:done] = (quest[:done] + completed).uniq

    if status
      quest[:status] = status
    elsif quest[:done].length == quest[:milestones].length && quest[:status] != 'blocked'
      quest[:status] = 'completed'
    end

    CAMPAIGNS.persist(params[:campaign_id])

    render json: quest_payload(params[:quest_id], quest)
  end

  def quest_summary
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    quests = (campaign[:quests] || {}).values
    render json: {
      campaign_id: params[:campaign_id],
      active: quests.count { |q| q[:status] == 'active' },
      completed: quests.count { |q| q[:status] == 'completed' },
      blocked: quests.count { |q| q[:status] == 'blocked' }
    }
  end

  private

  def quest_payload(id, quest, include_title: false)
    payload = { id: id }
    payload[:title] = quest[:title] if include_title
    payload[:status] = quest[:status]
    payload[:milestones_total] = quest[:milestones].length
    payload[:milestones_done] = quest[:done].length
    payload
  end
end

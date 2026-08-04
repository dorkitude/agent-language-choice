# Downtime crafting projects: creation and day-by-day progress tracking.
# Projects are stored inline on the campaign hash under :crafting_projects,
# keyed by project id, and persisted through CAMPAIGNS.persist.
class DowntimeController < ApplicationController
  def create_crafting_project
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    id = params[:id]
    character_id = params[:character_id]
    item_slug = params[:item_slug]
    days_required = params[:days_required]
    cost_gp = params[:cost_gp]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless character_id.is_a?(String) && !character_id.empty?
      render json: { error: 'invalid character_id' }, status: :bad_request
      return
    end

    unless item_slug.is_a?(String) && !item_slug.empty?
      render json: { error: 'invalid item_slug' }, status: :bad_request
      return
    end

    unless valid_integer?(days_required) && days_required.to_i.positive?
      render json: { error: 'invalid days_required' }, status: :bad_request
      return
    end

    unless valid_integer?(cost_gp) && cost_gp.to_i >= 0
      render json: { error: 'invalid cost_gp' }, status: :bad_request
      return
    end

    campaign[:crafting_projects] ||= {}
    if campaign[:crafting_projects].key?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    campaign[:crafting_projects][id] = {
      character_id: character_id,
      item_slug: item_slug,
      days_required: days_required.to_i,
      days_completed: 0,
      cost_gp: cost_gp.to_i,
      status: 'active'
    }
    CAMPAIGNS.persist(params[:campaign_id])

    render json: crafting_payload(id, campaign[:crafting_projects][id], full: true), status: :created
  end

  def advance_crafting_project
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    project = campaign[:crafting_projects] && campaign[:crafting_projects][params[:project_id]]
    if project.nil?
      render json: { error: 'crafting project not found' }, status: :not_found
      return
    end

    days = params[:days]
    unless valid_integer?(days) && days.to_i.positive?
      render json: { error: 'invalid days' }, status: :bad_request
      return
    end

    if project[:status] == 'complete'
      render json: { error: 'crafting project already complete' }, status: :conflict
      return
    end

    project[:days_completed] = [project[:days_completed] + days.to_i, project[:days_required]].min

    if project[:days_completed] >= project[:days_required]
      project[:status] = 'complete'
    end

    CAMPAIGNS.persist(params[:campaign_id])

    render json: crafting_payload(params[:project_id], project)
  end

  private

  def crafting_payload(id, project, full: false)
    payload = { id: id }
    if full
      payload[:character_id] = project[:character_id]
      payload[:item_slug] = project[:item_slug]
      payload[:days_required] = project[:days_required]
    end
    payload[:days_completed] = project[:days_completed]
    payload[:status] = project[:status]
    payload
  end
end

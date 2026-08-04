# Campaign lifecycle: creation, roster and event-log management, and
# state readback. Backed by the CAMPAIGNS persistent collection.
class CampaignsController < ApplicationController
  def create_campaign
    id = params[:id]
    name = params[:name]
    dm = params[:dm]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless name.is_a?(String) && !name.empty?
      render json: { error: 'invalid name' }, status: :bad_request
      return
    end

    unless dm.is_a?(String) && !dm.empty?
      render json: { error: 'invalid dm' }, status: :bad_request
      return
    end

    if CAMPAIGNS.key?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    CAMPAIGNS[id] = { name: name, dm: dm, characters: [], event_ids: [], events: [], log_count: 0 }

    render json: { id: id, name: name, dm: dm }, status: :created
  end

  def add_campaign_character
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    id = params[:id]
    name = params[:name]
    level = params[:level]
    klass = params[:class]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless name.is_a?(String) && !name.empty?
      render json: { error: 'invalid name' }, status: :bad_request
      return
    end

    unless valid_integer?(level)
      render json: { error: 'invalid level' }, status: :bad_request
      return
    end

    unless klass.is_a?(String) && !klass.empty?
      render json: { error: 'invalid class' }, status: :bad_request
      return
    end

    if campaign[:characters].any? { |c| c[:id] == id }
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    character = { id: id, name: name, level: level.to_i, class: klass }
    campaign[:characters] << character
    CAMPAIGNS.persist(params[:campaign_id])

    render json: character, status: :created
  end

  def add_campaign_event
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    id = params[:id]
    kind = params[:kind]
    summary = params[:summary]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    unless kind.is_a?(String) && !kind.empty?
      render json: { error: 'invalid kind' }, status: :bad_request
      return
    end

    unless summary.is_a?(String) && !summary.empty?
      render json: { error: 'invalid summary' }, status: :bad_request
      return
    end

    if campaign[:event_ids].include?(id)
      render json: { error: 'duplicate id' }, status: :conflict
      return
    end

    campaign[:event_ids] << id
    campaign[:events] ||= []
    campaign[:events] << { id: id, kind: kind, summary: summary }
    campaign[:log_count] += 1
    CAMPAIGNS.persist(params[:campaign_id])

    render json: { id: id, kind: kind }, status: :created
  end

  def campaign_state
    campaign = CAMPAIGNS[params[:campaign_id]]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    render json: {
      id: params[:campaign_id],
      name: campaign[:name],
      dm: campaign[:dm],
      characters: campaign[:characters].map { |c| { id: c[:id], name: c[:name], level: c[:level], class: c[:class] } },
      log_count: campaign[:log_count]
    }
  end
end

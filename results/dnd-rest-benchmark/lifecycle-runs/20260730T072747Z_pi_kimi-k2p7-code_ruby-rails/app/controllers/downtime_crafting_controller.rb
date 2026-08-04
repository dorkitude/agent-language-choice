class DowntimeCraftingController < ApplicationController
  def create
    campaign_id = params[:id]
    id = @body['id']
    character_id = @body['character_id']
    item_slug = @body['item_slug']
    days_required = @body['days_required']
    cost_gp = @body['cost_gp']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless valid_id?(character_id)
      bad_request('invalid character_id')
      return
    end

    unless valid_id?(item_slug)
      bad_request('invalid item_slug')
      return
    end

    unless days_required.is_a?(Integer) && days_required.positive?
      bad_request('invalid days_required')
      return
    end

    unless cost_gp.is_a?(Integer) && cost_gp >= 0
      bad_request('invalid cost_gp')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      character = GameStorage.db.get_first_row(
        'SELECT id FROM campaign_characters WHERE id = ? AND campaign_id = ?',
        [character_id, campaign_id]
      )
      if character.nil?
        render json: { error: 'character not found' }, status: :not_found
        return
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO crafting_projects (id, campaign_id, character_id, item_slug, days_required, days_completed, cost_gp, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
          [id, campaign_id, character_id, item_slug, days_required, 0, cost_gp, 'active']
        )
        render json: {
          id: id,
          character_id: character_id,
          item_slug: item_slug,
          days_required: days_required,
          days_completed: 0,
          status: 'active'
        }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'project id taken' }, status: :conflict
      end
    end
  end

  def advance
    campaign_id = params[:id]
    project_id = params[:project_id]
    days = @body['days']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(project_id)
      bad_request('invalid project id')
      return
    end

    unless days.is_a?(Integer) && days.positive?
      bad_request('invalid days')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      project = GameStorage.db.get_first_row(
        'SELECT id, days_required, days_completed, status, item_slug FROM crafting_projects WHERE id = ? AND campaign_id = ?',
        [project_id, campaign_id]
      )
      if project.nil?
        render json: { error: 'project not found' }, status: :not_found
        return
      end

      days_required = project[1]
      days_completed = project[2]
      status = project[3]

      if status == 'complete'
        render json: { id: project_id, days_completed: days_completed, status: 'complete' }
        return
      end

      new_days_completed = [days_completed + days, days_required].min
      new_status = new_days_completed >= days_required ? 'complete' : 'active'

      GameStorage.db.execute(
        'UPDATE crafting_projects SET days_completed = ?, status = ? WHERE id = ?',
        [new_days_completed, new_status, project_id]
      )

      render json: {
        id: project_id,
        days_completed: new_days_completed,
        status: new_status
      }
    end
  end
end

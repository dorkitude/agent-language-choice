class NpcsAndFactionsController < ApplicationController
  def create_faction
    campaign_id = params[:id]
    id = @body['id']
    name = @body['name']
    stance = @body['stance']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless valid_non_empty_string?(stance)
      bad_request('invalid stance')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      begin
        GameStorage.db.execute(
          'INSERT INTO factions (id, campaign_id, name, stance) VALUES (?, ?, ?, ?)',
          [id, campaign_id, name, stance]
        )
        render json: { id: id, name: name, stance: stance }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'faction id taken' }, status: :conflict
      end
    end
  end

  def create_npc
    campaign_id = params[:id]
    id = @body['id']
    name = @body['name']
    faction_id = @body['faction_id']
    disposition = @body['disposition']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless disposition.is_a?(Integer)
      bad_request('invalid disposition')
      return
    end

    unless faction_id.nil? || valid_id?(faction_id)
      bad_request('invalid faction id')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      if faction_id
        faction = GameStorage.db.get_first_row(
          'SELECT id FROM factions WHERE id = ? AND campaign_id = ?',
          [faction_id, campaign_id]
        )
        if faction.nil?
          render json: { error: 'faction not found' }, status: :not_found
          return
        end
      end

      begin
        GameStorage.db.execute(
          'INSERT INTO npcs (id, campaign_id, name, faction_id, disposition) VALUES (?, ?, ?, ?, ?)',
          [id, campaign_id, name, faction_id, disposition]
        )
        render json: { id: id, name: name, faction_id: faction_id, disposition: disposition }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'npc id taken' }, status: :conflict
      end
    end
  end

  def relationships
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    faction_count = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM factions WHERE campaign_id = ?',
      campaign_id
    ).to_i

    npc_count = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM npcs WHERE campaign_id = ?',
      campaign_id
    ).to_i

    friendly_npc_count = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM npcs WHERE campaign_id = ? AND disposition > 0',
      campaign_id
    ).to_i

    render json: {
      campaign_id: campaign_id,
      factions: faction_count,
      npcs: npc_count,
      friendly_npcs: friendly_npc_count
    }
  end
end

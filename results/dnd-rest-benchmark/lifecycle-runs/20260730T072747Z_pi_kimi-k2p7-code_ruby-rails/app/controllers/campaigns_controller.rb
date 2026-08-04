class CampaignsController < ApplicationController
  def create
    id = @body['id']
    name = @body['name']
    dm = @body['dm']

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    unless valid_non_empty_string?(dm)
      bad_request('invalid dm')
      return
    end

    GameStorage.with_lock do
      begin
        GameStorage.db.execute(
          'INSERT INTO campaigns (id, name, dm) VALUES (?, ?, ?)',
          [id, name, dm]
        )
        render json: { id: id, name: name, dm: dm }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'campaign id taken' }, status: :conflict
      end
    end
  end

  def add_character
    campaign_id = params[:id]
    id = @body['id']
    name = @body['name']
    level = @body['level']
    char_class = @body['class']

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

    unless level.is_a?(Integer)
      bad_request('invalid level')
      return
    end

    unless valid_non_empty_string?(char_class)
      bad_request('invalid class')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      begin
        GameStorage.db.execute(
          'INSERT INTO campaign_characters (id, campaign_id, name, level, class) VALUES (?, ?, ?, ?, ?)',
          [id, campaign_id, name, level, char_class]
        )
        render json: { id: id, name: name, level: level, class: char_class }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'character id taken' }, status: :conflict
      end
    end
  end

  def add_event
    campaign_id = params[:id]
    id = @body['id']
    kind = @body['kind']
    summary = @body['summary']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    unless valid_id?(id)
      bad_request('invalid id')
      return
    end

    unless valid_non_empty_string?(kind)
      bad_request('invalid kind')
      return
    end

    unless summary.nil? || summary.is_a?(String)
      bad_request('invalid summary')
      return
    end

    GameStorage.with_lock do
      campaign = find_campaign(campaign_id)
      return if campaign.nil?

      begin
        GameStorage.db.execute(
          'INSERT INTO campaign_events (id, campaign_id, kind, summary) VALUES (?, ?, ?, ?)',
          [id, campaign_id, kind, summary]
        )
        render json: { id: id, kind: kind }, status: :created
      rescue SQLite3::ConstraintException
        render json: { error: 'event id taken' }, status: :conflict
      end
    end
  end

  def state
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    characters = GameStorage.db.execute(
      'SELECT id, name, level, class FROM campaign_characters WHERE campaign_id = ? ORDER BY id',
      campaign_id
    ).map do |row|
      { id: row[0], name: row[1], level: row[2], class: row[3] }
    end

    log_count = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?',
      campaign_id
    )

    render json: {
      id: campaign[0],
      name: campaign[1],
      dm: campaign[2],
      characters: characters,
      log_count: log_count
    }
  end

  def audit
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    events = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM campaign_events WHERE campaign_id = ?',
      campaign_id
    )
    quests = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM quests WHERE campaign_id = ?',
      campaign_id
    )
    npcs = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM npcs WHERE campaign_id = ?',
      campaign_id
    )
    sessions = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM sessions WHERE campaign_id = ?',
      campaign_id
    )

    render json: {
      campaign_id: campaign_id,
      events: events,
      quests: quests,
      npcs: npcs,
      sessions: sessions
    }
  end

  def export
    campaign_id = params[:id]

    unless valid_id?(campaign_id)
      bad_request('invalid campaign id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    characters = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM campaign_characters WHERE campaign_id = ?',
      campaign_id
    )
    quests = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM quests WHERE campaign_id = ?',
      campaign_id
    )
    npcs = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM npcs WHERE campaign_id = ?',
      campaign_id
    )
    inventory_items = GameStorage.db.get_first_value(
      "SELECT COUNT(*) FROM inventory WHERE campaign_id = ? AND owner = 'party'",
      campaign_id
    )
    sessions = GameStorage.db.get_first_value(
      'SELECT COUNT(*) FROM sessions WHERE campaign_id = ?',
      campaign_id
    )

    render json: {
      campaign_id: campaign_id,
      name: campaign[1],
      characters: characters,
      quests: quests,
      npcs: npcs,
      inventory_items: inventory_items,
      sessions: sessions,
      schema_version: GameStorage::SCHEMA_VERSION
    }
  end
end

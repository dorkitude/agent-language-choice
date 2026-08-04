# DM-managed campaign settlements with player discovery.
#
# Settlements are owned by the campaign DM. Players discover them by posting
# to the discover endpoint, which appends the player's character ID to the
# ordered `discovered_by` list. Player responses filter the list to their own
# character ID.
class SettlementsController < ApplicationController
  before_action :require_authentication

  VALID_AVAILABILITY = %w[open limited closed].freeze

  def create
    settlement_id = @body['settlement_id']
    name = @body['name']
    services = @body['services']
    availability = @body['availability']
    campaign_id = params[:id]
    username = @current_user[:username]

    unless valid_non_empty_string?(settlement_id)
      bad_request('invalid settlement_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    normalized_services = validate_services(services)
    return if normalized_services.nil?

    unless VALID_AVAILABILITY.include?(availability)
      bad_request('invalid availability')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      duplicate = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?',
        [campaign_id, settlement_id]
      )

      if duplicate
        render json: { error: 'settlement id taken' }, status: :conflict
        return
      end

      GameStorage.db.execute(
        'INSERT INTO play_campaign_settlements (campaign_id, settlement_id, name, services_json, availability, discovered_by_json) VALUES (?, ?, ?, ?, ?, ?)',
        [campaign_id, settlement_id, name, JSON.generate(normalized_services), availability, '[]']
      )

      render json: settlement_response(settlement_id, name, normalized_services, availability, []), status: :created
    end
  end

  def update
    settlement_id = params[:settlement_id]
    name = @body['name']
    services = @body['services']
    availability = @body['availability']
    campaign_id = params[:id]
    username = @current_user[:username]

    unless valid_non_empty_string?(settlement_id)
      bad_request('invalid settlement_id')
      return
    end

    unless valid_non_empty_string?(name)
      bad_request('invalid name')
      return
    end

    normalized_services = validate_services(services)
    return if normalized_services.nil?

    unless VALID_AVAILABILITY.include?(availability)
      bad_request('invalid availability')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      unless campaign[1] == username
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      settlement = find_play_settlement(campaign_id, settlement_id)
      return unless settlement

      discovered_by = JSON.parse(settlement[4] || '[]')

      GameStorage.db.execute(
        'UPDATE play_campaign_settlements SET name = ?, services_json = ?, availability = ? WHERE campaign_id = ? AND settlement_id = ?',
        [name, JSON.generate(normalized_services), availability, campaign_id, settlement_id]
      )

      render json: settlement_response(settlement_id, name, normalized_services, availability, discovered_by), status: :ok
    end
  end

  def discover
    settlement_id = params[:settlement_id]
    campaign_id = params[:id]
    username = @current_user[:username]

    unless valid_non_empty_string?(settlement_id)
      bad_request('invalid settlement_id')
      return
    end

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      if username == campaign[1]
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      member = GameStorage.db.get_first_row(
        'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      settlement = find_play_settlement(campaign_id, settlement_id)
      return unless settlement

      character_id = member[0]
      discovered_by = JSON.parse(settlement[4] || '[]')
      services = JSON.parse(settlement[2] || '[]')
      name = settlement[1]
      availability = settlement[3]

      if discovered_by.include?(character_id)
        render json: settlement_response(settlement_id, name, services, availability, [character_id]), status: :ok
      else
        discovered_by << character_id
        GameStorage.db.execute(
          'UPDATE play_campaign_settlements SET discovered_by_json = ? WHERE campaign_id = ? AND settlement_id = ?',
          [JSON.generate(discovered_by), campaign_id, settlement_id]
        )
        render json: settlement_response(settlement_id, name, services, availability, [character_id]), status: :created
      end
    end
  end

  def index
    campaign_id = params[:id]
    username = @current_user[:username]

    GameStorage.with_lock do
      campaign = find_play_campaign(campaign_id)
      return unless campaign

      is_owner = campaign[1] == username
      is_member = GameStorage.db.get_first_value(
        'SELECT 1 FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
        [campaign_id, username]
      )

      unless is_owner || is_member
        render json: { error: 'forbidden' }, status: :forbidden
        return
      end

      rows = GameStorage.db.execute(
        'SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_campaign_settlements WHERE campaign_id = ? ORDER BY ROWID',
        campaign_id
      )

      if is_owner
        settlements = rows.map do |row|
          settlement_response(row[0], row[1], JSON.parse(row[2] || '[]'), row[3], JSON.parse(row[4] || '[]'))
        end
      else
        member = GameStorage.db.get_first_row(
          'SELECT character_id FROM play_campaign_members WHERE campaign_id = ? AND username = ?',
          [campaign_id, username]
        )
        my_character_id = member[0]

        settlements = rows.each_with_object([]) do |row, arr|
          discovered_by = JSON.parse(row[4] || '[]')
          if discovered_by.include?(my_character_id)
            arr << settlement_response(row[0], row[1], JSON.parse(row[2] || '[]'), row[3], [my_character_id])
          end
        end
      end

      render json: { settlements: settlements }, status: :ok
    end
  end

  private

  def validate_services(services)
    unless services.is_a?(Array) && !services.empty?
      bad_request('invalid services')
      return nil
    end

    normalized = []
    seen = {}

    services.each do |service|
      unless service.is_a?(String)
        bad_request('invalid services')
        return nil
      end

      trimmed = service.strip
      if trimmed.empty?
        bad_request('invalid services')
        return nil
      end

      if seen.key?(trimmed)
        bad_request('invalid services')
        return nil
      end

      seen[trimmed] = true
      normalized << trimmed
    end

    normalized
  end

  def settlement_response(settlement_id, name, services, availability, discovered_by)
    {
      settlement_id: settlement_id,
      name: name,
      services: services,
      availability: availability,
      discovered_by: discovered_by
    }
  end

  def find_play_campaign(campaign_id)
    row = GameStorage.db.get_first_row(
      'SELECT id, owner FROM play_campaigns WHERE id = ?',
      campaign_id
    )
    if row.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return nil
    end
    row
  end

  def find_play_settlement(campaign_id, settlement_id)
    row = GameStorage.db.get_first_row(
      'SELECT settlement_id, name, services_json, availability, discovered_by_json FROM play_campaign_settlements WHERE campaign_id = ? AND settlement_id = ?',
      [campaign_id, settlement_id]
    )
    if row.nil?
      render json: { error: 'settlement not found' }, status: :not_found
      return nil
    end
    row
  end
end

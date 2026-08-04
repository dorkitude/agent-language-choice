# frozen_string_literal: true

# Input validation helpers for all HTTP endpoints.
#
# Methods in this module run inside the Sinatra request context and may halt the
# request with a JSON 400 response when the input is invalid. Callers are
# responsible for setting a successful response's content type.
module Validation
  def valid_positive_integer?(value)
    value.is_a?(Integer) && value.positive?
  end

  def validate_integer!(value, name, range)
    unless value.is_a?(Integer) && range.cover?(value)
      json_error(400, "invalid #{name}")
    end
  end

  def validate_username!(username)
    unless username.is_a?(String) && username.match?(/\A[a-z0-9_-]{2,32}\z/)
      json_error(400, 'invalid username')
    end
  end

  def validate_password!(password)
    unless password.is_a?(String) && password.length >= 8
      json_error(400, 'invalid password')
    end
  end

  def validate_role!(role)
    unless role == 'dm' || role == 'player'
      json_error(400, 'invalid role')
    end
  end

  def validate_slug!(slug)
    unless slug.is_a?(String) && slug.match?(/\A[a-z0-9-]+\z/)
      json_error(400, 'invalid slug')
    end
  end

  def validate_campaign_id!(id)
    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid campaign id')
    end
  end

  def validate_monster_body!(body)
    slug = body['slug']
    name = body['name']
    cr = body['cr']
    armor_class = body['armor_class']
    hit_points = body['hit_points']
    tags = body['tags']

    validate_slug!(slug)
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless cr.is_a?(String) && cr.match?(/\A(\d+|1\/\d+)\z/)
      json_error(400, 'invalid cr')
    end
    unless armor_class.is_a?(Integer) && armor_class.positive?
      json_error(400, 'invalid armor_class')
    end
    unless hit_points.is_a?(Integer) && hit_points.positive?
      json_error(400, 'invalid hit_points')
    end
    unless tags.is_a?(Array) && tags.all? { |t| t.is_a?(String) }
      json_error(400, 'invalid tags')
    end
  end

  def validate_item_body!(body)
    slug = body['slug']
    name = body['name']
    type = body['type']
    rarity = body['rarity']
    cost_gp = body['cost_gp']

    validate_slug!(slug)
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless type.is_a?(String) && type != ''
      json_error(400, 'invalid type')
    end
    unless rarity.is_a?(String) && rarity != ''
      json_error(400, 'invalid rarity')
    end
    unless cost_gp.is_a?(Integer) && cost_gp >= 0
      json_error(400, 'invalid cost_gp')
    end
  end

  def validate_campaign_body!(body)
    id = body['id']
    name = body['name']
    dm = body['dm']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless dm.is_a?(String) && dm != ''
      json_error(400, 'invalid dm')
    end
  end

  def validate_character_body!(body)
    id = body['id']
    name = body['name']
    level = body['level']
    class_name = body['class']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless level.is_a?(Integer) && level.positive?
      json_error(400, 'invalid level')
    end
    unless class_name.is_a?(String) && class_name != ''
      json_error(400, 'invalid class')
    end
  end

  def validate_event_body!(body)
    id = body['id']
    kind = body['kind']
    summary = body['summary']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless kind.is_a?(String) && kind != ''
      json_error(400, 'invalid kind')
    end
    unless summary.is_a?(String)
      json_error(400, 'invalid summary')
    end
  end

  def validate_quest_body!(body)
    id = body['id']
    title = body['title']
    status = body['status']
    milestones = body['milestones']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless title.is_a?(String) && title != ''
      json_error(400, 'invalid title')
    end
    unless %w[active completed blocked].include?(status)
      json_error(400, 'invalid status')
    end
    unless milestones.is_a?(Array) && milestones.all? { |m| m.is_a?(String) }
      json_error(400, 'invalid milestones')
    end
  end

  def validate_progress_body!(body)
    completed = body['completed']

    unless completed.is_a?(Array) && completed.all? { |m| m.is_a?(String) }
      json_error(400, 'invalid completed')
    end
  end

  def validate_faction_body!(body)
    id = body['id']
    name = body['name']
    stance = body['stance']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless stance.is_a?(String) && stance != ''
      json_error(400, 'invalid stance')
    end
  end

  def validate_npc_body!(body)
    id = body['id']
    name = body['name']
    faction_id = body['faction_id']
    disposition = body['disposition']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless faction_id.is_a?(String) && faction_id != ''
      json_error(400, 'invalid faction_id')
    end
    unless disposition.is_a?(Integer)
      json_error(400, 'invalid disposition')
    end
  end

  def validate_party!(party)
    unless party.is_a?(Array) && !party.empty?
      json_error(400, 'invalid party')
    end
    party.each do |member|
      unless member.is_a?(Hash) && member['level'].is_a?(Integer) && member['level'].positive?
        json_error(400, 'invalid party member')
      end
    end
  end

  def validate_monster_slugs!(slugs)
    unless slugs.is_a?(Array) && !slugs.empty?
      json_error(400, 'invalid monster_slugs')
    end
    slugs.each { |slug| validate_slug!(slug) }
  end

  def validate_inventory_item_body!(body)
    item_slug = body['item_slug']
    quantity = body['quantity']
    owner = body['owner']

    validate_slug!(item_slug)
    unless valid_positive_integer?(quantity)
      json_error(400, 'invalid quantity')
    end
    unless owner.is_a?(String) && owner != ''
      json_error(400, 'invalid owner')
    end
  end

  def validate_equipment_assignment_body!(body)
    item_slug = body['item_slug']
    quantity = body['quantity']

    validate_slug!(item_slug)
    unless valid_positive_integer?(quantity)
      json_error(400, 'invalid quantity')
    end
  end

  def validate_crafting_project_body!(body)
    id = body['id']
    character_id = body['character_id']
    item_slug = body['item_slug']
    days_required = body['days_required']
    cost_gp = body['cost_gp']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless character_id.is_a?(String) && character_id != ''
      json_error(400, 'invalid character_id')
    end
    validate_slug!(item_slug)
    unless valid_positive_integer?(days_required)
      json_error(400, 'invalid days_required')
    end
    unless cost_gp.is_a?(Integer) && cost_gp >= 0
      json_error(400, 'invalid cost_gp')
    end
  end

  def validate_crafting_advance_body!(body)
    days = body['days']
    unless valid_positive_integer?(days)
      json_error(400, 'invalid days')
    end
  end

  def validate_session_body!(body)
    id = body['id']
    starts_at = body['starts_at']
    duration_minutes = body['duration_minutes']
    agenda = body['agenda']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless starts_at.is_a?(String) && starts_at.match?(/\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?\z/)
      json_error(400, 'invalid starts_at')
    end
    unless valid_positive_integer?(duration_minutes)
      json_error(400, 'invalid duration_minutes')
    end
    unless agenda.is_a?(Array) && agenda.all? { |item| item.is_a?(String) }
      json_error(400, 'invalid agenda')
    end
  end

  def validate_attendance_body!(body)
    present = body['present']
    absent = body['absent']

    unless present.is_a?(Array) && present.all? { |id| id.is_a?(String) }
      json_error(400, 'invalid present')
    end
    unless absent.is_a?(Array) && absent.all? { |id| id.is_a?(String) }
      json_error(400, 'invalid absent')
    end
  end

  def validate_play_campaign_body!(body)
    id = body['id']
    name = body['name']
    max_players = body['max_players']

    unless id.is_a?(String) && id != ''
      json_error(400, 'invalid id')
    end
    unless name.is_a?(String) && name != ''
      json_error(400, 'invalid name')
    end
    unless valid_positive_integer?(max_players)
      json_error(400, 'invalid max_players')
    end
  end
end

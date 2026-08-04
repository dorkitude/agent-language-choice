# frozen_string_literal: true

require 'json'
require_relative '../config'
require_relative '../auth'
require_relative '../campaigns'
require_relative '../combat'
require_relative '../compendium'
require_relative '../crafting'
require_relative '../dm_tools'
require_relative '../factions'
require_relative '../inventory'
require_relative '../player_handbook'
require_relative '../play_campaigns'
require_relative '../pure_rules'
require_relative '../quests'
require_relative '../sessions'
require_relative '../analytics'
require_relative '../persistence'
require_relative 'request'
require_relative 'response'

# Request routing and JSON dispatch.
module Router
  # Route table: a long if/elsif dispatch. Path parameters are captured with
  # anchored regexes and forced to UTF-8 so SQLite binds them as text.
  def self.route(request)
    return not_found unless request

    payload = parse_json(request.body)
    return bad_request if payload.nil?

    method = request.method
    path = request.path

    # Core / rules
    if method == 'GET' && path == '/health'
      json_response(200, { ok: true })
    elsif method == 'POST' && path == '/v1/dice/stats'
      result = PureRules.dice_stats(payload['expression'])
      result ? json_response(200, result) : bad_request
    elsif method == 'POST' && path == '/v1/checks/ability'
      roll = payload['roll']
      modifier = payload['modifier']
      dc = payload['dc']
      if roll.is_a?(Integer) && modifier.is_a?(Integer) && dc.is_a?(Integer)
        json_response(200, PureRules.ability_check(roll, modifier, dc))
      else
        bad_request
      end
    elsif method == 'POST' && path == '/v1/encounters/adjusted-xp'
      result = PureRules.adjusted_xp(payload['party'], payload['monsters'])
      result ? json_response(200, result) : bad_request
    elsif method == 'POST' && path == '/v1/initiative/order'
      result = PureRules.initiative_order(payload['combatants'])
      result ? json_response(200, result) : bad_request
    elsif method == 'POST' && path == '/v1/characters/ability-modifier'
      score = payload['score']
      mod = PureRules.ability_modifier(score)
      mod ? json_response(200, { score: score, modifier: mod }) : bad_request
    elsif method == 'POST' && path == '/v1/characters/proficiency'
      level = payload['level']
      bonus = PureRules.proficiency_bonus(level)
      bonus ? json_response(200, { level: level, proficiency_bonus: bonus }) : bad_request
    elsif method == 'POST' && path == '/v1/characters/derived-stats'
      result = PureRules.derived_stats(payload)
      result ? json_response(200, result) : bad_request

    # Combat
    elsif method == 'POST' && path == '/v1/combat/sessions'
      tag, data = Combat.create_session(payload)
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/combat/sessions/([^/]+)/conditions\z}.match(path))
      tag, data = Combat.add_condition(match[1], payload)
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/combat/sessions/([^/]+)/advance\z}.match(path))
      tag, data = Combat.advance_turn(match[1])
      handle_result(tag, data, status: 200)

    # Auth
    elsif method == 'POST' && path == '/v1/auth/register'
      username = payload['username']
      password = payload['password']
      role = payload['role']
      if Auth.valid_username?(username) && Auth.valid_password?(password) && Auth.valid_role?(role)
        if Auth.register_user(username, password, role)
          json_response(201, { username: username, role: role })
        else
          error_response(409)
        end
      else
        bad_request
      end
    elsif method == 'POST' && path == '/v1/auth/login'
      username = payload['username']
      password = payload['password']
      if username.is_a?(String) && password.is_a?(String) && Auth.authenticate_user(username, password)
        json_response(200, { username: username, token: "session-#{username}" })
      else
        error_response(401)
      end

    # Play campaigns (most routes require bearer auth)
    elsif method == 'POST' && path == '/v1/play/campaigns'
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create(payload, actor[:username])
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/members\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.join(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/start\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.start(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/narrations\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.narrate(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/locations\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_location(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/locations/([^/]+)/connections\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_connection(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/locations/([^/]+)/travel\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.valid_travel(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/scenes\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_scene(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/scenes/([^/]+)/enter\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.enter_scene(match[1], actor, match[2])
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/scenes/([^/]+)/close\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.close_scene(match[1], actor, match[2])
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/scenes/current\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.current_scene(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/document\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_document(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/document\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.update_document(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/turn\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.turn(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/turn/nudge\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.nudge(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/turn/travel\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.travel(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/my-turn\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.my_turn(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/gm/status\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.gm_status(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/actions\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.submit_action(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/resolutions\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.resolve(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end

    # Storage
    elsif method == 'GET' && path == '/v1/storage/status'
      json_response(200, Persistence.status)
    elsif method == 'POST' && path == '/v1/storage/reset'
      Persistence.soft_reset!
      json_response(200, { ok: true, schema_version: Config::SCHEMA_VERSION })

    # Compendium
    elsif method == 'POST' && path == '/v1/compendium/monsters'
      tag, data = Compendium.create_monster(payload)
      handle_result(tag, data, status: 201)
    elsif method == 'GET' && (match = %r{\A/v1/compendium/monsters/([^/]+)\z}.match(path))
      tag, data = Compendium.read_monster(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && path == '/v1/compendium/items'
      tag, data = Compendium.create_item(payload)
      handle_result(tag, data, status: 201)
    elsif method == 'GET' && (match = %r{\A/v1/compendium/items/([^/]+)\z}.match(path))
      tag, data = Compendium.read_item(match[1])
      handle_result(tag, data, status: 200)

    # Campaigns and related resources
    elsif method == 'POST' && path == '/v1/campaigns'
      tag, data = Campaigns.create(payload)
      handle_result(tag, data, status: 201)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/characters\z}.match(path))
      tag, data = Campaigns.create_character(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/events\z}.match(path))
      tag, data = Campaigns.create_event(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/state\z}.match(path))
      tag, data = Campaigns.state(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/audit\z}.match(path))
      tag, data = Campaigns.audit(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/export\z}.match(path))
      tag, data = Campaigns.export(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/quests\z}.match(path))
      tag, data = Quests.create(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/quests/([^/]+)/progress\z}.match(path))
      tag, data = Quests.update_progress(match[1], match[2], payload)
      handle_result(tag, data, status: 200)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/quests/summary\z}.match(path))
      tag, data = Quests.summary(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/factions\z}.match(path))
      tag, data = Factions.create_faction(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/npcs\z}.match(path))
      tag, data = Factions.create_npc(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/relationships\z}.match(path))
      tag, data = Factions.relationships(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/inventory\z}.match(path))
      tag, data = Inventory.add_item(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/characters/([^/]+)/equipment\z}.match(path))
      tag, data = Inventory.assign_equipment(match[1], match[2], payload)
      handle_result(tag, data, status: 200)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/inventory/summary\z}.match(path))
      tag, data = Inventory.summary(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/downtime/crafting\z}.match(path))
      tag, data = Crafting.create_project(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance\z}.match(path))
      tag, data = Crafting.advance_project(match[1], match[2], payload)
      handle_result(tag, data, status: 200)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/sessions/next\z}.match(path))
      tag, data = Sessions.next_session(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/sessions\z}.match(path))
      tag, data = Sessions.create(match[1], payload)
      handle_result(tag, data, status: 201)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance\z}.match(path))
      tag, data = Sessions.record_attendance(match[1], match[2], payload)
      handle_result(tag, data, status: 200)
    elsif method == 'GET' && (match = %r{\A/v1/campaigns/([^/]+)/analytics/summary\z}.match(path))
      tag, data = Analytics.summary(match[1])
      handle_result(tag, data, status: 200)
    elsif method == 'POST' && (match = %r{\A/v1/campaigns/([^/]+)/analytics/risk-report\z}.match(path))
      tag, data = Analytics.risk_report(match[1], payload)
      handle_result(tag, data, status: 200)

    # PHB rules
    elsif method == 'POST' && path == '/v1/phb/spell-slots'
      result = PlayerHandbook.spell_slots(payload)
      result ? json_response(200, result) : bad_request
    elsif method == 'POST' && path == '/v1/phb/rests/long'
      result = PlayerHandbook.long_rest(payload)
      result ? json_response(200, result) : bad_request
    elsif method == 'POST' && path == '/v1/phb/equipment-load'
      result = PlayerHandbook.equipment_load(payload)
      result ? json_response(200, result) : bad_request

    # DM tools
    elsif method == 'POST' && path == '/v1/dm/encounter-builder'
      result = DmTools.encounter_builder(payload)
      result ? json_response(200, result) : bad_request
    elsif method == 'POST' && path == '/v1/dm/loot-parcel'
      result = DmTools.loot_parcel(payload)
      result ? json_response(200, result) : bad_request
    elsif method == 'POST' && path == '/v1/dm/session-recap'
      result = DmTools.session_recap(payload)
      result ? json_response(200, result) : bad_request
    else
      not_found
    end
  end

  def self.parse_json(body)
    return {} if body.nil? || body.empty?

    JSON.parse(body)
  rescue JSON::ParserError
    nil
  end
  private_class_method :parse_json

  def self.require_auth(request, allowed_roles)
    actor = Auth.authenticate_bearer(request)
    return [:unauthorized] unless actor

    return [:forbidden] unless actor[:role] && allowed_roles.include?(actor[:role])

    [:ok, actor]
  end
  private_class_method :require_auth

  # Wraps an authenticated route. Returns 401/403 if the caller is missing or
  # has the wrong role; otherwise yields the authenticated actor and returns the
  # response produced by the block.
  def self.with_auth(request, allowed_roles)
    auth_tag, actor = require_auth(request, allowed_roles)
    case auth_tag
    when :unauthorized
      error_response(401)
    when :forbidden
      error_response(403)
    else
      yield actor
    end
  end
  private_class_method :with_auth

  def self.handle_result(tag, data, status:)
    case tag
    when :ok
      json_response(status, data)
    when :invalid
      bad_request
    when :not_found
      not_found
    when :conflict
      error_response(409)
    when :forbidden
      error_response(403)
    else
      error_response(500)
    end
  end
  private_class_method :handle_result

  def self.json_response(status, data)
    Response.new(status, JSON.generate(data))
  end
  private_class_method :json_response

  def self.bad_request
    error_response(400)
  end
  private_class_method :bad_request

  def self.not_found
    error_response(404)
  end
  private_class_method :not_found

  def self.error_response(status)
    Response.new(status, JSON.generate({ error: Response::STATUS_TEXT.fetch(status, 'Error') }))
  end
  private_class_method :error_response
end

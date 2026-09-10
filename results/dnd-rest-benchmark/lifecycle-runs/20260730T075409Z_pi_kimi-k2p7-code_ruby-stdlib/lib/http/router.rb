# frozen_string_literal: true

require 'json'
require_relative '../config'
require_relative '../service_mode'
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
  # anchored regexes; the request path is already forced to UTF-8 by Request.parse
  # so SQLite binds path parameters as text rather than blobs.
  def self.route(request)
    return not_found unless request

    payload = parse_json(request.body)
    return bad_request if payload.nil?

    method = request.method
    path = request.path

    # Public API schema (no auth, no state mutation)
    if method == 'GET' && path == '/v1/schema'
      json_response(200, api_schema)

    # Core / rules
    elsif method == 'GET' && path == '/health'
      json_response(200, { ok: true })
    elsif method == 'GET' && path == '/healthz'
      json_response(200, { status: 'ok' })
    elsif method == 'GET' && path == '/readyz'
      if ServiceMode.maintenance?
        json_response(503, { status: 'maintenance', schema_version: 2 })
      else
        json_response(200, { status: 'ready', schema_version: 2 })
      end
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
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/onboarding\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.onboarding(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/spectators\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_spectator(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/spectator-view\z}.match(path))
      with_spectator_auth(request) do |spectator_id|
        tag, data = PlayCampaigns.spectator_view(match[1], spectator_id)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/feed-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.append_feed_event(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/event-feed\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.read_event_feed(match[1], actor, request.query_params['cursor'], request.query_params['limit'])
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/session-zero\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.set_session_zero(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/session-zero\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_session_zero(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/invitations\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_invitation(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/invitations/([^/]+)/accept\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.accept_invitation(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/invitations\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_invitations(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/delegations\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.grant_delegation(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'DELETE' && (match = %r{\A/v1/play/campaigns/([^/]+)/delegations/([^/]+)\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.revoke_delegation(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/delegations/audit\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.delegation_audit(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/audit-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.create_audit_event(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/audit-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_audit_events(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/projection-events\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.create_projection_event(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/projection/rebuild\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.rebuild_projection(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/projection\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_projection(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/idempotent-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        idempotency_key = request.headers['idempotency-key']&.strip
        tag, data = PlayCampaigns.create_idempotent_event(match[1], actor, idempotency_key, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/idempotent-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_idempotent_events(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/safe-turns\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.submit_safe_turn(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/safe-turns\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_safe_turns(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/content\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_content(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/content/([^/]+)/tags\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.update_content_tags(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/content\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        exclude_tag = request.query_params['exclude_tag']
        tag, data = PlayCampaigns.list_content(match[1], actor, exclude_tag)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/notes\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.create_note(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/notes\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_notes(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/notes/([^/]+)\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_note(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/notes/([^/]+)\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.update_note(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/whispers\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.create_whisper(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/whispers\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_whispers(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/sheet\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_character_sheet(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/narrations\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.narrate(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/messages\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.create_message(match[1], actor, payload)
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
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/exports\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_export(match[1], actor)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/exports/([^/]+)\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        version = match[2].to_i
        tag, data = PlayCampaigns.get_export(match[1], version, actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/exports\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.list_exports(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/imports\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.import_snapshot(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/import-state\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.import_state(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/migrations\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.migrate_snapshot(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/migration-state\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.migration_state(match[1], actor)
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
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/turn/rest\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.rest(match[1], actor, payload)
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
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_encounter(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.add_monster(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'DELETE' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters/([^/]+)\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.remove_monster(match[1], match[2], match[3], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/conditions\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.apply_condition(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/status\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.encounter_status(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.bind_member(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'DELETE' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants/([^/]+)\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.unbind_member(match[1], match[2], match[3], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/advance\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.advance_encounter_turn(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/delay\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.delay(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/ready\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.ready(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.encounter_turn(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/actions\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.submit_combat_action(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/damage\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.damage(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/heal\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.heal(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/damage\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.damage_character(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/death-saves\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.death_save(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/status\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.character_status(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/owner\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.character_owner(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/claim\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.claim_character(match[1], match[2], actor)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/transfer\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.transfer_character(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/build\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.build_character(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/level-up\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.level_up(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/skill-check\z}.match(path))
      with_auth(request, %w[player dm]) do |actor|
        tag, data = PlayCampaigns.skill_check(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.add_spell(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_spells(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.prepare_spells(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_prepared_spells(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.cast_spell(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_casts(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.set_concentration(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_concentration(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration/advance-turn\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.advance_concentration(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'DELETE' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.clear_concentration(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.add_inventory_item(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_inventory_items(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'DELETE' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.remove_inventory_item(match[1], match[2], match[3], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)/consume\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.consume_item(match[1], match[2], match[3], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.equip_item(match[1], match[2], actor, match[3], payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_equipment(match[1], match[2], actor, match[3])
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.attune_equipment(match[1], match[2], actor, match[3])
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_currency(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency/transfers\z}.match(path))
      with_auth(request, %w[player dm]) do |actor|
        tag, data = PlayCampaigns.transfer_currency(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/transactional-transfers\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.create_transactional_transfer(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/transactional-transfers\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_transactional_transfers(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/loot\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_loot(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/loot/([^/]+)/votes\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.vote_loot(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/loot/([^/]+)/assign\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.assign_loot(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/loot/([^/]+)\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_loot(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/npcs\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_npc(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)/agenda\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.update_npc_agenda(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_npc(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_dialogue(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_dialogue(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/factions\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_faction(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.change_reputation(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_reputation(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/relationships\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_relationship(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/relationships/([^/]+)/([^/]+)/([^/]+)\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.update_relationship(match[1], match[2], match[3], match[4], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/relationships\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_relationships(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/clues\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_clue(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/clues\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_clues(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/quests\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_quest(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/quests/([^/]+)/state\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.update_quest_state(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/quests\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_quests(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.configure_quest_rewards(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards/award\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.award_quest_rewards(match[1], match[2], actor)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/rewards\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_character_rewards(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/rewards\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.award_rewards(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/close\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.close_encounter(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/end\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.end_encounter(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/world-events\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.schedule_world_event(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/world-events/([^/]+)/resolve\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.resolve_world_event(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/world-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_world_events(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/calendar\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.initialize_calendar(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/calendar\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_calendar(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/calendar/advance\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.advance_calendar(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_settlement(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.update_settlement(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/discover\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.discover_settlement(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_settlements(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_shop(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_shop(match[1], match[2], match[3], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/buy\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.buy(match[1], match[2], match[3], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/sell\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.sell(match[1], match[2], match[3], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/recipes\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_recipe(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/recipes\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_recipes(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/recipes/([^/]+)/craft\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.craft_recipe(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/downtime/activities\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_downtime_activity(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.allocate_downtime(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)/progress\z}.match(path))
      with_auth(request, %w[player]) do |actor|
        tag, data = PlayCampaigns.progress_downtime(match[1], match[2], match[3], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_allocation(match[1], match[2], match[3], actor)
        handle_result(tag, data, status: 200)
      end

    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/search-records\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_search_record(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/search-records\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_search_records(match[1], actor, request.query_params)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/rate-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.create_rate_event(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/rate-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_rate_events(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/metrics\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_metrics(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/service-mode\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        maintenance = payload['maintenance']
        if maintenance != true && maintenance != false
          next error_response(400)
        end

        tag, data = PlayCampaigns.service_mode(match[1], actor, maintenance)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/backups\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.create_backup(match[1], actor)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/backups\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.list_backups(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/backups/([^/]+)/restore\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.restore_backup(match[1], match[2], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/replay-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.append_replay_event(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/replay\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_replay(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/replay/check\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.check_replay(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/rng-seed\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.set_rng_seed(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/rng-rolls\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.append_rng_roll(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/rng-ledger\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_rng_ledger(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/moderation/reports\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.submit_moderation_report(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/moderation/reports\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_moderation_reports(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/moderation/reports/([^/]+)/resolution\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.resolve_moderation_report(match[1], match[2], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'PUT' && (match = %r{\A/v1/play/campaigns/([^/]+)/safety-boundaries\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.set_safety_boundaries(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/safety-boundaries\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_safety_boundaries(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/safety-checks\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.submit_safety_check(match[1], actor, payload)
        handle_result(tag, data, status: 201)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/safety-events\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.list_safety_events(match[1], actor)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'POST' && (match = %r{\A/v1/play/campaigns/([^/]+)/fixture-seeds\z}.match(path))
      with_auth(request, %w[dm]) do |actor|
        tag, data = PlayCampaigns.seed_fixture(match[1], actor, payload)
        handle_result(tag, data, status: 200)
      end
    elsif method == 'GET' && (match = %r{\A/v1/play/campaigns/([^/]+)/fixture-state\z}.match(path))
      with_auth(request, %w[dm player]) do |actor|
        tag, data = PlayCampaigns.get_fixture_state(match[1], actor)
        handle_result(tag, data, status: 200)
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

  # Authenticates a spectator bearer token. Session tokens (DM/player) are
  # rejected with 403; missing or malformed tokens are rejected with 401.
  # A well-shaped spectator token yields the spectator_id to the block.
  def self.with_spectator_auth(request)
    header = request.headers['authorization']
    return error_response(401) unless header.is_a?(String) && header.start_with?('Bearer ')

    token = header.sub('Bearer ', '').strip
    return error_response(403) if token.start_with?('session-')
    return error_response(401) unless token.start_with?('spectator-')

    spectator_id = token.sub('spectator-', '').force_encoding(Encoding::UTF_8)
    return error_response(401) if spectator_id.empty?

    yield spectator_id
  end
  private_class_method :with_spectator_auth

  def self.handle_result(tag, data, status:)
    case tag
    when :ok
      json_response(status, data)
    when :created
      json_response(201, data)
    when :invalid
      bad_request
    when :not_found
      not_found
    when :conflict
      data ? json_response(409, data) : error_response(409)
    when :rate_limited
      json_response(429, data || { 'error' => 'rate limited' })
    when :forbidden
      error_response(403)
    when :unauthorized
      error_response(401)
    when :server_error
      json_response(500, data || { 'error' => 'internal server error' })
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

  def self.api_schema
    {
      'version' => '2026-07-29',
      'endpoints' => [
        { 'method' => 'GET', 'path' => '/v1/play/campaigns/{id}/rng-ledger', 'auth' => 'member' },
        { 'method' => 'GET', 'path' => '/v1/schema', 'auth' => 'public' },
        { 'method' => 'POST', 'path' => '/v1/play/campaigns', 'auth' => 'dm' },
        { 'method' => 'POST', 'path' => '/v1/play/campaigns/{id}/fixture-seeds', 'auth' => 'dm' },
        { 'method' => 'POST', 'path' => '/v1/play/campaigns/{id}/members', 'auth' => 'member' },
        { 'method' => 'POST', 'path' => '/v1/play/campaigns/{id}/moderation/reports', 'auth' => 'member' },
        { 'method' => 'POST', 'path' => '/v1/play/campaigns/{id}/rng-rolls', 'auth' => 'member' },
        { 'method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', 'auth' => 'dm' },
        { 'method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/rng-seed', 'auth' => 'dm' },
        { 'method' => 'PUT', 'path' => '/v1/play/campaigns/{id}/safety-boundaries', 'auth' => 'dm' }
      ]
    }
  end
  private_class_method :api_schema
end

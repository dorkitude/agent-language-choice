# frozen_string_literal: true

require_relative '../errors'
require_relative '../game_rules'
require_relative '../service_state'

module Handlers
  # Stateless dice/check/encounter math that doesn't belong to a specific
  # domain (auth, combat, compendium, ...). Every method takes the parsed
  # JSON request body and returns [http_status, response_hash].
  module Core
    DICE_EXPRESSION_PATTERN = /\A(\d+)d(\d+)([+-]\d+)?\z/

    module_function

    def health(_body)
      [200, { ok: true }]
    end

    # Public liveness probe: always 200, unaffected by maintenance mode.
    def healthz(_body)
      [200, { status: 'ok' }]
    end

    # Public readiness probe: 503 while the process-global maintenance
    # switch (see ServiceState) is on, 200 otherwise.
    def readyz(_body)
      if ServiceState.maintenance?
        [503, { status: 'maintenance', schema_version: 2 }]
      else
        [200, { status: 'ready', schema_version: 2 }]
      end
    end

    # Public API schema: static, sorted list of the play/schema endpoints.
    # No dynamic state and no dependence on hash/map ordering.
    SCHEMA_VERSION = '2026-07-29'
    SCHEMA_ENDPOINTS = [
      { method: 'GET', path: '/v1/play/campaigns/{id}/rng-ledger', auth: 'member' },
      { method: 'GET', path: '/v1/schema', auth: 'public' },
      { method: 'POST', path: '/v1/play/campaigns', auth: 'dm' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/fixture-seeds', auth: 'dm' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/members', auth: 'member' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/moderation/reports', auth: 'member' },
      { method: 'POST', path: '/v1/play/campaigns/{id}/rng-rolls', auth: 'member' },
      { method: 'PUT', path: '/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution', auth: 'dm' },
      { method: 'PUT', path: '/v1/play/campaigns/{id}/rng-seed', auth: 'dm' },
      { method: 'PUT', path: '/v1/play/campaigns/{id}/safety-boundaries', auth: 'dm' }
    ].freeze

    def schema(_body)
      [200, { version: SCHEMA_VERSION, endpoints: SCHEMA_ENDPOINTS }]
    end

    def dice_stats(body)
      count, sides, modifier = parse_dice_expression(body['expression'])

      min = count * 1 + modifier
      max = count * sides + modifier
      average = GameRules.numeric_json((count * (sides + 1) / 2.0) + modifier)

      [200, {
        dice_count: count,
        sides: sides,
        modifier: modifier,
        min: min,
        max: max,
        average: average
      }]
    end

    def ability_check(body)
      roll = body['roll']
      modifier = body['modifier']
      dc = body['dc']

      raise HttpError.new(400, 'roll must be numeric') unless roll.is_a?(Numeric)
      raise HttpError.new(400, 'modifier must be numeric') unless modifier.is_a?(Numeric)
      raise HttpError.new(400, 'dc must be numeric') unless dc.is_a?(Numeric)

      total = roll + modifier

      [200, {
        total: GameRules.numeric_json(total),
        success: total >= dc,
        margin: GameRules.numeric_json(total - dc)
      }]
    end

    def adjusted_xp(body)
      party = body['party']
      monsters = body['monsters']

      raise HttpError.new(400, 'party must be an array') unless party.is_a?(Array)
      raise HttpError.new(400, 'monsters must be an array') unless monsters.is_a?(Array)

      base_xp = 0
      monster_count = 0

      monsters.each do |monster|
        cr = monster['cr'].to_s
        count = monster['count']
        raise HttpError.new(400, 'count must be a positive integer') unless count.is_a?(Integer) && count.positive?

        xp = GameRules.xp_for_cr(cr)
        raise HttpError.new(400, "unsupported cr: #{cr}") unless xp

        base_xp += xp * count
        monster_count += count
      end

      multiplier = GameRules.multiplier_for(monster_count)
      total = GameRules.numeric_json(base_xp * multiplier)
      thresholds = GameRules.party_thresholds(party)

      [200, {
        base_xp: GameRules.numeric_json(base_xp),
        monster_count: monster_count,
        multiplier: GameRules.numeric_json(multiplier),
        adjusted_xp: total,
        difficulty: GameRules.difficulty_for(total, thresholds),
        thresholds: thresholds
      }]
    end

    def initiative_order(body)
      combatants = body['combatants']
      raise HttpError.new(400, 'combatants must be an array') unless combatants.is_a?(Array)

      scored = combatants.map do |combatant|
        name = combatant['name']
        dex = combatant['dex']
        roll = combatant['roll']

        raise HttpError.new(400, 'name must be a string') unless name.is_a?(String)
        raise HttpError.new(400, 'dex must be numeric') unless dex.is_a?(Numeric)
        raise HttpError.new(400, 'roll must be numeric') unless roll.is_a?(Numeric)

        { name: name, dex: dex, score: GameRules.numeric_json(roll + dex) }
      end

      ordered = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }

      [200, { order: ordered.map { |c| { name: c[:name], score: c[:score] } } }]
    end

    # Parses a "NdM+K" style dice expression (e.g. "2d6+3") into its
    # [count, sides, modifier] components.
    def parse_dice_expression(expression)
      raise HttpError.new(400, 'expression must be a string') unless expression.is_a?(String)

      match = DICE_EXPRESSION_PATTERN.match(expression.strip)
      raise HttpError.new(400, 'invalid dice expression') unless match

      count = match[1].to_i
      sides = match[2].to_i
      modifier = match[3] ? match[3].to_i : 0

      raise HttpError.new(400, 'count must be positive') unless count.positive?
      raise HttpError.new(400, 'sides must be positive') unless sides.positive?

      [count, sides, modifier]
    end
    private_class_method :parse_dice_expression
  end
end

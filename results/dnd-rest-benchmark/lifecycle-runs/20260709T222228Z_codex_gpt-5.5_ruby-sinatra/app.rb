require 'json'
require 'puma'
require 'sinatra/base'

class DndRestApi < Sinatra::Base
  CR_XP = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1_100,
    '5' => 1_800
  }.freeze

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  ABILITY_NAMES = %w[str dex con int wis cha].freeze
  COMBAT_SESSIONS = {}

  configure do
    set :bind, '127.0.0.1'
    set :server, :puma
  end

  before do
    content_type :json
  end

  get '/health' do
    json(ok: true)
  end

  post '/v1/dice/stats' do
    body = json_body
    match = body['expression'].to_s.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/)
    halt_json(400, error: 'invalid expression') unless match

    count = match[1].to_i
    sides = match[2].to_i
    halt_json(400, error: 'invalid expression') unless count.positive? && sides.positive?

    modifier = match[4].to_i
    modifier *= -1 if match[3] == '-'

    json(
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: count + modifier,
      max: (count * sides) + modifier,
      average: number_for_json((count * (sides + 1) / 2.0) + modifier)
    )
  end

  post '/v1/checks/ability' do
    body = json_body
    roll = integer_field(body, 'roll')
    modifier = integer_field(body, 'modifier')
    dc = integer_field(body, 'dc')

    total = roll + modifier
    json(total: total, success: total >= dc, margin: total - dc)
  end

  post '/v1/encounters/adjusted-xp' do
    body = json_body
    party = array_field(body, 'party')
    monsters = array_field(body, 'monsters')

    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      halt_json(400, error: 'invalid monster') unless monster.is_a?(Hash)

      cr = monster['cr'].to_s
      count = integer_field(monster, 'count')
      xp = CR_XP[cr]
      halt_json(400, error: 'unsupported challenge rating') unless xp && count.positive?

      base_xp += xp * count
      monster_count += count
    end

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      halt_json(400, error: 'invalid party member') unless member.is_a?(Hash)

      level = integer_field(member, 'level')
      member_thresholds = LEVEL_THRESHOLDS[level]
      halt_json(400, error: 'unsupported level') unless member_thresholds

      thresholds.each_key do |key|
        thresholds[key] += member_thresholds[key]
      end
    end

    multiplier = encounter_multiplier(monster_count)
    adjusted_xp = base_xp * multiplier

    json(
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: number_for_json(multiplier),
      adjusted_xp: number_for_json(adjusted_xp),
      difficulty: difficulty(adjusted_xp, thresholds),
      thresholds: thresholds
    )
  end

  post '/v1/initiative/order' do
    body = json_body
    combatants = array_field(body, 'combatants')
    json(order: initiative_order(combatants))
  end

  post '/v1/characters/ability-modifier' do
    body = json_body
    score = ability_score(body, 'score')

    json(score: score, modifier: ability_modifier(score))
  end

  post '/v1/characters/proficiency' do
    body = json_body
    level = character_level(body)

    json(level: level, proficiency_bonus: proficiency_bonus(level))
  end

  post '/v1/characters/derived-stats' do
    body = json_body
    level = character_level(body)
    abilities = hash_field(body, 'abilities')
    armor = hash_field(body, 'armor')

    modifiers = {}
    ABILITY_NAMES.each do |name|
      modifiers[name.to_sym] = ability_modifier(ability_score(abilities, name))
    end

    armor_base = integer_field(armor, 'base')
    dex_cap = integer_field(armor, 'dex_cap')
    shield = armor['shield']
    halt_json(400, error: 'invalid shield') unless [true, false].include?(shield)

    shield_bonus = shield ? 2 : 0
    armor_class = armor_base + [modifiers[:dex], dex_cap].min + shield_bonus
    hp_max = level * (6 + modifiers[:con])

    json(
      level: level,
      proficiency_bonus: proficiency_bonus(level),
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    )
  end

  post '/v1/combat/sessions' do
    body = json_body
    id = body['id'].to_s
    halt_json(400, error: 'invalid id') if id.empty? || COMBAT_SESSIONS.key?(id)

    order = initiative_order(array_field(body, 'combatants'))
    halt_json(400, error: 'invalid combatants') if order.empty?

    conditions = {}
    order.each { |combatant| conditions[combatant[:name]] = [] }

    session = {
      id: id,
      round: 1,
      turn_index: 0,
      order: order,
      conditions: conditions,
      condition_targets: {}
    }
    COMBAT_SESSIONS[id] = session

    json(combat_session_payload(session, include_conditions: false))
  end

  post '/v1/combat/sessions/:id/conditions' do |id|
    session = combat_session(id)
    body = json_body
    target = body['target'].to_s
    condition = body['condition'].to_s
    duration = integer_field(body, 'duration_rounds')

    halt_json(400, error: 'invalid target') unless session[:conditions].key?(target)
    halt_json(400, error: 'invalid condition') if condition.empty?
    halt_json(400, error: 'invalid duration_rounds') unless duration.positive?

    session[:conditions][target] << { condition: condition, remaining_rounds: duration }
    session[:condition_targets][target] = true

    json(target: target, conditions: session[:conditions][target])
  end

  post '/v1/combat/sessions/:id/advance' do |id|
    session = combat_session(id)
    session[:turn_index] += 1
    if session[:turn_index] >= session[:order].length
      session[:turn_index] = 0
      session[:round] += 1
    end

    active_name = session[:order][session[:turn_index]][:name]
    session[:conditions][active_name].each do |condition|
      condition[:remaining_rounds] -= 1
    end
    session[:conditions][active_name].reject! { |condition| condition[:remaining_rounds] <= 0 }

    json(combat_session_payload(session, include_conditions: true))
  end

  not_found do
    halt_json(404, error: 'not found')
  end

  error JSON::ParserError do
    halt_json(400, error: 'invalid json')
  end

  helpers do
    def json(payload)
      JSON.generate(payload)
    end

    def json_body
      raw = request.body.read
      halt_json(400, error: 'invalid json') if raw.empty?

      parsed = JSON.parse(raw)
      halt_json(400, error: 'invalid json') unless parsed.is_a?(Hash)

      parsed
    end

    def integer_field(body, name)
      value = body[name]
      halt_json(400, error: "invalid #{name}") unless value.is_a?(Integer)

      value
    end

    def array_field(body, name)
      value = body[name]
      halt_json(400, error: "invalid #{name}") unless value.is_a?(Array)

      value
    end

    def hash_field(body, name)
      value = body[name]
      halt_json(400, error: "invalid #{name}") unless value.is_a?(Hash)

      value
    end

    def initiative_order(combatants)
      combatants.map do |combatant|
        halt_json(400, error: 'invalid combatant') unless combatant.is_a?(Hash)

        name = combatant['name'].to_s
        dex = integer_field(combatant, 'dex')
        roll = integer_field(combatant, 'roll')
        halt_json(400, error: 'invalid combatant') if name.empty?

        { name: name, dex: dex, score: roll + dex }
      end
                .sort_by { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }
                .map { |combatant| { name: combatant[:name], score: combatant[:score] } }
    end

    def character_level(body)
      level = integer_field(body, 'level')
      halt_json(400, error: 'invalid level') unless (1..20).cover?(level)

      level
    end

    def ability_score(body, name)
      score = integer_field(body, name)
      halt_json(400, error: "invalid #{name}") unless (1..30).cover?(score)

      score
    end

    def ability_modifier(score)
      ((score - 10) / 2.0).floor
    end

    def proficiency_bonus(level)
      2 + ((level - 1) / 4)
    end

    def encounter_multiplier(monster_count)
      case monster_count
      when 0 then 1
      when 1 then 1
      when 2 then 1.5
      when 3..6 then 2
      when 7..10 then 2.5
      when 11..14 then 3
      else 4
      end
    end

    def difficulty(adjusted_xp, thresholds)
      return 'deadly' if adjusted_xp >= thresholds[:deadly]
      return 'hard' if adjusted_xp >= thresholds[:hard]
      return 'medium' if adjusted_xp >= thresholds[:medium]
      return 'easy' if adjusted_xp >= thresholds[:easy]

      'trivial'
    end

    def number_for_json(number)
      number.to_i == number ? number.to_i : number
    end

    def combat_session(id)
      COMBAT_SESSIONS.fetch(id) { halt_json(404, error: 'unknown session') }
    end

    def combat_session_payload(session, include_conditions:)
      active = session[:order][session[:turn_index]]
      payload = {
        id: session[:id],
        round: session[:round],
        turn_index: session[:turn_index],
        active: active
      }

      if include_conditions
        payload[:conditions] = session[:conditions].each_with_object({}) do |(name, conditions), result|
          result[name] = conditions if !conditions.empty? || session.fetch(:condition_targets, {}).key?(name)
        end
      else
        payload[:order] = session[:order]
      end

      payload
    end

    def halt_json(status, payload)
      halt status, json(payload)
    end
  end

  def self.start_puma!
    port = Integer(ENV.fetch('PORT', '4567'), 10)
    server = Puma::Server.new(self)
    server.add_tcp_listener('127.0.0.1', port)

    %w[INT TERM].each do |signal|
      Signal.trap(signal) { server.stop(true) }
    end

    server.run
    server.thread.join
  end

  start_puma! if app_file == $PROGRAM_NAME
end

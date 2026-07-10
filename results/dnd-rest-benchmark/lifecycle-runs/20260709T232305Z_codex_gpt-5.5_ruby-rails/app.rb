require "rails"
require "action_controller/railtie"

class DndRestApplication < Rails::Application
  config.load_defaults 8.1
  config.api_only = true
  config.eager_load = false
  config.hosts.clear
  config.secret_key_base = "benchmark-secret-key-base"
end

class ApplicationController < ActionController::API
  private

  def body_params
    request.request_parameters
  end

  def bad_request(message = "bad request")
    render json: { error: message }, status: :bad_request
  end

  def whole_number(value)
    value.is_a?(Float) && value.finite? && value == value.to_i ? value.to_i : value
  end

  def integer_in_range(value, range)
    return value if value.is_a?(Integer) && range.cover?(value)

    nil
  end

  def integer_value(value)
    value if value.is_a?(Integer)
  end
end

class HealthController < ApplicationController
  def show
    render json: { ok: true }
  end
end

class DiceController < ApplicationController
  DICE_PATTERN = /\A([1-9]\d*)d([1-9]\d*)(?:([+-])(\d+))?\z/

  def stats
    expression = body_params["expression"]
    match = expression.is_a?(String) ? expression.match(DICE_PATTERN) : nil
    return bad_request("invalid dice expression") unless match

    dice_count = match[1].to_i
    sides = match[2].to_i
    modifier = match[4] ? match[4].to_i : 0
    modifier = -modifier if match[3] == "-"

    render json: {
      dice_count: dice_count,
      sides: sides,
      modifier: modifier,
      min: dice_count + modifier,
      max: dice_count * sides + modifier,
      average: (dice_count * (sides + 1) / 2.0) + modifier
    }.transform_values { |value| whole_number(value) }
  end
end

class ChecksController < ApplicationController
  def ability
    roll = body_params["roll"].to_i
    modifier = body_params["modifier"].to_i
    dc = body_params["dc"].to_i
    total = roll + modifier

    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end
end

class EncountersController < ApplicationController
  MONSTER_XP = {
    "0" => 10,
    "1/8" => 25,
    "1/4" => 50,
    "1/2" => 100,
    "1" => 200,
    "2" => 450,
    "3" => 700,
    "4" => 1_100,
    "5" => 1_800
  }.freeze

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  def adjusted_xp
    party = Array(body_params["party"])
    monsters = Array(body_params["monsters"])

    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      cr = monster["cr"].to_s
      count = monster["count"].to_i
      xp = MONSTER_XP[cr]
      return bad_request("unsupported challenge rating") unless xp && count.positive?

      base_xp += xp * count
      monster_count += count
    end

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      member_thresholds = LEVEL_THRESHOLDS[member["level"].to_i]
      return bad_request("unsupported character level") unless member_thresholds

      thresholds.each_key { |key| thresholds[key] += member_thresholds[key] }
    end

    multiplier = multiplier_for(monster_count)
    adjusted = base_xp * multiplier

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: whole_number(adjusted),
      difficulty: difficulty_for(adjusted, thresholds),
      thresholds: thresholds
    }
  end

  private

  def multiplier_for(count)
    case count
    when 0 then 0
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def difficulty_for(adjusted, thresholds)
    return "deadly" if adjusted >= thresholds[:deadly]
    return "hard" if adjusted >= thresholds[:hard]
    return "medium" if adjusted >= thresholds[:medium]
    return "easy" if adjusted >= thresholds[:easy]

    "trivial"
  end
end

class InitiativeController < ApplicationController
  def order
    combatants = Array(body_params["combatants"])
    order = combatants
      .map do |combatant|
        name = combatant["name"].to_s
        dex = combatant["dex"].to_i
        roll = combatant["roll"].to_i
        { name: name, dex: dex, score: roll + dex }
      end
      .sort_by { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }
      .map { |combatant| { name: combatant[:name], score: combatant[:score] } }

    render json: { order: order }
  end
end

class CombatSessionsController < ApplicationController
  SESSIONS = {}
  LOCK = Mutex.new

  def create
    id = body_params["id"]
    combatants = body_params["combatants"]
    return bad_request("invalid session id") unless id.is_a?(String) && !id.empty?
    return bad_request("invalid combatants") unless combatants.is_a?(Array) && !combatants.empty?

    order = combatants.map do |combatant|
      return bad_request("invalid combatant") unless combatant.is_a?(Hash)

      name = combatant["name"]
      dex = combatant["dex"]
      roll = combatant["roll"]
      return bad_request("invalid combatant") unless name.is_a?(String) && !name.empty?
      return bad_request("invalid combatant") unless dex.is_a?(Integer) && roll.is_a?(Integer)

      { name: name, dex: dex, score: roll + dex }
    end

    order.sort_by! { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }
    session = {
      id: id,
      round: 1,
      turn_index: 0,
      order: order.map { |combatant| { name: combatant[:name], score: combatant[:score] } },
      conditions: Hash.new { |hash, key| hash[key] = [] }
    }

    LOCK.synchronize do
      return bad_request("session already exists") if SESSIONS.key?(id)

      SESSIONS[id] = session
    end

    render json: session_response(session, include_order: true)
  end

  def add_condition
    session = find_session
    return unless session

    target = body_params["target"]
    condition = body_params["condition"]
    duration_rounds = body_params["duration_rounds"]
    return bad_request("invalid target") unless target.is_a?(String)
    return bad_request("unknown combatant") unless session[:order].any? { |combatant| combatant[:name] == target }
    return bad_request("invalid condition") unless condition.is_a?(String)
    return bad_request("invalid duration_rounds") unless duration_rounds.is_a?(Integer) && duration_rounds.positive?

    conditions = nil
    LOCK.synchronize do
      session[:conditions][target] << { condition: condition, remaining_rounds: duration_rounds }
      conditions = session[:conditions][target].map(&:dup)
    end

    render json: { target: target, conditions: conditions }
  end

  def advance
    session = find_session
    return unless session

    LOCK.synchronize do
      session[:turn_index] += 1
      if session[:turn_index] >= session[:order].length
        session[:turn_index] = 0
        session[:round] += 1
      end

      active_name = active_combatant(session)[:name]
      if session[:conditions].key?(active_name)
        session[:conditions][active_name].each { |condition| condition[:remaining_rounds] -= 1 }
        session[:conditions][active_name].reject! { |condition| condition[:remaining_rounds] <= 0 }
      end
    end

    render json: session_response(session).merge(conditions: conditions_response(session))
  end

  private

  def find_session
    session = nil
    LOCK.synchronize { session = SESSIONS[params[:id]] }
    return session if session

    render json: { error: "session not found" }, status: :not_found
    nil
  end

  def active_combatant(session)
    session[:order][session[:turn_index]]
  end

  def session_response(session, include_order: false)
    active = active_combatant(session)
    response = {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] }
    }
    response[:order] = session[:order].map(&:dup) if include_order
    response
  end

  def conditions_response(session)
    session[:conditions].each_with_object({}) do |(target, conditions), result|
      result[target] = conditions.map(&:dup)
    end
  end
end

class CharactersController < ApplicationController
  ABILITIES = %w[str dex con int wis cha].freeze

  def ability_modifier
    score = valid_ability_score(body_params["score"])
    return bad_request("invalid ability score") unless score

    render json: { score: score, modifier: ability_modifier_for(score) }
  end

  def proficiency
    level = valid_level(body_params["level"])
    return bad_request("invalid character level") unless level

    render json: { level: level, proficiency_bonus: proficiency_bonus_for(level) }
  end

  def derived_stats
    level = valid_level(body_params["level"])
    abilities = body_params["abilities"]
    armor = body_params["armor"]
    return bad_request("invalid character level") unless level
    return bad_request("invalid abilities") unless abilities.is_a?(Hash)
    return bad_request("invalid armor") unless armor.is_a?(Hash)

    modifiers = {}
    ABILITIES.each do |ability|
      score = valid_ability_score(abilities[ability])
      return bad_request("invalid abilities") unless score

      modifiers[ability] = ability_modifier_for(score)
    end

    armor_base = integer_value(armor["base"])
    dex_cap = integer_value(armor["dex_cap"])
    shield = armor["shield"]
    return bad_request("invalid armor") unless armor_base && dex_cap && [true, false].include?(shield)

    proficiency_bonus = proficiency_bonus_for(level)
    hp_max = level * (6 + modifiers["con"])
    armor_class = armor_base + [modifiers["dex"], dex_cap].min + (shield ? 2 : 0)

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus,
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    }
  end

  private

  def valid_ability_score(value)
    integer_in_range(value, 1..30)
  end

  def valid_level(value)
    integer_in_range(value, 1..20)
  end

  def ability_modifier_for(score)
    ((score - 10) / 2.0).floor
  end

  def proficiency_bonus_for(level)
    ((level - 1) / 4) + 2
  end
end

DndRestApplication.initialize!

Rails.application.routes.draw do
  get "/health", to: "health#show"
  post "/v1/dice/stats", to: "dice#stats"
  post "/v1/checks/ability", to: "checks#ability"
  post "/v1/encounters/adjusted-xp", to: "encounters#adjusted_xp"
  post "/v1/initiative/order", to: "initiative#order"
  post "/v1/combat/sessions", to: "combat_sessions#create"
  post "/v1/combat/sessions/:id/conditions", to: "combat_sessions#add_condition"
  post "/v1/combat/sessions/:id/advance", to: "combat_sessions#advance"
  post "/v1/characters/ability-modifier", to: "characters#ability_modifier"
  post "/v1/characters/proficiency", to: "characters#proficiency"
  post "/v1/characters/derived-stats", to: "characters#derived_stats"
end

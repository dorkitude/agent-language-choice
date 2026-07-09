require "action_controller/railtie"

class DndRestApp < Rails::Application
  config.load_defaults 8.1
  config.api_only = true
  config.eager_load = false
  config.secret_key_base = "benchmark-secret-key-base"
  config.hosts.clear

  routes.append do
    get "/health", to: "dnd#health"
    post "/v1/dice/stats", to: "dnd#dice_stats"
    post "/v1/checks/ability", to: "dnd#ability_check"
    post "/v1/encounters/adjusted-xp", to: "dnd#adjusted_xp"
    post "/v1/initiative/order", to: "dnd#initiative_order"
  end
end

class DndController < ActionController::API
  rescue_from ActionController::ParameterMissing, ArgumentError, KeyError do
    render json: { error: "bad request" }, status: :bad_request
  end

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

  def health
    render json: { ok: true }
  end

  def dice_stats
    expression = params.require(:expression).to_s
    match = /\A([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?\z/.match(expression)
    raise ArgumentError unless match

    dice_count = Integer(match[1], 10)
    sides = Integer(match[2], 10)
    raise ArgumentError unless dice_count.positive? && sides.positive?

    modifier = match[4] ? Integer(match[4], 10) : 0
    modifier = -modifier if match[3] == "-"

    average = (dice_count * (sides + 1) / 2.0) + modifier
    average = average.to_i if average == average.to_i

    render json: {
      dice_count: dice_count,
      sides: sides,
      modifier: modifier,
      min: dice_count + modifier,
      max: (dice_count * sides) + modifier,
      average: average
    }
  end

  def ability_check
    roll = int_param(:roll)
    modifier = int_param(:modifier)
    dc = int_param(:dc)
    total = roll + modifier

    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end

  def adjusted_xp
    party = params.require(:party)
    monsters = params.require(:monsters)
    raise ArgumentError unless party.is_a?(Array) && monsters.is_a?(Array)

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      member_thresholds = LEVEL_THRESHOLDS.fetch(parse_integer(fetch_value(member, :level)))
      thresholds.each_key { |key| thresholds[key] += member_thresholds.fetch(key) }
    end

    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      count = parse_integer(fetch_value(monster, :count))
      raise ArgumentError if count.negative?

      base_xp += MONSTER_XP.fetch(fetch_value(monster, :cr).to_s) * count
      monster_count += count
    end

    multiplier = encounter_multiplier(monster_count)
    adjusted_xp = base_xp * multiplier
    difficulty = encounter_difficulty(adjusted_xp, thresholds)

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      thresholds: thresholds
    }
  end

  def initiative_order
    combatants = params.require(:combatants)
    raise ArgumentError unless combatants.is_a?(Array)

    order = combatants.map do |combatant|
      name = fetch_value(combatant, :name).to_s
      dex = parse_integer(fetch_value(combatant, :dex))
      roll = parse_integer(fetch_value(combatant, :roll))
      { name: name, dex: dex, score: roll + dex }
    end

    order.sort_by! { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }

    render json: {
      order: order.map { |combatant| { name: combatant[:name], score: combatant[:score] } }
    }
  end

  private

  def int_param(name)
    parse_integer(params.require(name))
  end

  def fetch_value(object, key)
    object.fetch(key)
  rescue KeyError
    object.fetch(key.to_s)
  end

  def parse_integer(value)
    value.is_a?(String) ? Integer(value, 10) : Integer(value)
  end

  def encounter_multiplier(monster_count)
    case monster_count
    when 0..1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def encounter_difficulty(adjusted_xp, thresholds)
    if adjusted_xp >= thresholds[:deadly]
      "deadly"
    elsif adjusted_xp >= thresholds[:hard]
      "hard"
    elsif adjusted_xp >= thresholds[:medium]
      "medium"
    elsif adjusted_xp >= thresholds[:easy]
      "easy"
    else
      "trivial"
    end
  end
end

DndRestApp.initialize!

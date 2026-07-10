require 'rails'
require 'action_controller/railtie'
require 'json'

class App < Rails::Application
  config.eager_load = false
  config.consider_all_requests_local = true
  config.secret_key_base = 'benchmark-secret-key-base'
  config.hosts.clear
  config.logger = Logger.new($stdout)
  config.log_level = :warn

  routes.append do
    get  '/health',                  to: 'main#health'
    post '/v1/dice/stats',           to: 'main#dice_stats'
    post '/v1/checks/ability',       to: 'main#ability_check'
    post '/v1/encounters/adjusted-xp', to: 'main#adjusted_xp'
    post '/v1/initiative/order',     to: 'main#initiative_order'
    post '/v1/characters/ability-modifier', to: 'main#ability_modifier'
    post '/v1/characters/proficiency',       to: 'main#proficiency'
    post '/v1/characters/derived-stats',     to: 'main#derived_stats'
    post '/v1/combat/sessions',              to: 'main#create_combat_session'
    post '/v1/combat/sessions/:id/conditions', to: 'main#add_condition'
    post '/v1/combat/sessions/:id/advance',    to: 'main#advance_turn'
  end
end

App.initialize!

class MainController < ActionController::API
  CR_XP = {
    '0' => 10, '1/8' => 25, '1/4' => 50, '1/2' => 100,
    '1' => 200, '2' => 450, '3' => 700, '4' => 1100, '5' => 1800
  }.freeze

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  def health
    render json: { ok: true }
  end

  def dice_stats
    expr = params[:expression].to_s
    m = expr.match(/\A(\d+)d(\d+)([+-]\d+)?\z/)
    return head(:bad_request) unless m

    count = m[1].to_i
    sides = m[2].to_i
    modifier = m[3] ? m[3].to_i : 0
    return head(:bad_request) unless count.positive? && sides.positive?

    min = count + modifier
    max = count * sides + modifier
    average = count * (sides + 1) / 2.0 + modifier
    average = average.to_i if average == average.to_i

    render json: {
      dice_count: count, sides: sides, modifier: modifier,
      min: min, max: max, average: average
    }
  end

  def ability_check
    roll = params[:roll].to_i
    modifier = params[:modifier].to_i
    dc = params[:dc].to_i
    total = roll + modifier
    render json: { total: total, success: total >= dc, margin: total - dc }
  end

  def adjusted_xp
    party = params[:party] || []
    monsters = params[:monsters] || []

    base_xp = monsters.sum do |mon|
      xp = CR_XP[mon[:cr].to_s]
      count = mon[:count].to_i
      xp ? xp * count : 0
    end

    monster_count = monsters.sum { |mon| mon[:count].to_i }
    multiplier = count_multiplier(monster_count)
    adjusted = base_xp * multiplier
    adjusted = adjusted.to_i if adjusted == adjusted.to_i
    multiplier = multiplier.to_i if multiplier == multiplier.to_i

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      t = LEVEL_THRESHOLDS[member[:level].to_i]
      next unless t
      thresholds.each_key { |k| thresholds[k] += t[k] }
    end

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted,
      difficulty: difficulty_for(adjusted, thresholds),
      thresholds: thresholds
    }
  end

  def initiative_order
    combatants = params[:combatants] || []
    ordered = combatants.map do |c|
      { name: c[:name].to_s, dex: c[:dex].to_i, roll: c[:roll].to_i }
    end.sort_by.with_index { |c, i| [-(c[:roll] + c[:dex]), -c[:dex], c[:name], i] }

    render json: {
      order: ordered.map { |c| { name: c[:name], score: c[:roll] + c[:dex] } }
    }
  end

  def ability_modifier
    score = integer_param(params[:score])
    return head(:bad_request) unless score && score >= 1 && score <= 30

    render json: { score: score, modifier: ability_mod(score) }
  end

  def proficiency
    level = integer_param(params[:level])
    return head(:bad_request) unless level && level >= 1 && level <= 20

    render json: { level: level, proficiency_bonus: proficiency_bonus(level) }
  end

  def derived_stats
    level = integer_param(params[:level])
    return head(:bad_request) unless level && level >= 1 && level <= 20

    abilities = params[:abilities]
    armor = params[:armor]
    return head(:bad_request) unless abilities.is_a?(ActionController::Parameters) || abilities.is_a?(Hash)
    return head(:bad_request) unless armor.is_a?(ActionController::Parameters) || armor.is_a?(Hash)

    keys = %w[str dex con int wis cha]
    scores = {}
    keys.each do |k|
      s = integer_param(abilities[k])
      return head(:bad_request) unless s && s >= 1 && s <= 30
      scores[k] = s
    end

    modifiers = {}
    keys.each { |k| modifiers[k.to_sym] = ability_mod(scores[k]) }

    base = integer_param(armor[:base])
    dex_cap = integer_param(armor[:dex_cap])
    return head(:bad_request) unless base && dex_cap
    shield_bonus = armor[:shield] ? 2 : 0

    hp_max = level * (6 + modifiers[:con])
    armor_class = base + [modifiers[:dex], dex_cap].min + shield_bonus

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus(level),
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    }
  end

  COMBAT_SESSIONS = {}

  def create_combat_session
    id = params[:id]
    return head(:bad_request) unless id.is_a?(String) && !id.empty?
    return head(:bad_request) if COMBAT_SESSIONS.key?(id)

    combatants = params[:combatants]
    return head(:bad_request) unless combatants.is_a?(Array) && !combatants.empty?

    parsed = []
    combatants.each do |c|
      return head(:bad_request) unless c.is_a?(ActionController::Parameters) || c.is_a?(Hash)
      name = c[:name]
      dex = integer_param(c[:dex])
      roll = integer_param(c[:roll])
      return head(:bad_request) unless name.is_a?(String) && !name.empty? && dex && roll
      parsed << { name: name, dex: dex, roll: roll, score: roll + dex }
    end

    ordered = parsed.sort_by.with_index { |c, i| [-c[:score], -c[:dex], c[:name], i] }

    session = {
      id: id,
      round: 1,
      turn_index: 0,
      order: ordered,
      conditions: {}
    }
    COMBAT_SESSIONS[id] = session

    render json: combat_session_state(session)
  end

  def add_condition
    session = COMBAT_SESSIONS[params[:id]]
    return head(:not_found) unless session

    target = params[:target]
    condition = params[:condition]
    duration = integer_param(params[:duration_rounds])

    return head(:bad_request) unless target.is_a?(String)
    return head(:bad_request) unless session[:order].any? { |c| c[:name] == target }
    return head(:bad_request) unless condition.is_a?(String) && !condition.empty?
    return head(:bad_request) unless duration && duration.positive?

    (session[:conditions][target] ||= []) << { condition: condition, remaining_rounds: duration }

    render json: {
      target: target,
      conditions: session[:conditions][target].map do |cond|
        { condition: cond[:condition], remaining_rounds: cond[:remaining_rounds] }
      end
    }
  end

  def advance_turn
    session = COMBAT_SESSIONS[params[:id]]
    return head(:not_found) unless session

    order = session[:order]
    session[:turn_index] += 1
    if session[:turn_index] >= order.length
      session[:turn_index] = 0
      session[:round] += 1
    end

    active_name = order[session[:turn_index]][:name]
    conds = session[:conditions][active_name]
    if conds
      conds.each { |c| c[:remaining_rounds] -= 1 }
      conds.reject! { |c| c[:remaining_rounds] <= 0 }
    end

    active = order[session[:turn_index]]
    render json: {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      conditions: conditions_view(session)
    }
  end

  private

  def combat_session_state(session)
    active = session[:order][session[:turn_index]]
    {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      order: session[:order].map { |c| { name: c[:name], score: c[:score] } }
    }
  end

  def conditions_view(session)
    view = {}
    session[:order].each do |c|
      list = session[:conditions][c[:name]]
      next unless list
      view[c[:name]] = list.map do |cond|
        { condition: cond[:condition], remaining_rounds: cond[:remaining_rounds] }
      end
    end
    view
  end

  def ability_mod(score)
    (score - 10).fdiv(2).floor
  end

  def proficiency_bonus(level)
    2 + (level - 1) / 4
  end

  def integer_param(value)
    return value if value.is_a?(Integer)
    return nil unless value.is_a?(String) && value.match?(/\A-?\d+\z/)
    value.to_i
  end

  def count_multiplier(n)
    case n
    when 0 then 1
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def difficulty_for(adjusted, thresholds)
    if adjusted >= thresholds[:deadly] then 'deadly'
    elsif adjusted >= thresholds[:hard] then 'hard'
    elsif adjusted >= thresholds[:medium] then 'medium'
    elsif adjusted >= thresholds[:easy] then 'easy'
    else 'trivial'
    end
  end
end

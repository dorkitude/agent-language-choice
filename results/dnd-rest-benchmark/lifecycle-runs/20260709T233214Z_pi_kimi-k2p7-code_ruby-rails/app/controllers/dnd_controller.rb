require 'set'

class DndController < ActionController::API
  rescue_from ActionController::ParameterMissing, ArgumentError, TypeError do
    head :bad_request
  end

  XP_BY_CR = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800,
  }.freeze

  THRESHOLDS_BY_LEVEL = {
    1 => { easy: 25, medium: 50, hard: 75, deadly: 100 },
    2 => { easy: 50, medium: 100, hard: 150, deadly: 200 },
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 },
    4 => { easy: 125, medium: 250, hard: 375, deadly: 500 },
    5 => { easy: 250, medium: 500, hard: 750, deadly: 1100 },
    6 => { easy: 300, medium: 600, hard: 900, deadly: 1400 },
    7 => { easy: 350, medium: 750, hard: 1100, deadly: 1700 },
    8 => { easy: 450, medium: 900, hard: 1400, deadly: 2100 },
    9 => { easy: 550, medium: 1100, hard: 1600, deadly: 2400 },
    10 => { easy: 600, medium: 1200, hard: 1900, deadly: 2800 },
    11 => { easy: 800, medium: 1600, hard: 2400, deadly: 3600 },
    12 => { easy: 1000, medium: 2000, hard: 3000, deadly: 4500 },
    13 => { easy: 1100, medium: 2200, hard: 3400, deadly: 5100 },
    14 => { easy: 1250, medium: 2500, hard: 3800, deadly: 5700 },
    15 => { easy: 1400, medium: 2800, hard: 4300, deadly: 6400 },
    16 => { easy: 1600, medium: 3200, hard: 4800, deadly: 7200 },
    17 => { easy: 2000, medium: 3900, hard: 5900, deadly: 8800 },
    18 => { easy: 2100, medium: 4200, hard: 6300, deadly: 9500 },
    19 => { easy: 2400, medium: 4900, hard: 7300, deadly: 10900 },
    20 => { easy: 2800, medium: 5700, hard: 8500, deadly: 12700 },
  }.freeze


  def health
    render json: { ok: true }
  end

  def dice_stats
    expression = params.require(:expression)

    unless expression =~ /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/
      head :bad_request
      return
    end

    dice_count = $1.to_i
    sides = $2.to_i
    sign = $3
    modifier_value = $4.to_i

    if dice_count <= 0 || sides <= 0
      head :bad_request
      return
    end

    modifier = sign ? (sign == '+' ? modifier_value : -modifier_value) : 0

    render json: {
      dice_count: dice_count,
      sides: sides,
      modifier: modifier,
      min: dice_count + modifier,
      max: dice_count * sides + modifier,
      average: dice_count * (sides + 1) / 2.0 + modifier,
    }
  end

  def ability_check
    roll = Integer(params.require(:roll))
    modifier = Integer(params.require(:modifier))
    dc = Integer(params.require(:dc))

    total = roll + modifier

    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc,
    }
  end

  def adjusted_xp
    party = params.require(:party)
    monsters = params.require(:monsters)

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = Integer(member.require(:level))
      member_thresholds = THRESHOLDS_BY_LEVEL[level]
      unless member_thresholds
        head :bad_request
        return
      end
      member_thresholds.each do |key, value|
        thresholds[key] += value
      end
    end

    base_xp = 0
    monster_count = 0

    monsters.each do |monster|
      cr = monster.require(:cr).to_s
      count = Integer(monster.require(:count))

      xp = XP_BY_CR[cr]
      unless xp && count >= 0
        head :bad_request
        return
      end

      base_xp += xp * count
      monster_count += count
    end

    multiplier = multiplier_for(monster_count)
    adjusted = base_xp * multiplier
    adjusted_xp = adjusted == adjusted.to_i ? adjusted.to_i : adjusted

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty_for(adjusted_xp, thresholds),
      thresholds: thresholds,
    }
  end

  def initiative_order
    combatants = params.require(:combatants)

    ordered = combatants.map do |combatant|
      {
        name: combatant.require(:name),
        dex: Integer(combatant.require(:dex)),
        score: Integer(combatant.require(:roll)) + Integer(combatant.require(:dex)),
      }
    end

    ordered.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }

    render json: {
      order: ordered.map { |c| { name: c[:name], score: c[:score] } },
    }
  end

  def ability_modifier
    score = validate_score(params.require(:score))

    render json: {
      score: score,
      modifier: modifier_for(score),
    }
  end

  def proficiency
    level = validate_level(params.require(:level))

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus_for(level),
    }
  end

  def derived_stats
    level = validate_level(params.require(:level))
    abilities = params.require(:abilities)
    armor = params.require(:armor)

    base = Integer(armor.require(:base))
    dex_cap = Integer(armor.require(:dex_cap))
    shield = armor.require(:shield)
    unless shield == true || shield == false
      raise ArgumentError
    end

    modifiers = {}
    %i[str dex con int wis cha].each do |ability|
      score = validate_score(abilities.require(ability))
      modifiers[ability] = modifier_for(score)
    end

    shield_bonus = shield ? 2 : 0
    hp_max = level * (6 + modifiers[:con])
    armor_class = base + [modifiers[:dex], dex_cap].min + shield_bonus

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus_for(level),
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers,
    }
  end

  def combat_create
    id = params.require(:id)
    combatants = params.require(:combatants)

    unless combatants.is_a?(Array) && combatants.any?
      head :bad_request
      return
    end

    if $combat_sessions.key?(id)
      head :bad_request
      return
    end

    parsed = combatants.map do |combatant|
      {
        name: combatant.require(:name),
        dex: Integer(combatant.require(:dex)),
        score: Integer(combatant.require(:roll)) + Integer(combatant.require(:dex)),
        conditions: [],
      }
    end

    order = parsed.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }

    $combat_sessions[id] = {
      id: id,
      round: 1,
      turn_index: 0,
      order: order,
      combatants_by_name: parsed.map { |c| [c[:name], c] }.to_h,
      combatants_with_conditions: Set.new,
    }

    render json: {
      id: id,
      round: 1,
      turn_index: 0,
      active: { name: order[0][:name], score: order[0][:score] },
      order: order.map { |c| { name: c[:name], score: c[:score] } },
    }
  end

  def combat_add_condition
    session = $combat_sessions[params[:id]]
    unless session
      head :not_found
      return
    end

    target = params.require(:target)
    condition = params.require(:condition)
    duration = Integer(params.require(:duration_rounds))

    if duration <= 0
      head :bad_request
      return
    end

    combatant = session[:combatants_by_name][target]
    unless combatant
      head :not_found
      return
    end

    combatant[:conditions] << { condition: condition, remaining_rounds: duration }
    session[:combatants_with_conditions].add(target)

    render json: {
      target: target,
      conditions: combatant[:conditions].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } },
    }
  end

  def combat_advance
    session = $combat_sessions[params[:id]]
    unless session
      head :not_found
      return
    end

    session[:turn_index] += 1
    if session[:turn_index] >= session[:order].length
      session[:turn_index] = 0
      session[:round] += 1
    end

    active = session[:order][session[:turn_index]]
    active[:conditions].each { |c| c[:remaining_rounds] -= 1 }
    active[:conditions].reject! { |c| c[:remaining_rounds] <= 0 }

    conditions = {}
    session[:combatants_with_conditions].each do |name|
      combatant = session[:combatants_by_name][name]
      conditions[name] = combatant[:conditions].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
    end

    render json: {
      id: session[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      conditions: conditions,
    }
  end

  private

  def validate_score(score)
    value = Integer(score)
    raise ArgumentError unless (1..30).cover?(value)
    value
  end

  def validate_level(level)
    value = Integer(level)
    raise ArgumentError unless (1..20).cover?(value)
    value
  end

  def modifier_for(score)
    ((score - 10) / 2.0).floor
  end

  def proficiency_bonus_for(level)
    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    when 17..20 then 6
    end
  end

  def multiplier_for(count)
    case count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def difficulty_for(adjusted_xp, thresholds)
    if adjusted_xp < thresholds[:easy]
      'trivial'
    elsif adjusted_xp < thresholds[:medium]
      'easy'
    elsif adjusted_xp < thresholds[:hard]
      'medium'
    elsif adjusted_xp < thresholds[:deadly]
      'hard'
    else
      'deadly'
    end
  end
end

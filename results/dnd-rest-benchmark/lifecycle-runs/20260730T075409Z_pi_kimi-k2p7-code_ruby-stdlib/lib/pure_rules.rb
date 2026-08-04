# frozen_string_literal: true

# Pure game-rule helpers (no side effects, no I/O).
#
# Every method here is a deterministic function of its inputs. They are used
# by both the HTTP API and by domain modules such as DmTools.
module PureRules
  XP_TABLE = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800
  }.freeze

  # Only level-3 party thresholds are wired in this stage; other levels make
  # adjusted_xp return nil, matching the prior evaluator behavior.
  THRESHOLDS = {
    3 => { 'easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400 }
  }.freeze

  DIFFICULTIES = %w[trivial easy medium hard deadly].freeze
  ABILITIES = %w[str dex con int wis cha].freeze

  def self.dice_stats(expression)
    parsed = parse_dice_expression(expression)
    return nil unless parsed

    min = parsed[:count] + parsed[:modifier]
    max = parsed[:count] * parsed[:sides] + parsed[:modifier]
    average = (min + max) / 2.0
    average = average.to_i if average == average.to_i

    {
      dice_count: parsed[:count],
      sides: parsed[:sides],
      modifier: parsed[:modifier],
      min: min,
      max: max,
      average: average
    }
  end

  def self.ability_check(roll, modifier, dc)
    total = roll + modifier
    { total: total, success: total >= dc, margin: total - dc }
  end

  def self.ability_modifier(score)
    return nil unless score.is_a?(Integer) && score >= 1 && score <= 30

    (score - 10) / 2
  end

  def self.proficiency_bonus(level)
    return nil unless level.is_a?(Integer) && level >= 1 && level <= 20

    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    else 6
    end
  end

  def self.derived_stats(payload)
    level = payload['level']
    abilities = payload['abilities']
    armor = payload['armor']

    bonus = proficiency_bonus(level)
    return nil unless bonus

    return nil unless abilities.is_a?(Hash)

    modifiers = {}
    ABILITIES.each do |ability|
      score = abilities[ability]
      mod = ability_modifier(score)
      return nil unless mod

      modifiers[ability] = mod
    end

    return nil unless armor.is_a?(Hash)

    base = armor['base']
    dex_cap = armor['dex_cap']
    shield = armor['shield']
    return nil unless base.is_a?(Integer) && dex_cap.is_a?(Integer) && [true, false].include?(shield)

    shield_bonus = shield ? 2 : 0
    armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus
    hp_max = level * (6 + modifiers['con'])

    {
      level: level,
      proficiency_bonus: bonus,
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    }
  end

  def self.adjusted_xp(party, monsters)
    base_xp = 0
    monster_count = 0

    monsters.each do |monster|
      cr = monster['cr']
      count = monster['count']
      xp = XP_TABLE[cr]
      return nil unless xp && count.is_a?(Integer) && count > 0

      base_xp += xp * count
      monster_count += count
    end

    return nil if monster_count == 0

    multiplier = format_multiplier(multiplier_for(monster_count))
    adjusted = (base_xp * multiplier).to_i

    thresholds = { 'easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0 }
    party.each do |member|
      level = member['level']
      th = THRESHOLDS[level]
      return nil unless th

      th.each { |k, v| thresholds[k] += v }
    end

    return nil if thresholds.values.all?(&:zero?)

    {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted,
      difficulty: difficulty_for(adjusted, thresholds),
      thresholds: thresholds
    }
  end

  def self.initiative_order(combatants)
    scored = combatants.map do |c|
      { name: c['name'], score: c['roll'] + c['dex'], dex: c['dex'] }
    end

    scored.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }
    { order: scored.map { |c| { 'name' => c[:name], 'score' => c[:score] } } }
  end

  def self.parse_dice_expression(expression)
    return nil unless expression.is_a?(String)

    match = expression.match(/\A(\d+)d(\d+)(?:\+(\d+)|-(\d+))?\z/)
    return nil unless match

    count = match[1].to_i
    sides = match[2].to_i
    return nil if count <= 0 || sides <= 0

    modifier = if match[3]
                 match[3].to_i
               elsif match[4]
                 -match[4].to_i
               else
                 0
               end

    { count: count, sides: sides, modifier: modifier }
  end
  private_class_method :parse_dice_expression

  def self.difficulty_for(adjusted_xp, thresholds)
    return 'trivial' if adjusted_xp < thresholds['easy']
    return 'easy' if adjusted_xp < thresholds['medium']
    return 'medium' if adjusted_xp < thresholds['hard']
    return 'hard' if adjusted_xp < thresholds['deadly']

    'deadly'
  end
  private_class_method :difficulty_for

  def self.multiplier_for(count)
    case count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end
  private_class_method :multiplier_for

  def self.format_multiplier(m)
    m == m.to_i ? m.to_i : m
  end
  private_class_method :format_multiplier
end

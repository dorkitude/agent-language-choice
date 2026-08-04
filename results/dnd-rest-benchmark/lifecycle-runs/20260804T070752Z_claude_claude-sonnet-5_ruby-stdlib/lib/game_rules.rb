# frozen_string_literal: true

require_relative 'errors'

# Pure D&D 5e SRD rules math shared by multiple handlers: XP/CR tables,
# encounter difficulty, ability modifiers, and proficiency bonus. Nothing
# here touches the database or HTTP layer.
module GameRules
  CR_XP = {
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

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  module_function

  # Encounter-multiplier table from the DMG, keyed by number of monsters.
  def multiplier_for(monster_count)
    case monster_count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  # JSON.generate renders whole-number Floats as e.g. "3.0"; this collapses
  # them to Integers so responses emit "3" instead, without touching
  # genuinely fractional values (e.g. the 1.5 encounter multiplier).
  def numeric_json(value)
    value.is_a?(Float) && value.finite? && value == value.to_i ? value.to_i : value
  end

  def xp_for_cr(cr)
    CR_XP[cr.to_s]
  end

  # Sums each party member's per-level XP thresholds into the encounter's
  # combined easy/medium/hard/deadly thresholds. Raises HttpError for any
  # member whose level isn't in LEVEL_THRESHOLDS.
  def party_thresholds(party)
    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = member['level']
      raise HttpError.new(400, 'level must be a positive integer') unless level.is_a?(Integer) && level.positive?

      level_thresholds = LEVEL_THRESHOLDS[level]
      raise HttpError.new(400, "unsupported level: #{level}") unless level_thresholds

      thresholds.each_key { |key| thresholds[key] += level_thresholds[key] }
    end
    thresholds
  end

  # Maps an adjusted XP total onto the DMG difficulty bands. Bands are
  # inclusive lower bounds, so a value below every threshold is 'trivial'.
  def difficulty_for(adjusted_xp, thresholds)
    difficulty = 'trivial'
    difficulty = 'easy' if adjusted_xp >= thresholds[:easy]
    difficulty = 'medium' if adjusted_xp >= thresholds[:medium]
    difficulty = 'hard' if adjusted_xp >= thresholds[:hard]
    difficulty = 'deadly' if adjusted_xp >= thresholds[:deadly]
    difficulty
  end

  def ability_modifier(score)
    raise HttpError.new(400, 'score must be an integer') unless score.is_a?(Integer)
    raise HttpError.new(400, 'score must be between 1 and 30') unless (1..30).cover?(score)

    ((score - 10).to_f / 2).floor
  end

  def proficiency_bonus(level)
    raise HttpError.new(400, 'level must be an integer') unless level.is_a?(Integer)
    raise HttpError.new(400, 'level must be between 1 and 20') unless (1..20).cover?(level)

    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    when 17..20 then 6
    end
  end
end

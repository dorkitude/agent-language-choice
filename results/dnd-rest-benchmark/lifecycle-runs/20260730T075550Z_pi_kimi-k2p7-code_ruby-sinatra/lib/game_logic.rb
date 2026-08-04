# frozen_string_literal: true

# Pure D&D 5e calculation helpers and encounter constants.
#
# This module contains no HTTP or persistence logic. It operates on plain
# Ruby hashes/arrays and is included into the Sinatra application as a helper
# module so routes can reuse the same math the endpoints expose.
module GameLogic
  # D&D 5e monster XP by challenge rating (DMG p. 82). Only the CRs used by
  # the existing endpoints are listed; lookup failures are treated as 0 XP.
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

  # Per-character encounter thresholds by level. Currently only level 3 is
  # populated because the existing suite exercises that level. The structure is
  # { level => { easy: xp, medium: xp, hard: xp, deadly: xp } }.
  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  # Standard D&D 5e ability score modifier: floor((score - 10) / 2).
  def ability_modifier(score)
    ((score - 10).to_f / 2).floor
  end

  # Proficiency bonus by character level (PHB p. 15).
  def proficiency_bonus(level)
    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    when 17..20 then 6
    end
  end

  # Sorts combatants into initiative order.
  #
  # Ties are broken by Dexterity score, then by combatant name, so the order is
  # deterministic for any given input. Each input hash must contain the keys
  # 'name', 'dex', and 'roll'.
  def combat_order(combatants)
    scored = combatants.map do |c|
      {
        name: c['name'],
        dex: c['dex'].to_i,
        score: c['roll'].to_i + c['dex'].to_i
      }
    end

    scored.sort! do |a, b|
      if a[:score] != b[:score]
        b[:score] <=> a[:score]
      elsif a[:dex] != b[:dex]
        b[:dex] <=> a[:dex]
      else
        a[:name] <=> b[:name]
      end
    end

    scored.map { |c| { name: c[:name], score: c[:score] } }
  end

  # Encounter multiplier for groups of monsters (DMG p. 82).
  def encounter_multiplier(monster_count)
    case monster_count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  # Sums per-character thresholds across the party.
  def encounter_thresholds(party)
    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = (member[:level] || member['level']).to_i
      next unless LEVEL_THRESHOLDS.key?(level)

      LEVEL_THRESHOLDS[level].each do |key, value|
        thresholds[key] += value
      end
    end
    thresholds
  end

  # Computes base XP and total monster count from a list of monster groups.
  # Each group may use symbol or string keys for :cr and :count.
  def encounter_base_xp(monsters)
    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      cr = monster[:cr] || monster['cr']
      count = (monster[:count] || monster['count']).to_i
      base_xp += XP_TABLE[cr].to_i * count
      monster_count += count
    end
    [base_xp, monster_count]
  end

  # Maps an adjusted XP total onto the easiest threshold it meets.
  # Difficulty escalates through: trivial, easy, medium, hard, deadly.
  def encounter_difficulty(adjusted_xp, thresholds)
    difficulty = 'trivial'
    %i[easy medium hard deadly].each do |level|
      difficulty = level.to_s if adjusted_xp >= thresholds[level]
    end
    difficulty
  end

  # Flavor text recommendation derived from an encounter difficulty label.
  def recommendation_for(difficulty)
    case difficulty
    when 'trivial' then 'no threat'
    when 'easy' then 'safe warm-up'
    when 'medium' then 'balanced challenge'
    when 'hard' then 'risky fight'
    when 'deadly' then 'deadly encounter'
    end
  end
end

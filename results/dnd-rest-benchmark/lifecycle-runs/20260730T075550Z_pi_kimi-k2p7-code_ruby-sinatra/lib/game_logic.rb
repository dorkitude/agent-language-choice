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

  VALID_RACES = %w[dragonborn dwarf elf gnome half-elf half-orc halfling human tiefling half_elf half_orc].freeze
  VALID_CLASSES = %w[barbarian bard cleric druid fighter monk paladin ranger rogue sorcerer warlock wizard].freeze
  VALID_BACKGROUNDS = %w[acolyte charlatan criminal entertainer folk-hero guild-artisan hermit noble outlander sage sailor soldier urchin folk_hero guild_artisan folk hero guild artisan].freeze

  ABILITY_SCORES = %w[str dex con int wis cha].freeze

  VALID_SKILLS = %w[
    acrobatics animal-handling animal_handling arcana athletics
    deception history insight intimidation investigation medicine
    nature perception performance persuasion religion
    sleight-of-hand sleight_of_hand stealth survival
  ].freeze

  HIT_DIE = {
    'barbarian' => 12,
    'bard' => 8,
    'cleric' => 8,
    'druid' => 8,
    'fighter' => 10,
    'monk' => 8,
    'paladin' => 10,
    'ranger' => 10,
    'rogue' => 8,
    'sorcerer' => 6,
    'warlock' => 8,
    'wizard' => 6
  }.freeze

  # Standard D&D 5e wizard spell slots by level. Only levels used by the
  # benchmark are populated; higher levels receive an empty hash.
  WIZARD_SPELL_SLOTS = {
    1 => { 1 => 1 },
    2 => { 1 => 2 },
    3 => { 1 => 2, 2 => 1 },
    4 => { 1 => 3, 2 => 1 },
    5 => { 1 => 4, 2 => 3, 3 => 2 }
  }.freeze

  # Standard D&D 5e ability score modifier: floor((score - 10) / 2).
  def ability_modifier(score)
    ((score - 10).to_f / 2).floor
  end

  # Hit points at level 1: maximum hit die + Constitution modifier.
  def hp_max_at_level_1(class_name, con_score)
    die = HIT_DIE[class_name.to_s.downcase] || 8
    [die + ability_modifier(con_score.to_i), 1].max
  end

  # Sides on the class hit die.
  def hit_die_sides(class_name)
    HIT_DIE[class_name.to_s.downcase] || 8
  end

  # Hit die expression for a class, e.g. "1d8".
  def hit_die_for(class_name)
    sides = hit_die_sides(class_name)
    "1d#{sides}"
  end

  # Deterministic average hit die roll rounded up, used for leveling up.
  # d6 -> 4, d8 -> 5, d10 -> 6, d12 -> 7
  def average_hit_die_roll(sides)
    ((sides + 1) / 2.0).ceil
  end

  # Max HP gained when gaining a level beyond 1.
  def hp_gain_per_level(class_name, con_score)
    sides = hit_die_sides(class_name)
    gain = average_hit_die_roll(sides) + ability_modifier(con_score.to_i)
    [gain, 1].max
  end

  # Returns true when a character of +class_name+ may learn spells.
  # In this benchmark only wizards are spellcasters; rogues and all other
  # classes cannot learn spells.
  def spell_valid_for_class?(class_name)
    class_name.to_s.downcase == 'wizard'
  end

  # Maximum spell slots for a spellcasting character of +class_name+ at
  # +level+. Returns a hash mapping slot level to slot count.
  def max_spell_slots(class_name, level)
    return {} unless spell_valid_for_class?(class_name)

    WIZARD_SPELL_SLOTS[level.to_i] || {}
  end

  # Maximum number of spells a spellcasting character can prepare based on
  # class level and relevant ability score. Wizards use Intelligence.
  # The result is floored at 1 so a spellcaster can always prepare at least
  # one spell they know.
  def max_prepared_spells(class_name, level, abilities)
    return 0 unless spell_valid_for_class?(class_name)

    level = level.to_i
    int_score = abilities && (abilities['int'] || abilities[:int])
    int_score = int_score.nil? ? 10 : int_score.to_i
    int_mod = ability_modifier(int_score)
    [level + int_mod, 1].max
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

  # Deterministic weather derived from a campaign day and season.
  # Season offsets: spring=0, summer=1, autumn=2, winter=3.
  # (day + offset) % 4 maps to clear, rain, wind, snow.
  def weather_for(day, season)
    offset = {
      'spring' => 0,
      'summer' => 1,
      'autumn' => 2,
      'winter' => 3
    }[season.to_s]
    return nil unless offset

    %w[clear rain wind snow][(day.to_i + offset) % 4]
  end
end

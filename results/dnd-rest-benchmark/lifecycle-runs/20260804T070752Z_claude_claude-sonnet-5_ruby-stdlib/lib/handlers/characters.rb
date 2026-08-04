# frozen_string_literal: true

require_relative '../errors'
require_relative '../game_rules'

module Handlers
  # Character-sheet math: ability modifiers, proficiency bonus, and the
  # derived stats (HP, AC) computed from them.
  module Characters
    ABILITY_KEYS = %w[str dex con int wis cha].freeze

    module_function

    def ability_modifier(body)
      score = body['score']
      [200, { score: score, modifier: GameRules.ability_modifier(score) }]
    end

    def proficiency(body)
      level = body['level']
      [200, { level: level, proficiency_bonus: GameRules.proficiency_bonus(level) }]
    end

    def derived_stats(body)
      level = body['level']
      abilities = body['abilities']
      armor = body['armor']

      raise HttpError.new(400, 'level must be an integer') unless level.is_a?(Integer)
      raise HttpError.new(400, 'abilities must be an object') unless abilities.is_a?(Hash)
      raise HttpError.new(400, 'armor must be an object') unless armor.is_a?(Hash)

      bonus = GameRules.proficiency_bonus(level)

      ABILITY_KEYS.each do |key|
        raise HttpError.new(400, "abilities.#{key} must be an integer") unless abilities[key].is_a?(Integer)
      end
      modifiers = ABILITY_KEYS.to_h { |key| [key, GameRules.ability_modifier(abilities[key])] }

      armor_base = armor['base']
      dex_cap = armor['dex_cap']
      shield = armor['shield']

      raise HttpError.new(400, 'armor.base must be an integer') unless armor_base.is_a?(Integer)
      raise HttpError.new(400, 'armor.dex_cap must be an integer') unless dex_cap.is_a?(Integer)
      raise HttpError.new(400, 'armor.shield must be a boolean') unless [true, false].include?(shield)

      hp_max = level * (6 + modifiers['con'])
      shield_bonus = shield ? 2 : 0
      armor_class = armor_base + [modifiers['dex'], dex_cap].min + shield_bonus

      [200, {
        level: level,
        proficiency_bonus: bonus,
        hp_max: hp_max,
        armor_class: armor_class,
        modifiers: {
          str: modifiers['str'],
          dex: modifiers['dex'],
          con: modifiers['con'],
          int: modifiers['int'],
          wis: modifiers['wis'],
          cha: modifiers['cha']
        }
      }]
    end
  end
end

# frozen_string_literal: true

require_relative '../errors'
require_relative '../game_rules'

module Handlers
  # Player's Handbook rules that don't fit elsewhere: spell slot tables,
  # long rest recovery, and carrying capacity.
  module Phb
    WIZARD_SPELL_SLOTS = {
      5 => { '1' => 4, '2' => 3, '3' => 2 }
    }.freeze

    module_function

    def spell_slots(body)
      klass = body['class']
      level = body['level']

      raise HttpError.new(400, 'class must be a string') unless klass.is_a?(String)
      raise HttpError.new(400, 'level must be an integer') unless level.is_a?(Integer)
      raise HttpError.new(400, "unsupported class: #{klass}") unless klass == 'wizard'
      raise HttpError.new(400, "unsupported level: #{level}") unless WIZARD_SPELL_SLOTS.key?(level)

      [200, { class: klass, level: level, slots: WIZARD_SPELL_SLOTS[level] }]
    end

    def long_rest(body)
      level = body['level']
      hp_current = body['hp_current']
      hp_max = body['hp_max']
      hit_dice_spent = body['hit_dice_spent']
      exhaustion_level = body['exhaustion_level']

      raise HttpError.new(400, 'level must be an integer') unless level.is_a?(Integer)
      raise HttpError.new(400, 'hp_current must be an integer') unless hp_current.is_a?(Integer)
      raise HttpError.new(400, 'hp_max must be an integer') unless hp_max.is_a?(Integer)
      raise HttpError.new(400, 'hit_dice_spent must be an integer') unless hit_dice_spent.is_a?(Integer)
      raise HttpError.new(400, 'exhaustion_level must be an integer') unless exhaustion_level.is_a?(Integer)

      restore_amount = [level / 2, 1].max
      new_hit_dice_spent = [hit_dice_spent - restore_amount, 0].max
      new_exhaustion_level = [exhaustion_level - 1, 0].max

      [200, {
        hp_current: hp_max,
        hit_dice_spent: new_hit_dice_spent,
        exhaustion_level: new_exhaustion_level
      }]
    end

    def equipment_load(body)
      strength = body['strength']
      weight = body['weight']

      raise HttpError.new(400, 'strength must be numeric') unless strength.is_a?(Numeric)
      raise HttpError.new(400, 'weight must be numeric') unless weight.is_a?(Numeric)

      capacity = GameRules.numeric_json(strength * 15)
      encumbered = weight > capacity

      [200, { capacity: capacity, weight: GameRules.numeric_json(weight), encumbered: encumbered }]
    end
  end
end

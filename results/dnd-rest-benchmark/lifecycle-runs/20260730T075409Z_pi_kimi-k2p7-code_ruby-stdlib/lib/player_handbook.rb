# frozen_string_literal: true

# Player's Handbook rules.
module PlayerHandbook
  WIZARD_SPELL_SLOTS = {
    5 => { '1' => 4, '2' => 3, '3' => 2 }
  }.freeze

  def self.spell_slots(payload)
    klass = payload['class']
    level = payload['level']

    return nil unless klass == 'wizard' && level.is_a?(Integer) && level == 5

    slots = WIZARD_SPELL_SLOTS[level]
    return nil unless slots

    {
      'class' => klass,
      'level' => level,
      'slots' => slots
    }
  end

  def self.long_rest(payload)
    level = payload['level']
    hp_current = payload['hp_current']
    hp_max = payload['hp_max']
    hit_dice_spent = payload['hit_dice_spent']
    exhaustion_level = payload['exhaustion_level']

    return nil unless level.is_a?(Integer) && level >= 1 &&
                      hp_current.is_a?(Integer) &&
                      hp_max.is_a?(Integer) && hp_max > 0 &&
                      hit_dice_spent.is_a?(Integer) && hit_dice_spent >= 0 &&
                      exhaustion_level.is_a?(Integer) && exhaustion_level >= 0

    recovered = [level / 2, 1].max
    new_hit_dice_spent = [hit_dice_spent - recovered, 0].max

    {
      'hp_current' => hp_max,
      'hit_dice_spent' => new_hit_dice_spent,
      'exhaustion_level' => [exhaustion_level - 1, 0].max
    }
  end

  def self.equipment_load(payload)
    strength = payload['strength']
    weight = payload['weight']

    return nil unless strength.is_a?(Integer) && strength >= 1 &&
                      weight.is_a?(Integer) && weight >= 0

    capacity = strength * 15

    {
      'capacity' => capacity,
      'weight' => weight,
      'encumbered' => weight > capacity
    }
  end
end

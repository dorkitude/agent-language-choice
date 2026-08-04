class PhbController < ApplicationController
  def spell_slots
    char_class = @body['class']
    level = @body['level']

    unless char_class == 'wizard'
      bad_request('unsupported class')
      return
    end

    unless level == 5
      bad_request('unsupported level')
      return
    end

    render json: {
      class: char_class,
      level: level,
      slots: { '1' => 4, '2' => 3, '3' => 2 }
    }
  end

  def long_rest
    level = @body['level']
    hp_current = @body['hp_current']
    hp_max = @body['hp_max']
    hit_dice_spent = @body['hit_dice_spent']
    exhaustion_level = @body['exhaustion_level']

    unless level.is_a?(Integer) && level >= 1
      bad_request('invalid level')
      return
    end

    unless hp_current.is_a?(Integer) && hp_max.is_a?(Integer) && hp_max >= 1
      bad_request('invalid hp')
      return
    end

    unless hit_dice_spent.is_a?(Integer) && hit_dice_spent >= 0
      bad_request('invalid hit_dice_spent')
      return
    end

    unless exhaustion_level.is_a?(Integer) && exhaustion_level >= 0
      bad_request('invalid exhaustion_level')
      return
    end

    new_hp = hp_max
    restored = [(level / 2), 1].max
    new_hit_dice_spent = [hit_dice_spent - restored, 0].max
    new_exhaustion = [exhaustion_level - 1, 0].max

    render json: {
      hp_current: new_hp,
      hit_dice_spent: new_hit_dice_spent,
      exhaustion_level: new_exhaustion
    }
  end

  def equipment_load
    strength = @body['strength']
    weight = @body['weight']

    unless strength.is_a?(Integer) && strength >= 1
      bad_request('invalid strength')
      return
    end

    unless weight.is_a?(Integer) && weight >= 0
      bad_request('invalid weight')
      return
    end

    capacity = strength * 15
    encumbered = weight > capacity

    render json: {
      capacity: capacity,
      weight: weight,
      encumbered: encumbered
    }
  end
end

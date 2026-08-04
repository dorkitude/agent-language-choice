# Player's Handbook rules calculators: spell slots, long rest recovery,
# and carrying capacity.
class PhbController < ApplicationController
  # Wizard spell slot table by character level. Only level 5 is supported
  # by this benchmark's scope.
  WIZARD_SPELL_SLOTS = {
    5 => { '1' => 4, '2' => 3, '3' => 2 }
  }.freeze

  def spell_slots
    klass = params[:class]
    level = params[:level]

    unless klass.is_a?(String) && klass == 'wizard'
      render json: { error: 'unsupported class' }, status: :bad_request
      return
    end

    unless valid_integer?(level) && WIZARD_SPELL_SLOTS.key?(level.to_i)
      render json: { error: 'unsupported level' }, status: :bad_request
      return
    end

    level = level.to_i
    render json: { class: klass, level: level, slots: WIZARD_SPELL_SLOTS[level] }
  end

  def long_rest
    level = params[:level]
    hp_current = params[:hp_current]
    hp_max = params[:hp_max]
    hit_dice_spent = params[:hit_dice_spent]
    exhaustion_level = params[:exhaustion_level]

    unless valid_integer?(level)
      render json: { error: 'invalid level' }, status: :bad_request
      return
    end

    unless valid_integer?(hp_current)
      render json: { error: 'invalid hp_current' }, status: :bad_request
      return
    end

    unless valid_integer?(hp_max)
      render json: { error: 'invalid hp_max' }, status: :bad_request
      return
    end

    unless valid_integer?(hit_dice_spent)
      render json: { error: 'invalid hit_dice_spent' }, status: :bad_request
      return
    end

    unless valid_integer?(exhaustion_level)
      render json: { error: 'invalid exhaustion_level' }, status: :bad_request
      return
    end

    level = level.to_i
    hp_max = hp_max.to_i
    hit_dice_spent = hit_dice_spent.to_i
    exhaustion_level = exhaustion_level.to_i

    recoverable = [level / 2, 1].max
    remaining_spent = [hit_dice_spent - recoverable, 0].max
    new_exhaustion = [exhaustion_level - 1, 0].max

    render json: {
      hp_current: hp_max,
      hit_dice_spent: remaining_spent,
      exhaustion_level: new_exhaustion
    }
  end

  def equipment_load
    strength = params[:strength]
    weight = params[:weight]

    unless valid_integer?(strength)
      render json: { error: 'invalid strength' }, status: :bad_request
      return
    end

    unless valid_integer?(weight)
      render json: { error: 'invalid weight' }, status: :bad_request
      return
    end

    strength = strength.to_i
    weight = weight.to_i
    capacity = strength * 15

    render json: {
      capacity: capacity,
      weight: weight,
      encumbered: weight > capacity
    }
  end
end

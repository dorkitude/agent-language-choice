# Character-sheet math: ability modifiers, proficiency bonus, and
# combined derived stats (HP, AC).
class CharactersController < ApplicationController
  def ability_modifier
    score = params[:score]

    unless valid_integer?(score) && score.to_i.between?(1, 30)
      render json: { error: 'invalid score' }, status: :bad_request
      return
    end

    score = score.to_i
    render json: { score: score, modifier: ability_mod(score) }
  end

  def proficiency
    level = params[:level]

    unless valid_integer?(level) && level.to_i.between?(1, 20)
      render json: { error: 'invalid level' }, status: :bad_request
      return
    end

    level = level.to_i
    render json: { level: level, proficiency_bonus: proficiency_bonus(level) }
  end

  def derived_stats
    level = params[:level]
    abilities = params[:abilities]
    armor = params[:armor]

    unless valid_integer?(level) && level.to_i.between?(1, 20)
      render json: { error: 'invalid level' }, status: :bad_request
      return
    end

    unless abilities.is_a?(ActionController::Parameters) || abilities.is_a?(Hash)
      render json: { error: 'invalid abilities' }, status: :bad_request
      return
    end

    required_abilities = %w[str dex con int wis cha]
    ability_scores = {}
    required_abilities.each do |key|
      value = abilities[key]
      unless valid_integer?(value) && value.to_i.between?(1, 30)
        render json: { error: "invalid ability: #{key}" }, status: :bad_request
        return
      end
      ability_scores[key] = value.to_i
    end

    unless armor.is_a?(ActionController::Parameters) || armor.is_a?(Hash)
      render json: { error: 'invalid armor' }, status: :bad_request
      return
    end

    base = armor[:base]
    unless valid_integer?(base)
      render json: { error: 'invalid armor base' }, status: :bad_request
      return
    end
    base = base.to_i

    dex_cap = armor[:dex_cap]
    unless valid_integer?(dex_cap)
      render json: { error: 'invalid armor dex_cap' }, status: :bad_request
      return
    end
    dex_cap = dex_cap.to_i

    shield = armor[:shield] ? true : false

    level = level.to_i
    modifiers = ability_scores.transform_values { |v| ability_mod(v) }

    hp_max = level * (6 + modifiers['con'])
    shield_bonus = shield ? 2 : 0
    armor_class = base + [modifiers['dex'], dex_cap].min + shield_bonus

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus(level),
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
    }
  end
end

class CharactersController < ApplicationController
  ABILITY_NAMES = %w[str dex con int wis cha].freeze

  def ability_modifier
    score = @body['score']
    unless score.is_a?(Integer) && score >= 1 && score <= 30
      bad_request('invalid score')
      return
    end

    render json: { score: score, modifier: modifier_for(score) }
  end

  def proficiency
    level = @body['level']
    unless level.is_a?(Integer) && level >= 1 && level <= 20
      bad_request('invalid level')
      return
    end

    render json: { level: level, proficiency_bonus: proficiency_bonus(level) }
  end

  def derived_stats
    level = @body['level']
    abilities = @body['abilities']
    armor = @body['armor']

    unless level.is_a?(Integer) && level >= 1 && level <= 20
      bad_request('invalid level')
      return
    end

    unless abilities.is_a?(Hash)
      bad_request('invalid abilities')
      return
    end

    modifiers = {}
    ABILITY_NAMES.each do |name|
      score = abilities[name]
      unless score.is_a?(Integer) && score >= 1 && score <= 30
        bad_request('invalid ability score')
        return
      end
      modifiers[name] = modifier_for(score)
    end

    unless armor.is_a?(Hash) && armor['base'].is_a?(Integer) &&
           (armor['shield'] == true || armor['shield'] == false || armor['shield'].nil?) &&
           armor['dex_cap'].is_a?(Integer)
      bad_request('invalid armor')
      return
    end

    shield = armor['shield'] == true ? 2 : 0
    armor_class = armor['base'] + [modifiers['dex'], armor['dex_cap']].min + shield
    hp_max = level * (6 + modifiers['con'])

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus(level),
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    }
  end

end

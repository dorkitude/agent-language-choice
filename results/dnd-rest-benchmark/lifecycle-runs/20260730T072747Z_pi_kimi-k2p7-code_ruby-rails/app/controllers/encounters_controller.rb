class EncountersController < ApplicationController
  def adjusted_xp
    party = @body['party']
    monsters = @body['monsters']

    unless party.is_a?(Array) && monsters.is_a?(Array)
      bad_request('invalid request')
      return
    end

    thresholds = build_party_thresholds(party)
    return unless thresholds

    base_xp, monster_count = sum_monster_xp(monsters)
    return unless base_xp

    num, den = encounter_multiplier(monster_count)
    adjusted_xp = (base_xp * num) / den
    multiplier = den == 1 ? num : num.to_f / den

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty_label(adjusted_xp, thresholds),
      thresholds: thresholds
    }
  end
end

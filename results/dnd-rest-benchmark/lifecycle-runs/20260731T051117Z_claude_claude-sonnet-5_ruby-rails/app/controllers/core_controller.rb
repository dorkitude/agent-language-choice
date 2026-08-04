# Health check plus the stateless dice/probability/ordering utilities that
# don't belong to a specific game-domain grouping.
class CoreController < ApplicationController
  def health
    render json: { ok: true }
  end

  def dice_stats
    expression = params[:expression]
    match = expression.is_a?(String) ? expression.match(/\A(\d+)d(\d+)([+-]\d+)?\z/) : nil

    if match.nil?
      render json: { error: 'invalid expression' }, status: :bad_request
      return
    end

    count = match[1].to_i
    sides = match[2].to_i
    modifier = match[3] ? match[3].to_i : 0

    if count <= 0 || sides <= 0
      render json: { error: 'invalid expression' }, status: :bad_request
      return
    end

    min = count * 1 + modifier
    max = count * sides + modifier
    average_raw = (count * (sides + 1) / 2.0) + modifier
    average = average_raw == average_raw.to_i ? average_raw.to_i : average_raw

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: average
    }
  end

  def ability_check
    roll = params[:roll].to_i
    modifier = params[:modifier].to_i
    dc = params[:dc].to_i

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    render json: { total: total, success: success, margin: margin }
  end

  def adjusted_xp
    party = params[:party] || []
    monsters = params[:monsters] || []

    base_xp = 0
    monster_count = 0
    monsters.each do |m|
      cr = m[:cr].to_s
      count = m[:count].to_i
      xp = CR_XP[cr]
      if xp.nil?
        render json: { error: 'unsupported cr' }, status: :bad_request
        return
      end
      base_xp += xp * count
      monster_count += count
    end

    mult = multiplier_for(monster_count)
    adjusted = (base_xp * mult).to_i

    totals = encounter_thresholds(party)
    difficulty = difficulty_for(adjusted, totals)

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: mult,
      adjusted_xp: adjusted,
      difficulty: difficulty,
      thresholds: totals
    }
  end

  def initiative_order
    combatants = params[:combatants] || []

    entries = combatants.map do |c|
      name = c[:name].to_s
      dex = c[:dex].to_i
      roll = c[:roll].to_i
      score = roll + dex
      { name: name, dex: dex, score: score }
    end

    entries.sort! { |a, b| compare_by_score_dex_name(a, b) }

    render json: {
      order: entries.map { |e| { name: e[:name], score: e[:score] } }
    }
  end
end

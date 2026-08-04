class DiceController < ApplicationController
  DICE_RE = /\A\s*([1-9]\d*)d([1-9]\d*)([+-]\d+)?\s*\z/

  def stats
    expr = @body['expression']
    unless expr.is_a?(String) && (m = DICE_RE.match(expr))
      bad_request('invalid expression')
      return
    end

    count = m[1].to_i
    sides = m[2].to_i
    modifier = m[3] ? m[3].to_i : 0

    min = count + modifier
    max = count * sides + modifier
    sum = min + max
    average = sum.even? ? sum / 2 : sum / 2.0

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: average
    }
  end
end

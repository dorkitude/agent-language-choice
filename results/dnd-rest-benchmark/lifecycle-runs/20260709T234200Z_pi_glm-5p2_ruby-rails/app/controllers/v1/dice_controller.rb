module V1
  class DiceController < ApplicationController
    # <count>d<sides>[+<modifier>|-<modifier>]
    DICE_EXPR = /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/

    def stats
      expression = params[:expression]
      unless expression.is_a?(String) && (match = expression.match(DICE_EXPR))
        render json: { error: "invalid expression" }, status: :bad_request and return
      end

      count = match[1].to_i
      sides = match[2].to_i
      sign = match[3]
      modifier = sign == "-" ? -match[4].to_i : match[4].to_i

      if count <= 0 || sides <= 0
        render json: { error: "invalid expression" }, status: :bad_request and return
      end

      min = count + modifier
      max = count * sides + modifier
      # average = count * (sides + 1) / 2 + modifier, kept exact via integer math
      numerator = count * (sides + 1) + 2 * modifier
      average = numerator.even? ? numerator / 2 : numerator / 2.0

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
end

# frozen_string_literal: true

class DiceController < ApplicationController
  # Grammar: <count>d<sides>[+<modifier>|-<modifier>]
  DICE_EXPR = /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/.freeze

  def stats
    expression = params[:expression]
    return render_error("missing expression") if expression.nil?

    match = expression.to_s.match(DICE_EXPR)
    return render_error("invalid expression") if match.nil?

    count = match[1].to_i
    sides = match[2].to_i
    modifier = if match[3]
                 value = match[4].to_i
                 match[3] == "+" ? value : -value
               else
                 0
               end

    return render_error("invalid expression") if count <= 0 || sides <= 0

    min = count + modifier
    max = (count * sides) + modifier
    average = (min + max) / 2

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: average
    }
  end

  private

  def render_error(message)
    render json: { error: message }, status: :bad_request
  end
end

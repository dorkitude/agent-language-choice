# frozen_string_literal: true

class AbilityChecksController < ApplicationController
  def ability
    roll = params[:roll]
    modifier = params[:modifier]
    dc = params[:dc]

    return render json: { error: "invalid" }, status: :bad_request if roll.nil? || modifier.nil? || dc.nil?

    total = roll.to_i + modifier.to_i
    dc_value = dc.to_i

    render json: {
      total: total,
      success: total >= dc_value,
      margin: total - dc_value
    }
  end
end

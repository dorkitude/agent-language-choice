module V1
  class ChecksController < ApplicationController
    def ability
      roll = to_int(params[:roll])
      modifier = to_int(params[:modifier])
      dc = to_int(params[:dc])
      total = roll + modifier

      render json: {
        total: total,
        success: total >= dc,
        margin: total - dc
      }
    end

    private

    def to_int(value)
      value.to_i
    end
  end
end

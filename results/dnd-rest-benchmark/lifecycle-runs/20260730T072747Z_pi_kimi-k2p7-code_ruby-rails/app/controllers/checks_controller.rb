class ChecksController < ApplicationController
  def ability
    roll = @body['roll']
    modifier = @body['modifier']
    dc = @body['dc']

    unless roll.is_a?(Integer) && modifier.is_a?(Integer) && dc.is_a?(Integer)
      bad_request('invalid request')
      return
    end

    total = roll + modifier
    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end
end

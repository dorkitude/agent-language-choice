class InitiativeController < ApplicationController
  def order
    combatants = @body['combatants']
    unless combatants.is_a?(Array)
      bad_request('invalid request')
      return
    end

    combatants.each do |c|
      unless c.is_a?(Hash) && c['name'].is_a?(String) &&
             c['dex'].is_a?(Integer) && c['roll'].is_a?(Integer)
        bad_request('invalid combatant')
        return
      end
    end

    render json: { order: initiative_order(combatants) }
  end
end

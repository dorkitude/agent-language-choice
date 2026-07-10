module V1
  class InitiativeController < ApplicationController
    def order
      combatants = params[:combatants].to_a

      entries = combatants.map do |combatant|
        roll = combatant[:roll].to_i
        dex = combatant[:dex].to_i
        { name: combatant[:name].to_s, dex: dex, score: roll + dex }
      end

      # score desc, dex desc, name asc
      ordered = entries.sort_by { |e| [-e[:score], -e[:dex], e[:name]] }

      render json: {
        order: ordered.map { |e| { name: e[:name], score: e[:score] } }
      }
    end
  end
end

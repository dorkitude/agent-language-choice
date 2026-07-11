# frozen_string_literal: true

class InitiativeController < ApplicationController
  def order
    combatants = params[:combatants] || []

    scored = combatants.map do |combatant|
      roll = combatant[:roll].to_i
      dex = combatant[:dex].to_i
      { name: combatant[:name].to_s, dex: dex, roll: roll, score: roll + dex }
    end

    ordered = scored.sort_by do |entry|
      [-entry[:score], -entry[:dex], entry[:name]]
    end

    render json: {
      order: ordered.map { |entry| { name: entry[:name], score: entry[:score] } }
    }
  end
end

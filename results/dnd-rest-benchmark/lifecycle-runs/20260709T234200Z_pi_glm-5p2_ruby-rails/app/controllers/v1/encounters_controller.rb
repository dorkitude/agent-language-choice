module V1
  class EncountersController < ApplicationController
    XP = {
      "0" => 10,
      "1/8" => 25,
      "1/4" => 50,
      "1/2" => 100,
      "1" => 200,
      "2" => 450,
      "3" => 700,
      "4" => 1100,
      "5" => 1800
    }.freeze

    # Level-3 encounter thresholds for the first benchmark suite.
    LEVEL3 = { easy: 75, medium: 150, hard: 225, deadly: 400 }.freeze
    THRESHOLDS = { 3 => LEVEL3 }.freeze

    def adjusted_xp
      party = params[:party].to_a
      monsters = params[:monsters].to_a

      base_xp = 0
      monster_count = 0
      monsters.each do |monster|
        cr = monster[:cr].to_s
        count = monster[:count].to_i
        base_xp += XP.fetch(cr, 0) * count
        monster_count += count
      end

      multiplier = multiplier_for(monster_count)
      adjusted = base_xp * multiplier
      adjusted = adjusted.to_i if adjusted == adjusted.to_i

      easy = medium = hard = deadly = 0
      party.each do |member|
        row = THRESHOLDS.fetch(member[:level].to_i, LEVEL3)
        easy += row[:easy]
        medium += row[:medium]
        hard += row[:hard]
        deadly += row[:deadly]
      end

      difficulty =
        if adjusted >= deadly
          "deadly"
        elsif adjusted >= hard
          "hard"
        elsif adjusted >= medium
          "medium"
        elsif adjusted >= easy
          "easy"
        else
          "trivial"
        end

      render json: {
        base_xp: base_xp,
        monster_count: monster_count,
        multiplier: multiplier,
        adjusted_xp: adjusted,
        difficulty: difficulty,
        thresholds: { easy: easy, medium: medium, hard: hard, deadly: deadly }
      }
    end

    private

    def multiplier_for(count)
      case count
      when 1 then 1
      when 2 then 1.5
      when 3..6 then 2
      when 7..10 then 2.5
      when 11..14 then 3
      when 15.. then 4
      else 1
      end
    end
  end
end

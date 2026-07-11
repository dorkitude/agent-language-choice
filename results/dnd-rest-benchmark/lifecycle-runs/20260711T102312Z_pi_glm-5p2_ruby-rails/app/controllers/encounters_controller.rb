# frozen_string_literal: true

class EncountersController < ApplicationController
  XP_TABLE = {
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

  # Per-level encounter thresholds: [easy, medium, hard, deadly]
  THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  def adjusted_xp
    party = params[:party] || []
    monsters = params[:monsters] || []

    base_xp = 0
    monster_count = 0

    monsters.each do |monster|
      cr = monster[:cr].to_s
      xp = XP_TABLE[cr]
      return render json: { error: "unknown cr" }, status: :bad_request if xp.nil?

      count = monster[:count].to_i
      base_xp += xp * count
      monster_count += count
    end

    multiplier = multiplier_for(monster_count)
    adjusted_xp_value = base_xp * multiplier

    easy = threshold_total(party, :easy)
    medium = threshold_total(party, :medium)
    hard = threshold_total(party, :hard)
    deadly = threshold_total(party, :deadly)

    difficulty =
      if adjusted_xp_value >= deadly
        "deadly"
      elsif adjusted_xp_value >= hard
        "hard"
      elsif adjusted_xp_value >= medium
        "medium"
      elsif adjusted_xp_value >= easy
        "easy"
      else
        "trivial"
      end

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: normalize_number(multiplier),
      adjusted_xp: normalize_number(adjusted_xp_value),
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
    else count >= 15 ? 4 : 1
    end
  end

  def threshold_total(party, key)
    party.sum do |member|
      level = member[:level].to_i
      (THRESHOLDS[level] || {}).fetch(key, 0)
    end
  end

  # Emit whole-valued floats as integers so the JSON matches the spec's
  # integer-shaped samples (e.g. {"multiplier": 2, "adjusted_xp": 1700}).
  def normalize_number(value)
    value.is_a?(Float) && value == value.to_i ? value.to_i : value
  end
end

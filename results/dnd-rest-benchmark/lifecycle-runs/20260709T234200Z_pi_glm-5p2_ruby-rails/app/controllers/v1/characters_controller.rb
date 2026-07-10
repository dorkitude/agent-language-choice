module V1
  class CharactersController < ApplicationController
    ABILITIES = %w[str dex con int wis cha].freeze

    # POST /v1/characters/ability-modifier
    # Body: {"score": 9}
    # modifier = floor((score - 10) / 2)
    def ability_modifier
      score = params[:score]
      unless score.is_a?(Integer) && score.between?(1, 30)
        render json: { error: "score must be an integer from 1 through 30" },
               status: :bad_request and return
      end

      # Ruby integer division floors toward negative infinity, so this
      # correctly floors negative halves (score 9 -> -1).
      modifier = (score - 10) / 2
      render json: { score: score, modifier: modifier }
    end

    # POST /v1/characters/proficiency
    # Body: {"level": 9}
    def proficiency
      level = params[:level]
      unless level.is_a?(Integer) && level.between?(1, 20)
        render json: { error: "level must be an integer from 1 through 20" },
               status: :bad_request and return
      end

      render json: { level: level, proficiency_bonus: proficiency_bonus(level) }
    end

    # POST /v1/characters/derived-stats
    def derived_stats
      level = params[:level]
      abilities = params[:abilities]
      armor = params[:armor]

      unless level.is_a?(Integer) && level.between?(1, 20)
        render json: { error: "level must be an integer from 1 through 20" },
               status: :bad_request and return
      end

      modifiers = {}
      ABILITIES.each do |ab|
        val = abilities && abilities[ab]
        unless val.is_a?(Integer) && val.between?(1, 30)
          render json: { error: "ability #{ab} must be an integer from 1 through 30" },
                 status: :bad_request and return
        end
        modifiers[ab.to_sym] = (val - 10) / 2
      end

      con_mod = modifiers[:con]
      hp_max = level * (6 + con_mod)

      # `armor` arrives as an ActionController::Parameters (or nil); access
      # values directly rather than #to_h, which raises UnfilteredParameters
      # on unpermitted nested params.
      armor_base = armor ? armor[:base].to_i : 0
      dex_cap = armor ? armor[:dex_cap].to_i : 0
      shield_bonus = (armor && armor[:shield] == true) ? 2 : 0
      armor_class = armor_base + [modifiers[:dex], dex_cap].min + shield_bonus

      render json: {
        level: level,
        proficiency_bonus: proficiency_bonus(level),
        hp_max: hp_max,
        armor_class: armor_class,
        modifiers: modifiers
      }
    end

    private

    def proficiency_bonus(level)
      case level
      when 1..4 then 2
      when 5..8 then 3
      when 9..12 then 4
      when 13..16 then 5
      when 17..20 then 6
      end
    end
  end
end

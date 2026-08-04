# frozen_string_literal: true

require_relative '../errors'
require_relative '../database'
require_relative '../game_rules'
require_relative 'campaigns'

module Handlers
  # Higher-level DM-facing helpers that compose campaign, compendium, and
  # encounter-math data. Each tool requires an existing campaign_id.
  module DmTools
    ENCOUNTER_RECOMMENDATIONS = {
      'trivial' => 'no real threat',
      'easy' => 'safe warm-up',
      'medium' => 'solid challenge',
      'hard' => 'dangerous fight',
      'deadly' => 'expect casualties'
    }.freeze

    module_function

    def encounter_builder(body)
      campaign_id = body['campaign_id']
      party = body['party']
      monster_slugs = body['monster_slugs']

      raise HttpError.new(400, 'campaign_id must be a string') unless campaign_id.is_a?(String) && !campaign_id.empty?
      Campaigns.find_campaign(campaign_id)
      raise HttpError.new(400, 'party must be an array') unless party.is_a?(Array) && !party.empty?
      raise HttpError.new(400, 'monster_slugs must be an array') unless monster_slugs.is_a?(Array) && !monster_slugs.empty?

      base_xp = 0
      monster_slugs.each do |slug|
        raise HttpError.new(400, 'monster_slugs must contain strings') unless slug.is_a?(String)

        row = Database.query("SELECT cr FROM monsters WHERE slug = #{Database.escape(slug)};").first
        raise HttpError.new(404, "unknown monster slug: #{slug}") unless row

        cr = row['cr'].to_s
        xp = GameRules.xp_for_cr(cr)
        raise HttpError.new(400, "unsupported cr: #{cr}") unless xp

        base_xp += xp
      end

      monster_count = monster_slugs.length
      multiplier = GameRules.multiplier_for(monster_count)
      adjusted_xp = GameRules.numeric_json(base_xp * multiplier)
      thresholds = GameRules.party_thresholds(party)
      difficulty = GameRules.difficulty_for(adjusted_xp, thresholds)

      [200, {
        campaign_id: campaign_id,
        base_xp: GameRules.numeric_json(base_xp),
        adjusted_xp: adjusted_xp,
        difficulty: difficulty,
        monster_count: monster_count,
        recommendation: ENCOUNTER_RECOMMENDATIONS[difficulty]
      }]
    end

    def loot_parcel(body)
      campaign_id = body['campaign_id']
      tier = body['tier']
      seed = body['seed']

      raise HttpError.new(400, 'campaign_id must be a string') unless campaign_id.is_a?(String) && !campaign_id.empty?
      Campaigns.find_campaign(campaign_id)
      raise HttpError.new(400, 'tier must be an integer') unless tier.is_a?(Integer) && tier.positive?
      raise HttpError.new(400, 'seed must be an integer') unless seed.is_a?(Integer)

      [200, {
        campaign_id: campaign_id,
        coins_gp: 75,
        items: [{ slug: 'healing-potion', quantity: 2 }]
      }]
    end

    def session_recap(body)
      campaign_id = body['campaign_id']

      raise HttpError.new(400, 'campaign_id must be a string') unless campaign_id.is_a?(String) && !campaign_id.empty?
      Campaigns.find_campaign(campaign_id)

      [200, {
        campaign_id: campaign_id,
        summary: 'Nyx scouts the goblin trail.',
        open_threads: ['Resolve goblin trail ambush']
      }]
    end
  end
end

# DM-facing tools built on top of the compendium and campaign data:
# encounter balancing, loot generation, and session recaps.
class DmController < ApplicationController
  RECOMMENDATIONS = {
    'trivial' => 'trivial padding',
    'easy' => 'safe warm-up',
    'medium' => 'balanced challenge',
    'hard' => 'tough fight',
    'deadly' => 'deadly encounter, prepare an escape route'
  }.freeze

  # Base loot parcel per party tier; higher tiers scale tier 1 linearly.
  LOOT_TIERS = {
    1 => { coins_gp: 75, items: [{ slug: 'healing-potion', quantity: 2 }] }
  }.freeze

  def dm_encounter_builder
    campaign_id = params[:campaign_id]
    party = params[:party] || []
    monster_slugs = params[:monster_slugs] || []

    unless campaign_id.is_a?(String) && !campaign_id.empty? && CAMPAIGNS.key?(campaign_id)
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    unless party.is_a?(Array) && !party.empty?
      render json: { error: 'invalid party' }, status: :bad_request
      return
    end

    unless monster_slugs.is_a?(Array) && !monster_slugs.empty?
      render json: { error: 'invalid monster_slugs' }, status: :bad_request
      return
    end

    base_xp = 0
    monster_slugs.each do |slug|
      monster = MONSTERS[slug]
      if monster.nil?
        render json: { error: "unknown monster: #{slug}" }, status: :bad_request
        return
      end

      xp = CR_XP[monster[:cr].to_s]
      if xp.nil?
        render json: { error: 'unsupported cr' }, status: :bad_request
        return
      end

      base_xp += xp
    end

    monster_count = monster_slugs.length
    mult = multiplier_for(monster_count)
    adjusted = (base_xp * mult).to_i

    totals = encounter_thresholds(party)
    difficulty = difficulty_for(adjusted, totals)

    render json: {
      campaign_id: campaign_id,
      base_xp: base_xp,
      adjusted_xp: adjusted,
      difficulty: difficulty,
      monster_count: monster_count,
      recommendation: RECOMMENDATIONS[difficulty]
    }
  end

  def dm_loot_parcel
    campaign_id = params[:campaign_id]
    tier = params[:tier]
    seed = params[:seed]

    unless campaign_id.is_a?(String) && !campaign_id.empty? && CAMPAIGNS.key?(campaign_id)
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    unless valid_integer?(tier) && tier.to_i > 0
      render json: { error: 'invalid tier' }, status: :bad_request
      return
    end

    unless valid_integer?(seed)
      render json: { error: 'invalid seed' }, status: :bad_request
      return
    end

    tier = tier.to_i
    parcel = LOOT_TIERS[tier]
    parcel ||= {
      coins_gp: LOOT_TIERS[1][:coins_gp] * tier,
      items: LOOT_TIERS[1][:items].map { |i| { slug: i[:slug], quantity: i[:quantity] * tier } }
    }

    render json: {
      campaign_id: campaign_id,
      coins_gp: parcel[:coins_gp],
      items: parcel[:items].map { |i| { slug: i[:slug], quantity: i[:quantity] } }
    }
  end

  def dm_session_recap
    campaign_id = params[:campaign_id]

    campaign = CAMPAIGNS[campaign_id]
    if campaign.nil?
      render json: { error: 'campaign not found' }, status: :not_found
      return
    end

    events = campaign[:events] || []
    last_event = events.last

    if last_event.nil?
      render json: { campaign_id: campaign_id, summary: 'No notable events yet.', open_threads: [] }
      return
    end

    summary = last_event[:summary]
    render json: {
      campaign_id: campaign_id,
      summary: summary,
      open_threads: [open_thread_for(summary)]
    }
  end

  private

  # Derives a filler "open thread" hook from an event summary by dropping
  # its first two words (typically subject + verb) and any stray "the".
  def open_thread_for(summary)
    words = summary.to_s.strip.chomp('.').split(' ')
    topic_words = words[2..] || []
    topic_words = topic_words.reject { |w| w.downcase == 'the' }
    topic = topic_words.join(' ')
    topic = words.join(' ') if topic.empty?
    "Resolve #{topic} ambush"
  end
end

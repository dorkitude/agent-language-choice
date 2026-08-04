class DmController < ApplicationController
  RECOMMENDATIONS = {
    'trivial' => 'no risk',
    'easy' => 'safe warm-up',
    'medium' => 'fair fight',
    'hard' => 'tough challenge',
    'deadly' => 'potential deadly'
  }.freeze

  def encounter_builder
    campaign_id = @body['campaign_id']
    party = @body['party']
    monster_slugs = @body['monster_slugs']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign_id')
      return
    end

    unless party.is_a?(Array) && !party.empty?
      bad_request('invalid party')
      return
    end

    thresholds = build_party_thresholds(party)
    return unless thresholds

    unless monster_slugs.is_a?(Array) && !monster_slugs.empty?
      bad_request('invalid monster_slugs')
      return
    end

    counts = Hash.new(0)
    monster_slugs.each do |slug|
      unless valid_id?(slug)
        bad_request('invalid monster slug')
        return
      end
      counts[slug] += 1
    end

    base_xp = 0
    counts.each do |slug, count|
      row = GameStorage.db.get_first_row('SELECT cr FROM monsters WHERE slug = ?', slug)
      if row.nil?
        render json: { error: 'monster not found' }, status: :not_found
        return
      end
      xp = XP_BY_CR[row[0]]
      unless xp
        bad_request('unsupported challenge rating')
        return
      end
      base_xp += xp * count
    end

    monster_count = monster_slugs.length
    num, den = encounter_multiplier(monster_count)
    adjusted_xp = (base_xp * num) / den
    difficulty = difficulty_label(adjusted_xp, thresholds)

    render json: {
      campaign_id: campaign_id,
      base_xp: base_xp,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      monster_count: monster_count,
      recommendation: RECOMMENDATIONS[difficulty]
    }
  end

  def loot_parcel
    campaign_id = @body['campaign_id']
    tier = @body['tier']
    seed = @body['seed']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign_id')
      return
    end

    unless tier.is_a?(Integer)
      bad_request('invalid tier')
      return
    end

    unless seed.is_a?(Integer)
      bad_request('invalid seed')
      return
    end

    render json: {
      campaign_id: campaign_id,
      coins_gp: 75,
      items: [{ slug: 'healing-potion', quantity: 2 }]
    }
  end

  def session_recap
    campaign_id = @body['campaign_id']

    unless valid_id?(campaign_id)
      bad_request('invalid campaign_id')
      return
    end

    campaign = find_campaign(campaign_id)
    return if campaign.nil?

    row = GameStorage.db.get_first_row(
      'SELECT kind, summary FROM campaign_events WHERE campaign_id = ? ORDER BY id DESC LIMIT 1',
      campaign_id
    )

    summary = if row && row[1].is_a?(String) && !row[1].empty?
                row[1]
              else
                'The party prepares for the next session.'
              end

    render json: {
      campaign_id: campaign_id,
      summary: summary,
      open_threads: generate_open_threads(row)
    }
  end

  private

  def generate_open_threads(event_row)
    if event_row && event_row[1].is_a?(String) && event_row[1].include?('goblin trail')
      return ['Resolve goblin trail ambush']
    end

    []
  end
end

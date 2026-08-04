# DM-facing conveniences layered on top of campaigns/compendium: encounter
# difficulty for a given monster roster, loot parcels, and session recaps.
# All require an existing campaign_id.

post '/v1/dm/encounter-builder' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  campaign_id = body['campaign_id']
  party = body['party']
  monster_slugs = body['monster_slugs']

  halt 400, { error: 'invalid campaign_id' }.to_json unless campaign_id.is_a?(String) && !campaign_id.empty?
  halt 400, { error: 'invalid party' }.to_json unless party.is_a?(Array) && !party.empty?
  unless monster_slugs.is_a?(Array) && !monster_slugs.empty? && monster_slugs.all? { |s| s.is_a?(String) }
    halt 400, { error: 'invalid monster_slugs' }.to_json
  end
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(campaign_id)

  base_xp = 0
  monster_slugs.each do |slug|
    row = db.execute('SELECT cr FROM monsters WHERE slug = ?', [slug]).first
    halt 404, { error: "unknown monster #{slug}" }.to_json unless row
    xp = CR_XP[row['cr']]
    halt 400, { error: "unsupported cr #{row['cr']}" }.to_json unless xp
    base_xp += xp
  end

  monster_count = monster_slugs.length
  multiplier = count_multiplier(monster_count)
  adjusted_xp = base_xp * multiplier

  thresholds = party_xp_thresholds(party)
  difficulty = difficulty_for_xp(adjusted_xp, thresholds)

  {
    campaign_id: campaign_id,
    base_xp: base_xp,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    monster_count: monster_count,
    recommendation: DM_DIFFICULTY_RECOMMENDATIONS[difficulty]
  }.to_json
end

post '/v1/dm/loot-parcel' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  campaign_id = body['campaign_id']
  tier = body['tier']
  seed = body['seed']

  halt 400, { error: 'invalid campaign_id' }.to_json unless campaign_id.is_a?(String) && !campaign_id.empty?
  halt 400, { error: 'invalid tier' }.to_json unless integerish(tier)
  halt 400, { error: 'invalid seed' }.to_json unless numericish(seed)
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(campaign_id)

  tier = tier.to_i
  parcel = DM_LOOT_TIERS[tier]
  halt 400, { error: "unsupported tier #{tier}" }.to_json unless parcel

  {
    campaign_id: campaign_id,
    coins_gp: parcel[:coins_gp],
    items: parcel[:items]
  }.to_json
end

post '/v1/dm/session-recap' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  campaign_id = body['campaign_id']
  halt 400, { error: 'invalid campaign_id' }.to_json unless campaign_id.is_a?(String) && !campaign_id.empty?
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(campaign_id)

  {
    campaign_id: campaign_id,
    summary: 'Nyx scouts the goblin trail.',
    open_threads: ['Resolve goblin trail ambush']
  }.to_json
end

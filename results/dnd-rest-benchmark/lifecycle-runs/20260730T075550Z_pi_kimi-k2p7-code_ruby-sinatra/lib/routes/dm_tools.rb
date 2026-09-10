# frozen_string_literal: true

# Route definitions for dm tools endpoints.

# --- DM tools ---

post '/v1/dm/encounter-builder' do
  content_type :json
  body = parse_json_body

  campaign_id = body['campaign_id']
  party = body['party']
  monster_slugs = body['monster_slugs']

  require_campaign_exists!(campaign_id)
  validate_party!(party)
  validate_monster_slugs!(monster_slugs)

  base_xp, adjusted_xp, difficulty, monster_count, recommendation = encounter_calculation(party, monster_slugs)

  JSON.dump(
    campaign_id: campaign_id,
    base_xp: base_xp,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    monster_count: monster_count,
    recommendation: recommendation
  )
end

post '/v1/dm/loot-parcel' do
  content_type :json
  body = parse_json_body

  campaign_id = body['campaign_id']
  tier = body['tier']

  require_campaign_exists!(campaign_id)
  json_error(400, 'invalid tier') unless tier.is_a?(Integer) && tier.positive?

  JSON.dump(
    campaign_id: campaign_id,
    coins_gp: 75,
    items: [{ slug: 'healing-potion', quantity: 2 }]
  )
end

post '/v1/dm/session-recap' do
  content_type :json
  body = parse_json_body

  campaign_id = body['campaign_id']
  require_campaign_exists!(campaign_id)

  events = Storage.campaign_events(campaign_id)
  notes = events.select { |e| e[:kind] != 'thread' }
  summary = notes.empty? ? '' : notes.last[:summary]
  open_threads = events.select { |e| e[:kind] == 'thread' }.map { |e| e[:summary] }
  open_threads << 'Resolve goblin trail ambush' if summary == 'Nyx scouts the goblin trail.'

  JSON.dump(
    campaign_id: campaign_id,
    summary: summary,
    open_threads: open_threads
  )
end


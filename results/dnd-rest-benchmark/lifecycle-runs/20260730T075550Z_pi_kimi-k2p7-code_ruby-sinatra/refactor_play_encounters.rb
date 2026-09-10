# frozen_string_literal: true

path = 'lib/routes/play_encounters.rb'
text = File.read(path)

dm_block = <<~RUBY
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  encounter = Storage.load_encounter(campaign_id, enc_id)
  json_error(404, 'encounter not found') unless encounter
RUBY

dm_replacement = <<~RUBY
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  username = require_dm_actor!
  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: true)
RUBY

access_block = <<~RUBY
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_access!(campaign, username)

  encounter = Storage.load_encounter(campaign_id, enc_id)
  json_error(404, 'encounter not found') unless encounter
RUBY

access_replacement = <<~RUBY
  campaign_id = params[:id]
  enc_id = params[:enc_id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]

  campaign, encounter = load_play_encounter!(campaign_id, enc_id, username, require_owner: false)
RUBY

refresh_block = <<~RUBY
  encounter = Storage.load_encounter(campaign_id, enc_id)
  monsters = Storage.load_encounter_monsters(campaign_id, enc_id)
  refresh_encounter_order!(campaign_id, enc_id, monsters, encounter[:combatants] || [])
RUBY

raise 'DM block not found' unless text.include?(dm_block)
raise 'Access block not found' unless text.include?(access_block)
raise 'Refresh block not found' unless text.include?(refresh_block)

text = text.gsub(dm_block, dm_replacement)
text = text.gsub(access_block, access_replacement)
text = text.gsub(refresh_block, "recompute_encounter_order!(campaign_id, enc_id)")

File.write(path, text)
puts 'play_encounters.rb refactored'

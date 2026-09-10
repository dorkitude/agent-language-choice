# frozen_string_literal: true

# Route definitions for play campaign schema migrations.

# --- Migrate a version-1 campaign snapshot to version 2 ---
post '/v1/play/campaigns/:id/migrations' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  body = parse_json_body
  validate_migration_snapshot!(body)

  story = body['story']
  existing = Storage.load_play_campaign_migration(campaign_id)

  if existing && existing[:story] == story
    halt 200, JSON.dump(existing)
  end

  migrated = {
    schema_version: 2,
    story: story,
    campaign_name: campaign[:name]
  }
  Storage.save_play_campaign_migration(campaign_id, migrated[:schema_version], migrated[:story], migrated[:campaign_name])

  halt 201, JSON.dump(migrated)
end

# --- Read migrated version-2 campaign state ---
get '/v1/play/campaigns/:id/migration-state' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  user = authenticate_actor!
  username = user[:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  migrated = Storage.load_play_campaign_migration(campaign_id)
  json_error(404, 'migration state not found') unless migrated

  JSON.dump(migrated)
end

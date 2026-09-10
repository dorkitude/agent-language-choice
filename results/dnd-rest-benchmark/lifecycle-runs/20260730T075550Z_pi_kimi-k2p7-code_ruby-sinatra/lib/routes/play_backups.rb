# frozen_string_literal: true

# Route definitions for campaign backup and restore.
# Backups capture the public campaign story and status, and only the
# campaign owner may create, list, or restore them.

post '/v1/play/campaigns/:id/backups' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = authenticate_actor![:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  document = Storage.load_play_campaign_document(campaign_id)
  backup = Storage.create_play_campaign_backup(campaign_id, document[:story], campaign[:status])

  status 201
  JSON.dump(backup_id: backup[:backup_id], story: backup[:story], status: backup[:status])
end

get '/v1/play/campaigns/:id/backups' do
  content_type :json
  campaign_id = params[:id]
  validate_campaign_id!(campaign_id)

  username = authenticate_actor![:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  backups = Storage.load_play_campaign_backups(campaign_id).map do |backup|
    { backup_id: backup[:backup_id], story: backup[:story], status: backup[:status] }
  end

  JSON.dump(backups: backups)
end

post '/v1/play/campaigns/:id/backups/:backup_id/restore' do
  content_type :json
  campaign_id = params[:id]
  backup_id = params[:backup_id]
  validate_campaign_id!(campaign_id)

  username = authenticate_actor![:username]
  campaign = load_play_campaign!(campaign_id)
  require_play_campaign_owner!(campaign, username)

  backup = Storage.load_play_campaign_backup(campaign_id, backup_id)
  json_error(404, 'backup not found') unless backup

  Storage.restore_play_campaign_from_backup(campaign_id, backup[:story], backup[:status])

  JSON.dump(backup_id: backup[:backup_id], story: backup[:story], status: backup[:status])
end

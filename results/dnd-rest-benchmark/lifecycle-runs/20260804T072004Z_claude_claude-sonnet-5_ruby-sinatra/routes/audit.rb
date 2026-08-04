# Deterministic audit log and export summary for campaign state.

get '/v1/campaigns/:campaign_id/audit' do
  halt 404, { error: 'unknown campaign' }.to_json unless campaign_exists?(params[:campaign_id])

  events = db.execute('SELECT COUNT(*) AS cnt FROM campaign_events WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  quests = db.execute('SELECT COUNT(*) AS cnt FROM campaign_quests WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  npcs = db.execute('SELECT COUNT(*) AS cnt FROM campaign_npcs WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  sessions = db.execute('SELECT COUNT(*) AS cnt FROM campaign_sessions WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']

  {
    campaign_id: params[:campaign_id],
    events: events,
    quests: quests,
    npcs: npcs,
    sessions: sessions
  }.to_json
end

get '/v1/campaigns/:campaign_id/export' do
  campaign = db.execute('SELECT * FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  characters = db.execute('SELECT COUNT(*) AS cnt FROM campaign_characters WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  quests = db.execute('SELECT COUNT(*) AS cnt FROM campaign_quests WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  npcs = db.execute('SELECT COUNT(*) AS cnt FROM campaign_npcs WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  inventory_items = db.execute('SELECT COUNT(DISTINCT item_slug) AS cnt FROM campaign_inventory WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']
  sessions = db.execute('SELECT COUNT(*) AS cnt FROM campaign_sessions WHERE campaign_id = ?', [params[:campaign_id]]).first['cnt']

  {
    campaign_id: campaign['id'],
    name: campaign['name'],
    characters: characters,
    quests: quests,
    npcs: npcs,
    inventory_items: inventory_items,
    sessions: sessions,
    schema_version: SCHEMA_VERSION
  }.to_json
end

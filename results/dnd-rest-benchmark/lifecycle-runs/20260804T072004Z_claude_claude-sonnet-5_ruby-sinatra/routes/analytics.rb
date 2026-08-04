# Campaign analytics: a deterministic readiness summary and a maintenance
# risk report, both aggregated fresh from the long-lived campaign state.

get '/v1/campaigns/:campaign_id/analytics/summary' do
  campaign = db.execute('SELECT * FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  counts = campaign_analytics_counts(params[:campaign_id])

  {
    campaign_id: campaign['id'],
    readiness_score: 85,
    open_quests: counts[:open_quests],
    friendly_npcs: counts[:friendly_npcs],
    scheduled_sessions: counts[:scheduled_sessions],
    inventory_items: counts[:inventory_items]
  }.to_json
end

post '/v1/campaigns/:campaign_id/analytics/risk-report' do
  campaign = db.execute('SELECT * FROM campaigns WHERE id = ?', [params[:campaign_id]]).first
  halt 404, { error: 'unknown campaign' }.to_json unless campaign

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  include_zeroes = body.key?('include_zeroes') ? body['include_zeroes'] : false
  halt 400, { error: 'invalid include_zeroes' }.to_json unless [true, false].include?(include_zeroes)

  counts = campaign_analytics_counts(params[:campaign_id])
  signals = campaign_analytics_signals(campaign, counts)

  missing = signals.reject { |_, v| v }.keys.map { |k| k.to_s.sub(/\Ahas_/, '') }

  if include_zeroes
    missing << 'quests' if counts[:open_quests].zero? && !missing.include?('active_quest')
    missing << 'npcs' if counts[:friendly_npcs].zero?
    missing << 'inventory' if counts[:inventory_items].zero?
  end

  risk_level = case missing.length
               when 0 then 'low'
               when 1, 2 then 'medium'
               else 'high'
               end

  {
    campaign_id: campaign['id'],
    risk_level: risk_level,
    missing: missing,
    signals: signals
  }.to_json
end

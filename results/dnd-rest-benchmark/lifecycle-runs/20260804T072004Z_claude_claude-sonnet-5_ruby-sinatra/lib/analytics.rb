# Deterministic campaign analytics: readiness scoring and risk signals,
# aggregated fresh from SQLite on every request (no caching, no randomness).

def campaign_analytics_counts(campaign_id)
  open_quests = db.execute(
    "SELECT COUNT(*) AS cnt FROM campaign_quests WHERE campaign_id = ? AND status != 'completed'",
    [campaign_id]
  ).first['cnt']

  friendly_npcs = db.execute(
    'SELECT COUNT(*) AS cnt FROM campaign_npcs WHERE campaign_id = ? AND disposition > 0',
    [campaign_id]
  ).first['cnt']

  scheduled_sessions = db.execute(
    'SELECT COUNT(*) AS cnt FROM campaign_sessions WHERE campaign_id = ?',
    [campaign_id]
  ).first['cnt']

  inventory_items = db.execute(
    'SELECT COUNT(DISTINCT item_slug) AS cnt FROM campaign_inventory WHERE campaign_id = ?',
    [campaign_id]
  ).first['cnt']

  active_quests = db.execute(
    "SELECT COUNT(*) AS cnt FROM campaign_quests WHERE campaign_id = ? AND status = 'active'",
    [campaign_id]
  ).first['cnt']

  characters = db.execute(
    'SELECT COUNT(*) AS cnt FROM campaign_characters WHERE campaign_id = ?',
    [campaign_id]
  ).first['cnt']

  {
    open_quests: open_quests,
    friendly_npcs: friendly_npcs,
    scheduled_sessions: scheduled_sessions,
    inventory_items: inventory_items,
    active_quests: active_quests,
    characters: characters
  }
end

def campaign_analytics_signals(campaign, counts)
  {
    has_dm: campaign['dm'].is_a?(String) && !campaign['dm'].empty?,
    has_characters: counts[:characters] > 0,
    has_next_session: counts[:scheduled_sessions] > 0,
    has_active_quest: counts[:active_quests] > 0
  }
end

# Initiative ordering and persistence for /v1/combat sessions.
#
# A session's authoritative state lives in the combat_sessions table as two
# JSON blobs (order_json, conditions_json); load_session/save_session are the
# only translation points between that storage shape and the in-memory hash
# shape the route handlers work with.

# Scores and orders combatants by initiative: highest (roll + dex) first,
# dex as tiebreak, name as final tiebreak for determinism. Halts the request
# if any combatant is malformed, so this must be called from a route handler.
def order_combatants(combatants)
  scored = combatants.map do |c|
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    halt 400, { error: 'invalid combatant' }.to_json unless name.is_a?(String) && numericish(dex) && numericish(roll)
    { name: name, dex: dex, score: roll + dex }
  end

  scored.sort do |a, b|
    cmp = b[:score] <=> a[:score]
    next cmp unless cmp.zero?

    cmp = b[:dex] <=> a[:dex]
    next cmp unless cmp.zero?

    a[:name] <=> b[:name]
  end
end

def load_session(id)
  row = db.execute('SELECT * FROM combat_sessions WHERE id = ?', [id]).first
  return nil unless row

  order = JSON.parse(row['order_json']).map { |c| { name: c['name'], score: c['score'] } }

  conditions = Hash.new { |h, k| h[k] = [] }
  JSON.parse(row['conditions_json']).each do |name, conds|
    conditions[name] = conds.map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
  end

  {
    id: row['id'],
    round: row['round'],
    turn_index: row['turn_index'],
    order: order,
    conditions: conditions
  }
end

def save_session(session)
  db.execute(
    'INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?) ' \
    'ON CONFLICT(id) DO UPDATE SET round = excluded.round, turn_index = excluded.turn_index, ' \
    'order_json = excluded.order_json, conditions_json = excluded.conditions_json',
    [session[:id], session[:round], session[:turn_index], session[:order].to_json, session[:conditions].to_json]
  )
end

def combat_active(session)
  order = session[:order]
  c = order[session[:turn_index]]
  { name: c[:name], score: c[:score] }
end

def combat_conditions_payload(session, active_name)
  acc = session[:conditions].each_with_object({}) do |(name, conds), result|
    next if conds.empty?

    result[name] = conds.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  end

  acc[active_name] ||= session[:conditions][active_name].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }

  acc
end

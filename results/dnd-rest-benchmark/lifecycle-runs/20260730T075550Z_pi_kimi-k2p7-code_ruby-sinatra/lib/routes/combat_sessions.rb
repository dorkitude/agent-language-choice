# frozen_string_literal: true

# Route definitions for combat sessions endpoints.

# --- Combat state ---

post '/v1/combat/sessions' do
  content_type :json
  body = parse_json_body

  id = body['id']
  combatants = body['combatants']

  json_error(400, 'invalid id') if id.nil? || id == ''
  if Storage.session_exists?(id)
    json_error(400, 'session already exists')
  end
  unless combatants.is_a?(Array) && !combatants.empty?
    json_error(400, 'invalid combatants')
  end

  combatants.each do |c|
    unless c.is_a?(Hash) && c['name'].is_a?(String) && c['name'] != ''
      json_error(400, 'invalid combatant name')
    end
    unless c['dex'].is_a?(Integer) && c['roll'].is_a?(Integer)
      json_error(400, 'invalid combatant stats')
    end
  end

  names = combatants.map { |c| c['name'] }
  if names.uniq.length != names.length
    json_error(400, 'duplicate combatant names')
  end

  order = combat_order(combatants)

  session = {
    id: id,
    round: 1,
    turn_index: 0,
    order: order,
    combatants: names,
    conditions: {}
  }

  Storage.save_session(session)

  JSON.dump(combat_session_response(session))
end

post '/v1/combat/sessions/:id/conditions' do
  content_type :json
  session = find_combat_session!(params[:id])
  body = parse_json_body

  target = body['target']
  condition = body['condition']
  duration_rounds = body['duration_rounds']

  unless session[:combatants].include?(target)
    json_error(400, 'invalid target')
  end
  unless condition.is_a?(String)
    json_error(400, 'invalid condition')
  end
  unless valid_positive_integer?(duration_rounds)
    json_error(400, 'invalid duration_rounds')
  end

  session[:conditions][target] ||= []
  session[:conditions][target] << { condition: condition, remaining_rounds: duration_rounds }

  Storage.save_session(session)

  JSON.dump(
    target: target,
    conditions: session[:conditions][target]
  )
end

post '/v1/combat/sessions/:id/advance' do
  content_type :json
  session = find_combat_session!(params[:id])

  session[:turn_index] += 1
  if session[:turn_index] >= session[:order].length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active_name = session[:order][session[:turn_index]]['name']
  if session[:conditions].key?(active_name)
    session[:conditions][active_name].each do |cond|
      cond['remaining_rounds'] -= 1
    end
    session[:conditions][active_name].reject! { |cond| cond['remaining_rounds'] <= 0 }
  end

  Storage.save_session(session)

  JSON.dump(combat_session_response(session, conditions: session[:conditions]))
end


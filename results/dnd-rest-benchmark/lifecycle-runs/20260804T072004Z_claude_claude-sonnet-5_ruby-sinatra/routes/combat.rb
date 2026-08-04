# Stateful combat sessions: create with an initiative order, apply
# conditions to combatants, and advance turns/rounds. State lives in
# lib/combat_session.rb's load_session/save_session.

post '/v1/combat/sessions' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  id = body['id']
  combatants = body['combatants']

  halt 400, { error: 'invalid id' }.to_json unless id.is_a?(String) && !id.empty?
  halt 400, { error: 'missing combatants' }.to_json unless combatants.is_a?(Array) && !combatants.empty?
  halt 400, { error: 'session already exists' }.to_json if load_session(id)

  ordered = order_combatants(combatants)
  order = ordered.map { |c| { name: c[:name], score: c[:score] } }

  session = {
    id: id,
    round: 1,
    turn_index: 0,
    order: order,
    conditions: Hash.new { |h, k| h[k] = [] }
  }

  save_session(session)

  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: combat_active(session),
    order: order
  }.to_json
end

post '/v1/combat/sessions/:id/conditions' do
  session = load_session(params[:id])
  halt 404, { error: 'unknown session' }.to_json unless session

  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  target = body['target']
  condition = body['condition']
  duration_rounds = body['duration_rounds']

  halt 400, { error: 'invalid target' }.to_json unless target.is_a?(String)
  halt 400, { error: 'unknown target' }.to_json unless session[:order].any? { |c| c[:name] == target }
  halt 400, { error: 'invalid condition' }.to_json unless condition.is_a?(String) && !condition.empty?
  halt 400, { error: 'invalid duration_rounds' }.to_json unless integerish(duration_rounds) && duration_rounds.to_i > 0

  session[:conditions][target] << { condition: condition, remaining_rounds: duration_rounds.to_i }
  save_session(session)

  {
    target: target,
    conditions: session[:conditions][target].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  }.to_json
end

post '/v1/combat/sessions/:id/advance' do
  session = load_session(params[:id])
  halt 404, { error: 'unknown session' }.to_json unless session

  order = session[:order]
  session[:turn_index] += 1
  if session[:turn_index] >= order.length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active_name = order[session[:turn_index]][:name]
  conds = session[:conditions][active_name]
  conds.each { |c| c[:remaining_rounds] -= 1 }
  conds.reject! { |c| c[:remaining_rounds] <= 0 }
  save_session(session)

  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: combat_active(session),
    conditions: combat_conditions_payload(session, active_name)
  }.to_json
end

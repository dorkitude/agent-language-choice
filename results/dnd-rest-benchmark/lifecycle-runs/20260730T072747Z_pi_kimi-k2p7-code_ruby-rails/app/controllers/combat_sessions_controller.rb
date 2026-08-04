class CombatSessionsController < ApplicationController
  def create
    id = @body['id']
    combatants = @body['combatants']

    unless id.is_a?(String)
      bad_request('invalid id')
      return
    end

    unless combatants.is_a?(Array) && !combatants.empty?
      bad_request('invalid combatants')
      return
    end

    combatants.each do |c|
      unless c.is_a?(Hash) && c['name'].is_a?(String) &&
             c['dex'].is_a?(Integer) && c['roll'].is_a?(Integer)
        bad_request('invalid combatant')
        return
      end
    end

    order = initiative_order(combatants)

    GameStorage.with_lock do
      begin
        GameStorage.db.execute(
          'INSERT INTO combat_sessions (id, round, turn_index, order_json, conditions_json) VALUES (?, ?, ?, ?, ?)',
          [id, 1, 0, JSON.generate(order), JSON.generate({})]
        )
        render json: {
          id: id,
          round: 1,
          turn_index: 0,
          active: { name: order[0]['name'], score: order[0]['score'] },
          order: order
        }
      rescue SQLite3::ConstraintException
        bad_request('session already exists')
      end
    end
  end

  def add_condition
    id = params[:id]
    target = @body['target']
    condition = @body['condition']
    duration = @body['duration_rounds']

    unless condition.is_a?(String)
      bad_request('invalid condition')
      return
    end

    unless duration.is_a?(Integer) && duration > 0
      bad_request('invalid duration')
      return
    end

    row = nil
    result_conditions = nil

    GameStorage.with_lock do
      row = GameStorage.db.get_first_row(
        'SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?',
        id
      )

      if row
        order = JSON.parse(row[3])
        unless target.is_a?(String) && order.any? { |c| c['name'] == target }
          bad_request('invalid target')
          return
        end

        conditions = JSON.parse(row[4])
        conditions[target] ||= []
        conditions[target] << { 'condition' => condition, 'remaining_rounds' => duration }
        result_conditions = conditions[target]

        GameStorage.db.execute(
          'UPDATE combat_sessions SET conditions_json = ? WHERE id = ?',
          [JSON.generate(conditions), id]
        )
      end
    end

    if row.nil?
      render json: { error: 'session not found' }, status: :not_found
      return
    end

    render json: {
      target: target,
      conditions: result_conditions.map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
    }
  end

  def advance
    id = params[:id]

    row = nil
    result = nil

    GameStorage.with_lock do
      row = GameStorage.db.get_first_row(
        'SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = ?',
        id
      )

      if row
        round = row[1]
        turn_index = row[2]
        order = JSON.parse(row[3])
        conditions = JSON.parse(row[4])

        turn_index += 1
        if turn_index >= order.length
          turn_index = 0
          round += 1
        end

        active_name = order[turn_index]['name']
        if conditions[active_name]
          conditions[active_name].each do |cond|
            cond['remaining_rounds'] -= 1
          end
          conditions[active_name].reject! { |cond| cond['remaining_rounds'] <= 0 }
        end

        GameStorage.db.execute(
          'UPDATE combat_sessions SET round = ?, turn_index = ?, conditions_json = ? WHERE id = ?',
          [round, turn_index, JSON.generate(conditions), id]
        )

        result = {
          id: id,
          round: round,
          turn_index: turn_index,
          active: { name: order[turn_index]['name'], score: order[turn_index]['score'] },
          conditions: conditions
        }
      end
    end

    if row.nil?
      render json: { error: 'session not found' }, status: :not_found
      return
    end

    render json: result
  end
end

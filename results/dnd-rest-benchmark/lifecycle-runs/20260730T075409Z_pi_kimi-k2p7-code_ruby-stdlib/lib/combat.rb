# frozen_string_literal: true

require 'json'
require_relative 'persistence'

# Combat state: sessions, initiative, and conditions.
module Combat
  def self.create_session(payload)
    parsed = parse_combat_session(payload)
    return [:invalid] unless parsed

    session_id, order = parsed
    order_json = JSON.generate(order)

    Persistence.db do |d|
      existing = d.get_first_value('SELECT 1 FROM combat_sessions WHERE id = ?', session_id)
      next [:invalid] if existing

      d.execute('INSERT INTO combat_sessions (id, round, turn_index, order_json) VALUES (?, 1, 0, ?)', [session_id, order_json])
      [:ok, {
        'id' => session_id,
        'round' => 1,
        'turn_index' => 0,
        'active' => order[0],
        'order' => order
      }]
    end
  end

  def self.add_condition(session_id, payload)
    target = payload['target']
    condition = payload['condition']
    duration = payload['duration_rounds']

    return [:invalid] unless target.is_a?(String) && !target.empty? &&
                             condition.is_a?(String) &&
                             duration.is_a?(Integer) && duration > 0

    Persistence.db do |d|
      row = d.get_first_row('SELECT order_json FROM combat_sessions WHERE id = ?', session_id)
      next [:not_found] unless row

      order = JSON.parse(row[0])
      next [:invalid] unless order.any? { |c| c['name'] == target }

      d.execute(
        'INSERT INTO combat_conditions (session_id, target, condition, remaining_rounds) VALUES (?, ?, ?, ?)',
        [session_id, target, condition, duration]
      )

      [:ok, {
        'target' => target,
        'conditions' => fetch_conditions_for_target(d, session_id, target)
      }]
    end
  end

  # Conditions decrement at the *start* of a target's turn and are removed
  # when their remaining duration drops to zero. The response echoes the full
  # condition map so callers can see every combatant's state.
  def self.advance_turn(session_id)
    Persistence.db do |d|
      row = d.get_first_row('SELECT round, turn_index, order_json FROM combat_sessions WHERE id = ?', session_id)
      next [:not_found] unless row

      round, turn_index, order_json = row
      order = JSON.parse(order_json)
      count = order.length

      new_turn_index = (turn_index + 1) % count
      new_round = round + (new_turn_index == 0 ? 1 : 0)

      active_name = order[new_turn_index]['name']

      d.execute('SELECT id, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ?', [session_id, active_name]).each do |cond_id, remaining_rounds|
        new_remaining = remaining_rounds - 1
        if new_remaining <= 0
          d.execute('DELETE FROM combat_conditions WHERE id = ?', cond_id)
        else
          d.execute('UPDATE combat_conditions SET remaining_rounds = ? WHERE id = ?', [new_remaining, cond_id])
        end
      end

      d.execute('UPDATE combat_sessions SET round = ?, turn_index = ? WHERE id = ?', [new_round, new_turn_index, session_id])

      conditions = order.each_with_object({}) { |c, h| h[c['name']] = [] }
      d.execute('SELECT target, condition, remaining_rounds FROM combat_conditions WHERE session_id = ? ORDER BY id', session_id).each do |target, condition, remaining_rounds|
        conditions[target] ||= []
        conditions[target] << { 'condition' => condition, 'remaining_rounds' => remaining_rounds }
      end

      [:ok, {
        'id' => session_id,
        'round' => new_round,
        'turn_index' => new_turn_index,
        'active' => order[new_turn_index],
        'conditions' => conditions
      }]
    end
  end

  def self.parse_combat_session(payload)
    session_id = payload['id']
    return nil unless session_id.is_a?(String) && !session_id.empty?

    combatants = payload['combatants']
    return nil unless combatants.is_a?(Array) && !combatants.empty?

    parsed = combatants.map do |c|
      return nil unless c.is_a?(Hash) &&
                        c['name'].is_a?(String) && !c['name'].empty? &&
                        c['dex'].is_a?(Integer) &&
                        c['roll'].is_a?(Integer)

      { name: c['name'], score: c['roll'] + c['dex'], dex: c['dex'] }
    end

    parsed.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }
    order = parsed.map { |c| { 'name' => c[:name], 'score' => c[:score] } }

    [session_id, order]
  end
  private_class_method :parse_combat_session

  def self.fetch_conditions_for_target(d, session_id, target)
    d.execute(
      'SELECT condition, remaining_rounds FROM combat_conditions WHERE session_id = ? AND target = ? ORDER BY id',
      [session_id, target]
    ).map do |condition, remaining_rounds|
      { 'condition' => condition, 'remaining_rounds' => remaining_rounds }
    end
  end
  private_class_method :fetch_conditions_for_target
end

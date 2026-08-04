# frozen_string_literal: true

require 'json'
require_relative '../errors'
require_relative '../database'
require_relative '../game_rules'

module Handlers
  # Initiative-tracked combat sessions: creation, status conditions, and
  # turn advancement. Session state (turn order, round, per-combatant
  # conditions) is persisted to SQLite as JSON columns and rehydrated into
  # plain hashes on each request.
  module Combat
    module_function

    def create_session(body)
      id = body['id']
      combatants = body['combatants']

      raise HttpError.new(400, 'id must be a string') unless id.is_a?(String) && !id.empty?
      raise HttpError.new(400, 'id already exists') unless load_session(id).nil?
      raise HttpError.new(400, 'combatants must be an array') unless combatants.is_a?(Array)
      raise HttpError.new(400, 'combatants must not be empty') if combatants.empty?

      scored = combatants.map do |combatant|
        raise HttpError.new(400, 'combatant must be an object') unless combatant.is_a?(Hash)

        name = combatant['name']
        dex = combatant['dex']
        roll = combatant['roll']

        raise HttpError.new(400, 'name must be a string') unless name.is_a?(String)
        raise HttpError.new(400, 'dex must be numeric') unless dex.is_a?(Numeric)
        raise HttpError.new(400, 'roll must be numeric') unless roll.is_a?(Numeric)

        { name: name, dex: dex, score: GameRules.numeric_json(roll + dex) }
      end

      ordered = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }
      order = ordered.map { |c| { name: c[:name], score: c[:score] } }

      session = {
        id: id,
        round: 1,
        turn_index: 0,
        order: order,
        conditions: Hash.new { |h, k| h[k] = [] }
      }
      save_session(session)

      [200, {
        id: id,
        round: session[:round],
        turn_index: session[:turn_index],
        active: active_combatant(session),
        order: order
      }]
    end

    def add_condition(id, body)
      session = find_session(id)

      target = body['target']
      condition = body['condition']
      duration_rounds = body['duration_rounds']

      raise HttpError.new(400, 'target must be a string') unless target.is_a?(String)
      raise HttpError.new(400, 'unknown target') unless session[:order].any? { |c| c[:name] == target }
      raise HttpError.new(400, 'condition must be a string') unless condition.is_a?(String)
      unless duration_rounds.is_a?(Integer) && duration_rounds.positive?
        raise HttpError.new(400, 'duration_rounds must be a positive integer')
      end

      session[:conditions][target] << { condition: condition, remaining_rounds: duration_rounds }
      save_session(session)

      [200, {
        target: target,
        conditions: session[:conditions][target]
      }]
    end

    def advance(id, _body)
      session = find_session(id)

      order = session[:order]
      session[:turn_index] += 1
      if session[:turn_index] >= order.length
        session[:turn_index] = 0
        session[:round] += 1
      end

      # Only the combatant whose turn is starting ticks down (and expires)
      # their own conditions, matching how duration is tracked round-to-round.
      active_name = order[session[:turn_index]][:name]
      active_conditions = session[:conditions][active_name]
      active_conditions.each { |c| c[:remaining_rounds] -= 1 }
      active_conditions.reject! { |c| c[:remaining_rounds] <= 0 }

      conditions_payload = {}
      session[:conditions].each { |name, conds| conditions_payload[name] = conds }

      save_session(session)

      [200, {
        id: session[:id],
        round: session[:round],
        turn_index: session[:turn_index],
        active: active_combatant(session),
        conditions: conditions_payload
      }]
    end

    def find_session(id)
      session = load_session(id)
      raise HttpError.new(404, 'unknown session id') unless session

      session
    end

    def active_combatant(session)
      combatant = session[:order][session[:turn_index]]
      { name: combatant[:name], score: combatant[:score] }
    end

    def load_session(id)
      rows = Database.query("SELECT id, round, turn_index, order_json, conditions_json FROM combat_sessions WHERE id = #{Database.escape(id)};")
      row = rows.first
      return nil unless row

      order = JSON.parse(row['order_json']).map { |c| { name: c['name'], score: c['score'] } }
      conditions_raw = JSON.parse(row['conditions_json'])
      conditions = Hash.new { |h, k| h[k] = [] }
      conditions_raw.each do |name, entries|
        conditions[name] = entries.map { |c| { condition: c['condition'], remaining_rounds: c['remaining_rounds'] } }
      end

      {
        id: row['id'],
        round: row['round'].to_i,
        turn_index: row['turn_index'].to_i,
        order: order,
        conditions: conditions
      }
    end

    def save_session(session)
      order_json = JSON.generate(session[:order])
      conditions_hash = {}
      session[:conditions].each { |name, entries| conditions_hash[name] = entries }
      conditions_json = JSON.generate(conditions_hash)

      Database.exec(<<~SQL)
        INSERT OR REPLACE INTO combat_sessions (id, round, turn_index, order_json, conditions_json)
        VALUES (
          #{Database.escape(session[:id])},
          #{Database.int(session[:round])},
          #{Database.int(session[:turn_index])},
          #{Database.escape(order_json)},
          #{Database.escape(conditions_json)}
        );
      SQL
    end
  end
end

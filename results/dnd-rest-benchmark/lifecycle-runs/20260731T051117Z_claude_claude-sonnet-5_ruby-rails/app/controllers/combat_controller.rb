# Encounter combat sessions: initiative order, conditions, and turn
# advancement. Session state lives in COMBAT_SESSIONS (see
# lib/persistent_collections.rb) and is persisted after every mutation.
class CombatController < ApplicationController
  def create_combat_session
    id = params[:id]
    combatants = params[:combatants]

    unless id.is_a?(String) && !id.empty?
      render json: { error: 'invalid id' }, status: :bad_request
      return
    end

    if COMBAT_SESSIONS.key?(id)
      render json: { error: 'duplicate id' }, status: :bad_request
      return
    end

    unless combatants.is_a?(Array) && !combatants.empty?
      render json: { error: 'invalid combatants' }, status: :bad_request
      return
    end

    entries = []
    combatants.each do |c|
      name = c[:name]
      dex = c[:dex]
      roll = c[:roll]

      unless name.is_a?(String) && !name.empty? && valid_integer?(dex) && valid_integer?(roll)
        render json: { error: 'invalid combatant' }, status: :bad_request
        return
      end

      dex = dex.to_i
      roll = roll.to_i
      entries << { name: name, dex: dex, score: roll + dex }
    end

    entries.sort! { |a, b| compare_by_score_dex_name(a, b) }

    COMBAT_SESSIONS[id] = {
      order: entries,
      round: 1,
      turn_index: 0,
      conditions: {}
    }

    render json: combat_session_json(id)
  end

  def add_combat_condition
    session = COMBAT_SESSIONS[params[:id]]
    if session.nil?
      render json: { error: 'session not found' }, status: :not_found
      return
    end

    target = params[:target]
    condition = params[:condition]
    duration_rounds = params[:duration_rounds]

    unless target.is_a?(String) && session[:order].any? { |e| e[:name] == target }
      render json: { error: 'invalid target' }, status: :bad_request
      return
    end

    unless condition.is_a?(String) && !condition.empty?
      render json: { error: 'invalid condition' }, status: :bad_request
      return
    end

    unless valid_integer?(duration_rounds) && duration_rounds.to_i > 0
      render json: { error: 'invalid duration_rounds' }, status: :bad_request
      return
    end

    session[:conditions][target] ||= []
    session[:conditions][target] << { condition: condition, remaining_rounds: duration_rounds.to_i }
    COMBAT_SESSIONS.persist(params[:id])

    render json: {
      target: target,
      conditions: session[:conditions][target]
    }
  end

  def advance_combat_turn
    session = COMBAT_SESSIONS[params[:id]]
    if session.nil?
      render json: { error: 'session not found' }, status: :not_found
      return
    end

    order = session[:order]
    session[:turn_index] += 1
    if session[:turn_index] >= order.length
      session[:turn_index] = 0
      session[:round] += 1
    end

    active_name = order[session[:turn_index]][:name]
    active_conditions = session[:conditions][active_name]
    if active_conditions
      active_conditions.each { |c| c[:remaining_rounds] -= 1 }
      active_conditions.reject! { |c| c[:remaining_rounds] <= 0 }
    end

    conditions = session[:conditions]
    COMBAT_SESSIONS.persist(params[:id])

    active = order[session[:turn_index]]
    render json: {
      id: params[:id],
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      conditions: conditions
    }
  end

  private

  def combat_session_json(id)
    session = COMBAT_SESSIONS[id]
    active = session[:order][session[:turn_index]]
    {
      id: id,
      round: session[:round],
      turn_index: session[:turn_index],
      active: { name: active[:name], score: active[:score] },
      order: session[:order].map { |e| { name: e[:name], score: e[:score] } }
    }
  end
end

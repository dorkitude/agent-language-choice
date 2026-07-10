module V1
  # In-memory store for combat sessions. Lives for the lifetime of the
  # server process. Guarded with a mutex for thread-safety under puma.
  module CombatStore
    SESSIONS = {} # id => { id:, round:, turn_index:, order:, conditions: }
    MUTEX = Mutex.new
  end

  class CombatSessionsController < ApplicationController
    # POST /v1/combat/sessions
    def create
      id = params[:id]
      combatants = params[:combatants]

      unless id.is_a?(String) && !id.empty?
        render json: { error: "id is required" }, status: :bad_request and return
      end

      unless combatants.is_a?(Array) && !combatants.empty?
        render json: { error: "combatants must be a non-empty array" },
               status: :bad_request and return
      end

      entries = []
      combatants.each do |c|
        name = c[:name]
        dex = c[:dex]
        roll = c[:roll]
        unless name.is_a?(String) && !name.empty?
          render json: { error: "combatant name is required" },
                 status: :bad_request and return
        end
        unless dex.is_a?(Integer) && roll.is_a?(Integer)
          render json: { error: "combatant dex and roll must be integers" },
                 status: :bad_request and return
        end
        entries << { name: name, dex: dex, score: roll + dex }
      end

      # score desc, dex desc, name asc
      ordered = entries.sort_by { |e| [-e[:score], -e[:dex], e[:name]] }

      session = {
        id: id,
        round: 1,
        turn_index: 0,
        order: ordered.map { |e| { name: e[:name], score: e[:score] } },
        conditions: {} # name => [{ condition:, remaining_rounds: }, ...]
      }

      CombatStore::MUTEX.synchronize do
        CombatStore::SESSIONS[id] = session
      end

      render json: create_response(session)
    end

    # POST /v1/combat/sessions/:id/conditions
    def add_condition
      session = find_session
      return unless session

      target = params[:target]
      condition = params[:condition]
      duration = params[:duration_rounds]

      unless target.is_a?(String) && combatant_exists?(session, target)
        render json: { error: "target must name a combatant in the session" },
               status: :bad_request and return
      end

      unless condition.is_a?(String)
        render json: { error: "condition must be a string" },
               status: :bad_request and return
      end

      unless duration.is_a?(Integer) && duration > 0
        render json: { error: "duration_rounds must be a positive integer" },
               status: :bad_request and return
      end

      CombatStore::MUTEX.synchronize do
        list = (session[:conditions][target] ||= [])
        list << { condition: condition, remaining_rounds: duration }
      end

      render json: {
        target: target,
        conditions: session[:conditions][target].map do |c|
          { condition: c[:condition], remaining_rounds: c[:remaining_rounds] }
        end
      }
    end

    # POST /v1/combat/sessions/:id/advance
    def advance
      session = find_session
      return unless session

      CombatStore::MUTEX.synchronize do
        order = session[:order]
        session[:turn_index] += 1
        if session[:turn_index] >= order.size
          session[:turn_index] = 0
          session[:round] += 1
        end

        active_name = order[session[:turn_index]][:name]
        list = session[:conditions][active_name]
        next unless list

        list.each { |c| c[:remaining_rounds] -= 1 }
        list.reject! { |c| c[:remaining_rounds] <= 0 }
        # Keep the combatant's key in the conditions map even when its
        # list becomes empty (expired conditions are removed but the
        # combatant entry remains so callers can see it was a target).
        session[:conditions][active_name] = list || []
      end

      render json: advance_response(session)
    end

    private

    def find_session
      id = params[:id]
      session = CombatStore::MUTEX.synchronize { CombatStore::SESSIONS[id] }
      unless session
        render json: { error: "unknown session" }, status: :not_found and return nil
      end
      session
    end

    def combatant_exists?(session, name)
      session[:order].any? { |e| e[:name] == name }
    end

    def create_response(session)
      active = session[:order][session[:turn_index]]
      {
        id: session[:id],
        round: session[:round],
        turn_index: session[:turn_index],
        active: { name: active[:name], score: active[:score] },
        order: session[:order].map { |e| { name: e[:name], score: e[:score] } }
      }
    end

    def advance_response(session)
      active = session[:order][session[:turn_index]]
      {
        id: session[:id],
        round: session[:round],
        turn_index: session[:turn_index],
        active: { name: active[:name], score: active[:score] },
        conditions: conditions_map(session)
      }
    end

    def conditions_map(session)
      map = {}
      session[:conditions].each do |name, list|
        map[name] = (list || []).map do |c|
          { condition: c[:condition], remaining_rounds: c[:remaining_rounds] }
        end
      end
      map
    end
  end
end

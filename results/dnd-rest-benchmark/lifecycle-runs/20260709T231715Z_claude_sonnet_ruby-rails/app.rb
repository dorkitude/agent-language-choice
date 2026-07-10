require 'rails'
require 'action_controller/railtie'

class DndApp < Rails::Application
  config.eager_load = false
  config.enable_reloading = false
  config.action_controller.perform_caching = false
  config.logger = Logger.new($stdout)
  config.log_level = :info
  config.secret_key_base = 'benchmark-secret-key-base'
  config.hosts.clear
end

module Dnd
  MONSTER_XP = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1100,
    '5' => 1800
  }.freeze

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  def self.count_multiplier(count)
    case count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  def self.numeric?(val)
    val.is_a?(Numeric)
  end

  def self.ability_modifier(score)
    ((score - 10) / 2.0).floor
  end

  def self.proficiency_bonus(level)
    case level
    when 1..4 then 2
    when 5..8 then 3
    when 9..12 then 4
    when 13..16 then 5
    when 17..20 then 6
    end
  end
end

class ApplicationController < ActionController::Base
  skip_forgery_protection

  rescue_from StandardError do |e|
    render json: { error: e.message }, status: :bad_request
  end
end

class HealthController < ApplicationController
  def show
    render json: { ok: true }
  end
end

class DiceController < ApplicationController
  def stats
    expression = params.require(:expression)
    match = /\A(\d+)d(\d+)([+-]\d+)?\z/.match(expression.to_s)
    return render json: { error: 'invalid expression' }, status: :bad_request unless match

    count = match[1].to_i
    sides = match[2].to_i
    modifier = match[3] ? match[3].to_i : 0

    return render json: { error: 'count and sides must be positive' }, status: :bad_request if count <= 0 || sides <= 0

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: count * 1 + modifier,
      max: count * sides + modifier,
      average: (count * (sides + 1) / 2.0) + modifier
    }
  end
end

class ChecksController < ApplicationController
  def ability
    roll = Integer(params.require(:roll))
    modifier = Integer(params.require(:modifier))
    dc = Integer(params.require(:dc))

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    render json: { total: total, success: success, margin: margin }
  end
end

class EncountersController < ApplicationController
  def adjusted_xp
    party = params.require(:party)
    monsters = params.require(:monsters)

    base_xp = 0
    monster_count = 0
    monsters.each do |m|
      cr = m[:cr].to_s
      count = Integer(m[:count])
      xp = Dnd::MONSTER_XP.fetch(cr) { raise "unsupported cr: #{cr}" }
      base_xp += xp * count
      monster_count += count
    end

    multiplier = Dnd.count_multiplier(monster_count)
    adjusted_xp = (base_xp * multiplier).round

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |p|
      level = Integer(p[:level])
      t = Dnd::LEVEL_THRESHOLDS.fetch(level) { raise "unsupported level: #{level}" }
      thresholds[:easy] += t[:easy]
      thresholds[:medium] += t[:medium]
      thresholds[:hard] += t[:hard]
      thresholds[:deadly] += t[:deadly]
    end

    difficulty = if adjusted_xp >= thresholds[:deadly]
                   'deadly'
                 elsif adjusted_xp >= thresholds[:hard]
                   'hard'
                 elsif adjusted_xp >= thresholds[:medium]
                   'medium'
                 elsif adjusted_xp >= thresholds[:easy]
                   'easy'
                 else
                   'trivial'
                 end

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty,
      thresholds: thresholds
    }
  end
end

class InitiativeController < ApplicationController
  def order
    combatants = params.require(:combatants)

    scored = combatants.map do |c|
      name = c[:name].to_s
      dex = Integer(c[:dex])
      roll = Integer(c[:roll])
      { name: name, dex: dex, score: roll + dex }
    end

    sorted = scored.sort do |a, b|
      cmp = b[:score] <=> a[:score]
      next cmp unless cmp.zero?

      cmp = b[:dex] <=> a[:dex]
      next cmp unless cmp.zero?

      a[:name] <=> b[:name]
    end

    render json: { order: sorted.map { |c| { name: c[:name], score: c[:score] } } }
  end
end

class CharactersController < ApplicationController
  def ability_modifier
    score = Integer(params.require(:score))
    raise 'score must be between 1 and 30' unless (1..30).cover?(score)

    render json: { score: score, modifier: Dnd.ability_modifier(score) }
  end

  def proficiency
    level = Integer(params.require(:level))
    raise 'level must be between 1 and 20' unless (1..20).cover?(level)

    render json: { level: level, proficiency_bonus: Dnd.proficiency_bonus(level) }
  end

  def derived_stats
    level = Integer(params.require(:level))
    raise 'level must be between 1 and 20' unless (1..20).cover?(level)

    abilities = params.require(:abilities)
    armor = params.require(:armor)

    modifiers = {}
    %i[str dex con int wis cha].each do |key|
      score = Integer(abilities.require(key))
      raise 'ability score must be between 1 and 30' unless (1..30).cover?(score)

      modifiers[key] = Dnd.ability_modifier(score)
    end

    armor_base = Integer(armor.require(:base))
    shield = [true, 'true'].include?(armor[:shield])
    dex_cap = Integer(armor.require(:dex_cap))

    proficiency_bonus = Dnd.proficiency_bonus(level)
    hp_max = level * (6 + modifiers[:con])
    shield_bonus = shield ? 2 : 0
    armor_class = armor_base + [modifiers[:dex], dex_cap].min + shield_bonus

    render json: {
      level: level,
      proficiency_bonus: proficiency_bonus,
      hp_max: hp_max,
      armor_class: armor_class,
      modifiers: modifiers
    }
  end
end

class CombatSession
  attr_reader :id, :order, :round, :turn_index, :conditions

  def initialize(id, combatants)
    @id = id
    @order = combatants
    @round = 1
    @turn_index = 0
    @conditions = Hash.new { |h, k| h[k] = [] }
    @tracked_targets = []
  end

  def active
    order[turn_index]
  end

  def add_condition(target, condition, duration_rounds)
    @tracked_targets << target unless @tracked_targets.include?(target)
    conditions[target] << { condition: condition, remaining_rounds: duration_rounds }
  end

  def advance
    @turn_index += 1
    if @turn_index >= order.length
      @turn_index = 0
      @round += 1
    end

    active_name = active[:name]
    remaining = conditions[active_name].filter_map do |c|
      updated = c.merge(remaining_rounds: c[:remaining_rounds] - 1)
      updated[:remaining_rounds] > 0 ? updated : nil
    end
    conditions[active_name] = remaining
  end

  def tracked_conditions
    @tracked_targets.each_with_object({}) { |name, h| h[name] = conditions[name] }
  end
end

class CombatController < ApplicationController
  @@sessions = {}

  def create
    id = params.require(:id).to_s
    raise 'session id already exists' if @@sessions.key?(id)

    combatants = params.require(:combatants)

    scored = combatants.map do |c|
      name = c[:name].to_s
      dex = Integer(c[:dex])
      roll = Integer(c[:roll])
      { name: name, dex: dex, score: roll + dex }
    end

    sorted = scored.sort do |a, b|
      cmp = b[:score] <=> a[:score]
      next cmp unless cmp.zero?

      cmp = b[:dex] <=> a[:dex]
      next cmp unless cmp.zero?

      a[:name] <=> b[:name]
    end

    order = sorted.map { |c| { name: c[:name], score: c[:score] } }
    session = CombatSession.new(id, order)
    @@sessions[id] = session

    render json: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: session.active,
      order: session.order
    }
  end

  def add_condition
    session = find_session
    return unless session

    target = params.require(:target).to_s
    condition = params.require(:condition).to_s
    duration_rounds = Integer(params.require(:duration_rounds))
    raise 'duration_rounds must be a positive integer' unless duration_rounds > 0

    unless session.order.any? { |c| c[:name] == target }
      return render json: { error: 'unknown target' }, status: :bad_request
    end

    session.add_condition(target, condition, duration_rounds)

    render json: {
      target: target,
      conditions: session.conditions[target]
    }
  end

  def advance
    session = find_session
    return unless session

    session.advance

    render json: {
      id: session.id,
      round: session.round,
      turn_index: session.turn_index,
      active: session.active,
      conditions: session.tracked_conditions
    }
  end

  private

  def find_session
    session = @@sessions[params[:id].to_s]
    render json: { error: 'unknown session id' }, status: :not_found unless session
    session
  end
end

DndApp.initialize!

DndApp.routes.draw do
  get '/health', to: 'health#show'
  post '/v1/dice/stats', to: 'dice#stats'
  post '/v1/checks/ability', to: 'checks#ability'
  post '/v1/encounters/adjusted-xp', to: 'encounters#adjusted_xp'
  post '/v1/initiative/order', to: 'initiative#order'
  post '/v1/characters/ability-modifier', to: 'characters#ability_modifier'
  post '/v1/characters/proficiency', to: 'characters#proficiency'
  post '/v1/characters/derived-stats', to: 'characters#derived_stats'
  post '/v1/combat/sessions', to: 'combat#create'
  post '/v1/combat/sessions/:id/conditions', to: 'combat#add_condition'
  post '/v1/combat/sessions/:id/advance', to: 'combat#advance'
end

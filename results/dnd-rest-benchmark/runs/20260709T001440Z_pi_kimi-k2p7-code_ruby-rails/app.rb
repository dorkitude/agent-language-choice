require 'rails'
require 'action_controller/railtie'

class DndApp < Rails::Application
  config.eager_load = false
  config.api_only = true
  config.secret_key_base = 'a' * 64
  config.logger = Logger.new(File::NULL)
  config.log_level = :fatal
  config.hosts = nil

  routes.draw do
    get '/health', to: 'health#index'

    post '/v1/dice/stats', to: 'dnd#dice_stats'
    post '/v1/checks/ability', to: 'dnd#ability_check'
    post '/v1/encounters/adjusted-xp', to: 'dnd#adjusted_xp'
    post '/v1/initiative/order', to: 'dnd#initiative_order'
  end
end

Rails.logger = DndApp.config.logger

class ApplicationController < ActionController::API
  before_action :parse_json_body

  private

  def parse_json_body
    body = request.raw_post.to_s
    @data = body.empty? ? {} : JSON.parse(body)
  rescue JSON::ParserError
    head :bad_request
  end

  def bad_request
    render json: { error: 'bad request' }, status: :bad_request
  end

  def require_int(key)
    value = @data[key.to_s]
    bad_request if !value.is_a?(Integer) && !performed?
    value
  end

  def require_string(key)
    value = @data[key.to_s]
    bad_request if !value.is_a?(String) && !performed?
    value
  end

  def require_array(key)
    value = @data[key.to_s]
    bad_request if !value.is_a?(Array) && !performed?
    value
  end
end

class HealthController < ApplicationController
  def index
    render json: { ok: true }
  end
end

class DndController < ApplicationController
  XP_BY_CR = {
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

  MULTIPLIERS = [
    [1..1, 1],
    [2..2, 1.5],
    [3..6, 2],
    [7..10, 2.5],
    [11..14, 3],
    [15..Float::INFINITY, 4]
  ].freeze

  DICE_RE = /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/.freeze

  def dice_stats
    expression = require_string(:expression)
    return if performed?

    match = expression.match(DICE_RE)
    return bad_request unless match

    dice_count = match[1].to_i
    sides = match[2].to_i
    modifier = match[3] ? (match[3] == '+' ? match[4].to_i : -match[4].to_i) : 0

    return bad_request if dice_count <= 0 || sides <= 0

    render json: {
      dice_count: dice_count,
      sides: sides,
      modifier: modifier,
      min: dice_count + modifier,
      max: dice_count * sides + modifier,
      average: dice_count * (sides + 1) / 2 + modifier
    }
  end

  def ability_check
    roll = require_int(:roll)
    modifier = require_int(:modifier)
    dc = require_int(:dc)
    return if performed?

    total = roll + modifier
    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end

  def adjusted_xp
    party = require_array(:party)
    monsters = require_array(:monsters)
    return if performed?

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = member['level']
      return bad_request unless level.is_a?(Integer)

      level_thresholds = LEVEL_THRESHOLDS[level]
      return bad_request unless level_thresholds

      thresholds[:easy] += level_thresholds[:easy]
      thresholds[:medium] += level_thresholds[:medium]
      thresholds[:hard] += level_thresholds[:hard]
      thresholds[:deadly] += level_thresholds[:deadly]
    end

    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      cr = monster['cr']
      count = monster['count']
      return bad_request unless cr.is_a?(String) && count.is_a?(Integer) && count > 0

      xp = XP_BY_CR[cr]
      return bad_request unless xp

      base_xp += xp * count
      monster_count += count
    end

    multiplier = MULTIPLIERS.find { |range, _| range.cover?(monster_count) }&.last || 1
    adjusted_xp = (base_xp * multiplier).to_i

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

  def initiative_order
    combatants = require_array(:combatants)
    return if performed?

    order = combatants.map do |combatant|
      name = combatant['name']
      dex = combatant['dex']
      roll = combatant['roll']
      return bad_request unless name.is_a?(String) && dex.is_a?(Integer) && roll.is_a?(Integer)

      { name: name, score: roll + dex, dex: dex }
    end

    order.sort_by! { |c| [-c[:score], -c[:dex], c[:name]] }

    render json: {
      order: order.map { |c| { name: c[:name], score: c[:score] } }
    }
  end
end

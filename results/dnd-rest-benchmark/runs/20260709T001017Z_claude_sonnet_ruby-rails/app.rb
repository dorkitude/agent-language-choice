require 'rails'
require 'action_controller/railtie'

class DndApp < Rails::Application
  config.eager_load = false
  config.hosts.clear
  config.logger = Logger.new($stdout)
  config.consider_all_requests_local = true
  config.api_only = true
  config.secret_key_base = 'dnd-rest-benchmark'
end

CR_XP = {
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

def count_multiplier(count)
  case count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

class ApiController < ActionController::API
  def health
    render json: { ok: true }
  end

  def dice_stats
    expression = params[:expression].to_s
    match = /\A(\d+)d(\d+)([+-]\d+)?\z/.match(expression)
    if match.nil?
      render json: { error: 'invalid expression' }, status: :bad_request
      return
    end

    count = match[1].to_i
    sides = match[2].to_i
    modifier = match[3] ? match[3].to_i : 0

    if count <= 0 || sides <= 0
      render json: { error: 'invalid expression' }, status: :bad_request
      return
    end

    min = count * 1 + modifier
    max = count * sides + modifier
    average = (count * (sides + 1) / 2.0) + modifier

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: average
    }
  end

  def ability_check
    roll = params[:roll].to_i
    modifier = params[:modifier].to_i
    dc = params[:dc].to_i

    total = roll + modifier
    success = total >= dc
    margin = total - dc

    render json: { total: total, success: success, margin: margin }
  end

  def adjusted_xp
    party = params[:party] || []
    monsters = params[:monsters] || []

    base_xp = 0
    monster_count = 0
    monsters.each do |m|
      cr = m[:cr].to_s
      count = m[:count].to_i
      base_xp += (CR_XP[cr] || 0) * count
      monster_count += count
    end

    multiplier = count_multiplier(monster_count)
    adjusted = (base_xp * multiplier).to_i

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |p|
      level = p[:level].to_i
      t = LEVEL_THRESHOLDS[level]
      next unless t

      thresholds[:easy] += t[:easy]
      thresholds[:medium] += t[:medium]
      thresholds[:hard] += t[:hard]
      thresholds[:deadly] += t[:deadly]
    end

    difficulty = 'trivial'
    difficulty = 'easy' if adjusted >= thresholds[:easy]
    difficulty = 'medium' if adjusted >= thresholds[:medium]
    difficulty = 'hard' if adjusted >= thresholds[:hard]
    difficulty = 'deadly' if adjusted >= thresholds[:deadly]

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted,
      difficulty: difficulty,
      thresholds: thresholds
    }
  end

  def initiative_order
    combatants = params[:combatants] || []

    scored = combatants.map do |c|
      dex = c[:dex].to_i
      roll = c[:roll].to_i
      {
        name: c[:name].to_s,
        dex: dex,
        score: roll + dex
      }
    end

    ordered = scored.sort do |a, b|
      cmp = b[:score] <=> a[:score]
      cmp = b[:dex] <=> a[:dex] if cmp == 0
      cmp = a[:name] <=> b[:name] if cmp == 0
      cmp
    end

    render json: {
      order: ordered.map { |c| { name: c[:name], score: c[:score] } }
    }
  end
end

DndApp.routes.draw do
  get '/health', to: 'api#health'
  post '/v1/dice/stats', to: 'api#dice_stats'
  post '/v1/checks/ability', to: 'api#ability_check'
  post '/v1/encounters/adjusted-xp', to: 'api#adjusted_xp'
  post '/v1/initiative/order', to: 'api#initiative_order'
end

DndApp.initialize!

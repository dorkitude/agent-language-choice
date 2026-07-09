require 'rails'
require 'action_controller/railtie'

class DndApp < Rails::Application
  config.load_defaults 8.1
  config.eager_load = false
  config.consider_all_requests_local = true
  config.logger = Logger.new($stdout)
  config.log_level = :warn
  config.secret_key_base = 'benchmark-secret-key-base-not-for-production'
  config.hosts.clear
  config.api_only = true

  routes.append do
    get  '/health',                  to: 'dnd#health'
    post '/v1/dice/stats',           to: 'dnd#dice_stats'
    post '/v1/checks/ability',       to: 'dnd#ability_check'
    post '/v1/encounters/adjusted-xp', to: 'dnd#adjusted_xp'
    post '/v1/initiative/order',     to: 'dnd#initiative_order'
  end
end

DndApp.initialize!

CR_XP = {
  '0'   => 10,
  '1/8' => 25,
  '1/4' => 50,
  '1/2' => 100,
  '1'   => 200,
  '2'   => 450,
  '3'   => 700,
  '4'   => 1100,
  '5'   => 1800
}.freeze

# Level => [easy, medium, hard, deadly]
LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

class DndController < ActionController::API
  def health
    render json: { ok: true }
  end

  def dice_stats
    expr = params[:expression]
    unless expr.is_a?(String) && (m = expr.strip.match(/\A(\d+)d(\d+)([+-]\d+)?\z/))
      return render json: { error: 'invalid expression' }, status: :bad_request
    end

    count    = Integer(m[1], 10)
    sides    = Integer(m[2], 10)
    modifier = m[3] ? Integer(m[3], 10) : 0

    if count <= 0 || sides <= 0
      return render json: { error: 'invalid expression' }, status: :bad_request
    end

    min = count * 1 + modifier
    max = count * sides + modifier
    average = (min + max) / 2.0

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: numeric(average)
    }
  end

  def ability_check
    roll     = Integer(params[:roll])
    modifier = Integer(params[:modifier])
    dc       = Integer(params[:dc])

    total = roll + modifier
    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  rescue ArgumentError, TypeError
    render json: { error: 'invalid input' }, status: :bad_request
  end

  def adjusted_xp
    party    = params[:party] || []
    monsters = params[:monsters] || []

    base_xp = 0
    monster_count = 0
    monsters.each do |mon|
      cr = mon[:cr].to_s
      xp = CR_XP[cr]
      return render json: { error: "unknown cr: #{cr}" }, status: :bad_request if xp.nil?

      count = Integer(mon[:count])
      base_xp += xp * count
      monster_count += count
    end

    multiplier = count_multiplier(monster_count)
    adjusted = base_xp * multiplier

    thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
    party.each do |member|
      level = Integer(member[:level])
      t = LEVEL_THRESHOLDS[level]
      return render json: { error: "unsupported level: #{level}" }, status: :bad_request if t.nil?

      thresholds[:easy]   += t[:easy]
      thresholds[:medium] += t[:medium]
      thresholds[:hard]   += t[:hard]
      thresholds[:deadly] += t[:deadly]
    end

    difficulty = 'trivial'
    difficulty = 'easy'   if adjusted >= thresholds[:easy]
    difficulty = 'medium' if adjusted >= thresholds[:medium]
    difficulty = 'hard'   if adjusted >= thresholds[:hard]
    difficulty = 'deadly' if adjusted >= thresholds[:deadly]

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: numeric(multiplier),
      adjusted_xp: numeric(adjusted),
      difficulty: difficulty,
      thresholds: thresholds
    }
  rescue ArgumentError, TypeError
    render json: { error: 'invalid input' }, status: :bad_request
  end

  def initiative_order
    combatants = params[:combatants] || []
    entries = combatants.map do |c|
      name = c[:name].to_s
      dex  = Integer(c[:dex])
      roll = Integer(c[:roll])
      { name: name, dex: dex, score: roll + dex }
    end

    entries.sort! do |a, b|
      cmp = b[:score] <=> a[:score]
      cmp = b[:dex] <=> a[:dex] if cmp.zero?
      cmp = a[:name] <=> b[:name] if cmp.zero?
      cmp
    end

    render json: {
      order: entries.map { |e| { name: e[:name], score: e[:score] } }
    }
  rescue ArgumentError, TypeError
    render json: { error: 'invalid input' }, status: :bad_request
  end

  private

  def count_multiplier(n)
    case n
    when 0    then 1
    when 1    then 1
    when 2    then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else 4
    end
  end

  # Render whole-number floats as integers (e.g. 10.0 -> 10, 1.5 stays 1.5).
  def numeric(value)
    if value.is_a?(Float) && value == value.to_i
      value.to_i
    else
      value
    end
  end
end

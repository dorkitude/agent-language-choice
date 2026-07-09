require "rails"
require "action_controller/railtie"

module DndApi
  class Application < Rails::Application
    config.api_only = true
    config.secret_key_base = "dndrestbenchmarksecretkeybase0123456789abcdef0123456789abcdef"
    config.eager_load = false
    config.cache_classes = true
    config.action_controller.perform_caching = false
    config.log_level = :fatal
    config.logger = Logger.new($stderr)
    config.logger.level = Logger::FATAL
    # Allow any host header (benchmark hits 127.0.0.1).
    config.hosts << /.*/
  end
end

# Minimal single-file Rails API controller implementing the D&D REST engine.
class DndController < ActionController::API
  XP_TABLE = {
    "0"   => 10,
    "1/8" => 25,
    "1/4" => 50,
    "1/2" => 100,
    "1"   => 200,
    "2"   => 450,
    "3"   => 700,
    "4"   => 1100,
    "5"   => 1800
  }.freeze

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  DICE_RE = /\A(\d+)d(\d+)(?:([+-])(\d+))?\z/

  # GET /health
  def health
    render json: { ok: true }
  end

  # POST /v1/dice/stats
  def dice_stats
    expr = body_json["expression"].to_s
    m = DICE_RE.match(expr)
    unless m
      render json: { error: "invalid expression" }, status: :bad_request and return
    end

    count = m[1].to_i
    sides = m[2].to_i
    if count <= 0 || sides <= 0
      render json: { error: "invalid expression" }, status: :bad_request and return
    end

    modifier = 0
    if m[3]
      mag = m[4].to_i
      modifier = (m[3] == "-" ? -mag : mag)
    end

    min_val = count + modifier
    max_val = count * sides + modifier
    avg = (min_val + max_val) / 2.0
    avg = avg.to_i if avg == avg.to_i

    render json: {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min_val,
      max: max_val,
      average: avg
    }
  end

  # POST /v1/checks/ability
  def ability_check
    b = body_json
    roll = as_int(b["roll"])
    mod = as_int(b["modifier"])
    dc = as_int(b["dc"])
    total = roll + mod
    render json: {
      total: total,
      success: total >= dc,
      margin: total - dc
    }
  end

  # POST /v1/encounters/adjusted-xp
  def adjusted_xp
    b = body_json
    party = b["party"] || []
    monsters = b["monsters"] || []

    base_xp = 0
    monster_count = 0
    monsters.each do |mon|
      cr = mon["cr"].to_s
      cnt = as_int(mon["count"])
      base_xp += XP_TABLE.fetch(cr, 0) * cnt
      monster_count += cnt
    end

    mult = multiplier_for(monster_count)
    adj = base_xp * mult
    adj = adj.to_i if adj.is_a?(Float) && adj == adj.to_i

    easy = medium = hard = deadly = 0
    party.each do |mem|
      lvl = as_int(mem["level"])
      th = LEVEL_THRESHOLDS.fetch(lvl, { easy: 0, medium: 0, hard: 0, deadly: 0 })
      easy += th[:easy]
      medium += th[:medium]
      hard += th[:hard]
      deadly += th[:deadly]
    end
    thresholds = { easy: easy, medium: medium, hard: hard, deadly: deadly }

    difficulty =
      if adj >= deadly
        "deadly"
      elsif adj >= hard
        "hard"
      elsif adj >= medium
        "medium"
      elsif adj >= easy
        "easy"
      else
        "trivial"
      end

    render json: {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: mult,
      adjusted_xp: adj,
      difficulty: difficulty,
      thresholds: thresholds
    }
  end

  # POST /v1/initiative/order
  def initiative_order
    b = body_json
    combatants = b["combatants"] || []
    entries = combatants.map do |c|
      dex = as_int(c["dex"])
      {
        name: c["name"].to_s,
        dex: dex,
        score: as_int(c["roll"]) + dex
      }
    end
    sorted = entries.sort_by { |e| [-e[:score], -e[:dex], e[:name]] }
    order = sorted.map { |e| { name: e[:name], score: e[:score] } }
    render json: { order: order }
  end

  private

  def body_json
    raw = request.raw_post.to_s
    return {} if raw.empty?
    JSON.parse(raw)
  rescue JSON::ParserError
    {}
  end

  def as_int(v)
    case v
    when Integer then v
    when Float then v.to_i
    when String then v.to_i
    else 0
    end
  end

  def multiplier_for(count)
    case count
    when 1 then 1
    when 2 then 1.5
    when 3..6 then 2
    when 7..10 then 2.5
    when 11..14 then 3
    else count >= 15 ? 4 : 1
    end
  end
end

DndApi::Application.routes.draw do
  get "/health", to: "dnd#health"
  post "/v1/dice/stats", to: "dnd#dice_stats"
  post "/v1/checks/ability", to: "dnd#ability_check"
  post "/v1/encounters/adjusted-xp", to: "dnd#adjusted_xp"
  post "/v1/initiative/order", to: "dnd#initiative_order"
end

# Boot the application (config.ru only requires + runs; it does not call
# initialize!, so initializers such as logger setup never run without this).
# Draw routes again AFTER init: the add_routing_paths initializer reloads
# routes from config/routes.rb (absent here), wiping the pre-init draw.
Rails.application.initialize!
DndApi::Application.routes.draw do
  get "/health", to: "dnd#health"
  post "/v1/dice/stats", to: "dnd#dice_stats"
  post "/v1/checks/ability", to: "dnd#ability_check"
  post "/v1/encounters/adjusted-xp", to: "dnd#adjusted_xp"
  post "/v1/initiative/order", to: "dnd#initiative_order"
end

require 'json'
require 'sinatra/base'

class DndRestApi < Sinatra::Base
  CR_XP = {
    '0' => 10,
    '1/8' => 25,
    '1/4' => 50,
    '1/2' => 100,
    '1' => 200,
    '2' => 450,
    '3' => 700,
    '4' => 1_100,
    '5' => 1_800
  }.freeze

  LEVEL_THRESHOLDS = {
    3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
  }.freeze

  configure do
    set :bind, '127.0.0.1'
    set :port, ENV.fetch('PORT', '4567').to_i
    set :server, :puma
  end

  before do
    content_type :json
  end

  helpers do
    def json_body
      JSON.parse(request.body.read)
    rescue JSON::ParserError
      halt 400, { error: 'invalid json' }.to_json
    end

    def require_integer(value)
      halt 400, { error: 'invalid request' }.to_json unless value.is_a?(Integer)
      value
    end

    def encounter_multiplier(count)
      case count
      when 1 then 1
      when 2 then 1.5
      when 3..6 then 2
      when 7..10 then 2.5
      when 11..14 then 3
      else 4
      end
    end

    def difficulty_for(adjusted_xp, thresholds)
      return 'deadly' if adjusted_xp >= thresholds[:deadly]
      return 'hard' if adjusted_xp >= thresholds[:hard]
      return 'medium' if adjusted_xp >= thresholds[:medium]
      return 'easy' if adjusted_xp >= thresholds[:easy]

      'trivial'
    end
  end

  get '/health' do
    { ok: true }.to_json
  end

  post '/v1/dice/stats' do
    expression = json_body['expression']
    match = expression.is_a?(String) && expression.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/)
    halt 400, { error: 'invalid expression' }.to_json unless match

    count = match[1].to_i
    sides = match[2].to_i
    halt 400, { error: 'invalid expression' }.to_json unless count.positive? && sides.positive?

    modifier = match[4] ? match[4].to_i : 0
    modifier = -modifier if match[3] == '-'
    min = count + modifier
    max = (count * sides) + modifier
    average_sum = min + max

    {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: average_sum.even? ? average_sum / 2 : average_sum / 2.0
    }.to_json
  end

  post '/v1/checks/ability' do
    body = json_body
    roll = require_integer(body['roll'])
    modifier = require_integer(body['modifier'])
    dc = require_integer(body['dc'])
    total = roll + modifier

    { total: total, success: total >= dc, margin: total - dc }.to_json
  end

  post '/v1/encounters/adjusted-xp' do
    body = json_body
    party = body['party']
    monsters = body['monsters']
    halt 400, { error: 'invalid request' }.to_json unless party.is_a?(Array) && monsters.is_a?(Array)

    thresholds = Hash.new(0)
    party.each do |member|
      level = member.is_a?(Hash) ? member['level'] : nil
      member_thresholds = LEVEL_THRESHOLDS[level]
      halt 400, { error: 'unsupported level' }.to_json unless member_thresholds

      member_thresholds.each { |key, value| thresholds[key] += value }
    end

    base_xp = 0
    monster_count = 0
    monsters.each do |monster|
      halt 400, { error: 'invalid request' }.to_json unless monster.is_a?(Hash)

      cr = monster['cr']
      count = require_integer(monster['count'])
      xp = CR_XP[cr]
      halt 400, { error: 'unsupported cr' }.to_json unless xp && count.positive?

      base_xp += xp * count
      monster_count += count
    end

    multiplier = monster_count.zero? ? 0 : encounter_multiplier(monster_count)
    adjusted_xp = base_xp * multiplier

    {
      base_xp: base_xp,
      monster_count: monster_count,
      multiplier: multiplier,
      adjusted_xp: adjusted_xp,
      difficulty: difficulty_for(adjusted_xp, thresholds),
      thresholds: {
        easy: thresholds[:easy],
        medium: thresholds[:medium],
        hard: thresholds[:hard],
        deadly: thresholds[:deadly]
      }
    }.to_json
  end

  post '/v1/initiative/order' do
    combatants = json_body['combatants']
    halt 400, { error: 'invalid request' }.to_json unless combatants.is_a?(Array)

    order = combatants.map do |combatant|
      halt 400, { error: 'invalid request' }.to_json unless combatant.is_a?(Hash)

      name = combatant['name']
      dex = require_integer(combatant['dex'])
      roll = require_integer(combatant['roll'])
      halt 400, { error: 'invalid request' }.to_json unless name.is_a?(String)

      { name: name, dex: dex, score: roll + dex }
    end.sort_by { |combatant| [-combatant[:score], -combatant[:dex], combatant[:name]] }

    { order: order.map { |combatant| { name: combatant[:name], score: combatant[:score] } } }.to_json
  end

  run! if app_file == $PROGRAM_NAME
end

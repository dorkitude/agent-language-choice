require 'sinatra/base'
require 'json'

class DnDApp < Sinatra::Base
  set :environment, :production
  disable :show_exceptions
  disable :raise_errors

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

  LEVEL_THRESHOLDS = {
    3 => { 'easy' => 75, 'medium' => 150, 'hard' => 225, 'deadly' => 400 }
  }.freeze

  helpers do
    def json_body
      raw = request.body.read
      raw.empty? ? {} : JSON.parse(raw)
    rescue JSON::ParserError
      halt 400, { error: 'invalid JSON' }.to_json
    end

    def bad_request(message = 'invalid request')
      halt 400, { error: message }.to_json
    end

    def multiplier_for(count)
      case count
      when 1 then 1
      when 2 then 1.5
      when 3..6 then 2
      when 7..10 then 2.5
      when 11..14 then 3
      else 4
      end
    end

    def numeric(number)
      number == number.to_i ? number.to_i : number
    end
  end

  before do
    content_type :json
  end

  get '/health' do
    { ok: true }.to_json
  end

  post '/v1/dice/stats' do
    data = json_body
    expr = data['expression']
    bad_request('expression required') unless expr.is_a?(String)

    match = expr.strip.match(/\A(\d+)d(\d+)([+-]\d+)?\z/)
    bad_request('invalid expression') unless match

    count = match[1].to_i
    sides = match[2].to_i
    modifier = match[3] ? match[3].to_i : 0
    bad_request('count and sides must be positive') unless count > 0 && sides > 0

    min = count * 1 + modifier
    max = count * sides + modifier
    average = (min + max) / 2.0

    {
      dice_count: count,
      sides: sides,
      modifier: modifier,
      min: min,
      max: max,
      average: numeric(average)
    }.to_json
  end

  post '/v1/checks/ability' do
    data = json_body
    roll = data['roll']
    modifier = data['modifier']
    dc = data['dc']
    bad_request('roll, modifier, dc required') unless [roll, modifier, dc].all? { |v| v.is_a?(Integer) }

    total = roll + modifier
    {
      total: total,
      success: total >= dc,
      margin: total - dc
    }.to_json
  end

  post '/v1/encounters/adjusted-xp' do
    data = json_body
    party = data['party']
    monsters = data['monsters']
    bad_request('party and monsters required') unless party.is_a?(Array) && monsters.is_a?(Array)

    base_xp = 0
    monster_count = 0
    monsters.each do |m|
      bad_request('invalid monster') unless m.is_a?(Hash)
      cr = m['cr'].to_s
      count = m['count']
      bad_request('unknown CR') unless CR_XP.key?(cr)
      bad_request('invalid count') unless count.is_a?(Integer) && count >= 0
      base_xp += CR_XP[cr] * count
      monster_count += count
    end

    multiplier = multiplier_for(monster_count)
    adjusted_xp = base_xp * multiplier

    thresholds = { 'easy' => 0, 'medium' => 0, 'hard' => 0, 'deadly' => 0 }
    party.each do |member|
      bad_request('invalid party member') unless member.is_a?(Hash)
      level = member['level']
      bad_request('unknown level') unless level.is_a?(Integer) && LEVEL_THRESHOLDS.key?(level)
      LEVEL_THRESHOLDS[level].each { |k, v| thresholds[k] += v }
    end

    difficulty = 'trivial'
    %w[easy medium hard deadly].each do |tier|
      difficulty = tier if adjusted_xp >= thresholds[tier]
    end

    {
      base_xp: numeric(base_xp),
      monster_count: monster_count,
      multiplier: numeric(multiplier),
      adjusted_xp: numeric(adjusted_xp),
      difficulty: difficulty,
      thresholds: {
        easy: thresholds['easy'],
        medium: thresholds['medium'],
        hard: thresholds['hard'],
        deadly: thresholds['deadly']
      }
    }.to_json
  end

  post '/v1/initiative/order' do
    data = json_body
    combatants = data['combatants']
    bad_request('combatants required') unless combatants.is_a?(Array)

    entries = combatants.map do |c|
      bad_request('invalid combatant') unless c.is_a?(Hash)
      name = c['name']
      dex = c['dex']
      roll = c['roll']
      bad_request('invalid combatant fields') unless name.is_a?(String) && dex.is_a?(Integer) && roll.is_a?(Integer)
      { name: name, dex: dex, score: roll + dex }
    end

    ordered = entries.sort_by.with_index { |e, i| [-e[:score], -e[:dex], e[:name], i] }

    { order: ordered.map { |e| { name: e[:name], score: e[:score] } } }.to_json
  end

  error 404 do
    { error: 'not found' }.to_json
  end
end

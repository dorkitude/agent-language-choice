require 'sinatra'
require 'json'

set :bind, '127.0.0.1'
set :port, (ENV['PORT'] || 4567).to_i

before do
  content_type :json
end

def json_error(status, message)
  halt status, { error: message }.to_json
end

def parse_body
  begin
    JSON.parse(request.body.read)
  rescue JSON::ParserError
    json_error(400, 'invalid JSON')
  end
end

get '/health' do
  { ok: true }.to_json
end

post '/v1/dice/stats' do
  body = parse_body
  expr = body['expression']
  json_error(400, 'expression is required') unless expr.is_a?(String)

  match = expr.match(/\A(\d+)d(\d+)([+-]\d+)?\z/)
  json_error(400, 'invalid expression') unless match

  count = match[1].to_i
  sides = match[2].to_i
  modifier = match[3] ? match[3].to_i : 0

  json_error(400, 'count must be positive') unless count > 0
  json_error(400, 'sides must be positive') unless sides > 0

  min = count * 1 + modifier
  max = count * sides + modifier
  average = (count * (sides + 1) / 2.0) + modifier
  average = average.to_i if average == average.to_i

  {
    dice_count: count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: average
  }.to_json
end

post '/v1/checks/ability' do
  body = parse_body
  roll = body['roll']
  modifier = body['modifier']
  dc = body['dc']

  json_error(400, 'roll, modifier, and dc are required') unless roll.is_a?(Numeric) && modifier.is_a?(Numeric) && dc.is_a?(Numeric)

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  { total: total, success: success, margin: margin }.to_json
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

LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

post '/v1/encounters/adjusted-xp' do
  body = parse_body
  party = body['party']
  monsters = body['monsters']

  json_error(400, 'party and monsters are required') unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0
  monsters.each do |m|
    cr = m['cr'].to_s
    count = m['count']
    xp = CR_XP[cr]
    json_error(400, "unsupported cr: #{cr}") unless xp
    base_xp += xp * count
    monster_count += count
  end

  multiplier = multiplier_for(monster_count)
  adjusted_xp = base_xp * multiplier

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  party.each do |p|
    level = p['level']
    t = LEVEL_THRESHOLDS[level]
    json_error(400, "unsupported level: #{level}") unless t
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

  {
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: thresholds
  }.to_json
end

post '/v1/initiative/order' do
  body = parse_body
  combatants = body['combatants']
  json_error(400, 'combatants is required') unless combatants.is_a?(Array)

  scored = combatants.map do |c|
    { name: c['name'], dex: c['dex'], score: c['roll'] + c['dex'] }
  end

  ordered = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }

  { order: ordered.map { |c| { name: c[:name], score: c[:score] } } }.to_json
end

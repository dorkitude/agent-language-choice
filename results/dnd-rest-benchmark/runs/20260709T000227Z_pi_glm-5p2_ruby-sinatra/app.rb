require 'sinatra'
require 'json'

set :show_exceptions, :none
set :raise_errors, false

before do
  content_type :json
end

error do
  [500, { 'Content-Type' => 'application/json' },
   [JSON.generate({ error: 'internal server error' })]
  ]
end

# CR -> XP
XP_TABLE = {
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

# level -> [easy, medium, hard, deadly]
THRESHOLDS = {
  1  => [25, 50, 75, 100],
  2  => [50, 100, 150, 200],
  3  => [75, 150, 225, 400],
  4  => [125, 250, 375, 500],
  5  => [250, 500, 750, 1100],
  6  => [300, 600, 900, 1400],
  7  => [350, 750, 1100, 1700],
  8  => [450, 900, 1400, 2100],
  9  => [550, 1100, 1600, 2400],
  10 => [600, 1200, 1900, 2800],
  11 => [800, 1600, 2400, 3600],
  12 => [1000, 2000, 3000, 4500],
  13 => [1100, 2200, 3300, 5100],
  14 => [1250, 2500, 3800, 5700],
  15 => [1400, 2800, 4300, 6400],
  16 => [1600, 3200, 4800, 7200],
  17 => [2000, 3900, 5900, 8800],
  18 => [2100, 4200, 6300, 9500],
  19 => [2400, 4700, 7200, 10900],
  20 => [2800, 5700, 8500, 12700]
}.freeze

helpers do
  def json_body
    body = request.body.read.to_s
    body = '{}' if body.strip.empty?
    JSON.parse(body)
  rescue JSON::ParserError
    halt 400, JSON.generate({ error: 'invalid json' })
  end

  def norm(n)
    n.is_a?(Float) && n == n.to_i ? n.to_i : n
  end

  def multiplier_for(count)
    return 1   if count <= 1
    return 1.5 if count == 2
    return 2   if count <= 6
    return 2.5 if count <= 10
    return 3   if count <= 14
    4
  end
end

get '/health' do
  JSON.generate({ ok: true })
end

post '/v1/dice/stats' do
  data = json_body
  expr = data['expression'].to_s.strip
  m = expr.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/i)
  halt 400, JSON.generate({ error: 'invalid expression' }) unless m

  count = m[1].to_i
  sides = m[2].to_i
  modifier = 0
  if m[3]
    modifier = m[4].to_i
    modifier = -modifier if m[3] == '-'
  end

  halt 400, JSON.generate({ error: 'invalid expression' }) if count <= 0 || sides <= 0

  min_roll = count + modifier
  max_roll = count * sides + modifier
  avg = count * (1 + sides) / 2.0 + modifier

  JSON.generate(
    dice_count: count,
    sides: sides,
    modifier: modifier,
    min: min_roll,
    max: max_roll,
    average: norm(avg)
  )
end

post '/v1/checks/ability' do
  data = json_body
  roll = data['roll'].to_i
  modifier = data['modifier'].to_i
  dc = data['dc'].to_i
  total = roll + modifier
  JSON.generate(
    total: total,
    success: total >= dc,
    margin: total - dc
  )
end

post '/v1/encounters/adjusted-xp' do
  data = json_body
  party = data['party'] || []
  monsters = data['monsters'] || []

  base_xp = 0
  monster_count = 0
  monsters.each do |mon|
    cr = mon['cr'].to_s
    count = mon['count'].to_i
    xp = XP_TABLE[cr]
    halt 400, JSON.generate({ error: 'unsupported cr' }) unless xp
    base_xp += xp * count
    monster_count += count
  end

  easy = medium = hard = deadly = 0
  party.each do |member|
    level = member['level'].to_i
    t = THRESHOLDS[level]
    halt 400, JSON.generate({ error: 'unsupported level' }) unless t
    easy += t[0]
    medium += t[1]
    hard += t[2]
    deadly += t[3]
  end

  multiplier = multiplier_for(monster_count)
  adjusted_xp = base_xp * multiplier

  difficulty = if adjusted_xp >= deadly
                 'deadly'
               elsif adjusted_xp >= hard
                 'hard'
               elsif adjusted_xp >= medium
                 'medium'
               elsif adjusted_xp >= easy
                 'easy'
               else
                 'trivial'
               end

  JSON.generate(
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: norm(multiplier),
    adjusted_xp: norm(adjusted_xp),
    difficulty: difficulty,
    thresholds: {
      easy: easy,
      medium: medium,
      hard: hard,
      deadly: deadly
    }
  )
end

post '/v1/initiative/order' do
  data = json_body
  combatants = data['combatants'] || []

  scored = combatants.map do |c|
    roll = c['roll'].to_i
    dex = c['dex'].to_i
    { name: c['name'].to_s, dex: dex, roll: roll, score: roll + dex }
  end

  ordered = scored.sort_by { |c| [-c[:score], -c[:dex], c[:name]] }

  JSON.generate(
    order: ordered.map { |c| { name: c[:name], score: c[:score] } }
  )
end

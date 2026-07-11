require 'sinatra'
require 'json'

set :server, :puma
set :show_exceptions, :none
set :raise_sinatra_not_found, true

before do
  content_type :json
end

not_found do
  content_type :json
  JSON.generate({ "error" => "not found" })
end

error 500 do
  content_type :json
  JSON.generate({ "error" => "internal server error" })
end

# ---- helpers ----

def json_body
  raw = request.body.read
  halt 400, JSON.generate({ "error" => "invalid json" }) if raw.nil? || raw.empty?
  data = JSON.parse(raw)
  halt 400, JSON.generate({ "error" => "invalid json" }) unless data.is_a?(Hash)
  data
rescue JSON::ParserError
  halt 400, JSON.generate({ "error" => "invalid json" })
end

def bad_request!(msg = "invalid input")
  halt 400, JSON.generate({ "error" => msg })
end

def integer?(v)
  v.is_a?(Integer)
end

# Convert a whole-number float to an integer so 1700 serializes as 1700,
# while leaving genuine fractions (e.g. 1.5, 52.5) intact.
def normalize_num(n)
  (n.is_a?(Float) && n == n.to_i) ? n.to_i : n
end

# D&D ability modifier: floor((score - 10) / 2). Uses float division then
# floor so negative halves floor correctly (score 9 -> -1, not 0).
def ability_modifier(score)
  ((score - 10) / 2.0).floor
end

# D&D proficiency bonus by level: 1-4 -> 2, 5-8 -> 3, 9-12 -> 4,
# 13-16 -> 5, 17-20 -> 6. Equivalent to 2 + floor((level - 1) / 4).
def proficiency_bonus(level)
  2 + (level - 1) / 4
end

ABILITY_KEYS = %w[str dex con int wis cha].freeze

# ---- routes ----

get '/health' do
  JSON.generate({ "ok" => true })
end

post '/v1/dice/stats' do
  data = json_body
  expr = data["expression"]
  bad_request!("invalid expression") unless expr.is_a?(String)

  m = expr.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/)
  bad_request!("invalid expression") unless m

  count = m[1].to_i
  sides = m[2].to_i
  modifier = 0
  if m[3]
    val = m[4].to_i
    modifier = (m[3] == "-") ? -val : val
  end

  bad_request!("invalid expression") if count <= 0 || sides <= 0

  min_v = count + modifier
  max_v = count * sides + modifier
  # Use float division so odd midpoints (e.g. 19/2 -> 9.5) are not
  # truncated. normalize_num collapses whole floats back to ints so
  # even midpoints (e.g. 20/2 -> 10) serialize as "10" not "10.0".
  average = normalize_num((min_v + max_v) / 2.0)

  JSON.generate({
    "dice_count" => count,
    "sides" => sides,
    "modifier" => modifier,
    "min" => min_v,
    "max" => max_v,
    "average" => average
  })
end

post '/v1/checks/ability' do
  data = json_body
  roll = data["roll"]
  modifier = data["modifier"]
  dc = data["dc"]
  bad_request!("invalid input") unless [roll, modifier, dc].all? { |v| integer?(v) }

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  JSON.generate({
    "total" => total,
    "success" => success,
    "margin" => margin
  })
end

CR_XP = {
  "0" => 10, "1/8" => 25, "1/4" => 50, "1/2" => 100,
  "1" => 200, "2" => 450, "3" => 700, "4" => 1100, "5" => 1800
}.freeze

LEVEL_THRESHOLDS = {
  3 => { "easy" => 75, "medium" => 150, "hard" => 225, "deadly" => 400 }
}.freeze

def multiplier_for(monster_count)
  case monster_count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4 # 15+
  end
end

post '/v1/encounters/adjusted-xp' do
  data = json_body
  party = data["party"]
  monsters = data["monsters"]
  bad_request!("invalid input") unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0

  monsters.each do |mon|
    cr = mon["cr"]
    count = mon["count"]
    bad_request!("invalid input") unless cr && count.is_a?(Integer)
    cr_key = cr.to_s
    bad_request!("invalid input") unless CR_XP.key?(cr_key)
    base_xp += CR_XP[cr_key] * count
    monster_count += count
  end

  multiplier = multiplier_for(monster_count)
  adjusted_xp = base_xp * multiplier

  easy = medium = hard = deadly = 0
  party.each do |member|
    level = member["level"]
    th = LEVEL_THRESHOLDS[level] || LEVEL_THRESHOLDS[3]
    easy += th["easy"]
    medium += th["medium"]
    hard += th["hard"]
    deadly += th["deadly"]
  end

  difficulty =
    if adjusted_xp >= deadly
      "deadly"
    elsif adjusted_xp >= hard
      "hard"
    elsif adjusted_xp >= medium
      "medium"
    elsif adjusted_xp >= easy
      "easy"
    else
      "trivial"
    end

  JSON.generate({
    "base_xp" => base_xp,
    "monster_count" => monster_count,
    "multiplier" => normalize_num(multiplier),
    "adjusted_xp" => normalize_num(adjusted_xp),
    "difficulty" => difficulty,
    "thresholds" => {
      "easy" => easy,
      "medium" => medium,
      "hard" => hard,
      "deadly" => deadly
    }
  })
end

post '/v1/initiative/order' do
  data = json_body
  combatants = data["combatants"]
  bad_request!("invalid input") unless combatants.is_a?(Array)

  entries = combatants.map do |c|
    name = c["name"]
    dex = c["dex"]
    roll = c["roll"]
    bad_request!("invalid input") unless name.is_a?(String) && integer?(dex) && integer?(roll)
    { name: name, dex: dex, score: roll + dex }
  end

  order = entries.sort_by { |e| [-e[:score], -e[:dex], e[:name]] }

  JSON.generate({
    "order" => order.map { |e| { "name" => e[:name], "score" => e[:score] } }
  })
end

post '/v1/characters/ability-modifier' do
  data = json_body
  score = data["score"]
  bad_request!("invalid input") unless integer?(score) && score.between?(1, 30)
  JSON.generate({ "score" => score, "modifier" => ability_modifier(score) })
end

post '/v1/characters/proficiency' do
  data = json_body
  level = data["level"]
  bad_request!("invalid input") unless integer?(level) && level.between?(1, 20)
  JSON.generate({ "level" => level, "proficiency_bonus" => proficiency_bonus(level) })
end

post '/v1/characters/derived-stats' do
  data = json_body
  level = data["level"]
  bad_request!("invalid input") unless integer?(level) && level.between?(1, 20)

  abilities = data["abilities"]
  bad_request!("invalid input") unless abilities.is_a?(Hash)
  modifiers = {}
  ABILITY_KEYS.each do |k|
    v = abilities[k]
    bad_request!("invalid input") unless integer?(v)
    modifiers[k] = ability_modifier(v)
  end

  armor = data["armor"]
  bad_request!("invalid input") unless armor.is_a?(Hash)
  base = armor["base"]
  dex_cap = armor["dex_cap"]
  bad_request!("invalid input") unless integer?(base) && integer?(dex_cap)

  shield_bonus = armor["shield"] == true ? 2 : 0
  dex_mod = modifiers["dex"]
  armor_class = base + [dex_mod, dex_cap].min + shield_bonus
  hp_max = level * (6 + modifiers["con"])

  JSON.generate({
    "level" => level,
    "proficiency_bonus" => proficiency_bonus(level),
    "hp_max" => hp_max,
    "armor_class" => armor_class,
    "modifiers" => modifiers
  })
end

# ---- combat state (stateful, in-memory) ----

# Session shape:
#   { "id" => String, "round" => Int, "turn_index" => Int,
#     "order" => [{"name"=>..,"score"=>..}, ...],
#     "conditions" => { name => [{"condition"=>..,"remaining_rounds"=>..}, ...] } }
COMBAT_SESSIONS = {}
COMBAT_LOCK = Mutex.new

def condition_entry(c)
  { "condition" => c["condition"], "remaining_rounds" => c["remaining_rounds"] }
end

# Map of every combatant that still has at least one condition.
def conditions_map(session)
  map = {}
  session["conditions"].each do |name, list|
    next if list.nil? || list.empty?
    map[name] = list.map { |c| condition_entry(c) }
  end
  map
end

post '/v1/combat/sessions' do
  data = json_body
  id = data["id"]
  combatants = data["combatants"]
  bad_request!("invalid input") unless id.is_a?(String) && !id.empty?
  bad_request!("invalid input") unless combatants.is_a?(Array) && !combatants.empty?

  built = combatants.map do |c|
    name = c["name"]
    dex = c["dex"]
    roll = c["roll"]
    bad_request!("invalid input") unless name.is_a?(String) && integer?(dex) && integer?(roll)
    { name: name, dex: dex, score: roll + dex }
  end

  # Initiative: score desc, dex desc, name asc.
  order = built.sort_by { |e| [-e[:score], -e[:dex], e[:name]] }
               .map { |e| { "name" => e[:name], "score" => e[:score] } }

  session = {
    "id" => id,
    "round" => 1,
    "turn_index" => 0,
    "order" => order,
    "conditions" => {}
  }
  COMBAT_LOCK.synchronize { COMBAT_SESSIONS[id] = session }

  JSON.generate({
    "id" => id,
    "round" => 1,
    "turn_index" => 0,
    "active" => order[0],
    "order" => order
  })
end

post '/v1/combat/sessions/:id/conditions' do
  sid = params[:id]
  COMBAT_LOCK.synchronize do
    session = COMBAT_SESSIONS[sid]
    halt 404, JSON.generate({ "error" => "not found" }) unless session

    data = json_body
    target = data["target"]
    condition = data["condition"]
    duration = data["duration_rounds"]
    bad_request!("invalid input") unless target.is_a?(String) &&
                                        condition.is_a?(String) &&
                                        integer?(duration) && duration > 0
    names = session["order"].map { |e| e["name"] }
    bad_request!("invalid input") unless names.include?(target)

    list = (session["conditions"][target] ||= [])
    list << { "condition" => condition, "remaining_rounds" => duration }

    JSON.generate({
      "target" => target,
      "conditions" => list.map { |c| condition_entry(c) }
    })
  end
end

post '/v1/combat/sessions/:id/advance' do
  sid = params[:id]
  COMBAT_LOCK.synchronize do
    session = COMBAT_SESSIONS[sid]
    halt 404, JSON.generate({ "error" => "not found" }) unless session

    order = session["order"]
    next_index = session["turn_index"] + 1
    if next_index >= order.length
      next_index = 0
      session["round"] += 1
    end
    session["turn_index"] = next_index
    active = order[next_index]

    # At the start of this combatant's turn, tick down their conditions.
    active_name = active["name"]
    if (list = session["conditions"][active_name])
      list.each { |c| c["remaining_rounds"] -= 1 }
      list.reject! { |c| c["remaining_rounds"] <= 0 }
      session["conditions"].delete(active_name) if list.empty?
    end

    JSON.generate({
      "id" => session["id"],
      "round" => session["round"],
      "turn_index" => session["turn_index"],
      "active" => active,
      "conditions" => conditions_map(session)
    })
  end
end

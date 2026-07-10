#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "socket"

CR_XP = {
  "0" => 10,
  "1/8" => 25,
  "1/4" => 50,
  "1/2" => 100,
  "1" => 200,
  "2" => 450,
  "3" => 700,
  "4" => 1100,
  "5" => 1800
}.freeze

LEVEL_THRESHOLDS = {
  3 => { "easy" => 75, "medium" => 150, "hard" => 225, "deadly" => 400 }
}.freeze

COMBAT_SESSIONS = {}

def integer?(value)
  value.is_a?(Integer)
end

def boolean?(value)
  value == true || value == false
end

def require_integer_in_range(value, range, name)
  raise ArgumentError, "invalid #{name}" unless integer?(value) && range.cover?(value)

  value
end

def multiplier_for(count)
  case count
  when 0 then 1
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

def format_number(value)
  value.is_a?(Float) && value == value.to_i ? value.to_i : value
end

def difficulty_for(adjusted_xp, thresholds)
  %w[deadly hard medium easy].each do |name|
    return name if adjusted_xp >= thresholds.fetch(name)
  end
  "trivial"
end

def dice_stats(data)
  expression = data["expression"]
  match = /\A([0-9]+)d([0-9]+)(?:([+-])([0-9]+))?\z/.match(expression.to_s)
  raise ArgumentError, "invalid dice expression" unless match

  count = match[1].to_i
  sides = match[2].to_i
  raise ArgumentError, "invalid dice expression" unless count.positive? && sides.positive?

  modifier = match[4] ? match[4].to_i : 0
  modifier = -modifier if match[3] == "-"
  min = count + modifier
  max = (count * sides) + modifier
  average = (min + max) / 2.0

  {
    "dice_count" => count,
    "sides" => sides,
    "modifier" => modifier,
    "min" => min,
    "max" => max,
    "average" => format_number(average)
  }
end

def ability_check(data)
  roll = data["roll"]
  modifier = data["modifier"]
  dc = data["dc"]
  raise ArgumentError, "invalid ability check" unless [roll, modifier, dc].all? { |value| integer?(value) }

  total = roll + modifier
  {
    "total" => total,
    "success" => total >= dc,
    "margin" => total - dc
  }
end

def ability_modifier_for(score)
  ((score - 10) / 2.0).floor
end

def ability_modifier(data)
  score = require_integer_in_range(data["score"], 1..30, "ability score")
  { "score" => score, "modifier" => ability_modifier_for(score) }
end

def proficiency_bonus_for(level)
  2 + ((level - 1) / 4)
end

def proficiency(data)
  level = require_integer_in_range(data["level"], 1..20, "level")
  { "level" => level, "proficiency_bonus" => proficiency_bonus_for(level) }
end

def derived_stats(data)
  level = require_integer_in_range(data["level"], 1..20, "level")
  abilities = data["abilities"]
  armor = data["armor"]
  raise ArgumentError, "invalid abilities" unless abilities.is_a?(Hash)
  raise ArgumentError, "invalid armor" unless armor.is_a?(Hash)

  modifiers = {}
  %w[str dex con int wis cha].each do |ability|
    score = require_integer_in_range(abilities[ability], 1..30, "ability score")
    modifiers[ability] = ability_modifier_for(score)
  end

  armor_base = armor["base"]
  dex_cap = armor["dex_cap"]
  shield = armor["shield"]
  raise ArgumentError, "invalid armor" unless integer?(armor_base) && integer?(dex_cap) && boolean?(shield)

  {
    "level" => level,
    "proficiency_bonus" => proficiency_bonus_for(level),
    "hp_max" => level * (6 + modifiers.fetch("con")),
    "armor_class" => armor_base + [modifiers.fetch("dex"), dex_cap].min + (shield ? 2 : 0),
    "modifiers" => modifiers
  }
end

def adjusted_xp(data)
  party = data["party"]
  monsters = data["monsters"]
  raise ArgumentError, "invalid encounter" unless party.is_a?(Array) && monsters.is_a?(Array)

  thresholds = { "easy" => 0, "medium" => 0, "hard" => 0, "deadly" => 0 }
  party.each do |member|
    level = member.is_a?(Hash) ? member["level"] : nil
    member_thresholds = LEVEL_THRESHOLDS[level]
    raise ArgumentError, "unsupported party level" unless member_thresholds

    thresholds.each_key { |name| thresholds[name] += member_thresholds.fetch(name) }
  end

  base_xp = 0
  monster_count = 0
  monsters.each do |monster|
    raise ArgumentError, "invalid monster" unless monster.is_a?(Hash)

    cr = monster["cr"].to_s
    count = monster["count"]
    xp = CR_XP[cr]
    raise ArgumentError, "unsupported challenge rating" unless xp && integer?(count) && count.positive?

    base_xp += xp * count
    monster_count += count
  end

  multiplier = multiplier_for(monster_count)
  adjusted = base_xp * multiplier
  adjusted = format_number(adjusted)

  {
    "base_xp" => base_xp,
    "monster_count" => monster_count,
    "multiplier" => format_number(multiplier),
    "adjusted_xp" => adjusted,
    "difficulty" => difficulty_for(adjusted, thresholds),
    "thresholds" => thresholds
  }
end

def initiative_order(data)
  combatants = data["combatants"]
  raise ArgumentError, "invalid initiative" unless combatants.is_a?(Array)

  { "order" => sorted_initiative(combatants) }
end

def sorted_initiative(combatants)
  raise ArgumentError, "invalid initiative" unless combatants.is_a?(Array)

  combatants.map do |combatant|
    raise ArgumentError, "invalid combatant" unless combatant.is_a?(Hash)

    name = combatant["name"]
    dex = combatant["dex"]
    roll = combatant["roll"]
    raise ArgumentError, "invalid combatant" unless name.is_a?(String) && integer?(dex) && integer?(roll)

    { "name" => name, "dex" => dex, "score" => roll + dex }
  end
    .sort_by { |combatant| [-combatant["score"], -combatant["dex"], combatant["name"]] }
    .map { |combatant| { "name" => combatant["name"], "score" => combatant["score"] } }
end

def combat_response(session, include_order: true, include_conditions: false, active_conditions_key: nil)
  active = session.fetch("order").fetch(session.fetch("turn_index"))
  payload = {
    "id" => session.fetch("id"),
    "round" => session.fetch("round"),
    "turn_index" => session.fetch("turn_index"),
    "active" => active
  }
  payload["order"] = session.fetch("order") if include_order
  payload["conditions"] = visible_conditions(session, active_conditions_key) if include_conditions
  payload
end

def visible_conditions(session, active_conditions_key = nil)
  conditions_by_name = session.fetch("conditions")
  visible = conditions_by_name.each_with_object({}) do |(name, conditions), result|
    result[name] = conditions.map(&:dup) unless conditions.empty?
  end
  visible[active_conditions_key] = [] if visible.empty? && active_conditions_key
  visible
end

def create_combat_session(data)
  id = data["id"]
  raise ArgumentError, "invalid session id" unless id.is_a?(String) && !id.empty?
  raise ArgumentError, "duplicate session id" if COMBAT_SESSIONS.key?(id)
  raise ArgumentError, "invalid combatants" unless data["combatants"].is_a?(Array) && !data["combatants"].empty?

  order = sorted_initiative(data["combatants"])
  session = {
    "id" => id,
    "round" => 1,
    "turn_index" => 0,
    "order" => order,
    "conditions" => {}
  }
  order.each { |combatant| session["conditions"][combatant.fetch("name")] = [] }
  COMBAT_SESSIONS[id] = session
  combat_response(session)
end

def add_condition(session, data)
  target = data["target"]
  condition = data["condition"]
  duration = data["duration_rounds"]
  raise ArgumentError, "invalid condition" unless target.is_a?(String) &&
                                            condition.is_a?(String) &&
                                            integer?(duration) &&
                                            duration.positive?

  conditions = session.fetch("conditions")[target]
  raise ArgumentError, "unknown target" unless conditions

  conditions << { "condition" => condition, "remaining_rounds" => duration }
  {
    "target" => target,
    "conditions" => conditions.map(&:dup)
  }
end

def advance_combat(session)
  order = session.fetch("order")
  next_index = session.fetch("turn_index") + 1
  if next_index >= order.length
    next_index = 0
    session["round"] += 1
  end
  session["turn_index"] = next_index

  active_name = order.fetch(next_index).fetch("name")
  active_conditions = session.fetch("conditions").fetch(active_name)
  active_conditions.each { |condition| condition["remaining_rounds"] -= 1 }
  active_conditions.reject! { |condition| condition.fetch("remaining_rounds") <= 0 }

  combat_response(session, include_order: false, include_conditions: true, active_conditions_key: active_name)
end

def route(method, path, body)
  return [200, { "ok" => true }] if method == "GET" && path == "/health"

  data = body.empty? ? {} : JSON.parse(body)
  if method == "POST" && path == "/v1/combat/sessions"
    return [200, create_combat_session(data)]
  end

  if method == "POST" && (match = %r{\A/v1/combat/sessions/([^/]+)/conditions\z}.match(path))
    session = COMBAT_SESSIONS[match[1]]
    return [404, { "error" => "not found" }] unless session

    return [200, add_condition(session, data)]
  end

  if method == "POST" && (match = %r{\A/v1/combat/sessions/([^/]+)/advance\z}.match(path))
    session = COMBAT_SESSIONS[match[1]]
    return [404, { "error" => "not found" }] unless session

    return [200, advance_combat(session)]
  end

  case [method, path]
  when ["POST", "/v1/dice/stats"]
    [200, dice_stats(data)]
  when ["POST", "/v1/checks/ability"]
    [200, ability_check(data)]
  when ["POST", "/v1/characters/ability-modifier"]
    [200, ability_modifier(data)]
  when ["POST", "/v1/characters/proficiency"]
    [200, proficiency(data)]
  when ["POST", "/v1/characters/derived-stats"]
    [200, derived_stats(data)]
  when ["POST", "/v1/encounters/adjusted-xp"]
    [200, adjusted_xp(data)]
  when ["POST", "/v1/initiative/order"]
    [200, initiative_order(data)]
  else
    [404, { "error" => "not found" }]
  end
rescue JSON::ParserError, ArgumentError, TypeError, NoMethodError
  [400, { "error" => "bad request" }]
end

def read_request(socket)
  request_line = socket.gets&.chomp
  return nil unless request_line && !request_line.empty?

  headers = {}
  while (line = socket.gets)
    line = line.chomp
    break if line.empty?

    name, value = line.split(":", 2)
    headers[name.downcase] = value.strip if name && value
  end

  length = headers.fetch("content-length", "0").to_i
  body = length.positive? ? socket.read(length).to_s : ""
  method, target, = request_line.split(" ")
  path = target.to_s.split("?", 2).first
  [method, path, body]
end

def write_response(socket, status, payload)
  body = JSON.generate(payload)
  reason = {
    200 => "OK",
    400 => "Bad Request",
    404 => "Not Found",
    500 => "Internal Server Error"
  }.fetch(status, "OK")

  socket.write(
    "HTTP/1.1 #{status} #{reason}\r\n" \
    "Content-Type: application/json\r\n" \
    "Content-Length: #{body.bytesize}\r\n" \
    "Connection: close\r\n" \
    "\r\n" \
    "#{body}"
  )
end

def run_server
  port = Integer(ENV.fetch("PORT"))
  server = TCPServer.new("127.0.0.1", port)

  trap("INT") { server.close }
  trap("TERM") { server.close }

  loop do
    client = server.accept
    request = read_request(client)
    status, payload = request ? route(*request) : [400, { "error" => "bad request" }]
    write_response(client, status, payload)
  rescue IOError, SystemCallError
    break if server.closed?
  ensure
    client&.close
  end
end

run_server if $PROGRAM_NAME == __FILE__

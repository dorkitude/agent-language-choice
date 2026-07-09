#!/usr/bin/env ruby
# frozen_string_literal: true

require "json"
require "socket"

HOST = "127.0.0.1"
PORT = Integer(ENV.fetch("PORT"))

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

def parse_request(socket)
  request_line = socket.gets
  return nil unless request_line

  method, path, _version = request_line.split(" ", 3)
  headers = {}

  while (line = socket.gets)
    line = line.chomp
    break if line.empty?

    key, value = line.split(":", 2)
    headers[key.downcase] = value.strip if key && value
  end

  length = headers.fetch("content-length", "0").to_i
  body = length.positive? ? socket.read(length) : ""

  [method, path, body]
end

def json_body(body)
  parsed = body.empty? ? {} : JSON.parse(body)
  parsed.is_a?(Hash) ? parsed : nil
rescue JSON::ParserError
  nil
end

def valid_integer?(value)
  value.is_a?(Integer)
end

def dice_stats(params)
  expression = params["expression"]
  match = expression.is_a?(String) && expression.match(/\A(\d+)d(\d+)(?:([+-])(\d+))?\z/)
  raise ArgumentError unless match

  count = match[1].to_i
  sides = match[2].to_i
  sign = match[3]
  amount = match[4] ? match[4].to_i : 0
  modifier = sign == "-" ? -amount : amount
  raise ArgumentError unless count.positive? && sides.positive?

  average = count * (sides + 1) / 2.0 + modifier
  average = average.to_i if average == average.to_i

  {
    "dice_count" => count,
    "sides" => sides,
    "modifier" => modifier,
    "min" => count + modifier,
    "max" => (count * sides) + modifier,
    "average" => average
  }
end

def ability_check(params)
  roll = params["roll"]
  modifier = params["modifier"]
  dc = params["dc"]
  raise ArgumentError unless [roll, modifier, dc].all? { |value| valid_integer?(value) }

  total = roll + modifier
  {
    "total" => total,
    "success" => total >= dc,
    "margin" => total - dc
  }
end

def encounter_multiplier(monster_count)
  case monster_count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

def adjusted_xp(params)
  party = params["party"]
  monsters = params["monsters"]
  raise ArgumentError unless party.is_a?(Array) && monsters.is_a?(Array)

  thresholds = { "easy" => 0, "medium" => 0, "hard" => 0, "deadly" => 0 }
  party.each do |member|
    level = member.is_a?(Hash) ? member["level"] : nil
    table = LEVEL_THRESHOLDS[level]
    raise ArgumentError unless table

    thresholds.each_key { |key| thresholds[key] += table[key] }
  end

  base_xp = 0
  monster_count = 0
  monsters.each do |monster|
    cr = monster.is_a?(Hash) ? monster["cr"] : nil
    count = monster.is_a?(Hash) ? monster["count"] : nil
    xp = CR_XP[cr]
    raise ArgumentError unless xp && valid_integer?(count) && count.positive?

    base_xp += xp * count
    monster_count += count
  end
  raise ArgumentError unless monster_count.positive?

  multiplier = encounter_multiplier(monster_count)
  adjusted = base_xp * multiplier
  difficulty =
    if adjusted >= thresholds["deadly"]
      "deadly"
    elsif adjusted >= thresholds["hard"]
      "hard"
    elsif adjusted >= thresholds["medium"]
      "medium"
    elsif adjusted >= thresholds["easy"]
      "easy"
    else
      "trivial"
    end

  {
    "base_xp" => base_xp,
    "monster_count" => monster_count,
    "multiplier" => multiplier,
    "adjusted_xp" => adjusted,
    "difficulty" => difficulty,
    "thresholds" => thresholds
  }
end

def initiative_order(params)
  combatants = params["combatants"]
  raise ArgumentError unless combatants.is_a?(Array)

  order = combatants.map do |combatant|
    raise ArgumentError unless combatant.is_a?(Hash)

    name = combatant["name"]
    dex = combatant["dex"]
    roll = combatant["roll"]
    raise ArgumentError unless name.is_a?(String) && valid_integer?(dex) && valid_integer?(roll)

    { "name" => name, "dex" => dex, "score" => roll + dex }
  end

  {
    "order" => order
      .sort_by { |combatant| [-combatant["score"], -combatant["dex"], combatant["name"]] }
      .map { |combatant| { "name" => combatant["name"], "score" => combatant["score"] } }
  }
end

def route(method, path, body)
  return [200, { "ok" => true }] if method == "GET" && path == "/health"

  params = json_body(body)
  raise ArgumentError unless params

  case [method, path]
  when ["POST", "/v1/dice/stats"]
    [200, dice_stats(params)]
  when ["POST", "/v1/checks/ability"]
    [200, ability_check(params)]
  when ["POST", "/v1/encounters/adjusted-xp"]
    [200, adjusted_xp(params)]
  when ["POST", "/v1/initiative/order"]
    [200, initiative_order(params)]
  else
    [404, { "error" => "not_found" }]
  end
rescue ArgumentError
  [400, { "error" => "bad_request" }]
end

def write_response(socket, status, payload)
  body = JSON.generate(payload)
  reason = { 200 => "OK", 400 => "Bad Request", 404 => "Not Found" }.fetch(status, "OK")

  socket.write("HTTP/1.1 #{status} #{reason}\r\n")
  socket.write("Content-Type: application/json\r\n")
  socket.write("Content-Length: #{body.bytesize}\r\n")
  socket.write("Connection: close\r\n")
  socket.write("\r\n")
  socket.write(body)
end

def serve
  server = TCPServer.new(HOST, PORT)

  loop do
    client = server.accept
    request = parse_request(client)
    if request
      status, payload = route(*request)
      write_response(client, status, payload)
    end
  rescue StandardError
    write_response(client, 400, { "error" => "bad_request" }) if client && !client.closed?
  ensure
    client&.close
  end
end

serve if $PROGRAM_NAME == __FILE__

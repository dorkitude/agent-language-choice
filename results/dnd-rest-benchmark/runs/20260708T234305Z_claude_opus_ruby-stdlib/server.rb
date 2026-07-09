#!/usr/bin/env ruby
# frozen_string_literal: true

require "socket"
require "json"

# --- Domain logic -----------------------------------------------------------

CR_XP = {
  "0"   => 10,
  "1/8" => 25,
  "1/4" => 50,
  "1/2" => 100,
  "1"   => 200,
  "2"   => 450,
  "3"   => 700,
  "4"   => 1100,
  "5"   => 1800,
}.freeze

# Level => [easy, medium, hard, deadly]
LEVEL_THRESHOLDS = {
  3 => { "easy" => 75, "medium" => 150, "hard" => 225, "deadly" => 400 },
}.freeze

def encounter_multiplier(monster_count)
  case monster_count
  when 0     then 0
  when 1     then 1
  when 2     then 1.5
  when 3..6  then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

# Return a number as Integer when it has no fractional part, else Float.
def numify(n)
  return n unless n.is_a?(Float)
  n == n.to_i ? n.to_i : n
end

class BadRequest < StandardError; end

def parse_dice(expression)
  raise BadRequest unless expression.is_a?(String)
  m = /\A\s*(\d+)d(\d+)\s*(?:([+-])\s*(\d+))?\s*\z/.match(expression)
  raise BadRequest unless m
  count = Integer(m[1], 10)
  sides = Integer(m[2], 10)
  raise BadRequest if count <= 0 || sides <= 0
  modifier = 0
  if m[3]
    modifier = Integer(m[4], 10)
    modifier = -modifier if m[3] == "-"
  end
  [count, sides, modifier]
end

def dice_stats(body)
  count, sides, modifier = parse_dice(body["expression"])
  min = count * 1 + modifier
  max = count * sides + modifier
  {
    "dice_count" => count,
    "sides" => sides,
    "modifier" => modifier,
    "min" => min,
    "max" => max,
    "average" => numify((min + max) / 2.0),
  }
end

def ability_check(body)
  roll = body["roll"]
  modifier = body["modifier"]
  dc = body["dc"]
  raise BadRequest unless roll.is_a?(Integer) && modifier.is_a?(Integer) && dc.is_a?(Integer)
  total = roll + modifier
  { "total" => total, "success" => total >= dc, "margin" => total - dc }
end

def adjusted_xp(body)
  party = body["party"]
  monsters = body["monsters"]
  raise BadRequest unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0
  monsters.each do |mon|
    raise BadRequest unless mon.is_a?(Hash)
    cr = mon["cr"]
    count = mon["count"]
    raise BadRequest unless CR_XP.key?(cr) && count.is_a?(Integer) && count >= 0
    base_xp += CR_XP[cr] * count
    monster_count += count
  end

  multiplier = encounter_multiplier(monster_count)
  adj = base_xp * multiplier

  thresholds = { "easy" => 0, "medium" => 0, "hard" => 0, "deadly" => 0 }
  party.each do |member|
    raise BadRequest unless member.is_a?(Hash)
    level = member["level"]
    lvl = LEVEL_THRESHOLDS[level]
    raise BadRequest unless lvl
    thresholds.each_key { |k| thresholds[k] += lvl[k] }
  end

  difficulty = "trivial"
  %w[easy medium hard deadly].each do |tier|
    difficulty = tier if adj >= thresholds[tier]
  end

  {
    "base_xp" => base_xp,
    "monster_count" => monster_count,
    "multiplier" => numify(multiplier),
    "adjusted_xp" => numify(adj),
    "difficulty" => difficulty,
    "thresholds" => thresholds,
  }
end

def initiative_order(body)
  combatants = body["combatants"]
  raise BadRequest unless combatants.is_a?(Array)

  scored = combatants.each_with_index.map do |c, i|
    raise BadRequest unless c.is_a?(Hash)
    name = c["name"]
    dex = c["dex"]
    roll = c["roll"]
    raise BadRequest unless name.is_a?(String) && dex.is_a?(Integer) && roll.is_a?(Integer)
    { name: name, dex: dex, score: roll + dex, idx: i }
  end

  scored.sort! do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp.zero?
    cmp = a[:name] <=> b[:name] if cmp.zero?
    cmp
  end

  { "order" => scored.map { |c| { "name" => c[:name], "score" => c[:score] } } }
end

# --- HTTP layer -------------------------------------------------------------

ROUTES = {
  ["POST", "/v1/dice/stats"]           => method(:dice_stats),
  ["POST", "/v1/checks/ability"]       => method(:ability_check),
  ["POST", "/v1/encounters/adjusted-xp"] => method(:adjusted_xp),
  ["POST", "/v1/initiative/order"]     => method(:initiative_order),
}.freeze

def read_request(client)
  request_line = client.gets
  return nil if request_line.nil?
  method, path, = request_line.split(" ")

  headers = {}
  while (line = client.gets)
    line = line.chomp
    break if line.empty?
    key, value = line.split(":", 2)
    headers[key.strip.downcase] = value.strip if value
  end

  length = headers["content-length"].to_i
  body = length > 0 ? client.read(length) : ""
  [method, path, body]
end

def write_response(client, status, payload)
  status_text = { 200 => "OK", 400 => "Bad Request", 404 => "Not Found" }[status] || "OK"
  json = JSON.generate(payload)
  client.write("HTTP/1.1 #{status} #{status_text}\r\n")
  client.write("Content-Type: application/json\r\n")
  client.write("Content-Length: #{json.bytesize}\r\n")
  client.write("Connection: close\r\n")
  client.write("\r\n")
  client.write(json)
end

def handle(method, path, raw_body)
  return [200, { "ok" => true }] if method == "GET" && path == "/health"

  handler = ROUTES[[method, path]]
  return [404, { "error" => "not found" }] unless handler

  begin
    body = raw_body.empty? ? {} : JSON.parse(raw_body)
  rescue JSON::ParserError
    return [400, { "error" => "invalid json" }]
  end
  raise BadRequest unless body.is_a?(Hash)

  [200, handler.call(body)]
rescue BadRequest
  [400, { "error" => "bad request" }]
end

port = Integer(ENV.fetch("PORT", "8080"), 10)
server = TCPServer.new("127.0.0.1", port)

loop do
  client = server.accept
  Thread.new(client) do |conn|
    begin
      req = read_request(conn)
      if req
        method, path, raw_body = req
        status, payload = handle(method, path, raw_body)
        write_response(conn, status, payload)
      end
    rescue StandardError
      # Best-effort; connection will be closed below.
    ensure
      conn.close rescue nil
    end
  end
end

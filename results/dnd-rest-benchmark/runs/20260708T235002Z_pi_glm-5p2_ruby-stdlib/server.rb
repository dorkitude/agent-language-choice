#!/usr/bin/env ruby
require "socket"
require "json"

# --- D&D data tables ---------------------------------------------------------

XP_TABLE = {
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

THRESHOLDS = {
  3 => { "easy" => 75, "medium" => 150, "hard" => 225, "deadly" => 400 },
}.freeze

# --- helpers -----------------------------------------------------------------

# Render whole floats as integers so 10.0 -> 10 but 1.5 stays 1.5.
def norm(n)
  n.is_a?(Float) && n == n.to_i ? n.to_i : n
end

def multiplier_for(count)
  case count
  when 0..1   then 1
  when 2      then 1.5
  when 3..6   then 2
  when 7..10  then 2.5
  when 11..14 then 3
  else             4 # 15+
  end
end

def parse_body(body)
  data = JSON.parse(body)
  data.is_a?(Hash) ? data : {}
rescue JSON::ParserError
  :bad_json
end

# --- endpoint handlers -------------------------------------------------------

def dice_stats(body)
  data = parse_body(body)
  return [400, { "error" => "invalid json" }] if data == :bad_json
  expr = data["expression"].to_s
  m = expr.match(/\A(\d+)d(\d+)(?:([+-]\d+))?\z/)
  return [400, { "error" => "invalid expression" }] unless m
  count = m[1].to_i
  sides = m[2].to_i
  modifier = m[3] ? m[3].to_i : 0
  return [400, { "error" => "invalid expression" }] if count <= 0 || sides <= 0
  min = count + modifier
  max = count * sides + modifier
  average = (min + max) / 2.0
  [200, {
    "dice_count" => count,
    "sides"      => sides,
    "modifier"   => modifier,
    "min"        => min,
    "max"        => max,
    "average"    => norm(average),
  }]
end

def ability_check(body)
  data = parse_body(body)
  return [400, { "error" => "invalid json" }] if data == :bad_json
  roll = data["roll"].to_i
  modifier = data["modifier"].to_i
  dc = data["dc"].to_i
  total = roll + modifier
  [200, {
    "total"   => total,
    "success" => total >= dc,
    "margin"  => total - dc,
  }]
end

def adjusted_xp(body)
  data = parse_body(body)
  return [400, { "error" => "invalid json" }] if data == :bad_json
  party = data["party"] || []
  monsters = data["monsters"] || []

  base_xp = 0
  monster_count = 0
  monsters.each do |mon|
    cr = mon["cr"].to_s
    count = mon["count"].to_i
    base_xp += (XP_TABLE[cr] || 0) * count
    monster_count += count
  end

  multiplier = multiplier_for(monster_count)
  adjusted_raw = base_xp * multiplier

  easy = medium = hard = deadly = 0
  party.each do |mem|
    t = THRESHOLDS[mem["level"].to_i] ||
        { "easy" => 0, "medium" => 0, "hard" => 0, "deadly" => 0 }
    easy   += t["easy"]
    medium += t["medium"]
    hard   += t["hard"]
    deadly += t["deadly"]
  end

  difficulty =
    if adjusted_raw >= deadly
      "deadly"
    elsif adjusted_raw >= hard
      "hard"
    elsif adjusted_raw >= medium
      "medium"
    elsif adjusted_raw >= easy
      "easy"
    else
      "trivial"
    end

  [200, {
    "base_xp"       => base_xp,
    "monster_count" => monster_count,
    "multiplier"    => norm(multiplier),
    "adjusted_xp"   => norm(adjusted_raw),
    "difficulty"    => difficulty,
    "thresholds"    => {
      "easy"   => easy,
      "medium" => medium,
      "hard"   => hard,
      "deadly" => deadly,
    },
  }]
end

def initiative_order(body)
  data = parse_body(body)
  return [400, { "error" => "invalid json" }] if data == :bad_json
  combatants = data["combatants"] || []
  list = combatants.map do |c|
    { "name" => c["name"].to_s, "dex" => c["dex"].to_i, "roll" => c["roll"].to_i }
  end
  # score desc, then dex desc, then name asc
  sorted = list.sort_by { |c| [-(c["roll"] + c["dex"]), -c["dex"], c["name"]] }
  [200, {
    "order" => sorted.map { |c| { "name" => c["name"], "score" => c["roll"] + c["dex"] } },
  }]
end

# --- routing -----------------------------------------------------------------

def route(method, path, body)
  case [method, path]
  when ["GET",  "/health"]
    [200, { "ok" => true }]
  when ["POST", "/v1/dice/stats"]
    dice_stats(body)
  when ["POST", "/v1/checks/ability"]
    ability_check(body)
  when ["POST", "/v1/encounters/adjusted-xp"]
    adjusted_xp(body)
  when ["POST", "/v1/initiative/order"]
    initiative_order(body)
  else
    [404, { "error" => "not found" }]
  end
end

# --- HTTP plumbing -----------------------------------------------------------

REASON = {
  200 => "OK",
  400 => "Bad Request",
  404 => "Not Found",
  500 => "Internal Server Error",
}.freeze

def send_response(client, status, obj)
  body = JSON.generate(obj)
  head = +"HTTP/1.1 #{status} #{REASON[status] || 'OK'}\r\n"
  head << "Content-Type: application/json\r\n"
  head << "Content-Length: #{body.bytesize}\r\n"
  head << "Connection: close\r\n\r\n"
  client.write(head)
  client.write(body)
end

def handle_connection(client)
  request_line = client.gets
  return unless request_line
  parts = request_line.strip.split(" ")
  method, full_path = parts[0], parts[1]
  return unless method && full_path
  path = full_path.split("?").first

  content_length = 0
  while (line = client.gets)
    line = line.strip
    break if line.empty?
    if line =~ /\A([^:]+):\s*(.*)\z/
      content_length = $2.to_i if $1.downcase == "content-length"
    end
  end

  body = content_length.positive? ? (client.read(content_length) || "") : ""
  status, obj = route(method, path, body)
  send_response(client, status, obj)
rescue => e
  begin
    send_response(client, 500, { "error" => "internal error" })
  rescue
    # ignore
  end
ensure
  client.close rescue nil
end

# --- server loop -------------------------------------------------------------

port = (ENV["PORT"] || 3000).to_i
server = TCPServer.new("127.0.0.1", port)
STDERR.puts "dnd-rest listening on 127.0.0.1:#{port}"
trap("TERM") { exit }
trap("INT")  { exit }

loop do
  client = server.accept
  Thread.new(client) { |c| handle_connection(c) }
end

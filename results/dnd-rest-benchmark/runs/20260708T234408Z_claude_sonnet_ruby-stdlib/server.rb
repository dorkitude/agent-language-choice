#!/usr/bin/env ruby
require 'socket'
require 'json'

HOST = '127.0.0.1'
PORT = Integer(ENV.fetch('PORT', '8080'))

CR_XP = {
  '0' => 10,
  '1/8' => 25,
  '1/4' => 50,
  '1/2' => 100,
  '1' => 200,
  '2' => 450,
  '3' => 700,
  '4' => 1100,
  '5' => 1800,
}.freeze

LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 },
}.freeze

def multiplier_for_count(n)
  case n
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

def json_response(status, body_hash)
  body = JSON.generate(body_hash)
  [status, body]
end

def error_response(status, message)
  json_response(status, { 'error' => message })
end

def handle_health(_req)
  json_response(200, { 'ok' => true })
end

def handle_dice_stats(req)
  expr = req['expression']
  return error_response(400, 'expression is required') unless expr.is_a?(String)

  m = /\A(\d+)d(\d+)([+-]\d+)?\z/.match(expr)
  return error_response(400, 'invalid expression') unless m

  count = m[1].to_i
  sides = m[2].to_i
  modifier = m[3] ? m[3].to_i : 0

  return error_response(400, 'count must be positive') unless count > 0
  return error_response(400, 'sides must be positive') unless sides > 0

  min = count * 1 + modifier
  max = count * sides + modifier
  average = (count * (sides + 1) / 2.0) + modifier
  average = average.to_i if average == average.to_i

  json_response(200, {
    'dice_count' => count,
    'sides' => sides,
    'modifier' => modifier,
    'min' => min,
    'max' => max,
    'average' => average,
  })
end

def handle_ability_check(req)
  roll = req['roll']
  modifier = req['modifier']
  dc = req['dc']

  return error_response(400, 'roll, modifier, dc must be numbers') unless [roll, modifier, dc].all? { |v| v.is_a?(Numeric) }

  total = roll + modifier
  success = total >= dc
  margin = total - dc

  json_response(200, {
    'total' => total,
    'success' => success,
    'margin' => margin,
  })
end

def handle_adjusted_xp(req)
  party = req['party']
  monsters = req['monsters']

  return error_response(400, 'party and monsters are required') unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0

  monsters.each do |m|
    cr = m['cr'].to_s
    count = m['count']
    return error_response(400, "unknown cr #{cr}") unless CR_XP.key?(cr)
    return error_response(400, 'count must be an integer') unless count.is_a?(Integer)

    base_xp += CR_XP[cr] * count
    monster_count += count
  end

  multiplier = multiplier_for_count(monster_count)
  adjusted_xp = base_xp * multiplier

  levels = party.map { |p| p['level'] }
  return error_response(400, 'unsupported party level') unless levels.all? { |l| LEVEL_THRESHOLDS.key?(l) }

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  levels.each do |lvl|
    t = LEVEL_THRESHOLDS[lvl]
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

  adjusted_xp = adjusted_xp.to_i if adjusted_xp == adjusted_xp.to_i

  json_response(200, {
    'base_xp' => base_xp,
    'monster_count' => monster_count,
    'multiplier' => multiplier,
    'adjusted_xp' => adjusted_xp,
    'difficulty' => difficulty,
    'thresholds' => {
      'easy' => thresholds[:easy],
      'medium' => thresholds[:medium],
      'hard' => thresholds[:hard],
      'deadly' => thresholds[:deadly],
    },
  })
end

def handle_initiative_order(req)
  combatants = req['combatants']
  return error_response(400, 'combatants is required') unless combatants.is_a?(Array)

  scored = combatants.map do |c|
    name = c['name']
    dex = c['dex']
    roll = c['roll']
    score = roll + dex
    { 'name' => name, 'dex' => dex, 'score' => score }
  end

  ordered = scored.sort do |a, b|
    cmp = b['score'] <=> a['score']
    next cmp unless cmp == 0
    cmp = b['dex'] <=> a['dex']
    next cmp unless cmp == 0
    a['name'] <=> b['name']
  end

  order = ordered.map { |c| { 'name' => c['name'], 'score' => c['score'] } }

  json_response(200, { 'order' => order })
end

ROUTES = {
  ['GET', '/health'] => method(:handle_health),
  ['POST', '/v1/dice/stats'] => method(:handle_dice_stats),
  ['POST', '/v1/checks/ability'] => method(:handle_ability_check),
  ['POST', '/v1/encounters/adjusted-xp'] => method(:handle_adjusted_xp),
  ['POST', '/v1/initiative/order'] => method(:handle_initiative_order),
}.freeze

def read_request(client)
  request_line = client.gets
  return nil if request_line.nil?

  method_str, path, _version = request_line.split(' ')
  headers = {}
  loop do
    line = client.gets
    break if line.nil? || line == "\r\n" || line == "\n"
    key, value = line.split(':', 2)
    headers[key.strip.downcase] = value.strip if key && value
  end

  body = ''
  content_length = headers['content-length'].to_i
  body = client.read(content_length) if content_length > 0

  { method: method_str, path: path, headers: headers, body: body }
end

def write_response(client, status, body)
  status_text = { 200 => 'OK', 400 => 'Bad Request', 404 => 'Not Found', 500 => 'Internal Server Error' }[status] || 'OK'
  client.write("HTTP/1.1 #{status} #{status_text}\r\n")
  client.write("Content-Type: application/json\r\n")
  client.write("Content-Length: #{body.bytesize}\r\n")
  client.write("Connection: close\r\n")
  client.write("\r\n")
  client.write(body)
end

server = TCPServer.new(HOST, PORT)
puts "Listening on #{HOST}:#{PORT}"

loop do
  client = server.accept
  Thread.new(client) do |conn|
    begin
      req = read_request(conn)
      if req.nil?
        conn.close
        next
      end

      handler = ROUTES[[req[:method], req[:path]]]

      if handler.nil?
        status, body = error_response(404, 'not found')
      else
        begin
          parsed = req[:body].empty? ? {} : JSON.parse(req[:body])
          status, body = handler.call(parsed)
        rescue JSON::ParserError
          status, body = error_response(400, 'invalid json')
        rescue StandardError => e
          status, body = error_response(400, e.message)
        end
      end

      write_response(conn, status, body)
    rescue StandardError => e
      warn "error handling request: #{e.message}"
    ensure
      conn.close
    end
  end
end

#!/usr/bin/env ruby
# frozen_string_literal: true

require 'json'
require 'socket'

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
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

DICE_RE = /^(\d+)d(\d+)([+-]\d+)?$/.freeze

HTTP_STATUS = {
  200 => 'OK',
  400 => 'Bad Request',
  404 => 'Not Found',
  405 => 'Method Not Allowed',
  500 => 'Internal Server Error'
}.freeze

def parse_json(body)
  body.to_s.empty? ? {} : JSON.parse(body)
rescue JSON::ParserError
  nil
end

def json_response(status, data)
  [status, JSON.generate(data)]
end

def dice_stats(params)
  expr = params['expression'].to_s.strip
  return json_response(400, { error: 'missing expression' }) unless expr =~ DICE_RE

  count = Regexp.last_match(1).to_i
  sides = Regexp.last_match(2).to_i
  modifier = Regexp.last_match(3).to_i

  min = count + modifier
  max = count * sides + modifier
  avg = (min + max) / 2.0
  avg = avg == avg.to_i ? avg.to_i : avg

  json_response(200, {
    dice_count: count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: avg
  })
end

def ability_check(params)
  roll = params['roll']
  modifier = params['modifier']
  dc = params['dc']

  return json_response(400, { error: 'missing roll, modifier, or dc' }) unless [roll, modifier, dc].all?

  total = roll + modifier
  json_response(200, {
    total: total,
    success: total >= dc,
    margin: total - dc
  })
end

def monster_multiplier(count)
  case count
  when 1 then 1.0
  when 2 then 1.5
  when 3..6 then 2.0
  when 7..10 then 2.5
  when 11..14 then 3.0
  else 4.0
  end
end

def adjusted_xp(params)
  party = params['party']
  monsters = params['monsters']

  return json_response(400, { error: 'missing party or monsters' }) unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0

  monsters.each do |m|
    cr = m['cr'].to_s
    count = m['count'].to_i
    xp = CR_XP[cr]
    return json_response(400, { error: "unknown cr: #{cr}" }) unless xp

    base_xp += xp * count
    monster_count += count
  end

  multiplier = monster_multiplier(monster_count)
  adjusted_xp = (base_xp * multiplier).to_i

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  party.each do |p|
    level = p['level'].to_i
    th = LEVEL_THRESHOLDS[level]
    return json_response(400, { error: "unsupported level: #{level}" }) unless th

    thresholds[:easy] += th[:easy]
    thresholds[:medium] += th[:medium]
    thresholds[:hard] += th[:hard]
    thresholds[:deadly] += th[:deadly]
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

  json_response(200, {
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted_xp,
    difficulty: difficulty,
    thresholds: {
      easy: thresholds[:easy],
      medium: thresholds[:medium],
      hard: thresholds[:hard],
      deadly: thresholds[:deadly]
    }
  })
end

def initiative_order(params)
  combatants = params['combatants']
  return json_response(400, { error: 'missing combatants' }) unless combatants.is_a?(Array)

  scored = combatants.map do |c|
    {
      name: c['name'],
      score: c['roll'] + c['dex'],
      dex: c['dex']
    }
  end

  order = scored.sort do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp == 0
    cmp = a[:name] <=> b[:name] if cmp == 0
    cmp
  end

  json_response(200, { order: order.map { |c| { name: c[:name], score: c[:score] } } })
end

def route(method, path, body)
  params = parse_json(body)
  return json_response(400, { error: 'invalid json' }) if params.nil?

  case [method, path]
  when ['GET', '/health']
    json_response(200, { ok: true })
  when ['POST', '/v1/dice/stats']
    dice_stats(params)
  when ['POST', '/v1/checks/ability']
    ability_check(params)
  when ['POST', '/v1/encounters/adjusted-xp']
    adjusted_xp(params)
  when ['POST', '/v1/initiative/order']
    initiative_order(params)
  else
    json_response(404, { error: 'not found' })
  end
end

class HttpServer
  def initialize(port)
    @server = TCPServer.new('127.0.0.1', port)
  end

  def start
    loop do
      client = @server.accept
      Thread.new { handle(client) }
    end
  rescue IOError
    # Server socket closed during shutdown.
  end

  def shutdown
    @server.close
  end

  private

  def handle(client)
    request_line = client.gets
    return close(client) unless request_line

    method, path, _protocol = request_line.split(' ')
    return close(client) unless method && path

    headers = {}
    loop do
      line = client.gets
      break if line.nil? || line.strip.empty?

      key, value = line.split(':', 2)
      headers[key.downcase] = value.strip if key && value
    end

    body = ''
    length = headers['content-length'].to_i
    body = client.read(length) if length > 0

    status, response_body = route(method, path, body)
    write_response(client, status, response_body)
  rescue StandardError => e
    puts "error: #{e.class}: #{e.message}"
    write_response(client, 500, JSON.generate({ error: 'internal server error' }))
  ensure
    close(client)
  end

  def write_response(client, status, response_body)
    client.write("HTTP/1.1 #{status} #{HTTP_STATUS[status] || 'Unknown'}\r\n")
    client.write("Content-Type: application/json\r\n")
    client.write("Content-Length: #{response_body.bytesize}\r\n")
    client.write("Connection: close\r\n")
    client.write("\r\n")
    client.write(response_body)
  end

  def close(client)
    client.close
  rescue IOError
    # ignore
  end
end

port = ENV.fetch('PORT', '3000').to_i
server = HttpServer.new(port)
server.start


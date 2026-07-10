#!/usr/bin/env ruby
# frozen_string_literal: true

require 'socket'
require 'json'

XP_TABLE = {
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

THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

DICE_RE = /\A([1-9]\d*)d([1-9]\d*)([+-]\d+)?\z/.freeze

STATUS_TEXT = {
  200 => 'OK',
  400 => 'Bad Request',
  404 => 'Not Found',
  405 => 'Method Not Allowed',
  500 => 'Internal Server Error'
}.freeze

$sessions = {}

def respond(code, body)
  [code, { 'Content-Type' => 'application/json' }, JSON.generate(body)]
end

def dice_stats(expression)
  m = DICE_RE.match(expression.to_s)
  return nil unless m

  count = m[1].to_i
  sides = m[2].to_i
  modifier = m[3] ? m[3].to_i : 0
  min = count + modifier
  max = count * sides + modifier
  avg = ((min + max) % 2).zero? ? (min + max) / 2 : (min + max) / 2.0

  {
    dice_count: count,
    sides: sides,
    modifier: modifier,
    min: min,
    max: max,
    average: avg
  }
end

def ability_check(data)
  roll = data['roll']
  modifier = data['modifier']
  dc = data['dc']
  return nil unless roll.is_a?(Integer) && modifier.is_a?(Integer) && dc.is_a?(Integer)

  total = roll + modifier
  { total: total, success: total >= dc, margin: total - dc }
end

def monster_multiplier(count)
  case count
  when 1 then 1
  when 2 then 1.5
  when 3..6 then 2
  when 7..10 then 2.5
  when 11..14 then 3
  else 4
  end
end

def encounter(data)
  party = data['party']
  monsters = data['monsters']
  return nil unless party.is_a?(Array) && monsters.is_a?(Array)

  base_xp = 0
  monster_count = 0
  monsters.each do |m|
    cr = m['cr']
    count = m['count']
    xp = XP_TABLE[cr]
    return nil unless xp && count.is_a?(Integer) && count.positive?

    base_xp += xp * count
    monster_count += count
  end

  multiplier = monster_multiplier(monster_count)
  adjusted = base_xp * multiplier
  adjusted = adjusted.to_i if (adjusted % 1).zero?

  thresholds = { easy: 0, medium: 0, hard: 0, deadly: 0 }
  party.each do |p|
    t = THRESHOLDS[p['level']]
    return nil unless t

    t.each { |k, v| thresholds[k] += v }
  end

  difficulty = if adjusted >= thresholds[:deadly]
                 'deadly'
               elsif adjusted >= thresholds[:hard]
                 'hard'
               elsif adjusted >= thresholds[:medium]
                 'medium'
               elsif adjusted >= thresholds[:easy]
                 'easy'
               else
                 'trivial'
               end

  {
    base_xp: base_xp,
    monster_count: monster_count,
    multiplier: multiplier,
    adjusted_xp: adjusted,
    difficulty: difficulty,
    thresholds: thresholds
  }
end

def ability_modifier(score)
  return nil unless score.is_a?(Integer) && score >= 1 && score <= 30

  { score: score, modifier: (score - 10) / 2 }
end

def proficiency_bonus(level)
  return nil unless level.is_a?(Integer) && level >= 1 && level <= 20

  bonus = case level
          when 1..4 then 2
          when 5..8 then 3
          when 9..12 then 4
          when 13..16 then 5
          when 17..20 then 6
          end

  { level: level, proficiency_bonus: bonus }
end

def derived_stats(data)
  level = data['level']
  abilities = data['abilities']
  armor = data['armor']

  return nil unless level.is_a?(Integer) && level >= 1 && level <= 20
  return nil unless abilities.is_a?(Hash)
  return nil unless armor.is_a?(Hash)

  required_abilities = %w[str dex con int wis cha]
  return nil unless required_abilities.all? { |k| abilities[k].is_a?(Integer) }

  base = armor['base']
  shield = armor['shield']
  dex_cap = armor['dex_cap']
  return nil unless base.is_a?(Integer) && (shield == true || shield == false) && dex_cap.is_a?(Integer)

  modifiers = {}
  required_abilities.each { |k| modifiers[k] = (abilities[k] - 10) / 2 }

  con_mod = modifiers['con']
  hp_max = level * (6 + con_mod)

  dex_mod = modifiers['dex']
  shield_bonus = shield ? 2 : 0
  armor_class = base + [dex_mod, dex_cap].min + shield_bonus

  {
    level: level,
    proficiency_bonus: proficiency_bonus(level)[:proficiency_bonus],
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers
  }
end

def create_combat_session(data)
  return nil unless data.is_a?(Hash) && data['id'].is_a?(String) && data['combatants'].is_a?(Array)
  return nil if data['combatants'].empty?
  return nil if $sessions.key?(data['id'])

  scored = data['combatants'].map do |c|
    return nil unless c.is_a?(Hash) && c['name'].is_a?(String) && c['dex'].is_a?(Integer) && c['roll'].is_a?(Integer)

    { name: c['name'], score: c['roll'] + c['dex'], dex: c['dex'] }
  end

  scored.sort! do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp.zero?
    cmp = a[:name] <=> b[:name] if cmp.zero?
    cmp
  end

  order = scored.map { |c| { name: c[:name], score: c[:score] } }

  session = {
    id: data['id'],
    round: 1,
    turn_index: 0,
    order: order,
    conditions: {}
  }
  $sessions[data['id']] = session

  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: order[0],
    order: order
  }
end

def add_condition(id, data)
  session = $sessions[id]
  return nil unless session
  return nil unless data.is_a?(Hash) && data['target'].is_a?(String) && data['condition'].is_a?(String)
  return nil unless data['duration_rounds'].is_a?(Integer) && data['duration_rounds'].positive?

  target = data['target']
  return nil unless session[:order].any? { |c| c[:name] == target }

  session[:conditions][target] ||= []
  session[:conditions][target] << { condition: data['condition'], remaining_rounds: data['duration_rounds'] }

  {
    target: target,
    conditions: session[:conditions][target].map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  }
end

def advance_turn(id)
  session = $sessions[id]
  return nil unless session

  session[:turn_index] += 1
  if session[:turn_index] >= session[:order].length
    session[:turn_index] = 0
    session[:round] += 1
  end

  active = session[:order][session[:turn_index]]
  active_name = active[:name]

  if session[:conditions][active_name]
    session[:conditions][active_name].each { |c| c[:remaining_rounds] -= 1 }
    session[:conditions][active_name].reject! { |c| c[:remaining_rounds] <= 0 }
    session[:conditions].delete(active_name) if session[:conditions][active_name].empty?
  end

  conditions = {}
  session[:conditions].each do |name, conds|
    conditions[name] = conds.map { |c| { condition: c[:condition], remaining_rounds: c[:remaining_rounds] } }
  end

  {
    id: session[:id],
    round: session[:round],
    turn_index: session[:turn_index],
    active: active,
    conditions: conditions
  }
end

def initiative_order(combatants)
  return nil unless combatants.is_a?(Array)

  scored = combatants.map do |c|
    return nil unless c['name'].is_a?(String) && c['roll'].is_a?(Integer) && c['dex'].is_a?(Integer)

    {
      name: c['name'],
      score: c['roll'] + c['dex'],
      dex: c['dex']
    }
  end

  scored.sort! do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp.zero?
    cmp = a[:name] <=> b[:name] if cmp.zero?
    cmp
  end

  scored.map { |c| { name: c[:name], score: c[:score] } }
end

def handle(method, path, body)
  data = nil
  begin
    data = JSON.parse(body) unless body.nil? || body.empty?
  rescue JSON::ParserError
    data = nil
  end

  case method
  when 'GET'
    return respond(200, { ok: true }) if path == '/health'
  when 'POST'
    case path
    when '/v1/dice/stats'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash) && data.key?('expression')

      result = dice_stats(data['expression'])
      return respond(400, { error: 'invalid expression' }) unless result

      return respond(200, result)
    when '/v1/checks/ability'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash) && data.key?('roll') && data.key?('modifier') && data.key?('dc')

      result = ability_check(data)
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, result)
    when '/v1/encounters/adjusted-xp'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash) && data.key?('party') && data.key?('monsters')

      result = encounter(data)
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, result)
    when '/v1/initiative/order'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash) && data.key?('combatants')

      result = initiative_order(data['combatants'])
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, { order: result })
    when '/v1/characters/ability-modifier'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash) && data.key?('score')

      result = ability_modifier(data['score'])
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, result)
    when '/v1/characters/proficiency'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash) && data.key?('level')

      result = proficiency_bonus(data['level'])
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, result)
    when '/v1/characters/derived-stats'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash)

      result = derived_stats(data)
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, result)
    when '/v1/combat/sessions'
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash)

      result = create_combat_session(data)
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, result)
    when %r{\A/v1/combat/sessions/([^/]+)/conditions\z}
      id = $1
      return respond(404, { error: 'not found' }) unless $sessions[id]
      return respond(400, { error: 'bad request' }) unless data.is_a?(Hash)

      result = add_condition(id, data)
      return respond(400, { error: 'bad request' }) unless result

      return respond(200, result)
    when %r{\A/v1/combat/sessions/([^/]+)/advance\z}
      id = $1
      return respond(404, { error: 'not found' }) unless $sessions[id]

      result = advance_turn(id)
      return respond(404, { error: 'not found' }) unless result

      return respond(200, result)
    end
  end

  respond(404, { error: 'not found' })
end

def serve_client(client)
  request_line = client.gets
  return unless request_line

  method, path, _proto = request_line.strip.split(' ', 3)
  method = method.to_s.upcase
  path = path.to_s

  headers = {}
  loop do
    line = client.gets
    break if line.nil? || line.strip.empty?

    key, value = line.split(':', 2)
    headers[key.strip.downcase] = value.strip if key && value
  end

  body = ''
  if headers['content-length']
    length = headers['content-length'].to_i
    body = client.read(length) if length.positive?
  end

  code, response_headers, response_body = handle(method, path, body)

  client.print "HTTP/1.1 #{code} #{STATUS_TEXT[code] || 'Unknown'}\r\n"
  response_headers.each { |k, v| client.print "#{k}: #{v}\r\n" }
  client.print "Content-Length: #{response_body.bytesize}\r\n"
  client.print "Connection: close\r\n"
  client.print "\r\n"
  client.print response_body
ensure
  client.close
end

port = ENV.fetch('PORT', '3000').to_i
server = TCPServer.new('127.0.0.1', port)

%w[INT TERM].each do |sig|
  Signal.trap(sig) do
    exit 0
  end
end

loop do
  begin
    client = server.accept
    serve_client(client)
  rescue IOError, Errno::EBADF
    break
  end
end

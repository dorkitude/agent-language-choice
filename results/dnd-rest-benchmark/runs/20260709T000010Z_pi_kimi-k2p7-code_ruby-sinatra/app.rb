# frozen_string_literal: true

require 'bundler/setup'
require 'sinatra'
require 'json'

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

LEVEL_THRESHOLDS = {
  3 => { easy: 75, medium: 150, hard: 225, deadly: 400 }
}.freeze

DIFFICULTIES = %w[trivial easy medium hard deadly].freeze

get '/health' do
  content_type :json
  { ok: true }.to_json
end

post '/v1/dice/stats' do
  content_type :json
  body = JSON.parse(request.body.read, symbolize_names: true)
  expression = body[:expression].to_s

  match = expression.match(/^(\d+)d(\d+)(?:([+-])(\d+))?$/)
  halt 400, { error: 'invalid expression' }.to_json unless match

  count = match[1].to_i
  sides = match[2].to_i
  sign = match[3]
  modifier = match[4] ? match[4].to_i : 0
  modifier = -modifier if sign == '-'

  halt 400, { error: 'invalid expression' }.to_json if count <= 0 || sides <= 0

  min = count + modifier
  max = count * sides + modifier
  average = (min + max) / 2

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
  content_type :json
  body = JSON.parse(request.body.read, symbolize_names: true)

  roll = body[:roll].to_i
  modifier = body[:modifier].to_i
  dc = body[:dc].to_i

  total = roll + modifier
  margin = total - dc
  success = total >= dc

  { total: total, success: success, margin: margin }.to_json
end

post '/v1/encounters/adjusted-xp' do
  content_type :json
  body = JSON.parse(request.body.read, symbolize_names: true)

  party = Array(body[:party])
  monsters = Array(body[:monsters])

  base_xp = monsters.sum do |m|
    cr = m[:cr].to_s
    count = m[:count].to_i
    (CR_XP[cr] || 0) * count
  end

  monster_count = monsters.sum { |m| m[:count].to_i }

  multiplier = case monster_count
               when 1 then 1
               when 2 then 1.5
               when 3..6 then 2
               when 7..10 then 2.5
               when 11..14 then 3
               else 4
               end

  adjusted_xp = base_xp * multiplier

  thresholds = party.each_with_object({ easy: 0, medium: 0, hard: 0, deadly: 0 }) do |member, acc|
    level = member[:level].to_i
    th = LEVEL_THRESHOLDS[level]
    next unless th

    acc[:easy] += th[:easy]
    acc[:medium] += th[:medium]
    acc[:hard] += th[:hard]
    acc[:deadly] += th[:deadly]
  end

  difficulty = 'trivial'
  DIFFICULTIES[1..].each do |d|
    difficulty = d if adjusted_xp >= thresholds[d.to_sym]
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
  content_type :json
  body = JSON.parse(request.body.read, symbolize_names: true)
  combatants = Array(body[:combatants])

  scored = combatants.map do |c|
    {
      name: c[:name].to_s,
      dex: c[:dex].to_i,
      score: c[:roll].to_i + c[:dex].to_i
    }
  end

  ordered = scored.sort do |a, b|
    cmp = b[:score] <=> a[:score]
    cmp = b[:dex] <=> a[:dex] if cmp == 0
    cmp = a[:name] <=> b[:name] if cmp == 0
    cmp
  end

  { order: ordered.map { |c| { name: c[:name], score: c[:score] } } }.to_json
end

not_found do
  content_type :json
  { error: 'not found' }.to_json
end

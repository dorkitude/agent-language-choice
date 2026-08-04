# Player's Handbook rules lookups: spell slots, long rest recovery, and
# carrying capacity. Stateless — no DB access.

post '/v1/phb/spell-slots' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  klass = body['class']
  level = body['level']

  halt 400, { error: 'invalid class' }.to_json unless klass.is_a?(String) && !klass.empty?
  halt 400, { error: 'invalid level' }.to_json unless integerish(level)

  level = level.to_i
  halt 400, { error: "unsupported class/level #{klass}/#{level}" }.to_json unless klass == 'wizard' && WIZARD_SPELL_SLOTS.key?(level)

  { class: klass, level: level, slots: WIZARD_SPELL_SLOTS[level] }.to_json
end

post '/v1/phb/rests/long' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  level = body['level']
  hp_current = body['hp_current']
  hp_max = body['hp_max']
  hit_dice_spent = body['hit_dice_spent']
  exhaustion_level = body['exhaustion_level']

  halt 400, { error: 'invalid level' }.to_json unless integerish(level)
  halt 400, { error: 'invalid hp_current' }.to_json unless integerish(hp_current)
  halt 400, { error: 'invalid hp_max' }.to_json unless integerish(hp_max)
  halt 400, { error: 'invalid hit_dice_spent' }.to_json unless integerish(hit_dice_spent)
  halt 400, { error: 'invalid exhaustion_level' }.to_json unless integerish(exhaustion_level)

  level = level.to_i
  hp_max = hp_max.to_i
  hit_dice_spent = hit_dice_spent.to_i
  exhaustion_level = exhaustion_level.to_i

  max_recovered = [level / 2, 1].max
  new_hit_dice_spent = [hit_dice_spent - max_recovered, 0].max
  new_exhaustion_level = [exhaustion_level - 1, 0].max

  {
    hp_current: hp_max,
    hit_dice_spent: new_hit_dice_spent,
    exhaustion_level: new_exhaustion_level
  }.to_json
end

post '/v1/phb/equipment-load' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  strength = body['strength']
  weight = body['weight']

  halt 400, { error: 'invalid strength' }.to_json unless integerish(strength)
  halt 400, { error: 'invalid weight' }.to_json unless numericish(weight)

  strength = strength.to_i
  capacity = strength * 15

  {
    capacity: capacity,
    weight: weight,
    encumbered: weight > capacity
  }.to_json
end

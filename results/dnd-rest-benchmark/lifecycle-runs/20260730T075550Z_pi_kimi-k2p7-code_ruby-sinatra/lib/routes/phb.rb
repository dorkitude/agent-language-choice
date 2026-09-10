# frozen_string_literal: true

# Route definitions for phb endpoints.

# --- PHB rules ---

post '/v1/phb/spell-slots' do
  content_type :json
  body = parse_json_body

  class_name = body['class']
  level = body['level']

  unless class_name == 'wizard'
    json_error(400, 'invalid class')
  end
  unless level == 5
    json_error(400, 'invalid level')
  end

  JSON.dump(
    class: 'wizard',
    level: 5,
    slots: { '1' => 4, '2' => 3, '3' => 2 }
  )
end

post '/v1/phb/rests/long' do
  content_type :json
  body = parse_json_body

  level = body['level']
  hp_current = body['hp_current']
  hp_max = body['hp_max']
  hit_dice_spent = body['hit_dice_spent']
  exhaustion_level = body['exhaustion_level']

  unless level.is_a?(Integer) && level.positive?
    json_error(400, 'invalid level')
  end
  unless hp_current.is_a?(Integer) && hp_current >= 0
    json_error(400, 'invalid hp_current')
  end
  unless hp_max.is_a?(Integer) && hp_max.positive?
    json_error(400, 'invalid hp_max')
  end
  unless hit_dice_spent.is_a?(Integer) && hit_dice_spent >= 0
    json_error(400, 'invalid hit_dice_spent')
  end
  unless exhaustion_level.is_a?(Integer) && exhaustion_level >= 0
    json_error(400, 'invalid exhaustion_level')
  end

  restored = [hit_dice_spent, [level / 2, 1].max].min

  JSON.dump(
    hp_current: hp_max,
    hit_dice_spent: hit_dice_spent - restored,
    exhaustion_level: [exhaustion_level - 1, 0].max
  )
end

post '/v1/phb/equipment-load' do
  content_type :json
  body = parse_json_body

  strength = body['strength']
  weight = body['weight']

  unless strength.is_a?(Integer) && strength.positive?
    json_error(400, 'invalid strength')
  end
  unless weight.is_a?(Integer) && weight >= 0
    json_error(400, 'invalid weight')
  end

  capacity = strength * 15

  JSON.dump(
    capacity: capacity,
    weight: weight,
    encumbered: weight > capacity
  )
end


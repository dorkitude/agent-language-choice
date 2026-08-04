# Stateless per-character calculations: ability modifiers, proficiency
# bonus, and derived combat stats (HP, AC). None of these touch the DB.

post '/v1/characters/ability-modifier' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  score = body['score']
  halt 400, { error: 'invalid score' }.to_json unless integerish(score) && score.to_i.between?(1, 30)

  score = score.to_i
  { score: score, modifier: ability_modifier(score) }.to_json
end

post '/v1/characters/proficiency' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  level = body['level']
  halt 400, { error: 'invalid level' }.to_json unless integerish(level) && level.to_i.between?(1, 20)

  level = level.to_i
  { level: level, proficiency_bonus: proficiency_bonus(level) }.to_json
end

post '/v1/characters/derived-stats' do
  body = json_body
  halt 400, { error: 'invalid json' }.to_json if body.nil?

  level = body['level']
  abilities = body['abilities']
  armor = body['armor']

  halt 400, { error: 'invalid level' }.to_json unless integerish(level) && level.to_i.between?(1, 20)
  halt 400, { error: 'invalid abilities' }.to_json unless abilities.is_a?(Hash)
  halt 400, { error: 'invalid armor' }.to_json unless armor.is_a?(Hash)

  level = level.to_i

  %w[str dex con int wis cha].each do |key|
    score = abilities[key]
    halt 400, { error: "invalid ability #{key}" }.to_json unless integerish(score) && score.to_i.between?(1, 30)
  end

  modifiers = %w[str dex con int wis cha].each_with_object({}) do |key, acc|
    acc[key.to_sym] = ability_modifier(abilities[key].to_i)
  end

  base = armor['base']
  shield = armor['shield']
  dex_cap = armor['dex_cap']

  halt 400, { error: 'invalid armor base' }.to_json unless integerish(base)
  halt 400, { error: 'invalid armor dex_cap' }.to_json unless integerish(dex_cap)
  halt 400, { error: 'invalid armor shield' }.to_json unless shield == true || shield == false

  base = base.to_i
  dex_cap = dex_cap.to_i

  shield_bonus = shield ? 2 : 0
  hp_max = level * (6 + modifiers[:con])
  armor_class = base + [modifiers[:dex], dex_cap].min + shield_bonus

  {
    level: level,
    proficiency_bonus: proficiency_bonus(level),
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers
  }.to_json
end

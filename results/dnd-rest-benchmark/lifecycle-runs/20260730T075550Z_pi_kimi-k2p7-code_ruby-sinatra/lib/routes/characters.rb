# frozen_string_literal: true

# Route definitions for characters endpoints.

# --- Characters ---

post '/v1/characters/ability-modifier' do
  content_type :json
  body = parse_json_body

  score = body['score']
  validate_integer!(score, 'score', 1..30)

  JSON.dump(score: score, modifier: ability_modifier(score))
end

post '/v1/characters/proficiency' do
  content_type :json
  body = parse_json_body

  level = body['level']
  validate_integer!(level, 'level', 1..20)

  JSON.dump(level: level, proficiency_bonus: proficiency_bonus(level))
end

post '/v1/characters/derived-stats' do
  content_type :json
  body = parse_json_body

  level = body['level']
  validate_integer!(level, 'level', 1..20)

  abilities = body['abilities'] || {}
  ability_names = %w[str dex con int wis cha]
  ability_names.each do |name|
    validate_integer!(abilities[name], name, 1..30)
  end

  armor = body['armor'] || {}
  base = armor['base']
  shield = armor['shield']
  dex_cap = armor['dex_cap']

  unless base.is_a?(Integer)
    json_error(400, 'invalid base')
  end
  unless dex_cap.is_a?(Integer)
    json_error(400, 'invalid dex_cap')
  end
  unless shield == true || shield == false
    json_error(400, 'invalid shield')
  end

  modifiers = {}
  ability_names.each do |name|
    modifiers[name.to_sym] = ability_modifier(abilities[name])
  end

  proficiency = proficiency_bonus(level)
  hp_max = level * (6 + modifiers[:con])
  shield_bonus = shield ? 2 : 0
  armor_class = base + [modifiers[:dex], dex_cap].min + shield_bonus

  JSON.dump(
    level: level,
    proficiency_bonus: proficiency,
    hp_max: hp_max,
    armor_class: armor_class,
    modifiers: modifiers
  )
end


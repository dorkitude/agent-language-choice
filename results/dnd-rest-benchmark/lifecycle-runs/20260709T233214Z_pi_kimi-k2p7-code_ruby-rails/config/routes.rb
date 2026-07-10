Rails.application.routes.draw do
  get '/health', to: 'dnd#health'

  post '/v1/dice/stats', to: 'dnd#dice_stats'
  post '/v1/checks/ability', to: 'dnd#ability_check'
  post '/v1/encounters/adjusted-xp', to: 'dnd#adjusted_xp'
  post '/v1/initiative/order', to: 'dnd#initiative_order'

  post '/v1/characters/ability-modifier', to: 'dnd#ability_modifier'
  post '/v1/characters/proficiency', to: 'dnd#proficiency'
  post '/v1/characters/derived-stats', to: 'dnd#derived_stats'

  post '/v1/combat/sessions', to: 'dnd#combat_create'
  post '/v1/combat/sessions/:id/conditions', to: 'dnd#combat_add_condition'
  post '/v1/combat/sessions/:id/advance', to: 'dnd#combat_advance'
end

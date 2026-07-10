Rails.application.routes.draw do
  get "health", to: "health#index"

  namespace :v1, defaults: { format: :json } do
    post "dice/stats", to: "dice#stats"
    post "checks/ability", to: "checks#ability"
    post "encounters/adjusted-xp", to: "encounters#adjusted_xp"
    post "initiative/order", to: "initiative#order"

    post "characters/ability-modifier", to: "characters#ability_modifier"
    post "characters/proficiency", to: "characters#proficiency"
    post "characters/derived-stats", to: "characters#derived_stats"

    post "combat/sessions", to: "combat_sessions#create"
    post "combat/sessions/:id/conditions", to: "combat_sessions#add_condition"
    post "combat/sessions/:id/advance", to: "combat_sessions#advance"
  end
end

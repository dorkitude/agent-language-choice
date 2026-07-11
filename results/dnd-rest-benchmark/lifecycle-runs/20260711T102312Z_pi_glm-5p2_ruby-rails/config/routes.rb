# frozen_string_literal: true

Rails.application.routes.draw do
  get "/health", to: "health#index"
  post "/v1/dice/stats", to: "dice#stats"
  post "/v1/checks/ability", to: "ability_checks#ability"
  post "/v1/encounters/adjusted-xp", to: "encounters#adjusted_xp"
  post "/v1/initiative/order", to: "initiative#order"
end

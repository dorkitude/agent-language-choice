# Route table for the D&D REST benchmark API, grouped by the domain
# controller each path maps to. Paths and controller#action targets must
# stay in sync with the cumulative dm-tools evaluator suite.
DndApp.routes.draw do
  get '/health', to: 'core#health'

  post '/v1/dice/stats', to: 'core#dice_stats'
  post '/v1/checks/ability', to: 'core#ability_check'
  post '/v1/encounters/adjusted-xp', to: 'core#adjusted_xp'
  post '/v1/initiative/order', to: 'core#initiative_order'

  post '/v1/characters/ability-modifier', to: 'characters#ability_modifier'
  post '/v1/characters/proficiency', to: 'characters#proficiency'
  post '/v1/characters/derived-stats', to: 'characters#derived_stats'

  post '/v1/combat/sessions', to: 'combat#create_combat_session'
  post '/v1/combat/sessions/:id/conditions', to: 'combat#add_combat_condition'
  post '/v1/combat/sessions/:id/advance', to: 'combat#advance_combat_turn'

  post '/v1/auth/register', to: 'auth#register'
  post '/v1/auth/login', to: 'auth#login'

  get '/v1/storage/status', to: 'storage#storage_status'
  post '/v1/storage/reset', to: 'storage#storage_reset'

  post '/v1/compendium/monsters', to: 'compendium#create_monster'
  get '/v1/compendium/monsters/:slug', to: 'compendium#show_monster'
  post '/v1/compendium/items', to: 'compendium#create_item'
  get '/v1/compendium/items/:slug', to: 'compendium#show_item'

  post '/v1/campaigns', to: 'campaigns#create_campaign'
  post '/v1/campaigns/:campaign_id/characters', to: 'campaigns#add_campaign_character'
  post '/v1/campaigns/:campaign_id/events', to: 'campaigns#add_campaign_event'
  get '/v1/campaigns/:campaign_id/state', to: 'campaigns#campaign_state'

  post '/v1/campaigns/:campaign_id/quests', to: 'quests#create_quest'
  post '/v1/campaigns/:campaign_id/quests/:quest_id/progress', to: 'quests#update_quest_progress'
  get '/v1/campaigns/:campaign_id/quests/summary', to: 'quests#quest_summary'

  post '/v1/phb/spell-slots', to: 'phb#spell_slots'
  post '/v1/phb/rests/long', to: 'phb#long_rest'
  post '/v1/phb/equipment-load', to: 'phb#equipment_load'

  post '/v1/dm/encounter-builder', to: 'dm#dm_encounter_builder'
  post '/v1/dm/loot-parcel', to: 'dm#dm_loot_parcel'
  post '/v1/dm/session-recap', to: 'dm#dm_session_recap'

  post '/v1/campaigns/:campaign_id/factions', to: 'npcs#create_faction'
  post '/v1/campaigns/:campaign_id/npcs', to: 'npcs#create_npc'
  get '/v1/campaigns/:campaign_id/relationships', to: 'npcs#relationship_summary'

  post '/v1/campaigns/:campaign_id/inventory', to: 'inventory#add_inventory_item'
  post '/v1/campaigns/:campaign_id/characters/:character_id/equipment', to: 'inventory#assign_equipment'
  get '/v1/campaigns/:campaign_id/inventory/summary', to: 'inventory#inventory_summary'

  post '/v1/campaigns/:campaign_id/downtime/crafting', to: 'downtime#create_crafting_project'
  post '/v1/campaigns/:campaign_id/downtime/crafting/:project_id/advance', to: 'downtime#advance_crafting_project'

  get '/v1/campaigns/:campaign_id/sessions/next', to: 'sessions#next_session'
  post '/v1/campaigns/:campaign_id/sessions', to: 'sessions#schedule_session'
  post '/v1/campaigns/:campaign_id/sessions/:session_id/attendance', to: 'sessions#record_attendance'

  get '/v1/campaigns/:campaign_id/audit', to: 'audit#audit_log'
  get '/v1/campaigns/:campaign_id/export', to: 'audit#export_campaign'

  get '/v1/campaigns/:campaign_id/analytics/summary', to: 'analytics#analytics_summary'
  post '/v1/campaigns/:campaign_id/analytics/risk-report', to: 'analytics#risk_report'

  post '/v1/play/campaigns', to: 'play#create_play_campaign'
  post '/v1/play/campaigns/:id/members', to: 'play#join_play_campaign'
  post '/v1/play/campaigns/:id/start', to: 'play#start_play_campaign'
  post '/v1/play/campaigns/:id/narrations', to: 'play#create_narration'
  post '/v1/play/campaigns/:id/actions', to: 'play#create_action'
  post '/v1/play/campaigns/:id/resolutions', to: 'play#create_resolution'
  get '/v1/play/campaigns/:id/turn', to: 'play#play_turn'
  post '/v1/play/campaigns/:id/turn/nudge', to: 'play#turn_nudge'
  post '/v1/play/campaigns/:id/turn/travel', to: 'play#travel_turn'
  post '/v1/play/campaigns/:id/turn/rest', to: 'play#rest_turn'
  get '/v1/play/campaigns/:id/my-turn', to: 'play#my_turn'
  get '/v1/play/campaigns/:id/gm/status', to: 'play#gm_status'
  put '/v1/play/campaigns/:id/document', to: 'play#update_campaign_document'
  get '/v1/play/campaigns/:id/document', to: 'play#show_campaign_document'

  post '/v1/play/campaigns/:id/invitations', to: 'play#create_invitation'
  post '/v1/play/campaigns/:id/invitations/:invitation_id/accept', to: 'play#accept_invitation'
  get '/v1/play/campaigns/:id/invitations', to: 'play#list_invitations'

  post '/v1/play/campaigns/:id/delegations', to: 'play#create_delegation'
  get '/v1/play/campaigns/:id/delegations/audit', to: 'play#delegations_audit'
  delete '/v1/play/campaigns/:id/delegations/:username', to: 'play#revoke_delegation'

  post '/v1/play/campaigns/:campaign_id/encounters', to: 'play#create_encounter'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/monsters', to: 'play#add_monster'
  delete '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/monsters/:monster_id', to: 'play#remove_monster'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/combatants', to: 'play#bind_combatant'
  delete '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/combatants/:member', to: 'play#unbind_combatant'
  get '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/turn', to: 'play#encounter_turn'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/turn/advance', to: 'play#advance_encounter_turn'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/turn/delay', to: 'play#delay_encounter_turn'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/turn/ready', to: 'play#ready_encounter_turn'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/actions', to: 'play#create_combat_action'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/damage', to: 'play#apply_damage'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/heal', to: 'play#apply_healing'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/conditions', to: 'play#add_condition'
  get '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/status', to: 'play#encounter_status'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/rewards', to: 'play#award_encounter_rewards'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/close', to: 'play#close_encounter'
  post '/v1/play/campaigns/:campaign_id/encounters/:encounter_id/end', to: 'play#end_encounter'

  post '/v1/play/campaigns/:campaign_id/characters/:char_id/damage', to: 'play#character_damage'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/death-saves', to: 'play#death_save'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/status', to: 'play#character_status'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/owner', to: 'play#character_owner'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/claim', to: 'play#claim_character'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/transfer', to: 'play#transfer_character'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/currency', to: 'play#character_currency'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/currency/transfers', to: 'play#create_currency_transfer'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/build', to: 'play#build_character'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/level-up', to: 'play#level_up'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/skill-check', to: 'play#skill_check'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/spells', to: 'play#add_spell'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/spells', to: 'play#list_spells'
  put '/v1/play/campaigns/:campaign_id/characters/:char_id/prepared-spells', to: 'play#update_prepared_spells'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/prepared-spells', to: 'play#prepared_spells'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/casts', to: 'play#cast_spell'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/casts', to: 'play#list_casts'
  put '/v1/play/campaigns/:campaign_id/characters/:char_id/concentration', to: 'play#set_concentration'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/concentration', to: 'play#get_concentration'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/concentration/advance-turn', to: 'play#advance_concentration_turn'
  delete '/v1/play/campaigns/:campaign_id/characters/:char_id/concentration', to: 'play#clear_concentration'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/inventory/items', to: 'play#add_inventory_item'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/inventory/items', to: 'play#list_inventory_items'
  delete '/v1/play/campaigns/:campaign_id/characters/:char_id/inventory/items/:item_id', to: 'play#remove_inventory_item'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/inventory/items/:item_id/consume', to: 'play#consume_inventory_item'
  put '/v1/play/campaigns/:campaign_id/characters/:char_id/equipment/:slot', to: 'play#update_equipment'
  get '/v1/play/campaigns/:campaign_id/characters/:char_id/equipment/:slot', to: 'play#show_equipment'
  post '/v1/play/campaigns/:campaign_id/characters/:char_id/equipment/:slot/attune', to: 'play#attune_equipment'

  post '/v1/play/campaigns/:campaign_id/scenes', to: 'play#create_scene'
  get '/v1/play/campaigns/:campaign_id/scenes/current', to: 'play#current_scene'
  post '/v1/play/campaigns/:campaign_id/scenes/:scene_id/enter', to: 'play#enter_scene'
  post '/v1/play/campaigns/:campaign_id/scenes/:scene_id/close', to: 'play#close_scene'

  post '/v1/play/campaigns/:campaign_id/locations', to: 'play#create_location'
  post '/v1/play/campaigns/:campaign_id/locations/:from_id/connections', to: 'play#create_location_connection'
  get '/v1/play/campaigns/:campaign_id/locations/:loc_id/travel', to: 'play#location_travel'

  post '/v1/play/campaigns/:campaign_id/loot', to: 'play#create_loot'
  post '/v1/play/campaigns/:campaign_id/loot/:loot_id/votes', to: 'play#create_loot_vote'
  post '/v1/play/campaigns/:campaign_id/loot/:loot_id/assign', to: 'play#assign_loot'
  get '/v1/play/campaigns/:campaign_id/loot/:loot_id', to: 'play#show_loot'

  post '/v1/play/campaigns/:id/npcs', to: 'play#create_play_npc'
  put '/v1/play/campaigns/:id/npcs/:npc_id/agenda', to: 'play#update_play_npc_agenda'
  get '/v1/play/campaigns/:id/npcs/:npc_id', to: 'play#show_play_npc'
  post '/v1/play/campaigns/:id/npcs/:npc_id/dialogue', to: 'play#create_play_npc_dialogue'
  get '/v1/play/campaigns/:id/npcs/:npc_id/dialogue', to: 'play#play_npc_dialogue'

  post '/v1/play/campaigns/:id/factions', to: 'play#create_play_faction'
  post '/v1/play/campaigns/:id/factions/:faction_id/reputation', to: 'play#update_faction_reputation'
  get '/v1/play/campaigns/:id/factions/:faction_id/reputation', to: 'play#faction_reputation'

  post '/v1/play/campaigns/:id/relationships', to: 'play#create_relationship'
  put '/v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind', to: 'play#update_relationship'
  get '/v1/play/campaigns/:id/relationships', to: 'play#list_relationships'

  post '/v1/play/campaigns/:id/clues', to: 'play#create_clue'
  get '/v1/play/campaigns/:id/clues', to: 'play#list_clues'

  post '/v1/play/campaigns/:id/quests', to: 'play#create_play_quest'
  put '/v1/play/campaigns/:id/quests/:quest_id/state', to: 'play#update_play_quest_state'
  get '/v1/play/campaigns/:id/quests', to: 'play#list_play_quests'
  put '/v1/play/campaigns/:id/quests/:quest_id/rewards', to: 'play#configure_quest_rewards'
  post '/v1/play/campaigns/:id/quests/:quest_id/rewards/award', to: 'play#award_quest_rewards'
  get '/v1/play/campaigns/:id/characters/:character_id/rewards', to: 'play#character_quest_rewards'

  post '/v1/play/campaigns/:id/world-events', to: 'play#create_world_event'
  post '/v1/play/campaigns/:id/world-events/:event_id/resolve', to: 'play#resolve_world_event'
  get '/v1/play/campaigns/:id/world-events', to: 'play#list_world_events'

  post '/v1/play/campaigns/:id/calendar', to: 'play#create_calendar'
  get '/v1/play/campaigns/:id/calendar', to: 'play#show_calendar'
  post '/v1/play/campaigns/:id/calendar/advance', to: 'play#advance_calendar'

  post '/v1/play/campaigns/:id/settlements', to: 'play#create_settlement'
  put '/v1/play/campaigns/:id/settlements/:settlement_id', to: 'play#update_settlement'
  post '/v1/play/campaigns/:id/settlements/:settlement_id/discover', to: 'play#discover_settlement'
  get '/v1/play/campaigns/:id/settlements', to: 'play#list_settlements'

  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops', to: 'play#create_shop'
  get '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id', to: 'play#show_shop'
  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy', to: 'play#buy_from_shop'
  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/sell', to: 'play#sell_to_shop'

  post '/v1/play/campaigns/:id/recipes', to: 'play#create_recipe'
  get '/v1/play/campaigns/:id/recipes', to: 'play#list_recipes'
  post '/v1/play/campaigns/:id/recipes/:recipe_id/craft', to: 'play#craft_recipe'

  post '/v1/play/campaigns/:id/downtime/activities', to: 'play#create_downtime_activity'
  post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations', to: 'play#create_downtime_allocation'
  post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress', to: 'play#progress_downtime_allocation'
  get '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id', to: 'play#show_downtime_allocation'

  put '/v1/play/campaigns/:id/session-zero', to: 'play#update_session_zero'
  get '/v1/play/campaigns/:id/session-zero', to: 'play#show_session_zero'

  post '/v1/play/campaigns/:id/content', to: 'play#create_content'
  put '/v1/play/campaigns/:id/content/:content_id/tags', to: 'play#update_content_tags'
  get '/v1/play/campaigns/:id/content', to: 'play#list_content'

  post '/v1/play/campaigns/:id/notes', to: 'play#create_note'
  get '/v1/play/campaigns/:id/notes', to: 'play#list_notes'
  get '/v1/play/campaigns/:id/notes/:note_id', to: 'play#show_note'
  put '/v1/play/campaigns/:id/notes/:note_id', to: 'play#update_note'

  post '/v1/play/campaigns/:id/whispers', to: 'play#create_whisper'
  get '/v1/play/campaigns/:id/whispers', to: 'play#list_whispers'

  get '/v1/play/campaigns/:id/characters/:character_id/sheet', to: 'play#show_character_sheet'
end

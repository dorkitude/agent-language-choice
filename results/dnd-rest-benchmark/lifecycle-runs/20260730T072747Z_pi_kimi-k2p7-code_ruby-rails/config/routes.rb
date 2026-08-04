Rails.application.routes.draw do
  # Public API schema
  get '/v1/schema', to: 'schema#show'

  # Liveness probe
  get '/health', to: 'health#index'
  get '/healthz', to: 'health#liveness'
  get '/readyz', to: 'health#readiness'

  # Core utilities (no persistence)
  post '/v1/auth/register', to: 'auth#register'
  post '/v1/auth/login', to: 'auth#login'
  post '/v1/dice/stats', to: 'dice#stats'
  post '/v1/checks/ability', to: 'checks#ability'
  post '/v1/encounters/adjusted-xp', to: 'encounters#adjusted_xp'
  post '/v1/initiative/order', to: 'initiative#order'
  post '/v1/characters/ability-modifier', to: 'characters#ability_modifier'
  post '/v1/characters/proficiency', to: 'characters#proficiency'
  post '/v1/characters/derived-stats', to: 'characters#derived_stats'

  # Combat and storage
  post '/v1/combat/sessions', to: 'combat_sessions#create'
  post '/v1/combat/sessions/:id/conditions', to: 'combat_sessions#add_condition'
  post '/v1/combat/sessions/:id/advance', to: 'combat_sessions#advance'
  get '/v1/storage/status', to: 'storage#status'
  post '/v1/storage/reset', to: 'storage#reset'

  # Compendium
  post '/v1/compendium/monsters', to: 'compendium#create_monster'
  get '/v1/compendium/monsters/:slug', to: 'compendium#read_monster'
  post '/v1/compendium/items', to: 'compendium#create_item'
  get '/v1/compendium/items/:slug', to: 'compendium#read_item'

  # Campaigns and analytics
  post '/v1/campaigns', to: 'campaigns#create'
  post '/v1/campaigns/:id/characters', to: 'campaigns#add_character'
  post '/v1/campaigns/:id/events', to: 'campaigns#add_event'
  get '/v1/campaigns/:id/state', to: 'campaigns#state'
  get '/v1/campaigns/:id/audit', to: 'campaigns#audit'
  get '/v1/campaigns/:id/export', to: 'campaigns#export'
  get '/v1/campaigns/:id/analytics/summary', to: 'analytics#summary'
  post '/v1/campaigns/:id/analytics/risk-report', to: 'analytics#risk_report'

  # Quests, NPCs/factions, inventory, downtime, sessions
  post '/v1/campaigns/:id/quests', to: 'quests#create'
  post '/v1/campaigns/:id/quests/:quest_id/progress', to: 'quests#progress'
  get '/v1/campaigns/:id/quests/summary', to: 'quests#summary'
  post '/v1/campaigns/:id/factions', to: 'npcs_and_factions#create_faction'
  post '/v1/campaigns/:id/npcs', to: 'npcs_and_factions#create_npc'
  get '/v1/campaigns/:id/relationships', to: 'npcs_and_factions#relationships'
  post '/v1/campaigns/:id/inventory', to: 'inventory#add_item'
  post '/v1/campaigns/:id/characters/:character_id/equipment', to: 'inventory#assign_equipment'
  get '/v1/campaigns/:id/inventory/summary', to: 'inventory#summary'
  post '/v1/campaigns/:id/downtime/crafting', to: 'downtime_crafting#create'
  post '/v1/campaigns/:id/downtime/crafting/:project_id/advance', to: 'downtime_crafting#advance'
  post '/v1/campaigns/:id/sessions', to: 'sessions#create'
  get '/v1/campaigns/:id/sessions/next', to: 'sessions#next'
  post '/v1/campaigns/:id/sessions/:session_id/attendance', to: 'sessions#attendance'

  # Player's Handbook rules
  post '/v1/phb/spell-slots', to: 'phb#spell_slots'
  post '/v1/phb/rests/long', to: 'phb#long_rest'
  post '/v1/phb/equipment-load', to: 'phb#equipment_load'

  # DM tools
  post '/v1/dm/encounter-builder', to: 'dm#encounter_builder'
  post '/v1/dm/loot-parcel', to: 'dm#loot_parcel'
  post '/v1/dm/session-recap', to: 'dm#session_recap'

  # Authenticated turn-based play surface
  post '/v1/play/campaigns', to: 'play_campaigns#create'
  post '/v1/play/campaigns/:id/spectators', to: 'play_campaigns#create_spectator'
  get '/v1/play/campaigns/:id/spectator-view', to: 'play_campaigns#spectator_view'
  post '/v1/play/campaigns/:id/members', to: 'play_campaigns#add_member'
  get '/v1/play/campaigns/:id/onboarding', to: 'play_campaigns#onboarding'
  post '/v1/play/campaigns/:id/start', to: 'play_campaigns#start'
  post '/v1/play/campaigns/:id/narrations', to: 'play_campaigns#narration'
  post '/v1/play/campaigns/:id/messages', to: 'play_campaigns#create_message'
  get '/v1/play/campaigns/:id/turn', to: 'play_campaigns#turn'
  post '/v1/play/campaigns/:id/turn/nudge', to: 'play_campaigns#nudge'
  get '/v1/play/campaigns/:id/my-turn', to: 'play_campaigns#my_turn'
  get '/v1/play/campaigns/:id/gm/status', to: 'play_campaigns#gm_status'
  post '/v1/play/campaigns/:id/actions', to: 'play_campaigns#action'
  post '/v1/play/campaigns/:id/resolutions', to: 'play_campaigns#resolution'
  get '/v1/play/campaigns/:id/document', to: 'play_campaigns#document'
  put '/v1/play/campaigns/:id/document', to: 'play_campaigns#update_document'

  # Scene state
  post '/v1/play/campaigns/:id/scenes', to: 'play_campaigns#create_scene'
  post '/v1/play/campaigns/:id/scenes/:scene_id/enter', to: 'play_campaigns#enter_scene'
  post '/v1/play/campaigns/:id/scenes/:scene_id/close', to: 'play_campaigns#close_scene'
  get '/v1/play/campaigns/:id/scenes/current', to: 'play_campaigns#current_scene'

  # Location graph
  post '/v1/play/campaigns/:id/locations', to: 'play_campaigns#create_location'
  post '/v1/play/campaigns/:id/locations/:from_id/connections', to: 'play_campaigns#create_connection'
  get '/v1/play/campaigns/:id/locations/:loc_id/travel', to: 'play_campaigns#travel'
  post '/v1/play/campaigns/:id/turn/travel', to: 'play_campaigns#travel_turn'

  # Rest turns
  post '/v1/play/campaigns/:id/turn/rest', to: 'play_campaigns#rest'

  # Encounters
  post '/v1/play/campaigns/:id/encounters', to: 'play_campaigns#create_encounter'
  post '/v1/play/campaigns/:id/encounters/:enc_id/monsters', to: 'play_campaigns#add_monster'
  delete '/v1/play/campaigns/:id/encounters/:enc_id/monsters/:monster_id', to: 'play_campaigns#remove_monster'

  # Party combat binding
  post '/v1/play/campaigns/:id/encounters/:enc_id/combatants', to: 'play_campaigns#bind_member'
  delete '/v1/play/campaigns/:id/encounters/:enc_id/combatants/:member', to: 'play_campaigns#unbind_member'

  # Combat turn authority
  get '/v1/play/campaigns/:id/encounters/:enc_id/turn', to: 'play_campaigns#encounter_turn'
  post '/v1/play/campaigns/:id/encounters/:enc_id/turn/advance', to: 'play_campaigns#encounter_advance'
  post '/v1/play/campaigns/:id/encounters/:enc_id/turn/delay', to: 'play_campaigns#turn_delay'
  post '/v1/play/campaigns/:id/encounters/:enc_id/turn/ready', to: 'play_campaigns#turn_ready'

  # Player combat actions
  post '/v1/play/campaigns/:id/encounters/:enc_id/actions', to: 'play_campaigns#combat_action'

  # Damage and healing
  post '/v1/play/campaigns/:id/encounters/:enc_id/damage', to: 'play_campaigns#damage'
  post '/v1/play/campaigns/:id/encounters/:enc_id/heal', to: 'play_campaigns#heal'

  # Encounter rewards and close
  post '/v1/play/campaigns/:id/encounters/:enc_id/rewards', to: 'play_campaigns#rewards'
  post '/v1/play/campaigns/:id/encounters/:enc_id/close', to: 'play_campaigns#close_encounter'
  post '/v1/play/campaigns/:id/encounters/:enc_id/end', to: 'play_campaigns#end_encounter'

  # Condition interactions
  post '/v1/play/campaigns/:id/encounters/:enc_id/conditions', to: 'play_campaigns#add_condition'
  get '/v1/play/campaigns/:id/encounters/:enc_id/status', to: 'play_campaigns#encounter_status'

  # Death saves
  post '/v1/play/campaigns/:id/characters/:char_id/damage', to: 'play_campaigns#character_damage'
  post '/v1/play/campaigns/:id/characters/:char_id/death-saves', to: 'play_campaigns#death_saves'
  get '/v1/play/campaigns/:id/characters/:char_id/status', to: 'play_campaigns#character_status'

  # Character ownership
  get '/v1/play/campaigns/:id/characters/:char_id/owner', to: 'play_campaigns#owner'
  post '/v1/play/campaigns/:id/characters/:char_id/claim', to: 'play_campaigns#claim'
  post '/v1/play/campaigns/:id/characters/:char_id/transfer', to: 'play_campaigns#transfer'

  # Character creation choices
  post '/v1/play/campaigns/:id/characters/:char_id/build', to: 'play_campaigns#build'

  # Level progression
  post '/v1/play/campaigns/:id/characters/:char_id/level-up', to: 'play_campaigns#level_up'

  # Skills and proficiencies
  post '/v1/play/campaigns/:id/characters/:char_id/skill-check', to: 'play_campaigns#skill_check'

  # Spellbook state
  post '/v1/play/campaigns/:id/characters/:char_id/spells', to: 'play_campaigns#add_spell'
  get '/v1/play/campaigns/:id/characters/:char_id/spells', to: 'play_campaigns#list_spells'

  # Prepared spells
  put '/v1/play/campaigns/:id/characters/:char_id/prepared-spells', to: 'play_campaigns#prepare_spells'
  get '/v1/play/campaigns/:id/characters/:char_id/prepared-spells', to: 'play_campaigns#get_prepared_spells'

  # Spell casting
  post '/v1/play/campaigns/:id/characters/:character_id/casts', to: 'play_campaigns#cast_spell'
  get '/v1/play/campaigns/:id/characters/:character_id/casts', to: 'play_campaigns#list_casts'

  # Concentration
  put '/v1/play/campaigns/:id/characters/:character_id/concentration', to: 'play_campaigns#set_concentration'
  get '/v1/play/campaigns/:id/characters/:character_id/concentration', to: 'play_campaigns#get_concentration'
  post '/v1/play/campaigns/:id/characters/:character_id/concentration/advance-turn', to: 'play_campaigns#advance_concentration'
  delete '/v1/play/campaigns/:id/characters/:character_id/concentration', to: 'play_campaigns#clear_concentration'

  # Inventory stacks
  post '/v1/play/campaigns/:id/characters/:character_id/inventory/items', to: 'play_campaigns#add_inventory_item'
  get '/v1/play/campaigns/:id/characters/:character_id/inventory/items', to: 'play_campaigns#list_inventory_items'
  delete '/v1/play/campaigns/:id/characters/:character_id/inventory/items/:item_id', to: 'play_campaigns#remove_inventory_item'

  # Consumables
  post '/v1/play/campaigns/:id/characters/:character_id/inventory/items/:item_id/consume', to: 'play_campaigns#consume'

  # Equipment and attunement
  put '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot', to: 'play_campaigns#equip'
  get '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot', to: 'play_campaigns#get_equipment'
  post '/v1/play/campaigns/:id/characters/:character_id/equipment/:slot/attune', to: 'play_campaigns#attune'

  # Currency and trade
  get '/v1/play/campaigns/:id/characters/:character_id/currency', to: 'play_campaigns#currency'
  post '/v1/play/campaigns/:id/characters/:character_id/currency/transfers', to: 'play_campaigns#transfer_currency'

  # Transactional transfers
  post '/v1/play/campaigns/:id/transactional-transfers', to: 'play_campaigns#create_transactional_transfer'
  get '/v1/play/campaigns/:id/transactional-transfers', to: 'play_campaigns#transactional_transfers'

  # Loot distribution
  post '/v1/play/campaigns/:id/loot', to: 'play_campaigns#create_loot'
  post '/v1/play/campaigns/:id/loot/:loot_id/votes', to: 'play_campaigns#vote_loot'
  post '/v1/play/campaigns/:id/loot/:loot_id/assign', to: 'play_campaigns#assign_loot'
  get '/v1/play/campaigns/:id/loot/:loot_id', to: 'play_campaigns#get_loot'

  # NPC agendas
  post '/v1/play/campaigns/:id/npcs', to: 'play_campaigns#create_npc'
  put '/v1/play/campaigns/:id/npcs/:npc_id/agenda', to: 'play_campaigns#update_npc_agenda'
  get '/v1/play/campaigns/:id/npcs/:npc_id', to: 'play_campaigns#get_npc'

  # NPC dialogue
  post '/v1/play/campaigns/:id/npcs/:npc_id/dialogue', to: 'play_campaigns#create_dialogue'
  get '/v1/play/campaigns/:id/npcs/:npc_id/dialogue', to: 'play_campaigns#list_dialogue'

  # Faction reputation
  post '/v1/play/campaigns/:id/factions', to: 'play_campaigns#create_faction'
  post '/v1/play/campaigns/:id/factions/:faction_id/reputation', to: 'play_campaigns#create_reputation'
  get '/v1/play/campaigns/:id/factions/:faction_id/reputation', to: 'play_campaigns#get_reputation'

  # Relationship graph
  post '/v1/play/campaigns/:id/relationships', to: 'play_campaigns#create_relationship'
  put '/v1/play/campaigns/:id/relationships/:source_id/:target_id/:kind', to: 'play_campaigns#update_relationship'
  get '/v1/play/campaigns/:id/relationships', to: 'play_campaigns#list_relationships'

  # Secrets and clues
  post '/v1/play/campaigns/:id/clues', to: 'play_campaigns#create_clue'
  get '/v1/play/campaigns/:id/clues', to: 'play_campaigns#list_clues'

  # Quest dependencies
  post '/v1/play/campaigns/:id/quests', to: 'play_quests#create'
  put '/v1/play/campaigns/:id/quests/:quest_id/state', to: 'play_quests#update_state'
  get '/v1/play/campaigns/:id/quests', to: 'play_quests#index'

  # Quest rewards
  put '/v1/play/campaigns/:id/quests/:quest_id/rewards', to: 'play_quests#configure_rewards'
  post '/v1/play/campaigns/:id/quests/:quest_id/rewards/award', to: 'play_quests#award'
  get '/v1/play/campaigns/:id/characters/:character_id/rewards', to: 'play_quests#character_rewards'

  # World events
  post '/v1/play/campaigns/:id/world-events', to: 'play_world_events#create'
  post '/v1/play/campaigns/:id/world-events/:event_id/resolve', to: 'play_world_events#resolve'
  get '/v1/play/campaigns/:id/world-events', to: 'play_world_events#index'

  # Calendar and weather
  post '/v1/play/campaigns/:id/calendar', to: 'calendar#create'
  get '/v1/play/campaigns/:id/calendar', to: 'calendar#show'
  post '/v1/play/campaigns/:id/calendar/advance', to: 'calendar#advance'

  # Settlements
  post '/v1/play/campaigns/:id/settlements', to: 'settlements#create'
  put '/v1/play/campaigns/:id/settlements/:settlement_id', to: 'settlements#update'
  post '/v1/play/campaigns/:id/settlements/:settlement_id/discover', to: 'settlements#discover'
  get '/v1/play/campaigns/:id/settlements', to: 'settlements#index'

  # Shops
  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops', to: 'shops#create'
  get '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id', to: 'shops#show'
  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/buy', to: 'shops#buy'
  post '/v1/play/campaigns/:id/settlements/:settlement_id/shops/:shop_id/sell', to: 'shops#sell'

  # Recipe catalog
  post '/v1/play/campaigns/:id/recipes', to: 'recipes#create'
  get '/v1/play/campaigns/:id/recipes', to: 'recipes#index'
  post '/v1/play/campaigns/:id/recipes/:recipe_id/craft', to: 'recipes#craft'

  # Recurring downtime
  post '/v1/play/campaigns/:id/downtime/activities', to: 'play_downtime#create_activity'
  post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations', to: 'play_downtime#create_allocation'
  post '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id/progress', to: 'play_downtime#progress'
  get '/v1/play/campaigns/:id/characters/:character_id/downtime/allocations/:activity_id', to: 'play_downtime#show_allocation'

  # Session-zero settings
  put '/v1/play/campaigns/:id/session-zero', to: 'session_zero#update'
  get '/v1/play/campaigns/:id/session-zero', to: 'session_zero#show'

  # Content tags
  post '/v1/play/campaigns/:id/content', to: 'play_campaigns#create_content'
  put '/v1/play/campaigns/:id/content/:content_id/tags', to: 'play_campaigns#update_content_tags'
  get '/v1/play/campaigns/:id/content', to: 'play_campaigns#list_content'

  # Privacy controls: notes, whispers, and character sheets
  post '/v1/play/campaigns/:id/notes', to: 'play_campaigns#create_note'
  get '/v1/play/campaigns/:id/notes', to: 'play_campaigns#list_notes'
  get '/v1/play/campaigns/:id/notes/:note_id', to: 'play_campaigns#show_note'
  put '/v1/play/campaigns/:id/notes/:note_id', to: 'play_campaigns#update_note'

  post '/v1/play/campaigns/:id/whispers', to: 'play_campaigns#create_whisper'
  get '/v1/play/campaigns/:id/whispers', to: 'play_campaigns#list_whispers'

  get '/v1/play/campaigns/:id/characters/:character_id/sheet', to: 'play_campaigns#character_sheet'

  # Campaign invitations
  post '/v1/play/campaigns/:id/invitations', to: 'play_campaigns#create_invitation'
  post '/v1/play/campaigns/:id/invitations/:invitation_id/accept', to: 'play_campaigns#accept_invitation'
  get '/v1/play/campaigns/:id/invitations', to: 'play_campaigns#list_invitations'

  # GM delegation
  post '/v1/play/campaigns/:id/delegations', to: 'play_campaigns#grant_delegation'
  get '/v1/play/campaigns/:id/delegations/audit', to: 'play_campaigns#delegation_audit'
  delete '/v1/play/campaigns/:id/delegations/:username', to: 'play_campaigns#revoke_delegation'

  # Actor audit trail
  post '/v1/play/campaigns/:id/audit-events', to: 'audit_events#create'
  get '/v1/play/campaigns/:id/audit-events', to: 'audit_events#index'

  # Projection event log
  post '/v1/play/campaigns/:id/projection-events', to: 'projection_events#create'
  get '/v1/play/campaigns/:id/projection', to: 'projection_events#show'
  get '/v1/play/campaigns/:id/projection/rebuild', to: 'projection_events#rebuild'

  # Idempotent events
  post '/v1/play/campaigns/:id/idempotent-events', to: 'idempotent_events#create'
  get '/v1/play/campaigns/:id/idempotent-events', to: 'idempotent_events#index'

  # Safe turns
  post '/v1/play/campaigns/:id/safe-turns', to: 'safe_turns#create'
  get '/v1/play/campaigns/:id/safe-turns', to: 'safe_turns#index'

  # Load-safe event feed
  post '/v1/play/campaigns/:id/feed-events', to: 'feed_events#create'
  get '/v1/play/campaigns/:id/event-feed', to: 'feed_events#index'

  # Versioned exports
  post '/v1/play/campaigns/:id/exports', to: 'play_campaigns#create_export'
  get '/v1/play/campaigns/:id/exports', to: 'play_campaigns#list_exports'
  get '/v1/play/campaigns/:id/exports/:version', to: 'play_campaigns#read_export'

  # Versioned imports
  post '/v1/play/campaigns/:id/imports', to: 'play_campaigns#create_import'
  get '/v1/play/campaigns/:id/import-state', to: 'play_campaigns#import_state'

  # Campaign backups
  post '/v1/play/campaigns/:id/backups', to: 'play_campaigns#create_backup'
  get '/v1/play/campaigns/:id/backups', to: 'play_campaigns#list_backups'
  post '/v1/play/campaigns/:id/backups/:backup_id/restore', to: 'play_campaigns#restore_backup'

  # Pagination/search records
  post '/v1/play/campaigns/:id/search-records', to: 'search_records#create'
  get '/v1/play/campaigns/:id/search-records', to: 'search_records#index'

  # Rate limits
  post '/v1/play/campaigns/:id/rate-events', to: 'rate_events#create'
  get '/v1/play/campaigns/:id/rate-events', to: 'rate_events#index'

  # Deterministic replay
  post '/v1/play/campaigns/:id/replay-events', to: 'play_campaigns#append_replay_event'
  get '/v1/play/campaigns/:id/replay', to: 'play_campaigns#replay'
  get '/v1/play/campaigns/:id/replay/check', to: 'play_campaigns#replay_check'

  # Deterministic RNG ledger
  put '/v1/play/campaigns/:id/rng-seed', to: 'play_campaigns#rng_seed'
  post '/v1/play/campaigns/:id/rng-rolls', to: 'play_campaigns#rng_roll'
  get '/v1/play/campaigns/:id/rng-ledger', to: 'play_campaigns#rng_ledger'

  # Moderation workflow
  post '/v1/play/campaigns/:id/moderation/reports', to: 'play_campaigns#create_moderation_report'
  get '/v1/play/campaigns/:id/moderation/reports', to: 'play_campaigns#list_moderation_reports'
  put '/v1/play/campaigns/:id/moderation/reports/:report_id/resolution', to: 'play_campaigns#resolve_moderation_report'

  # Safety boundaries
  put '/v1/play/campaigns/:id/safety-boundaries', to: 'play_campaigns#replace_safety_boundaries'
  get '/v1/play/campaigns/:id/safety-boundaries', to: 'play_campaigns#read_safety_boundaries'
  post '/v1/play/campaigns/:id/safety-checks', to: 'play_campaigns#submit_safety_check'
  get '/v1/play/campaigns/:id/safety-events', to: 'play_campaigns#read_safety_events'

  # Fixture seeding
  post '/v1/play/campaigns/:id/fixture-seeds', to: 'play_campaigns#seed_fixture'
  get '/v1/play/campaigns/:id/fixture-state', to: 'play_campaigns#read_fixture_state'

  # Service metrics
  get '/v1/play/campaigns/:id/metrics', to: 'metrics#show'

  # Global maintenance switch (DM only)
  post '/v1/play/campaigns/:id/service-mode', to: 'service_mode#update'

  # Schema migrations
  post '/v1/play/campaigns/:id/migrations', to: 'play_campaigns#create_migration'
  get '/v1/play/campaigns/:id/migration-state', to: 'play_campaigns#migration_state'
end

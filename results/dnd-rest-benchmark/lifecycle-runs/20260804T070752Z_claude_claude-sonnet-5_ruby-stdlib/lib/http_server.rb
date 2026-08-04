# frozen_string_literal: true

require 'json'
require 'uri'
require_relative 'errors'
require_relative 'handlers/core'
require_relative 'handlers/characters'
require_relative 'handlers/combat'
require_relative 'handlers/auth'
require_relative 'handlers/storage'
require_relative 'handlers/compendium'
require_relative 'handlers/campaigns'
require_relative 'handlers/phb'
require_relative 'handlers/dm_tools'
require_relative 'handlers/quests'
require_relative 'handlers/npcs'
require_relative 'handlers/inventory'
require_relative 'handlers/downtime'
require_relative 'handlers/sessions'
require_relative 'handlers/audit'
require_relative 'handlers/analytics'
require_relative 'handlers/play'

# Minimal single-threaded HTTP/1.1 server built directly on TCPSocket: reads
# one request, dispatches it by exact [method, path] match or, for routes
# with a path parameter, by regex, then writes one response and closes the
# connection (Connection: close, no keep-alive).
module HttpServer
  # Exact-match routes: no path parameters.
  ROUTES = {
    ['GET', '/health'] => Handlers::Core.method(:health),
    ['GET', '/healthz'] => Handlers::Core.method(:healthz),
    ['GET', '/readyz'] => Handlers::Core.method(:readyz),
    ['GET', '/v1/schema'] => Handlers::Core.method(:schema),
    ['POST', '/v1/auth/register'] => Handlers::Auth.method(:register),
    ['POST', '/v1/auth/login'] => Handlers::Auth.method(:login),
    ['POST', '/v1/dice/stats'] => Handlers::Core.method(:dice_stats),
    ['POST', '/v1/checks/ability'] => Handlers::Core.method(:ability_check),
    ['POST', '/v1/encounters/adjusted-xp'] => Handlers::Core.method(:adjusted_xp),
    ['POST', '/v1/initiative/order'] => Handlers::Core.method(:initiative_order),
    ['POST', '/v1/characters/ability-modifier'] => Handlers::Characters.method(:ability_modifier),
    ['POST', '/v1/characters/proficiency'] => Handlers::Characters.method(:proficiency),
    ['POST', '/v1/characters/derived-stats'] => Handlers::Characters.method(:derived_stats),
    ['POST', '/v1/combat/sessions'] => Handlers::Combat.method(:create_session),
    ['POST', '/v1/compendium/monsters'] => Handlers::Compendium.method(:create_monster),
    ['POST', '/v1/compendium/items'] => Handlers::Compendium.method(:create_item),
    ['GET', '/v1/storage/status'] => Handlers::Storage.method(:status),
    ['POST', '/v1/storage/reset'] => Handlers::Storage.method(:reset),
    ['POST', '/v1/campaigns'] => Handlers::Campaigns.method(:create_campaign),
    ['POST', '/v1/phb/spell-slots'] => Handlers::Phb.method(:spell_slots),
    ['POST', '/v1/phb/rests/long'] => Handlers::Phb.method(:long_rest),
    ['POST', '/v1/phb/equipment-load'] => Handlers::Phb.method(:equipment_load),
    ['POST', '/v1/dm/encounter-builder'] => Handlers::DmTools.method(:encounter_builder),
    ['POST', '/v1/dm/loot-parcel'] => Handlers::DmTools.method(:loot_parcel),
    ['POST', '/v1/dm/session-recap'] => Handlers::DmTools.method(:session_recap)
  }.freeze

  # Routes with a path parameter, matched in declaration order after the
  # exact-match ROUTES table misses. Each entry pairs an HTTP method, a
  # regex whose single capture group is the path parameter, and a handler
  # called as handler.(param, body).
  PARAMETERIZED_ROUTES = [
    ['POST', %r{\A/v1/combat/sessions/([^/]+)/conditions\z}, Handlers::Combat.method(:add_condition)],
    ['POST', %r{\A/v1/combat/sessions/([^/]+)/advance\z}, Handlers::Combat.method(:advance)],
    ['GET', %r{\A/v1/compendium/monsters/([^/]+)\z}, Handlers::Compendium.method(:get_monster)],
    ['GET', %r{\A/v1/compendium/items/([^/]+)\z}, Handlers::Compendium.method(:get_item)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/characters\z}, Handlers::Campaigns.method(:add_character)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/events\z}, Handlers::Campaigns.method(:add_event)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/state\z}, Handlers::Campaigns.method(:state)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/quests/summary\z}, Handlers::Quests.method(:summary)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/quests\z}, Handlers::Quests.method(:create_quest)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/quests/([^/]+)/progress\z}, Handlers::Quests.method(:update_progress)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/factions\z}, Handlers::Npcs.method(:create_faction)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/npcs\z}, Handlers::Npcs.method(:create_npc)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/relationships\z}, Handlers::Npcs.method(:relationships)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/inventory\z}, Handlers::Inventory.method(:add_inventory_item)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/inventory/summary\z}, Handlers::Inventory.method(:summary)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/characters/([^/]+)/equipment\z}, Handlers::Inventory.method(:assign_equipment)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/downtime/crafting\z}, Handlers::Downtime.method(:create_crafting_project)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance\z}, Handlers::Downtime.method(:advance)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/sessions/next\z}, Handlers::Sessions.method(:next_session)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/sessions\z}, Handlers::Sessions.method(:create_session)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance\z}, Handlers::Sessions.method(:record_attendance)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/audit\z}, Handlers::Audit.method(:audit)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/export\z}, Handlers::Audit.method(:export)],
    ['GET', %r{\A/v1/campaigns/([^/]+)/analytics/summary\z}, Handlers::Analytics.method(:summary)],
    ['POST', %r{\A/v1/campaigns/([^/]+)/analytics/risk-report\z}, Handlers::Analytics.method(:risk_report)]
  ].freeze

  # Routes requiring "Authorization: Bearer session-<username>". Resolved
  # separately from ROUTES/PARAMETERIZED_ROUTES so unauthenticated requests
  # never reach these handlers; each is called as handler.(actor, *args, body).
  PROTECTED_ROUTES = {
    ['POST', '/v1/play/campaigns'] => Handlers::Play.method(:create_campaign)
  }.freeze

  # Protected routes with a path parameter, matched the same way as
  # PARAMETERIZED_ROUTES but resolved only after authentication.
  PROTECTED_PARAMETERIZED_ROUTES = [
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/onboarding\z}, Handlers::Play.method(:onboarding)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/members\z}, Handlers::Play.method(:join_campaign)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/start\z}, Handlers::Play.method(:start_campaign)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/narrations\z}, Handlers::Play.method(:add_narration)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/actions\z}, Handlers::Play.method(:submit_action)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/resolutions\z}, Handlers::Play.method(:add_resolution)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/turn\z}, Handlers::Play.method(:get_turn)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/turn/nudge\z}, Handlers::Play.method(:nudge_turn)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/my-turn\z}, Handlers::Play.method(:my_turn)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/gm/status\z}, Handlers::Play.method(:gm_status)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/document\z}, Handlers::Play.method(:update_document)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/document\z}, Handlers::Play.method(:get_document)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/session-zero\z}, Handlers::Play.method(:update_session_zero)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/session-zero\z}, Handlers::Play.method(:get_session_zero)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/scenes/current\z}, Handlers::Play.method(:current_scene)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/scenes\z}, Handlers::Play.method(:create_scene)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/scenes/([^/]+)/enter\z}, Handlers::Play.method(:enter_scene)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/scenes/([^/]+)/close\z}, Handlers::Play.method(:close_scene)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/locations\z}, Handlers::Play.method(:create_location)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/locations/([^/]+)/connections\z}, Handlers::Play.method(:create_connection)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/locations/([^/]+)/travel\z}, Handlers::Play.method(:travel)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/turn/travel\z}, Handlers::Play.method(:travel_turn)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/turn/rest\z}, Handlers::Play.method(:rest_turn)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters\z}, Handlers::Play.method(:create_encounter)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters\z}, Handlers::Play.method(:add_monster)],
    ['DELETE', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters/([^/]+)\z}, Handlers::Play.method(:remove_monster)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants\z}, Handlers::Play.method(:bind_combatant)],
    ['DELETE', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants/([^/]+)\z}, Handlers::Play.method(:unbind_combatant)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn\z}, Handlers::Play.method(:get_encounter_turn)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/advance\z}, Handlers::Play.method(:advance_encounter_turn)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/delay\z}, Handlers::Play.method(:delay_turn)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/ready\z}, Handlers::Play.method(:ready_turn)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/actions\z}, Handlers::Play.method(:record_combat_action)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/damage\z}, Handlers::Play.method(:damage_target)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/heal\z}, Handlers::Play.method(:heal_target)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/conditions\z}, Handlers::Play.method(:add_condition)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/status\z}, Handlers::Play.method(:encounter_status)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/rewards\z}, Handlers::Play.method(:award_rewards)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/close\z}, Handlers::Play.method(:close_encounter)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/encounters/([^/]+)/end\z}, Handlers::Play.method(:end_encounter)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/damage\z}, Handlers::Play.method(:damage_character)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/status\z}, Handlers::Play.method(:character_status)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/death-saves\z}, Handlers::Play.method(:death_save)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/owner\z}, Handlers::Play.method(:character_owner)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/claim\z}, Handlers::Play.method(:claim_character)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/transfer\z}, Handlers::Play.method(:transfer_character)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/build\z}, Handlers::Play.method(:build_character)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/skill-check\z}, Handlers::Play.method(:skill_check)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/level-up\z}, Handlers::Play.method(:level_up_character)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells\z}, Handlers::Play.method(:add_spell)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells\z}, Handlers::Play.method(:list_spells)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells\z}, Handlers::Play.method(:set_prepared_spells)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells\z}, Handlers::Play.method(:get_prepared_spells)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts\z}, Handlers::Play.method(:cast_spell)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts\z}, Handlers::Play.method(:list_casts)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration\z}, Handlers::Play.method(:set_concentration)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration\z}, Handlers::Play.method(:get_concentration)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration/advance-turn\z}, Handlers::Play.method(:advance_concentration_turn)],
    ['DELETE', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration\z}, Handlers::Play.method(:clear_concentration)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items\z}, Handlers::Play.method(:add_inventory_item)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items\z}, Handlers::Play.method(:list_inventory_items)],
    ['DELETE', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)\z}, Handlers::Play.method(:remove_inventory_item)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)/consume\z}, Handlers::Play.method(:consume_inventory_item)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)\z}, Handlers::Play.method(:equip_item)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)\z}, Handlers::Play.method(:get_equipment)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune\z}, Handlers::Play.method(:attune_equipment)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency\z}, Handlers::Play.method(:currency)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency/transfers\z}, Handlers::Play.method(:create_currency_transfer)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/loot\z}, Handlers::Play.method(:create_loot)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/loot/([^/]+)/votes\z}, Handlers::Play.method(:vote_loot)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/loot/([^/]+)/assign\z}, Handlers::Play.method(:assign_loot)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/loot/([^/]+)\z}, Handlers::Play.method(:get_loot)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/npcs\z}, Handlers::Play.method(:create_npc)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)/agenda\z}, Handlers::Play.method(:update_npc_agenda)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)\z}, Handlers::Play.method(:get_npc)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue\z}, Handlers::Play.method(:create_npc_dialogue)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue\z}, Handlers::Play.method(:npc_dialogue_history)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/factions\z}, Handlers::Play.method(:create_faction)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation\z}, Handlers::Play.method(:update_faction_reputation)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation\z}, Handlers::Play.method(:faction_reputation_history)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/relationships\z}, Handlers::Play.method(:create_relationship)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/relationships/([^/]+)/([^/]+)/([^/]+)\z}, Handlers::Play.method(:update_relationship)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/relationships\z}, Handlers::Play.method(:list_relationships)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/clues\z}, Handlers::Play.method(:create_clue)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/clues\z}, Handlers::Play.method(:list_clues)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/quests\z}, Handlers::Play.method(:create_quest)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/quests/([^/]+)/state\z}, Handlers::Play.method(:update_quest_state)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/quests\z}, Handlers::Play.method(:list_quests)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards\z}, Handlers::Play.method(:configure_quest_rewards)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards/award\z}, Handlers::Play.method(:award_quest_rewards)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/rewards\z}, Handlers::Play.method(:character_rewards)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/world-events\z}, Handlers::Play.method(:create_world_event)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/world-events/([^/]+)/resolve\z}, Handlers::Play.method(:resolve_world_event)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/world-events\z}, Handlers::Play.method(:list_world_events)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/calendar\z}, Handlers::Play.method(:create_calendar)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/calendar\z}, Handlers::Play.method(:get_calendar)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/calendar/advance\z}, Handlers::Play.method(:advance_calendar)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/settlements\z}, Handlers::Play.method(:create_settlement)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)\z}, Handlers::Play.method(:update_settlement)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/discover\z}, Handlers::Play.method(:discover_settlement)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/settlements\z}, Handlers::Play.method(:list_settlements)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops\z}, Handlers::Play.method(:create_shop)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)\z}, Handlers::Play.method(:get_shop)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/buy\z}, Handlers::Play.method(:buy_from_shop)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/sell\z}, Handlers::Play.method(:sell_to_shop)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/recipes\z}, Handlers::Play.method(:create_recipe)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/recipes\z}, Handlers::Play.method(:list_recipes)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/recipes/([^/]+)/craft\z}, Handlers::Play.method(:craft_recipe)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/downtime/activities\z}, Handlers::Play.method(:create_downtime_activity)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations\z}, Handlers::Play.method(:create_downtime_allocation)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)/progress\z}, Handlers::Play.method(:progress_downtime_allocation)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)\z}, Handlers::Play.method(:get_downtime_allocation)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/content\z}, Handlers::Play.method(:create_content)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/content/([^/]+)/tags\z}, Handlers::Play.method(:replace_content_tags)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/content\z}, Handlers::Play.method(:list_content)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/notes\z}, Handlers::Play.method(:create_note)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/notes\z}, Handlers::Play.method(:list_notes)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/notes/([^/]+)\z}, Handlers::Play.method(:get_note)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/notes/([^/]+)\z}, Handlers::Play.method(:update_note)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/messages\z}, Handlers::Play.method(:create_message)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/whispers\z}, Handlers::Play.method(:create_whisper)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/whispers\z}, Handlers::Play.method(:list_whispers)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/characters/([^/]+)/sheet\z}, Handlers::Play.method(:character_sheet)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/invitations\z}, Handlers::Play.method(:create_invitation)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/invitations/([^/]+)/accept\z}, Handlers::Play.method(:accept_invitation)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/invitations\z}, Handlers::Play.method(:list_invitations)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/delegations/audit\z}, Handlers::Play.method(:delegation_audit)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/delegations\z}, Handlers::Play.method(:grant_delegation)],
    ['DELETE', %r{\A/v1/play/campaigns/([^/]+)/delegations/([^/]+)\z}, Handlers::Play.method(:revoke_delegation)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/audit-events\z}, Handlers::Play.method(:create_audit_event)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/audit-events\z}, Handlers::Play.method(:list_audit_events)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/projection-events\z}, Handlers::Play.method(:append_projection_event)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/projection/rebuild\z}, Handlers::Play.method(:rebuild_projection)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/projection\z}, Handlers::Play.method(:get_projection)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/idempotent-events\z}, Handlers::Play.method(:create_idempotent_event)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/idempotent-events\z}, Handlers::Play.method(:list_idempotent_events)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/safe-turns\z}, Handlers::Play.method(:submit_safe_turn)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/safe-turns\z}, Handlers::Play.method(:list_safe_turns)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/transactional-transfers\z}, Handlers::Play.method(:create_transactional_transfer)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/transactional-transfers\z}, Handlers::Play.method(:list_transactional_transfers)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/exports\z}, Handlers::Play.method(:create_export)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/exports\z}, Handlers::Play.method(:list_exports)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/exports/([^/]+)\z}, Handlers::Play.method(:get_export)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/imports\z}, Handlers::Play.method(:create_import)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/import-state\z}, Handlers::Play.method(:get_import_state)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/migrations\z}, Handlers::Play.method(:create_migration)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/migration-state\z}, Handlers::Play.method(:get_migration_state)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/search-records\z}, Handlers::Play.method(:create_search_record)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/search-records\z}, Handlers::Play.method(:list_search_records)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/rate-events\z}, Handlers::Play.method(:create_rate_event)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/rate-events\z}, Handlers::Play.method(:list_rate_events)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/metrics\z}, Handlers::Play.method(:get_metrics)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/service-mode\z}, Handlers::Play.method(:service_mode)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/backups\z}, Handlers::Play.method(:create_backup)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/backups\z}, Handlers::Play.method(:list_backups)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/backups/([^/]+)/restore\z}, Handlers::Play.method(:restore_backup)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/replay-events\z}, Handlers::Play.method(:create_replay_event)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/replay\z}, Handlers::Play.method(:get_replay)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/replay/check\z}, Handlers::Play.method(:check_replay)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/rng-seed\z}, Handlers::Play.method(:set_rng_seed)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/rng-rolls\z}, Handlers::Play.method(:create_rng_roll)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/rng-ledger\z}, Handlers::Play.method(:get_rng_ledger)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/moderation/reports\z}, Handlers::Play.method(:create_moderation_report)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/moderation/reports\z}, Handlers::Play.method(:list_moderation_reports)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/moderation/reports/([^/]+)/resolution\z}, Handlers::Play.method(:resolve_moderation_report)],
    ['PUT', %r{\A/v1/play/campaigns/([^/]+)/safety-boundaries\z}, Handlers::Play.method(:replace_safety_boundaries)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/safety-boundaries\z}, Handlers::Play.method(:get_safety_boundaries)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/safety-checks\z}, Handlers::Play.method(:submit_safety_check)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/safety-events\z}, Handlers::Play.method(:list_safety_events)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/fixture-seeds\z}, Handlers::Play.method(:create_fixture_seed)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/fixture-state\z}, Handlers::Play.method(:get_fixture_state)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/spectators\z}, Handlers::Play.method(:create_spectator)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/spectator-view\z}, Handlers::Play.method(:spectator_view)],
    ['POST', %r{\A/v1/play/campaigns/([^/]+)/feed-events\z}, Handlers::Play.method(:append_feed_event)],
    ['GET', %r{\A/v1/play/campaigns/([^/]+)/event-feed\z}, Handlers::Play.method(:get_event_feed)]
  ].freeze

  STATUS_REASONS = {
    200 => 'OK',
    201 => 'Created',
    400 => 'Bad Request',
    401 => 'Unauthorized',
    403 => 'Forbidden',
    404 => 'Not Found',
    409 => 'Conflict',
    429 => 'Too Many Requests',
    503 => 'Service Unavailable'
  }.freeze

  module_function

  # Reads a single HTTP request off the socket: request line, headers, and
  # a Content-Length-delimited body. Returns nil if the client closed the
  # connection before sending a request line.
  def read_request(socket)
    request_line = socket.gets
    return nil if request_line.nil?

    method_name, path, = request_line.split(' ')
    headers = {}
    loop do
      line = socket.gets
      break if line.nil? || line == "\r\n" || line == "\n"

      key, value = line.split(':', 2)
      headers[key.strip.downcase] = value.strip if key && value
    end

    content_length = headers['content-length'].to_i
    raw_body = content_length.positive? ? socket.read(content_length) : ''

    [method_name, path, headers, raw_body]
  end

  def write_response(socket, status, payload)
    body = JSON.generate(payload)
    reason = STATUS_REASONS.fetch(status, 'Internal Server Error')
    socket.write("HTTP/1.1 #{status} #{reason}\r\n")
    socket.write("Content-Type: application/json\r\n")
    socket.write("Content-Length: #{body.bytesize}\r\n")
    socket.write("Connection: close\r\n")
    socket.write("\r\n")
    socket.write(body)
  end

  # Parses a request's query string (the part of the path after '?', if
  # any) into a plain string-keyed hash, matching the key type JSON.parse
  # uses for request bodies so handlers can treat both uniformly.
  def parse_query(query_string)
    return {} if query_string.nil? || query_string.empty?

    URI.decode_www_form(query_string).each_with_object({}) { |(key, value), memo| memo[key] = value }
  end

  def parse_body(raw_body)
    return {} if raw_body.nil? || raw_body.empty?

    parsed = JSON.parse(raw_body)
    raise HttpError.new(400, 'body must be a JSON object') unless parsed.is_a?(Hash)

    parsed
  rescue JSON::ParserError
    raise HttpError.new(400, 'invalid JSON body')
  end

  # Finds a handler for (method, path) within one exact/parameterized route
  # table pair: first an exact match, then a regex match. Returns
  # [handler_proc, args] where args is either [] (exact match) or the
  # regex's captures, in order (parameterized match), or nil if nothing
  # matches. Shared by resolve/resolve_protected, which just pick the table
  # pair (unauthenticated vs. protected).
  def resolve_in(exact_table, parameterized_table, method_name, path)
    handler = exact_table[[method_name, path]]
    return [handler, []] if handler

    parameterized_table.each do |route_method, pattern, route_handler|
      next unless route_method == method_name

      match = pattern.match(path)
      return [route_handler, match.captures] if match
    end

    nil
  end

  def resolve(method_name, path)
    resolve_in(ROUTES, PARAMETERIZED_ROUTES, method_name, path)
  end

  def resolve_protected(method_name, path)
    resolve_in(PROTECTED_ROUTES, PROTECTED_PARAMETERIZED_ROUTES, method_name, path)
  end

  def handle_connection(socket)
    method_name, full_path, headers, raw_body = read_request(socket)
    return if method_name.nil?

    path, _sep, query_string = full_path.partition('?')
    body = parse_body(raw_body).merge(parse_query(query_string))

    handler, args = resolve(method_name, path) || [nil, nil]
    if handler
      status, payload = handler.call(*args, body)
      write_response(socket, status, payload)
      return
    end

    protected_handler, protected_args = resolve_protected(method_name, path) || [nil, nil]
    if protected_handler
      actor = Handlers::Auth.authenticate(headers)
      body = body.merge('idempotency_key_header' => headers['idempotency-key'])
      status, payload = protected_handler.call(actor, *protected_args, body)
      write_response(socket, status, payload)
      return
    end

    write_response(socket, 404, { error: 'not found' })
  rescue HttpError => e
    write_response(socket, e.status, { error: e.message })
  rescue StandardError => e
    write_response(socket, 400, { error: e.message })
  ensure
    socket.close
  end
end

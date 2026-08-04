"""URL routing table. View logic lives in dndsite/views/, grouped by domain."""

from django.urls import path

from dndsite import db
from dndsite.views import analytics, audit, auth, campaigns, characters, combat, compendium, core, dice, dm_tools, downtime, encounters, npcs, phb, play, sessions, storage

db.init_schema()

urlpatterns = [
    path("health", core.health),
    path("v1/storage/status", storage.storage_status),
    path("v1/storage/reset", storage.storage_reset),
    path("v1/auth/register", auth.auth_register),
    path("v1/auth/login", auth.auth_login),
    path("v1/dice/stats", dice.dice_stats),
    path("v1/checks/ability", dice.ability_check),
    path("v1/encounters/adjusted-xp", encounters.adjusted_xp),
    path("v1/initiative/order", encounters.initiative_order),
    path("v1/characters/ability-modifier", characters.ability_modifier_view),
    path("v1/characters/proficiency", characters.proficiency_view),
    path("v1/characters/derived-stats", characters.derived_stats),
    path("v1/combat/sessions", combat.combat_sessions),
    path("v1/combat/sessions/<str:session_id>/conditions", combat.combat_conditions),
    path("v1/combat/sessions/<str:session_id>/advance", combat.combat_advance),
    path("v1/compendium/monsters", compendium.monsters_collection),
    path("v1/compendium/monsters/<str:slug>", compendium.monster_detail),
    path("v1/compendium/items", compendium.items_collection),
    path("v1/compendium/items/<str:slug>", compendium.item_detail),
    path("v1/campaigns", campaigns.campaigns_collection),
    path("v1/campaigns/<str:campaign_id>/characters", campaigns.campaign_characters_collection),
    path("v1/campaigns/<str:campaign_id>/events", campaigns.campaign_events_collection),
    path("v1/campaigns/<str:campaign_id>/state", campaigns.campaign_state),
    path("v1/campaigns/<str:campaign_id>/quests", campaigns.campaign_quests_collection),
    path("v1/campaigns/<str:campaign_id>/quests/summary", campaigns.campaign_quests_summary),
    path(
        "v1/campaigns/<str:campaign_id>/quests/<str:quest_id>/progress",
        campaigns.campaign_quest_progress,
    ),
    path("v1/phb/spell-slots", phb.phb_spell_slots),
    path("v1/phb/rests/long", phb.phb_long_rest),
    path("v1/phb/equipment-load", phb.phb_equipment_load),
    path("v1/dm/encounter-builder", dm_tools.dm_encounter_builder),
    path("v1/dm/loot-parcel", dm_tools.dm_loot_parcel),
    path("v1/dm/session-recap", dm_tools.dm_session_recap),
    path("v1/campaigns/<str:campaign_id>/factions", npcs.campaign_factions_collection),
    path("v1/campaigns/<str:campaign_id>/npcs", npcs.campaign_npcs_collection),
    path("v1/campaigns/<str:campaign_id>/relationships", npcs.campaign_relationships),
    path("v1/campaigns/<str:campaign_id>/inventory", campaigns.campaign_inventory_collection),
    path("v1/campaigns/<str:campaign_id>/inventory/summary", campaigns.campaign_inventory_summary),
    path(
        "v1/campaigns/<str:campaign_id>/characters/<str:character_id>/equipment",
        campaigns.campaign_character_equipment_collection,
    ),
    path("v1/campaigns/<str:campaign_id>/downtime/crafting", downtime.campaign_crafting_collection),
    path(
        "v1/campaigns/<str:campaign_id>/downtime/crafting/<str:project_id>/advance",
        downtime.campaign_crafting_advance,
    ),
    path("v1/campaigns/<str:campaign_id>/sessions", sessions.campaign_sessions_collection),
    path("v1/campaigns/<str:campaign_id>/sessions/next", sessions.campaign_next_session),
    path(
        "v1/campaigns/<str:campaign_id>/sessions/<str:session_id>/attendance",
        sessions.campaign_session_attendance,
    ),
    path("v1/campaigns/<str:campaign_id>/audit", audit.campaign_audit),
    path("v1/campaigns/<str:campaign_id>/export", audit.campaign_export),
    path("v1/campaigns/<str:campaign_id>/analytics/summary", analytics.campaign_analytics_summary),
    path("v1/campaigns/<str:campaign_id>/analytics/risk-report", analytics.campaign_risk_report),
    path("v1/play/campaigns", play.play_campaigns_collection),
    path(
        "v1/play/campaigns/<str:campaign_id>/members",
        play.play_campaign_members_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/start",
        play.play_campaign_start,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/session-zero",
        play.play_campaign_session_zero,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/content",
        play.play_campaign_content_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/content/<str:content_id>/tags",
        play.play_campaign_content_tags,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/narrations",
        play.play_campaign_narrations_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/actions",
        play.play_campaign_actions_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/resolutions",
        play.play_campaign_resolutions_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/turn",
        play.play_campaign_turn,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/turn/nudge",
        play.play_campaign_turn_nudge,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/turn/travel",
        play.play_campaign_turn_travel,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/turn/rest",
        play.play_campaign_turn_rest,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/my-turn",
        play.play_campaign_my_turn,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/gm/status",
        play.play_campaign_gm_status,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/document",
        play.play_campaign_document,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/scenes/current",
        play.play_campaign_scene_current,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/scenes",
        play.play_campaign_scenes_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/scenes/<str:scene_id>/enter",
        play.play_campaign_scene_enter,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/scenes/<str:scene_id>/close",
        play.play_campaign_scene_close,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/locations",
        play.play_campaign_locations_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/locations/<str:from_id>/connections",
        play.play_campaign_location_connections_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/locations/<str:loc_id>/travel",
        play.play_campaign_location_travel,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters",
        play.play_campaign_encounters_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/monsters",
        play.play_campaign_encounter_monsters_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/monsters/<str:monster_id>",
        play.play_campaign_encounter_monster_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/combatants",
        play.play_campaign_encounter_combatants_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/turn",
        play.play_campaign_encounter_turn,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/turn/advance",
        play.play_campaign_encounter_turn_advance,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/turn/delay",
        play.play_campaign_encounter_turn_delay,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/turn/ready",
        play.play_campaign_encounter_turn_ready,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/combatants/<str:member>",
        play.play_campaign_encounter_combatant_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/actions",
        play.play_campaign_encounter_actions_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/damage",
        play.play_campaign_encounter_damage,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/heal",
        play.play_campaign_encounter_heal,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/conditions",
        play.play_campaign_encounter_conditions_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/status",
        play.play_campaign_encounter_status,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/rewards",
        play.play_campaign_encounter_rewards,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/close",
        play.play_campaign_encounter_close,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/encounters/<str:enc_id>/end",
        play.play_campaign_encounter_end,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/damage",
        play.play_campaign_character_damage,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/death-saves",
        play.play_campaign_character_death_saves,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/status",
        play.play_campaign_character_status,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/owner",
        play.play_campaign_character_owner,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/claim",
        play.play_campaign_character_claim,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/transfer",
        play.play_campaign_character_transfer,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/build",
        play.play_campaign_character_build,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/level-up",
        play.play_campaign_character_level_up,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/skill-check",
        play.play_campaign_character_skill_check,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/spells",
        play.play_campaign_character_spells,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/prepared-spells",
        play.play_campaign_character_prepared_spells,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/casts",
        play.play_campaign_character_casts,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/concentration",
        play.play_campaign_character_concentration,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:char_id>/concentration/advance-turn",
        play.play_campaign_character_concentration_advance_turn,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/inventory/items",
        play.play_campaign_character_inventory_items_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/inventory/items/<str:item_id>",
        play.play_campaign_character_inventory_item_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/inventory/items/<str:item_id>/consume",
        play.play_campaign_character_inventory_item_consume,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/equipment/<str:slot>",
        play.play_campaign_character_equipment_slot,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/equipment/<str:slot>/attune",
        play.play_campaign_character_equipment_slot_attune,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/currency",
        play.play_campaign_character_currency,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/currency/transfers",
        play.play_campaign_character_currency_transfers,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/loot",
        play.play_campaign_loot_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/loot/<str:loot_id>",
        play.play_campaign_loot_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/loot/<str:loot_id>/votes",
        play.play_campaign_loot_votes_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/loot/<str:loot_id>/assign",
        play.play_campaign_loot_assign,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/npcs",
        play.play_campaign_npcs_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/npcs/<str:npc_id>/agenda",
        play.play_campaign_npc_agenda,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/npcs/<str:npc_id>",
        play.play_campaign_npc_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/npcs/<str:npc_id>/dialogue",
        play.play_campaign_npc_dialogue_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/factions",
        play.play_campaign_factions_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/factions/<str:faction_id>/reputation",
        play.play_campaign_faction_reputation_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/relationships",
        play.play_campaign_relationships_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/relationships/<str:source_id>/<str:target_id>/<str:kind>",
        play.play_campaign_relationship_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/clues",
        play.play_campaign_clues_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/quests",
        play.play_campaign_quests_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/quests/<str:quest_id>/state",
        play.play_campaign_quest_state,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/quests/<str:quest_id>/rewards",
        play.play_campaign_quest_rewards,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/quests/<str:quest_id>/rewards/award",
        play.play_campaign_quest_rewards_award,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/rewards",
        play.play_campaign_character_rewards,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/world-events",
        play.play_campaign_world_events_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/world-events/<str:event_id>/resolve",
        play.play_campaign_world_event_resolve,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/calendar",
        play.play_campaign_calendar,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/calendar/advance",
        play.play_campaign_calendar_advance,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements",
        play.play_campaign_settlements_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>",
        play.play_campaign_settlement_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/discover",
        play.play_campaign_settlement_discover,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops",
        play.play_campaign_settlement_shops_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops/<str:shop_id>",
        play.play_campaign_settlement_shop_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops/<str:shop_id>/buy",
        play.play_campaign_settlement_shop_buy,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/settlements/<str:settlement_id>/shops/<str:shop_id>/sell",
        play.play_campaign_settlement_shop_sell,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/recipes",
        play.play_campaign_recipes_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/recipes/<str:recipe_id>/craft",
        play.play_campaign_recipe_craft,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/downtime/activities",
        play.play_campaign_downtime_activities_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/downtime/allocations",
        play.play_campaign_downtime_allocations_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/downtime/allocations/<str:activity_id>/progress",
        play.play_campaign_downtime_allocation_progress,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/downtime/allocations/<str:activity_id>",
        play.play_campaign_downtime_allocation_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/notes",
        play.play_campaign_notes_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/notes/<str:note_id>",
        play.play_campaign_note_detail,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/whispers",
        play.play_campaign_whispers_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/characters/<str:character_id>/sheet",
        play.play_campaign_character_sheet,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/invitations",
        play.play_campaign_invitations_collection,
    ),
    path(
        "v1/play/campaigns/<str:campaign_id>/invitations/<str:invitation_id>/accept",
        play.play_campaign_invitation_accept,
    ),
]

"""Literal constants and compiled route patterns used by the service."""

import re

# XP awarded per defeated monster by challenge rating.
XP = {
    "0": 10,
    "1/8": 25,
    "1/4": 50,
    "1/2": 100,
    "1": 200,
    "2": 450,
    "3": 700,
    "4": 1100,
    "5": 1800,
}

# Per-character daily XP thresholds for encounter difficulty by level.
THRESHOLDS = {
    1: {"easy": 25, "medium": 50, "hard": 75, "deadly": 100},
    2: {"easy": 50, "medium": 100, "hard": 150, "deadly": 200},
    3: {"easy": 75, "medium": 150, "hard": 225, "deadly": 400},
    4: {"easy": 125, "medium": 250, "hard": 375, "deadly": 500},
    5: {"easy": 250, "medium": 500, "hard": 750, "deadly": 1100},
    6: {"easy": 300, "medium": 600, "hard": 900, "deadly": 1400},
    7: {"easy": 350, "medium": 750, "hard": 1100, "deadly": 1700},
    8: {"easy": 450, "medium": 900, "hard": 1400, "deadly": 2100},
    9: {"easy": 550, "medium": 1100, "hard": 1600, "deadly": 2400},
    10: {"easy": 600, "medium": 1200, "hard": 1900, "deadly": 2800},
    11: {"easy": 800, "medium": 1600, "hard": 2400, "deadly": 3600},
    12: {"easy": 1000, "medium": 2000, "hard": 3000, "deadly": 4500},
    13: {"easy": 1100, "medium": 2200, "hard": 3400, "deadly": 5100},
    14: {"easy": 1250, "medium": 2500, "hard": 3800, "deadly": 5700},
    15: {"easy": 1400, "medium": 2800, "hard": 4300, "deadly": 6400},
    16: {"easy": 1600, "medium": 3200, "hard": 4800, "deadly": 7200},
    17: {"easy": 2000, "medium": 3900, "hard": 5900, "deadly": 8800},
    18: {"easy": 2100, "medium": 4200, "hard": 6300, "deadly": 9500},
    19: {"easy": 2400, "medium": 4900, "hard": 7300, "deadly": 10900},
    20: {"easy": 2800, "medium": 5700, "hard": 8500, "deadly": 12700},
}

# Matches a dice expression such as "2d6+3" or "1d20-1".
DICE_RE = re.compile(r"^(\d+)d(\d+)(?:([+-])(\d+))?$")

# Dynamic route patterns. The capture group is the identifier used for lookups.
COMBAT_SESSION_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_SESSION_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")
MONSTER_RE = re.compile(r"^/v1/compendium/monsters/([^/]+)$")
ITEM_RE = re.compile(r"^/v1/compendium/items/([^/]+)$")
CAMPAIGN_CHARACTERS_RE = re.compile(r"^/v1/campaigns/([^/]+)/characters$")
CAMPAIGN_EVENTS_RE = re.compile(r"^/v1/campaigns/([^/]+)/events$")
CAMPAIGN_STATE_RE = re.compile(r"^/v1/campaigns/([^/]+)/state$")
CAMPAIGN_FACTIONS_RE = re.compile(r"^/v1/campaigns/([^/]+)/factions$")
CAMPAIGN_NPCS_RE = re.compile(r"^/v1/campaigns/([^/]+)/npcs$")
CAMPAIGN_RELATIONSHIPS_RE = re.compile(r"^/v1/campaigns/([^/]+)/relationships$")
CAMPAIGN_QUESTS_RE = re.compile(r"^/v1/campaigns/([^/]+)/quests$")
CAMPAIGN_QUESTS_SUMMARY_RE = re.compile(r"^/v1/campaigns/([^/]+)/quests/summary$")
CAMPAIGN_QUEST_PROGRESS_RE = re.compile(r"^/v1/campaigns/([^/]+)/quests/([^/]+)/progress$")
CAMPAIGN_INVENTORY_RE = re.compile(r"^/v1/campaigns/([^/]+)/inventory$")
CAMPAIGN_INVENTORY_SUMMARY_RE = re.compile(r"^/v1/campaigns/([^/]+)/inventory/summary$")
CAMPAIGN_CHARACTER_EQUIPMENT_RE = re.compile(r"^/v1/campaigns/([^/]+)/characters/([^/]+)/equipment$")
CAMPAIGN_CRAFTING_RE = re.compile(r"^/v1/campaigns/([^/]+)/downtime/crafting$")
CAMPAIGN_CRAFTING_ADVANCE_RE = re.compile(r"^/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance$")
CAMPAIGN_SESSIONS_RE = re.compile(r"^/v1/campaigns/([^/]+)/sessions$")
CAMPAIGN_SESSION_ATTENDANCE_RE = re.compile(r"^/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance$")
CAMPAIGN_SESSIONS_NEXT_RE = re.compile(r"^/v1/campaigns/([^/]+)/sessions/next$")
CAMPAIGN_AUDIT_RE = re.compile(r"^/v1/campaigns/([^/]+)/audit$")
CAMPAIGN_EXPORT_RE = re.compile(r"^/v1/campaigns/([^/]+)/export$")
CAMPAIGN_ANALYTICS_SUMMARY_RE = re.compile(r"^/v1/campaigns/([^/]+)/analytics/summary$")
CAMPAIGN_ANALYTICS_RISK_REPORT_RE = re.compile(r"^/v1/campaigns/([^/]+)/analytics/risk-report$")
PLAY_CAMPAIGNS_RE = re.compile(r"^/v1/play/campaigns$")
PLAY_CAMPAIGN_MEMBERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/members$")
PLAY_CAMPAIGN_START_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/start$")
PLAY_CAMPAIGN_NARRATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/narrations$")
PLAY_CAMPAIGN_ACTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/actions$")
PLAY_CAMPAIGN_TURN_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn$")
PLAY_CAMPAIGN_TURN_NUDGE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn/nudge$")
PLAY_CAMPAIGN_TURN_TRAVEL_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn/travel$")
PLAY_CAMPAIGN_TURN_REST_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn/rest$")
PLAY_CAMPAIGN_MY_TURN_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/my-turn$")
PLAY_CAMPAIGN_GM_STATUS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/gm/status$")
PLAY_CAMPAIGN_RESOLUTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/resolutions$")
PLAY_CAMPAIGN_DOCUMENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/document$")
PLAY_CAMPAIGN_EXPORTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/exports$")
PLAY_CAMPAIGN_EXPORT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/exports/([^/]+)$")
PLAY_CAMPAIGN_IMPORTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/imports$")
PLAY_CAMPAIGN_IMPORT_STATE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/import-state$")
PLAY_CAMPAIGN_MIGRATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/migrations$")
PLAY_CAMPAIGN_MIGRATION_STATE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/migration-state$")
PLAY_CAMPAIGN_SEARCH_RECORDS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/search-records(?:\?.*)?$")
PLAY_CAMPAIGN_SESSION_ZERO_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/session-zero$")
PLAY_CAMPAIGN_CONTENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/content(?:\?.*)?$")
PLAY_CAMPAIGN_CONTENT_TAGS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/content/([^/]+)/tags$")
PLAY_CAMPAIGN_SCENES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes$")
PLAY_CAMPAIGN_SCENE_ENTER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/enter$")
PLAY_CAMPAIGN_SCENE_CLOSE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/close$")
PLAY_CAMPAIGN_SCENE_CURRENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes/current$")
PLAY_CAMPAIGN_LOCATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/locations$")
PLAY_CAMPAIGN_CONNECTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/locations/([^/]+)/connections$")
PLAY_CAMPAIGN_TRAVEL_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/locations/([^/]+)/travel$")
PLAY_CAMPAIGN_ENCOUNTERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters$")
PLAY_CAMPAIGN_ENCOUNTER_MONSTERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters$")
PLAY_CAMPAIGN_ENCOUNTER_MONSTER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters/([^/]+)$")
PLAY_CAMPAIGN_ENCOUNTER_COMBATANTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants$")
PLAY_CAMPAIGN_ENCOUNTER_COMBATANT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants/([^/]+)$")
PLAY_CAMPAIGN_ENCOUNTER_TURN_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn$")
PLAY_CAMPAIGN_ENCOUNTER_TURN_ADVANCE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/advance$")
PLAY_CAMPAIGN_ENCOUNTER_TURN_DELAY_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/delay$")
PLAY_CAMPAIGN_ENCOUNTER_TURN_READY_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/ready$")
PLAY_CAMPAIGN_ENCOUNTER_ACTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/actions$")
PLAY_CAMPAIGN_ENCOUNTER_DAMAGE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/damage$")
PLAY_CAMPAIGN_ENCOUNTER_HEAL_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/heal$")
PLAY_CAMPAIGN_CHARACTER_DAMAGE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/damage$")
PLAY_CAMPAIGN_CHARACTER_DEATH_SAVES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/death-saves$")
PLAY_CAMPAIGN_CHARACTER_STATUS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/status$")
PLAY_CAMPAIGN_CHARACTER_OWNER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/owner$")
PLAY_CAMPAIGN_CHARACTER_CLAIM_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/claim$")
PLAY_CAMPAIGN_CHARACTER_TRANSFER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/transfer$")
PLAY_CAMPAIGN_CHARACTER_BUILD_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/build$")
PLAY_CAMPAIGN_CHARACTER_LEVEL_UP_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/level-up$")
PLAY_CAMPAIGN_CHARACTER_SKILL_CHECK_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/skill-check$")
PLAY_CAMPAIGN_CHARACTER_SPELLS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells$")
PLAY_CAMPAIGN_CHARACTER_PREPARED_SPELLS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells$")
PLAY_CAMPAIGN_CHARACTER_CASTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts$")
PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$")
PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_ADVANCE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration/advance-turn$")
PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items$")
PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)$")
PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_CONSUME_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)/consume$")
PLAY_CAMPAIGN_CHARACTER_CURRENCY_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency$")
PLAY_CAMPAIGN_CHARACTER_CURRENCY_TRANSFERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency/transfers$")
PLAY_CAMPAIGN_LOOT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/loot$")
PLAY_CAMPAIGN_LOOT_ID_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/loot/([^/]+)$")
PLAY_CAMPAIGN_LOOT_VOTES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/loot/([^/]+)/votes$")
PLAY_CAMPAIGN_LOOT_ASSIGN_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/loot/([^/]+)/assign$")
PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)$")
PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_ATTUNE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune$")
PLAY_CAMPAIGN_ENCOUNTER_CONDITIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/conditions$")
PLAY_CAMPAIGN_ENCOUNTER_STATUS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/status$")
PLAY_CAMPAIGN_ENCOUNTER_REWARDS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/rewards$")
PLAY_CAMPAIGN_ENCOUNTER_CLOSE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/close$")
PLAY_CAMPAIGN_ENCOUNTER_END_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/end$")
PLAY_CAMPAIGN_NPCS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/npcs$")
PLAY_CAMPAIGN_NPC_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/npcs/([^/]+)$")
PLAY_CAMPAIGN_NPC_AGENDA_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/agenda$")
PLAY_CAMPAIGN_NPC_DIALOGUE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue$")
PLAY_CAMPAIGN_FACTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/factions$")
PLAY_CAMPAIGN_FACTION_REPUTATION_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation$")
PLAY_CAMPAIGN_RELATIONSHIPS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/relationships$")
PLAY_CAMPAIGN_RELATIONSHIP_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/relationships/([^/]+)/([^/]+)/([^/]+)$")
PLAY_CAMPAIGN_CLUES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/clues$")
PLAY_CAMPAIGN_QUESTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/quests$")
PLAY_CAMPAIGN_QUEST_STATE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/quests/([^/]+)/state$")
PLAY_CAMPAIGN_QUEST_REWARDS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards$")
PLAY_CAMPAIGN_QUEST_REWARDS_AWARD_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards/award$")
PLAY_CAMPAIGN_CHARACTER_REWARDS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/rewards$")
PLAY_CAMPAIGN_WORLD_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/world-events$")
PLAY_CAMPAIGN_WORLD_EVENT_RESOLVE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/world-events/([^/]+)/resolve$")
PLAY_CAMPAIGN_CALENDAR_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/calendar$")
PLAY_CAMPAIGN_CALENDAR_ADVANCE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/calendar/advance$")
PLAY_CAMPAIGN_SETTLEMENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/settlements$")
PLAY_CAMPAIGN_SETTLEMENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)$")
PLAY_CAMPAIGN_SETTLEMENT_DISCOVER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/discover$")
PLAY_CAMPAIGN_SETTLEMENT_SHOPS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops$")
PLAY_CAMPAIGN_SETTLEMENT_SHOP_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)$")
PLAY_CAMPAIGN_SETTLEMENT_SHOP_BUY_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/buy$")
PLAY_CAMPAIGN_SETTLEMENT_SHOP_SELL_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/sell$")
PLAY_CAMPAIGN_RECIPES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/recipes$")
PLAY_CAMPAIGN_RECIPE_CRAFT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/recipes/([^/]+)/craft$")
PLAY_CAMPAIGN_DOWNTIME_ACTIVITIES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/downtime/activities$")
PLAY_CAMPAIGN_DOWNTIME_ALLOCATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations$")
PLAY_CAMPAIGN_DOWNTIME_ALLOCATION_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)$")
PLAY_CAMPAIGN_DOWNTIME_ALLOCATION_PROGRESS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)/progress$")
PLAY_CAMPAIGN_NOTES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/notes$")
PLAY_CAMPAIGN_NOTE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/notes/([^/]+)$")
PLAY_CAMPAIGN_WHISPERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/whispers$")
PLAY_CAMPAIGN_MESSAGES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/messages$")
PLAY_CAMPAIGN_INVITATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/invitations$")
PLAY_CAMPAIGN_INVITATION_ACCEPT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/invitations/([^/]+)/accept$")
PLAY_CAMPAIGN_CHARACTER_SHEET_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/sheet$")
PLAY_CAMPAIGN_DELEGATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/delegations$")
PLAY_CAMPAIGN_DELEGATION_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/delegations/([^/]+)$")
PLAY_CAMPAIGN_DELEGATIONS_AUDIT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/delegations/audit$")
PLAY_CAMPAIGN_AUDIT_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/audit-events$")
PLAY_CAMPAIGN_PROJECTION_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/projection-events$")
PLAY_CAMPAIGN_PROJECTION_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/projection$")
PLAY_CAMPAIGN_PROJECTION_REBUILD_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/projection/rebuild$")
PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/idempotent-events$")
PLAY_CAMPAIGN_SAFE_TURNS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/safe-turns$")
PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/transactional-transfers$")
PLAY_CAMPAIGN_RATE_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rate-events$")
PLAY_CAMPAIGN_METRICS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/metrics$")
PLAY_CAMPAIGN_SERVICE_MODE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/service-mode$")
PLAY_CAMPAIGN_BACKUPS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/backups$")
PLAY_CAMPAIGN_BACKUP_RESTORE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/backups/([^/]+)/restore$")
PLAY_CAMPAIGN_REPLAY_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/replay-events$")
PLAY_CAMPAIGN_REPLAY_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/replay$")
PLAY_CAMPAIGN_REPLAY_CHECK_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/replay/check$")
PLAY_CAMPAIGN_RNG_SEED_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rng-seed$")
PLAY_CAMPAIGN_RNG_ROLLS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rng-rolls$")
PLAY_CAMPAIGN_RNG_LEDGER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rng-ledger$")
PLAY_CAMPAIGN_MODERATION_REPORTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/moderation/reports$")
PLAY_CAMPAIGN_MODERATION_REPORT_RESOLUTION_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/moderation/reports/([^/]+)/resolution$")
PLAY_CAMPAIGN_SAFETY_BOUNDARIES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/safety-boundaries$")
PLAY_CAMPAIGN_SAFETY_CHECKS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/safety-checks$")
PLAY_CAMPAIGN_SAFETY_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/safety-events$")
PLAY_CAMPAIGN_FIXTURE_SEEDS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/fixture-seeds$")
PLAY_CAMPAIGN_FIXTURE_STATE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/fixture-state$")
PLAY_CAMPAIGN_ONBOARDING_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/onboarding$")
PLAY_CAMPAIGN_SPECTATORS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/spectators$")
PLAY_CAMPAIGN_SPECTATOR_VIEW_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/spectator-view$")
PLAY_CAMPAIGN_FEED_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/feed-events$")
PLAY_CAMPAIGN_EVENT_FEED_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/event-feed(?:\?.*)?$")

# Username validation: lowercase alphanumeric plus underscore/hyphen, 2-32 chars.
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")

# Valid character creation choices.
VALID_RACES = {
    "dragonborn",
    "dwarf",
    "elf",
    "gnome",
    "half-elf",
    "half-orc",
    "halfling",
    "human",
    "tiefling",
}
VALID_CLASSES = {
    "barbarian",
    "bard",
    "cleric",
    "druid",
    "fighter",
    "monk",
    "paladin",
    "ranger",
    "rogue",
    "sorcerer",
    "warlock",
    "wizard",
}
VALID_BACKGROUNDS = {
    "acolyte",
    "charlatan",
    "criminal",
    "entertainer",
    "folk-hero",
    "guild-artisan",
    "hermit",
    "noble",
    "outlander",
    "sage",
    "sailor",
    "soldier",
    "urchin",
}

VALID_ABILITIES = {"str", "dex", "con", "int", "wis", "cha"}

# Wizard spell list for spellbook validation. Rogues may not learn spells.
WIZARD_SPELLS = {
    "acid-splash",
    "arcane-lock",
    "blur",
    "burning-hands",
    "charm-person",
    "chill-touch",
    "color-spray",
    "comprehend-languages",
    "cone-of-cold",
    "counterspell",
    "dancing-lights",
    "darkness",
    "darkvision",
    "detect-magic",
    "dimension-door",
    "dispel-magic",
    "feather-fall",
    "find-familiar",
    "fire-bolt",
    "fireball",
    "flaming-sphere",
    "fly",
    "fog-cloud",
    "grease",
    "greater-invisibility",
    "haste",
    "hold-person",
    "ice-storm",
    "identify",
    "invisibility",
    "knock",
    "light",
    "lightning-bolt",
    "mage-hand",
    "magic-missile",
    "minor-illusion",
    "mirror-image",
    "misty-step",
    "polymorph",
    "prestidigitation",
    "ray-of-frost",
    "scorching-ray",
    "shield",
    "shocking-grasp",
    "sleep",
    "slow",
    "teleportation-circle",
    "thunderwave",
    "wall-of-force",
    "web",
}

VALID_SKILLS = {
    "acrobatics",
    "animal-handling",
    "arcana",
    "athletics",
    "deception",
    "history",
    "insight",
    "intimidation",
    "investigation",
    "medicine",
    "nature",
    "perception",
    "performance",
    "persuasion",
    "religion",
    "sleight-of-hand",
    "stealth",
    "survival",
}

# First-level hit points by class (PHB hit dice + con modifier).
CLASS_HP_BASE = {
    "barbarian": 12,
    "bard": 8,
    "cleric": 8,
    "druid": 8,
    "fighter": 10,
    "monk": 8,
    "paladin": 10,
    "ranger": 10,
    "rogue": 8,
    "sorcerer": 6,
    "warlock": 8,
    "wizard": 6,
}

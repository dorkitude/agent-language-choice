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
PLAY_CAMPAIGN_TURN_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn$")

# Username validation: lowercase alphanumeric plus underscore/hyphen, 2-32 chars.
USERNAME_RE = re.compile(r"^[a-z0-9_-]{2,32}$")

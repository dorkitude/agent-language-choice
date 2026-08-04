#!/usr/bin/env python3
"""HTTP entry point: routing and request/response handling only.

Domain rules and calculations live in rules.py; all persistence lives in
db.py. Handlers here are responsible for parsing/validating request bodies,
calling into those two modules, and shaping JSON responses — see CODEBASE.md
for the full module map and conventions for adding new endpoints.
"""
import json
import os
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

import db
import rules

# Process-global service mode. Set by any DM through any campaign's
# service-mode endpoint; read by the public /readyz endpoint.
_MAINTENANCE_MODE = False

# Path-parameter routes (path segments can't be matched with plain equality).
COMBAT_CONDITIONS_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/conditions$")
COMBAT_ADVANCE_RE = re.compile(r"^/v1/combat/sessions/([^/]+)/advance$")
MONSTER_GET_RE = re.compile(r"^/v1/compendium/monsters/([^/]+)$")
ITEM_GET_RE = re.compile(r"^/v1/compendium/items/([^/]+)$")
CAMPAIGN_CHARACTERS_RE = re.compile(r"^/v1/campaigns/([^/]+)/characters$")
CAMPAIGN_EVENTS_RE = re.compile(r"^/v1/campaigns/([^/]+)/events$")
CAMPAIGN_STATE_RE = re.compile(r"^/v1/campaigns/([^/]+)/state$")
CAMPAIGN_QUESTS_RE = re.compile(r"^/v1/campaigns/([^/]+)/quests$")
QUEST_SUMMARY_RE = re.compile(r"^/v1/campaigns/([^/]+)/quests/summary$")
QUEST_PROGRESS_RE = re.compile(r"^/v1/campaigns/([^/]+)/quests/([^/]+)/progress$")
CAMPAIGN_FACTIONS_RE = re.compile(r"^/v1/campaigns/([^/]+)/factions$")
CAMPAIGN_NPCS_RE = re.compile(r"^/v1/campaigns/([^/]+)/npcs$")
CAMPAIGN_RELATIONSHIPS_RE = re.compile(r"^/v1/campaigns/([^/]+)/relationships$")
CAMPAIGN_INVENTORY_RE = re.compile(r"^/v1/campaigns/([^/]+)/inventory$")
CAMPAIGN_INVENTORY_SUMMARY_RE = re.compile(r"^/v1/campaigns/([^/]+)/inventory/summary$")
CAMPAIGN_CHARACTER_EQUIPMENT_RE = re.compile(r"^/v1/campaigns/([^/]+)/characters/([^/]+)/equipment$")
CAMPAIGN_CRAFTING_RE = re.compile(r"^/v1/campaigns/([^/]+)/downtime/crafting$")
CAMPAIGN_CRAFTING_ADVANCE_RE = re.compile(r"^/v1/campaigns/([^/]+)/downtime/crafting/([^/]+)/advance$")
CAMPAIGN_SESSIONS_RE = re.compile(r"^/v1/campaigns/([^/]+)/sessions$")
CAMPAIGN_SESSIONS_NEXT_RE = re.compile(r"^/v1/campaigns/([^/]+)/sessions/next$")
SESSION_ATTENDANCE_RE = re.compile(r"^/v1/campaigns/([^/]+)/sessions/([^/]+)/attendance$")
CAMPAIGN_AUDIT_RE = re.compile(r"^/v1/campaigns/([^/]+)/audit$")
CAMPAIGN_EXPORT_RE = re.compile(r"^/v1/campaigns/([^/]+)/export$")
CAMPAIGN_ANALYTICS_SUMMARY_RE = re.compile(r"^/v1/campaigns/([^/]+)/analytics/summary$")
CAMPAIGN_ANALYTICS_RISK_RE = re.compile(r"^/v1/campaigns/([^/]+)/analytics/risk-report$")
ISO_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
PLAY_CAMPAIGN_MEMBERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/members$")
PLAY_CAMPAIGN_START_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/start$")
PLAY_CAMPAIGN_NARRATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/narrations$")
PLAY_CAMPAIGN_ACTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/actions$")
PLAY_CAMPAIGN_RESOLUTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/resolutions$")
PLAY_CAMPAIGN_TURN_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn$")
PLAY_CAMPAIGN_TURN_NUDGE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn/nudge$")
PLAY_CAMPAIGN_TURN_TRAVEL_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn/travel$")
PLAY_CAMPAIGN_TURN_REST_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/turn/rest$")
PLAY_CAMPAIGN_MY_TURN_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/my-turn$")
PLAY_CAMPAIGN_GM_STATUS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/gm/status$")
PLAY_CAMPAIGN_ONBOARDING_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/onboarding$")
PLAY_CAMPAIGN_DOCUMENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/document$")
PLAY_CAMPAIGN_BACKUPS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/backups$")
PLAY_CAMPAIGN_BACKUP_RESTORE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/backups/([^/]+)/restore$"
)
PLAY_CAMPAIGN_REPLAY_EVENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/replay-events$"
)
PLAY_CAMPAIGN_REPLAY_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/replay$")
PLAY_CAMPAIGN_REPLAY_CHECK_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/replay/check$"
)
PLAY_CAMPAIGN_SESSION_ZERO_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/session-zero$"
)
PLAY_CAMPAIGN_CONTENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/content$")
PLAY_CAMPAIGN_CONTENT_TAGS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/content/([^/]+)/tags$"
)
PLAY_CAMPAIGN_SCENES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes$")
PLAY_CAMPAIGN_SCENE_CURRENT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes/current$")
PLAY_CAMPAIGN_SCENE_ENTER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/enter$")
PLAY_CAMPAIGN_SCENE_CLOSE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/scenes/([^/]+)/close$")
PLAY_CAMPAIGN_LOCATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/locations$")
PLAY_CAMPAIGN_LOCATION_CONNECTIONS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/locations/([^/]+)/connections$"
)
PLAY_CAMPAIGN_LOCATION_TRAVEL_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/locations/([^/]+)/travel$"
)
PLAY_CAMPAIGN_ENCOUNTERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/encounters$")
PLAY_CAMPAIGN_ENCOUNTER_MONSTERS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters$"
)
PLAY_CAMPAIGN_ENCOUNTER_MONSTER_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/monsters/([^/]+)$"
)
PLAY_CAMPAIGN_ENCOUNTER_COMBATANTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants$"
)
PLAY_CAMPAIGN_ENCOUNTER_TURN_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn$"
)
PLAY_CAMPAIGN_ENCOUNTER_TURN_ADVANCE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/advance$"
)
PLAY_CAMPAIGN_ENCOUNTER_TURN_DELAY_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/delay$"
)
PLAY_CAMPAIGN_ENCOUNTER_TURN_READY_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/turn/ready$"
)
PLAY_CAMPAIGN_ENCOUNTER_COMBATANT_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/combatants/([^/]+)$"
)
PLAY_CAMPAIGN_ENCOUNTER_ACTIONS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/actions$"
)
PLAY_CAMPAIGN_ENCOUNTER_DAMAGE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/damage$"
)
PLAY_CAMPAIGN_ENCOUNTER_HEAL_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/heal$"
)
PLAY_CAMPAIGN_ENCOUNTER_CONDITIONS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/conditions$"
)
PLAY_CAMPAIGN_ENCOUNTER_STATUS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/status$"
)
PLAY_CAMPAIGN_ENCOUNTER_REWARDS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/rewards$"
)
PLAY_CAMPAIGN_ENCOUNTER_CLOSE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/close$"
)
PLAY_CAMPAIGN_ENCOUNTER_END_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/encounters/([^/]+)/end$"
)
PLAY_CAMPAIGN_CHARACTER_DAMAGE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/damage$"
)
PLAY_CAMPAIGN_CHARACTER_DEATH_SAVES_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/death-saves$"
)
PLAY_CAMPAIGN_CHARACTER_STATUS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/status$"
)
PLAY_CAMPAIGN_CHARACTER_OWNER_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/owner$"
)
PLAY_CAMPAIGN_CHARACTER_CLAIM_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/claim$"
)
PLAY_CAMPAIGN_CHARACTER_TRANSFER_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/transfer$"
)
PLAY_CAMPAIGN_CHARACTER_BUILD_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/build$"
)
PLAY_CAMPAIGN_CHARACTER_LEVEL_UP_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/level-up$"
)
PLAY_CAMPAIGN_CHARACTER_SKILL_CHECK_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/skill-check$"
)
PLAY_CAMPAIGN_CHARACTER_SPELLS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/spells$"
)
PLAY_CAMPAIGN_CHARACTER_PREPARED_SPELLS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/prepared-spells$"
)
PLAY_CAMPAIGN_CHARACTER_CASTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/casts$"
)
PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration$"
)
PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_ADVANCE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/concentration/advance-turn$"
)
PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items$"
)
PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)$"
)
PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_CONSUME_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/inventory/items/([^/]+)/consume$"
)
PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_SLOT_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)$"
)
PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_ATTUNE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/equipment/([^/]+)/attune$"
)
PLAY_CAMPAIGN_CHARACTER_CURRENCY_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency$"
)
PLAY_CAMPAIGN_LOOT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/loot$")
PLAY_CAMPAIGN_LOOT_ITEM_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/loot/([^/]+)$")
PLAY_CAMPAIGN_LOOT_VOTES_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/loot/([^/]+)/votes$"
)
PLAY_CAMPAIGN_LOOT_ASSIGN_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/loot/([^/]+)/assign$"
)
PLAY_CAMPAIGN_NPCS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/npcs$")
PLAY_CAMPAIGN_NPC_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/npcs/([^/]+)$")
PLAY_CAMPAIGN_NPC_AGENDA_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/agenda$"
)
PLAY_CAMPAIGN_NPC_DIALOGUE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/npcs/([^/]+)/dialogue$"
)
PLAY_CAMPAIGN_CHARACTER_CURRENCY_TRANSFERS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/currency/transfers$"
)
PLAY_CAMPAIGN_FACTIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/factions$")
PLAY_CAMPAIGN_FACTION_REPUTATION_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/factions/([^/]+)/reputation$"
)
PLAY_CAMPAIGN_RELATIONSHIPS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/relationships$"
)
PLAY_CAMPAIGN_RELATIONSHIP_EDGE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/relationships/([^/]+)/([^/]+)/([^/]+)$"
)
PLAY_CAMPAIGN_CLUES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/clues$")
PLAY_CAMPAIGN_QUESTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/quests$")
PLAY_CAMPAIGN_QUEST_STATE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/quests/([^/]+)/state$"
)
PLAY_CAMPAIGN_QUEST_REWARDS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards$"
)
PLAY_CAMPAIGN_QUEST_REWARDS_AWARD_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/quests/([^/]+)/rewards/award$"
)
PLAY_CAMPAIGN_CHARACTER_QUEST_REWARDS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/rewards$"
)
PLAY_CAMPAIGN_WORLD_EVENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/world-events$"
)
PLAY_CAMPAIGN_WORLD_EVENT_RESOLVE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/world-events/([^/]+)/resolve$"
)
PLAY_CAMPAIGN_CALENDAR_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/calendar$"
)
PLAY_CAMPAIGN_CALENDAR_ADVANCE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/calendar/advance$"
)
PLAY_CAMPAIGN_SETTLEMENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/settlements$"
)
PLAY_CAMPAIGN_SETTLEMENT_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)$"
)
PLAY_CAMPAIGN_SETTLEMENT_DISCOVER_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/discover$"
)
PLAY_CAMPAIGN_SETTLEMENT_SHOPS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops$"
)
PLAY_CAMPAIGN_SETTLEMENT_SHOP_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)$"
)
PLAY_CAMPAIGN_SETTLEMENT_SHOP_BUY_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/buy$"
)
PLAY_CAMPAIGN_SETTLEMENT_SHOP_SELL_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/settlements/([^/]+)/shops/([^/]+)/sell$"
)
PLAY_CAMPAIGN_RECIPES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/recipes$")
PLAY_CAMPAIGN_RECIPE_CRAFT_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/recipes/([^/]+)/craft$"
)
PLAY_CAMPAIGN_DOWNTIME_ACTIVITIES_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/downtime/activities$"
)
PLAY_CAMPAIGN_CHARACTER_DOWNTIME_ALLOCATIONS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations$"
)
PLAY_CAMPAIGN_CHARACTER_DOWNTIME_ALLOCATION_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)$"
)
PLAY_CAMPAIGN_CHARACTER_DOWNTIME_PROGRESS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/downtime/allocations/([^/]+)/progress$"
)
PLAY_CAMPAIGN_NOTES_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/notes$")
PLAY_CAMPAIGN_NOTE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/notes/([^/]+)$")
PLAY_CAMPAIGN_SEARCH_RECORDS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/search-records$"
)
PLAY_CAMPAIGN_WHISPERS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/whispers$")
PLAY_CAMPAIGN_CHARACTER_SHEET_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/characters/([^/]+)/sheet$"
)
PLAY_CAMPAIGN_INVITATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/invitations$")
PLAY_CAMPAIGN_INVITATION_ACCEPT_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/invitations/([^/]+)/accept$"
)
PLAY_CAMPAIGN_DELEGATIONS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/delegations$"
)
PLAY_CAMPAIGN_DELEGATION_AUDIT_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/delegations/audit$"
)
PLAY_CAMPAIGN_DELEGATION_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/delegations/([^/]+)$"
)
PLAY_CAMPAIGN_AUDIT_EVENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/audit-events$"
)
PLAY_CAMPAIGN_PROJECTION_EVENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/projection-events$"
)
PLAY_CAMPAIGN_PROJECTION_REBUILD_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/projection/rebuild$"
)
PLAY_CAMPAIGN_PROJECTION_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/projection$"
)
PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/idempotent-events$"
)
PLAY_CAMPAIGN_SAFE_TURNS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/safe-turns$"
)
PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/transactional-transfers$"
)
PLAY_CAMPAIGN_EXPORTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/exports$")
PLAY_CAMPAIGN_EXPORT_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/exports/([^/]+)$")
PLAY_CAMPAIGN_IMPORTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/imports$")
PLAY_CAMPAIGN_IMPORT_STATE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/import-state$")
PLAY_CAMPAIGN_MIGRATIONS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/migrations$")
PLAY_CAMPAIGN_MIGRATION_STATE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/migration-state$")
PLAY_CAMPAIGN_RATE_EVENTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rate-events$")
PLAY_CAMPAIGN_METRICS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/metrics$")
PLAY_CAMPAIGN_SERVICE_MODE_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/service-mode$")
PLAY_CAMPAIGN_RNG_SEED_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rng-seed$")
PLAY_CAMPAIGN_RNG_ROLLS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rng-rolls$")
PLAY_CAMPAIGN_RNG_LEDGER_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/rng-ledger$")
PLAY_CAMPAIGN_MODERATION_REPORTS_RE = re.compile(r"^/v1/play/campaigns/([^/]+)/moderation/reports$")
PLAY_CAMPAIGN_MODERATION_RESOLUTION_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/moderation/reports/([^/]+)/resolution$"
)
PLAY_CAMPAIGN_SAFETY_BOUNDARIES_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/safety-boundaries$"
)
PLAY_CAMPAIGN_SAFETY_CHECKS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/safety-checks$"
)
PLAY_CAMPAIGN_SAFETY_EVENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/safety-events$"
)
PLAY_CAMPAIGN_FIXTURE_SEEDS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/fixture-seeds$"
)
PLAY_CAMPAIGN_FIXTURE_STATE_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/fixture-state$"
)
PLAY_CAMPAIGN_SPECTATORS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/spectators$"
)
PLAY_CAMPAIGN_SPECTATOR_VIEW_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/spectator-view$"
)
PLAY_CAMPAIGN_MESSAGES_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/messages$"
)
PLAY_CAMPAIGN_FEED_EVENTS_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/feed-events$"
)
PLAY_CAMPAIGN_EVENT_FEED_RE = re.compile(
    r"^/v1/play/campaigns/([^/]+)/event-feed$"
)

RATE_EVENT_LIMIT = 2

API_SCHEMA = {
    "version": "2026-07-29",
    "endpoints": [
        {"method": "GET", "path": "/v1/play/campaigns/{id}/rng-ledger", "auth": "member"},
        {"method": "GET", "path": "/v1/schema", "auth": "public"},
        {"method": "POST", "path": "/v1/play/campaigns", "auth": "dm"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/fixture-seeds", "auth": "dm"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/members", "auth": "member"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/moderation/reports", "auth": "member"},
        {"method": "POST", "path": "/v1/play/campaigns/{id}/rng-rolls", "auth": "member"},
        {
            "method": "PUT",
            "path": "/v1/play/campaigns/{id}/moderation/reports/{report_id}/resolution",
            "auth": "dm",
        },
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/rng-seed", "auth": "dm"},
        {"method": "PUT", "path": "/v1/play/campaigns/{id}/safety-boundaries", "auth": "dm"},
    ],
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        return json.loads(raw)

    def do_GET(self):
        if self.path == "/v1/schema":
            self._send_json(200, API_SCHEMA)
            return
        if self.path == "/health":
            self._send_json(200, {"ok": True})
            return
        if self.path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/readyz":
            if _MAINTENANCE_MODE:
                self._send_json(503, {"status": "maintenance", "schema_version": 2})
            else:
                self._send_json(200, {"status": "ready", "schema_version": 2})
            return
        if self.path == "/v1/storage/status":
            self._handle_storage_status()
            return
        monster_match = MONSTER_GET_RE.match(self.path)
        if monster_match:
            self._handle_get_monster(monster_match.group(1))
            return
        item_match = ITEM_GET_RE.match(self.path)
        if item_match:
            self._handle_get_item(item_match.group(1))
            return
        state_match = CAMPAIGN_STATE_RE.match(self.path)
        if state_match:
            self._handle_campaign_state(state_match.group(1))
            return
        quest_summary_match = QUEST_SUMMARY_RE.match(self.path)
        if quest_summary_match:
            self._handle_quest_summary(quest_summary_match.group(1))
            return
        relationships_match = CAMPAIGN_RELATIONSHIPS_RE.match(self.path)
        if relationships_match:
            self._handle_relationships(relationships_match.group(1))
            return
        inventory_summary_match = CAMPAIGN_INVENTORY_SUMMARY_RE.match(self.path)
        if inventory_summary_match:
            self._handle_inventory_summary(inventory_summary_match.group(1))
            return
        session_next_match = CAMPAIGN_SESSIONS_NEXT_RE.match(self.path)
        if session_next_match:
            self._handle_next_session(session_next_match.group(1))
            return
        audit_match = CAMPAIGN_AUDIT_RE.match(self.path)
        if audit_match:
            self._handle_campaign_audit(audit_match.group(1))
            return
        export_match = CAMPAIGN_EXPORT_RE.match(self.path)
        if export_match:
            self._handle_campaign_export(export_match.group(1))
            return
        analytics_summary_match = CAMPAIGN_ANALYTICS_SUMMARY_RE.match(self.path)
        if analytics_summary_match:
            self._handle_analytics_summary(analytics_summary_match.group(1))
            return
        play_turn_match = PLAY_CAMPAIGN_TURN_RE.match(self.path)
        if play_turn_match:
            self._handle_play_campaign_turn(play_turn_match.group(1))
            return
        my_turn_match = PLAY_CAMPAIGN_MY_TURN_RE.match(self.path)
        if my_turn_match:
            self._handle_play_campaign_my_turn(my_turn_match.group(1))
            return
        gm_status_match = PLAY_CAMPAIGN_GM_STATUS_RE.match(self.path)
        if gm_status_match:
            self._handle_play_campaign_gm_status(gm_status_match.group(1))
            return
        document_match = PLAY_CAMPAIGN_DOCUMENT_RE.match(self.path)
        if document_match:
            self._handle_get_play_campaign_document(document_match.group(1))
            return
        backups_match = PLAY_CAMPAIGN_BACKUPS_RE.match(self.path)
        if backups_match:
            self._handle_list_play_campaign_backups(backups_match.group(1))
            return
        replay_check_match = PLAY_CAMPAIGN_REPLAY_CHECK_RE.match(self.path)
        if replay_check_match:
            self._handle_get_play_campaign_replay(replay_check_match.group(1))
            return
        replay_match = PLAY_CAMPAIGN_REPLAY_RE.match(self.path)
        if replay_match:
            self._handle_get_play_campaign_replay(replay_match.group(1))
            return
        session_zero_match = PLAY_CAMPAIGN_SESSION_ZERO_RE.match(self.path)
        if session_zero_match:
            self._handle_get_play_campaign_session_zero(session_zero_match.group(1))
            return
        request_path, _, query_string = self.path.partition("?")
        content_match = PLAY_CAMPAIGN_CONTENT_RE.match(request_path)
        if content_match:
            self._handle_get_play_campaign_content(
                content_match.group(1), parse_qs(query_string, keep_blank_values=True)
            )
            return
        scene_current_match = PLAY_CAMPAIGN_SCENE_CURRENT_RE.match(self.path)
        if scene_current_match:
            self._handle_get_play_campaign_current_scene(scene_current_match.group(1))
            return
        location_travel_match = PLAY_CAMPAIGN_LOCATION_TRAVEL_RE.match(self.path)
        if location_travel_match:
            self._handle_get_play_campaign_location_travel(
                location_travel_match.group(1), location_travel_match.group(2)
            )
            return
        encounter_turn_match = PLAY_CAMPAIGN_ENCOUNTER_TURN_RE.match(self.path)
        if encounter_turn_match:
            self._handle_get_play_campaign_encounter_turn(
                encounter_turn_match.group(1), encounter_turn_match.group(2)
            )
            return
        character_status_match = PLAY_CAMPAIGN_CHARACTER_STATUS_RE.match(self.path)
        if character_status_match:
            self._handle_get_play_campaign_character_status(
                character_status_match.group(1), character_status_match.group(2)
            )
            return
        character_owner_match = PLAY_CAMPAIGN_CHARACTER_OWNER_RE.match(self.path)
        if character_owner_match:
            self._handle_get_play_campaign_character_owner(
                character_owner_match.group(1), character_owner_match.group(2)
            )
            return
        character_spells_match = PLAY_CAMPAIGN_CHARACTER_SPELLS_RE.match(self.path)
        if character_spells_match:
            self._handle_get_play_campaign_character_spells(
                character_spells_match.group(1), character_spells_match.group(2)
            )
            return
        encounter_status_match = PLAY_CAMPAIGN_ENCOUNTER_STATUS_RE.match(self.path)
        if encounter_status_match:
            self._handle_get_play_campaign_encounter_status(
                encounter_status_match.group(1), encounter_status_match.group(2)
            )
            return
        prepared_spells_match = PLAY_CAMPAIGN_CHARACTER_PREPARED_SPELLS_RE.match(self.path)
        if prepared_spells_match:
            self._handle_get_play_campaign_character_prepared_spells(
                prepared_spells_match.group(1), prepared_spells_match.group(2)
            )
            return
        casts_match = PLAY_CAMPAIGN_CHARACTER_CASTS_RE.match(self.path)
        if casts_match:
            self._handle_get_play_campaign_character_casts(
                casts_match.group(1), casts_match.group(2)
            )
            return
        concentration_match = PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE.match(self.path)
        if concentration_match:
            self._handle_get_play_campaign_character_concentration(
                concentration_match.group(1), concentration_match.group(2)
            )
            return
        inventory_items_match = PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE.match(self.path)
        if inventory_items_match:
            self._handle_get_play_campaign_character_inventory_items(
                inventory_items_match.group(1), inventory_items_match.group(2)
            )
            return
        equipment_slot_match = PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_SLOT_RE.match(self.path)
        if equipment_slot_match:
            self._handle_get_play_campaign_character_equipment(
                equipment_slot_match.group(1), equipment_slot_match.group(2),
                equipment_slot_match.group(3)
            )
            return
        currency_match = PLAY_CAMPAIGN_CHARACTER_CURRENCY_RE.match(self.path)
        if currency_match:
            self._handle_get_play_campaign_character_currency(
                currency_match.group(1), currency_match.group(2)
            )
            return
        loot_match = PLAY_CAMPAIGN_LOOT_ITEM_RE.match(self.path)
        if loot_match:
            self._handle_get_play_campaign_loot(loot_match.group(1), loot_match.group(2))
            return
        npc_match = PLAY_CAMPAIGN_NPC_RE.match(self.path)
        if npc_match:
            self._handle_get_play_campaign_npc(npc_match.group(1), npc_match.group(2))
            return
        reputation_match = PLAY_CAMPAIGN_FACTION_REPUTATION_RE.match(self.path)
        if reputation_match:
            self._handle_get_play_campaign_faction_reputation(
                reputation_match.group(1), reputation_match.group(2)
            )
            return
        npc_dialogue_match = PLAY_CAMPAIGN_NPC_DIALOGUE_RE.match(self.path)
        if npc_dialogue_match:
            self._handle_get_play_campaign_npc_dialogue(
                npc_dialogue_match.group(1), npc_dialogue_match.group(2)
            )
            return
        play_relationships_match = PLAY_CAMPAIGN_RELATIONSHIPS_RE.match(self.path)
        if play_relationships_match:
            self._handle_get_play_campaign_relationships(play_relationships_match.group(1))
            return
        clues_match = PLAY_CAMPAIGN_CLUES_RE.match(self.path)
        if clues_match:
            self._handle_get_play_campaign_clues(clues_match.group(1))
            return
        quests_match = PLAY_CAMPAIGN_QUESTS_RE.match(self.path)
        if quests_match:
            self._handle_get_play_campaign_quests(quests_match.group(1))
            return
        character_quest_rewards_match = PLAY_CAMPAIGN_CHARACTER_QUEST_REWARDS_RE.match(self.path)
        if character_quest_rewards_match:
            self._handle_get_play_campaign_character_quest_rewards(
                character_quest_rewards_match.group(1), character_quest_rewards_match.group(2)
            )
            return
        world_events_match = PLAY_CAMPAIGN_WORLD_EVENTS_RE.match(self.path)
        if world_events_match:
            self._handle_get_play_campaign_world_events(world_events_match.group(1))
            return
        calendar_match = PLAY_CAMPAIGN_CALENDAR_RE.match(self.path)
        if calendar_match:
            self._handle_get_play_campaign_calendar(calendar_match.group(1))
            return
        settlements_match = PLAY_CAMPAIGN_SETTLEMENTS_RE.match(self.path)
        if settlements_match:
            self._handle_get_play_campaign_settlements(settlements_match.group(1))
            return
        shop_match = PLAY_CAMPAIGN_SETTLEMENT_SHOP_RE.match(self.path)
        if shop_match:
            self._handle_get_play_campaign_shop(
                shop_match.group(1), shop_match.group(2), shop_match.group(3)
            )
            return
        recipes_match = PLAY_CAMPAIGN_RECIPES_RE.match(self.path)
        if recipes_match:
            self._handle_get_play_campaign_recipes(recipes_match.group(1))
            return
        downtime_allocation_match = PLAY_CAMPAIGN_CHARACTER_DOWNTIME_ALLOCATION_RE.match(
            self.path
        )
        if downtime_allocation_match:
            self._handle_get_play_campaign_downtime_allocation(
                downtime_allocation_match.group(1),
                downtime_allocation_match.group(2),
                downtime_allocation_match.group(3),
            )
            return
        note_match = PLAY_CAMPAIGN_NOTE_RE.match(self.path)
        if note_match:
            self._handle_get_play_campaign_note(note_match.group(1), note_match.group(2))
            return
        notes_match = PLAY_CAMPAIGN_NOTES_RE.match(self.path)
        if notes_match:
            self._handle_get_play_campaign_notes(notes_match.group(1))
            return
        search_records_path, _, search_records_query = self.path.partition("?")
        search_records_match = PLAY_CAMPAIGN_SEARCH_RECORDS_RE.match(search_records_path)
        if search_records_match:
            self._handle_get_play_campaign_search_records(
                search_records_match.group(1),
                parse_qs(search_records_query, keep_blank_values=True),
            )
            return
        whispers_match = PLAY_CAMPAIGN_WHISPERS_RE.match(self.path)
        if whispers_match:
            self._handle_get_play_campaign_whispers(whispers_match.group(1))
            return
        sheet_match = PLAY_CAMPAIGN_CHARACTER_SHEET_RE.match(self.path)
        if sheet_match:
            self._handle_get_play_campaign_character_sheet(
                sheet_match.group(1), sheet_match.group(2)
            )
            return
        delegation_audit_match = PLAY_CAMPAIGN_DELEGATION_AUDIT_RE.match(self.path)
        if delegation_audit_match:
            self._handle_get_play_campaign_delegation_audit(delegation_audit_match.group(1))
            return
        audit_events_match = PLAY_CAMPAIGN_AUDIT_EVENTS_RE.match(self.path)
        if audit_events_match:
            self._handle_get_play_campaign_audit_events(audit_events_match.group(1))
            return
        projection_rebuild_match = PLAY_CAMPAIGN_PROJECTION_REBUILD_RE.match(self.path)
        if projection_rebuild_match:
            self._handle_get_play_campaign_projection(projection_rebuild_match.group(1))
            return
        projection_match = PLAY_CAMPAIGN_PROJECTION_RE.match(self.path)
        if projection_match:
            self._handle_get_play_campaign_projection(projection_match.group(1))
            return
        invitations_match = PLAY_CAMPAIGN_INVITATIONS_RE.match(self.path)
        if invitations_match:
            self._handle_get_play_campaign_invitations(invitations_match.group(1))
            return
        idempotent_events_match = PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE.match(self.path)
        if idempotent_events_match:
            self._handle_get_play_campaign_idempotent_events(idempotent_events_match.group(1))
            return
        safe_turns_match = PLAY_CAMPAIGN_SAFE_TURNS_RE.match(self.path)
        if safe_turns_match:
            self._handle_get_play_campaign_safe_turns(safe_turns_match.group(1))
            return
        transactional_transfers_match = PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE.match(self.path)
        if transactional_transfers_match:
            self._handle_get_play_campaign_transactional_transfers(
                transactional_transfers_match.group(1)
            )
            return
        export_item_match = PLAY_CAMPAIGN_EXPORT_RE.match(self.path)
        if export_item_match:
            self._handle_get_play_campaign_export(
                export_item_match.group(1), export_item_match.group(2)
            )
            return
        exports_match = PLAY_CAMPAIGN_EXPORTS_RE.match(self.path)
        if exports_match:
            self._handle_get_play_campaign_exports(exports_match.group(1))
            return
        import_state_match = PLAY_CAMPAIGN_IMPORT_STATE_RE.match(self.path)
        if import_state_match:
            self._handle_get_play_campaign_import_state(import_state_match.group(1))
            return
        migration_state_match = PLAY_CAMPAIGN_MIGRATION_STATE_RE.match(self.path)
        if migration_state_match:
            self._handle_get_play_campaign_migration_state(migration_state_match.group(1))
            return
        rate_events_match = PLAY_CAMPAIGN_RATE_EVENTS_RE.match(self.path)
        if rate_events_match:
            self._handle_get_play_campaign_rate_events(rate_events_match.group(1))
            return
        metrics_match = PLAY_CAMPAIGN_METRICS_RE.match(self.path)
        if metrics_match:
            self._handle_get_play_campaign_metrics(metrics_match.group(1))
            return
        rng_ledger_match = PLAY_CAMPAIGN_RNG_LEDGER_RE.match(self.path)
        if rng_ledger_match:
            self._handle_get_play_campaign_rng_ledger(rng_ledger_match.group(1))
            return
        moderation_reports_match = PLAY_CAMPAIGN_MODERATION_REPORTS_RE.match(self.path)
        if moderation_reports_match:
            self._handle_get_play_campaign_moderation_reports(
                moderation_reports_match.group(1)
            )
            return
        safety_boundaries_match = PLAY_CAMPAIGN_SAFETY_BOUNDARIES_RE.match(self.path)
        if safety_boundaries_match:
            self._handle_get_play_campaign_safety_boundaries(
                safety_boundaries_match.group(1)
            )
            return
        safety_events_match = PLAY_CAMPAIGN_SAFETY_EVENTS_RE.match(self.path)
        if safety_events_match:
            self._handle_get_play_campaign_safety_events(
                safety_events_match.group(1)
            )
            return
        fixture_state_match = PLAY_CAMPAIGN_FIXTURE_STATE_RE.match(self.path)
        if fixture_state_match:
            self._handle_get_play_campaign_fixture_state(
                fixture_state_match.group(1)
            )
            return
        onboarding_match = PLAY_CAMPAIGN_ONBOARDING_RE.match(self.path)
        if onboarding_match:
            self._handle_get_play_campaign_onboarding(onboarding_match.group(1))
            return
        spectator_view_match = PLAY_CAMPAIGN_SPECTATOR_VIEW_RE.match(self.path)
        if spectator_view_match:
            self._handle_get_play_campaign_spectator_view(spectator_view_match.group(1))
            return
        event_feed_path, _, event_feed_query = self.path.partition("?")
        event_feed_match = PLAY_CAMPAIGN_EVENT_FEED_RE.match(event_feed_path)
        if event_feed_match:
            self._handle_get_play_campaign_event_feed(
                event_feed_match.group(1),
                parse_qs(event_feed_query, keep_blank_values=True),
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_PUT(self):
        try:
            body = self._read_json()
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid json"})
            return

        document_match = PLAY_CAMPAIGN_DOCUMENT_RE.match(self.path)
        if document_match:
            self._handle_put_play_campaign_document(document_match.group(1), body)
            return
        session_zero_match = PLAY_CAMPAIGN_SESSION_ZERO_RE.match(self.path)
        if session_zero_match:
            self._handle_put_play_campaign_session_zero(
                session_zero_match.group(1), body
            )
            return
        prepared_spells_match = PLAY_CAMPAIGN_CHARACTER_PREPARED_SPELLS_RE.match(self.path)
        if prepared_spells_match:
            self._handle_put_play_campaign_character_prepared_spells(
                prepared_spells_match.group(1), prepared_spells_match.group(2), body
            )
            return
        concentration_match = PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE.match(self.path)
        if concentration_match:
            self._handle_put_play_campaign_character_concentration(
                concentration_match.group(1), concentration_match.group(2), body
            )
            return
        equipment_slot_match = PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_SLOT_RE.match(self.path)
        if equipment_slot_match:
            self._handle_put_play_campaign_character_equipment(
                equipment_slot_match.group(1), equipment_slot_match.group(2),
                equipment_slot_match.group(3), body
            )
            return
        npc_agenda_match = PLAY_CAMPAIGN_NPC_AGENDA_RE.match(self.path)
        if npc_agenda_match:
            self._handle_put_play_campaign_npc_agenda(
                npc_agenda_match.group(1), npc_agenda_match.group(2), body
            )
            return
        relationship_edge_match = PLAY_CAMPAIGN_RELATIONSHIP_EDGE_RE.match(self.path)
        if relationship_edge_match:
            self._handle_put_play_campaign_relationship(
                relationship_edge_match.group(1), relationship_edge_match.group(2),
                relationship_edge_match.group(3), relationship_edge_match.group(4), body
            )
            return
        quest_state_match = PLAY_CAMPAIGN_QUEST_STATE_RE.match(self.path)
        if quest_state_match:
            self._handle_put_play_campaign_quest_state(
                quest_state_match.group(1), quest_state_match.group(2), body
            )
            return
        quest_rewards_match = PLAY_CAMPAIGN_QUEST_REWARDS_RE.match(self.path)
        if quest_rewards_match:
            self._handle_put_play_campaign_quest_rewards(
                quest_rewards_match.group(1), quest_rewards_match.group(2), body
            )
            return
        settlement_match = PLAY_CAMPAIGN_SETTLEMENT_RE.match(self.path)
        if settlement_match:
            self._handle_put_play_campaign_settlement(
                settlement_match.group(1), settlement_match.group(2), body
            )
            return
        content_tags_match = PLAY_CAMPAIGN_CONTENT_TAGS_RE.match(self.path)
        if content_tags_match:
            self._handle_put_play_campaign_content_tags(
                content_tags_match.group(1), content_tags_match.group(2), body
            )
            return
        note_match = PLAY_CAMPAIGN_NOTE_RE.match(self.path)
        if note_match:
            self._handle_put_play_campaign_note(
                note_match.group(1), note_match.group(2), body
            )
            return
        rng_seed_match = PLAY_CAMPAIGN_RNG_SEED_RE.match(self.path)
        if rng_seed_match:
            self._handle_put_play_campaign_rng_seed(rng_seed_match.group(1), body)
            return
        moderation_resolution_match = PLAY_CAMPAIGN_MODERATION_RESOLUTION_RE.match(self.path)
        if moderation_resolution_match:
            self._handle_put_play_campaign_moderation_resolution(
                moderation_resolution_match.group(1),
                moderation_resolution_match.group(2),
                body,
            )
            return
        safety_boundaries_match = PLAY_CAMPAIGN_SAFETY_BOUNDARIES_RE.match(self.path)
        if safety_boundaries_match:
            self._handle_put_play_campaign_safety_boundaries(
                safety_boundaries_match.group(1), body
            )
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self):
        try:
            body = self._read_json()
        except (json.JSONDecodeError, ValueError):
            self._send_json(400, {"error": "invalid json"})
            return

        if self.path == "/v1/dice/stats":
            self._handle_dice_stats(body)
        elif self.path == "/v1/checks/ability":
            self._handle_ability_check(body)
        elif self.path == "/v1/encounters/adjusted-xp":
            self._handle_adjusted_xp(body)
        elif self.path == "/v1/initiative/order":
            self._handle_initiative_order(body)
        elif self.path == "/v1/characters/ability-modifier":
            self._handle_ability_modifier(body)
        elif self.path == "/v1/characters/proficiency":
            self._handle_proficiency(body)
        elif self.path == "/v1/characters/derived-stats":
            self._handle_derived_stats(body)
        elif self.path == "/v1/phb/spell-slots":
            self._handle_spell_slots(body)
        elif self.path == "/v1/phb/rests/long":
            self._handle_long_rest(body)
        elif self.path == "/v1/phb/equipment-load":
            self._handle_equipment_load(body)
        elif self.path == "/v1/combat/sessions":
            self._handle_create_combat_session(body)
        elif COMBAT_CONDITIONS_RE.match(self.path):
            match = COMBAT_CONDITIONS_RE.match(self.path)
            self._handle_add_condition(match.group(1), body)
        elif COMBAT_ADVANCE_RE.match(self.path):
            match = COMBAT_ADVANCE_RE.match(self.path)
            self._handle_advance_turn(match.group(1), body)
        elif self.path == "/v1/auth/register":
            self._handle_register(body)
        elif self.path == "/v1/auth/login":
            self._handle_login(body)
        elif self.path == "/v1/storage/reset":
            self._handle_storage_reset(body)
        elif self.path == "/v1/compendium/monsters":
            self._handle_create_monster(body)
        elif self.path == "/v1/compendium/items":
            self._handle_create_item(body)
        elif self.path == "/v1/campaigns":
            self._handle_create_campaign(body)
        elif CAMPAIGN_CHARACTERS_RE.match(self.path):
            match = CAMPAIGN_CHARACTERS_RE.match(self.path)
            self._handle_add_character(match.group(1), body)
        elif CAMPAIGN_EVENTS_RE.match(self.path):
            match = CAMPAIGN_EVENTS_RE.match(self.path)
            self._handle_add_event(match.group(1), body)
        elif QUEST_PROGRESS_RE.match(self.path):
            match = QUEST_PROGRESS_RE.match(self.path)
            self._handle_quest_progress(match.group(1), match.group(2), body)
        elif CAMPAIGN_QUESTS_RE.match(self.path):
            match = CAMPAIGN_QUESTS_RE.match(self.path)
            self._handle_create_quest(match.group(1), body)
        elif CAMPAIGN_FACTIONS_RE.match(self.path):
            match = CAMPAIGN_FACTIONS_RE.match(self.path)
            self._handle_create_faction(match.group(1), body)
        elif CAMPAIGN_NPCS_RE.match(self.path):
            match = CAMPAIGN_NPCS_RE.match(self.path)
            self._handle_create_npc(match.group(1), body)
        elif CAMPAIGN_INVENTORY_RE.match(self.path):
            match = CAMPAIGN_INVENTORY_RE.match(self.path)
            self._handle_add_inventory(match.group(1), body)
        elif CAMPAIGN_CHARACTER_EQUIPMENT_RE.match(self.path):
            match = CAMPAIGN_CHARACTER_EQUIPMENT_RE.match(self.path)
            self._handle_assign_equipment(match.group(1), match.group(2), body)
        elif CAMPAIGN_CRAFTING_ADVANCE_RE.match(self.path):
            match = CAMPAIGN_CRAFTING_ADVANCE_RE.match(self.path)
            self._handle_advance_crafting(match.group(1), match.group(2), body)
        elif CAMPAIGN_CRAFTING_RE.match(self.path):
            match = CAMPAIGN_CRAFTING_RE.match(self.path)
            self._handle_create_crafting_project(match.group(1), body)
        elif self.path == "/v1/dm/encounter-builder":
            self._handle_encounter_builder(body)
        elif self.path == "/v1/dm/loot-parcel":
            self._handle_loot_parcel(body)
        elif self.path == "/v1/dm/session-recap":
            self._handle_session_recap(body)
        elif SESSION_ATTENDANCE_RE.match(self.path):
            match = SESSION_ATTENDANCE_RE.match(self.path)
            self._handle_session_attendance(match.group(1), match.group(2), body)
        elif CAMPAIGN_SESSIONS_RE.match(self.path):
            match = CAMPAIGN_SESSIONS_RE.match(self.path)
            self._handle_create_session(match.group(1), body)
        elif CAMPAIGN_ANALYTICS_RISK_RE.match(self.path):
            match = CAMPAIGN_ANALYTICS_RISK_RE.match(self.path)
            self._handle_analytics_risk_report(match.group(1), body)
        elif self.path == "/v1/play/campaigns":
            self._handle_create_play_campaign(body)
        elif PLAY_CAMPAIGN_MEMBERS_RE.match(self.path):
            match = PLAY_CAMPAIGN_MEMBERS_RE.match(self.path)
            self._handle_join_play_campaign(match.group(1), body)
        elif PLAY_CAMPAIGN_START_RE.match(self.path):
            match = PLAY_CAMPAIGN_START_RE.match(self.path)
            self._handle_start_play_campaign(match.group(1), body)
        elif PLAY_CAMPAIGN_NARRATIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_NARRATIONS_RE.match(self.path)
            self._handle_add_narration(match.group(1), body)
        elif PLAY_CAMPAIGN_ACTIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_ACTIONS_RE.match(self.path)
            self._handle_add_action(match.group(1), body)
        elif PLAY_CAMPAIGN_RESOLUTIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_RESOLUTIONS_RE.match(self.path)
            self._handle_add_resolution(match.group(1), body)
        elif PLAY_CAMPAIGN_TURN_NUDGE_RE.match(self.path):
            match = PLAY_CAMPAIGN_TURN_NUDGE_RE.match(self.path)
            self._handle_play_campaign_turn_nudge(match.group(1), body)
        elif PLAY_CAMPAIGN_TURN_TRAVEL_RE.match(self.path):
            match = PLAY_CAMPAIGN_TURN_TRAVEL_RE.match(self.path)
            self._handle_play_campaign_turn_travel(match.group(1), body)
        elif PLAY_CAMPAIGN_TURN_REST_RE.match(self.path):
            match = PLAY_CAMPAIGN_TURN_REST_RE.match(self.path)
            self._handle_play_campaign_turn_rest(match.group(1), body)
        elif PLAY_CAMPAIGN_SCENE_ENTER_RE.match(self.path):
            match = PLAY_CAMPAIGN_SCENE_ENTER_RE.match(self.path)
            self._handle_enter_play_campaign_scene(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_SCENE_CLOSE_RE.match(self.path):
            match = PLAY_CAMPAIGN_SCENE_CLOSE_RE.match(self.path)
            self._handle_close_play_campaign_scene(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_SCENES_RE.match(self.path):
            match = PLAY_CAMPAIGN_SCENES_RE.match(self.path)
            self._handle_create_play_campaign_scene(match.group(1), body)
        elif PLAY_CAMPAIGN_CONTENT_RE.match(self.path):
            match = PLAY_CAMPAIGN_CONTENT_RE.match(self.path)
            self._handle_create_play_campaign_content(match.group(1), body)
        elif PLAY_CAMPAIGN_LOCATION_CONNECTIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_LOCATION_CONNECTIONS_RE.match(self.path)
            self._handle_create_play_campaign_location_connection(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_LOCATIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_LOCATIONS_RE.match(self.path)
            self._handle_create_play_campaign_location(match.group(1), body)
        elif PLAY_CAMPAIGN_ENCOUNTER_MONSTERS_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_MONSTERS_RE.match(self.path)
            self._handle_add_play_campaign_encounter_monster(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_ACTIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_ACTIONS_RE.match(self.path)
            self._handle_add_play_campaign_encounter_action(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_TURN_ADVANCE_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_TURN_ADVANCE_RE.match(self.path)
            self._handle_advance_play_campaign_encounter_turn(
                match.group(1), match.group(2)
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_TURN_DELAY_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_TURN_DELAY_RE.match(self.path)
            self._handle_delay_play_campaign_encounter_turn(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_TURN_READY_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_TURN_READY_RE.match(self.path)
            self._handle_ready_play_campaign_encounter_turn(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_DAMAGE_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_DAMAGE_RE.match(self.path)
            self._handle_damage_play_campaign_encounter(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_HEAL_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_HEAL_RE.match(self.path)
            self._handle_heal_play_campaign_encounter(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_CONDITIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_CONDITIONS_RE.match(self.path)
            self._handle_add_play_campaign_encounter_condition(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_COMBATANTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_COMBATANTS_RE.match(self.path)
            self._handle_add_play_campaign_encounter_combatant(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_REWARDS_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_REWARDS_RE.match(self.path)
            self._handle_award_play_campaign_encounter_rewards(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_ENCOUNTER_CLOSE_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_CLOSE_RE.match(self.path)
            self._handle_close_play_campaign_encounter(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_ENCOUNTER_END_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTER_END_RE.match(self.path)
            self._handle_end_play_campaign_encounter(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_ENCOUNTERS_RE.match(self.path):
            match = PLAY_CAMPAIGN_ENCOUNTERS_RE.match(self.path)
            self._handle_create_play_campaign_encounter(match.group(1), body)
        elif PLAY_CAMPAIGN_CHARACTER_DAMAGE_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_DAMAGE_RE.match(self.path)
            self._handle_damage_play_campaign_character(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_DEATH_SAVES_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_DEATH_SAVES_RE.match(self.path)
            self._handle_play_campaign_character_death_save(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_CLAIM_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_CLAIM_RE.match(self.path)
            self._handle_claim_play_campaign_character(
                match.group(1), match.group(2)
            )
        elif PLAY_CAMPAIGN_CHARACTER_TRANSFER_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_TRANSFER_RE.match(self.path)
            self._handle_transfer_play_campaign_character(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_BUILD_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_BUILD_RE.match(self.path)
            self._handle_build_play_campaign_character(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_LEVEL_UP_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_LEVEL_UP_RE.match(self.path)
            self._handle_level_up_play_campaign_character(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_SKILL_CHECK_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_SKILL_CHECK_RE.match(self.path)
            self._handle_skill_check_play_campaign_character(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_SPELLS_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_SPELLS_RE.match(self.path)
            self._handle_add_play_campaign_character_spell(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_CASTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_CASTS_RE.match(self.path)
            self._handle_post_play_campaign_character_cast(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_ADVANCE_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_ADVANCE_RE.match(self.path)
            self._handle_advance_play_campaign_character_concentration(
                match.group(1), match.group(2)
            )
        elif PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEMS_RE.match(self.path)
            self._handle_add_play_campaign_character_inventory_item(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_ATTUNE_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_EQUIPMENT_ATTUNE_RE.match(self.path)
            self._handle_attune_play_campaign_character_equipment(
                match.group(1), match.group(2), match.group(3)
            )
        elif PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_CONSUME_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_CONSUME_RE.match(self.path)
            self._handle_consume_play_campaign_character_inventory_item(
                match.group(1), match.group(2), match.group(3)
            )
        elif PLAY_CAMPAIGN_CHARACTER_CURRENCY_TRANSFERS_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_CURRENCY_TRANSFERS_RE.match(self.path)
            self._handle_post_play_campaign_character_currency_transfer(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_LOOT_VOTES_RE.match(self.path):
            match = PLAY_CAMPAIGN_LOOT_VOTES_RE.match(self.path)
            self._handle_post_play_campaign_loot_vote(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_LOOT_ASSIGN_RE.match(self.path):
            match = PLAY_CAMPAIGN_LOOT_ASSIGN_RE.match(self.path)
            self._handle_post_play_campaign_loot_assign(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_LOOT_RE.match(self.path):
            match = PLAY_CAMPAIGN_LOOT_RE.match(self.path)
            self._handle_create_play_campaign_loot(match.group(1), body)
        elif PLAY_CAMPAIGN_NPC_DIALOGUE_RE.match(self.path):
            match = PLAY_CAMPAIGN_NPC_DIALOGUE_RE.match(self.path)
            self._handle_post_play_campaign_npc_dialogue(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_NPCS_RE.match(self.path):
            match = PLAY_CAMPAIGN_NPCS_RE.match(self.path)
            self._handle_create_play_campaign_npc(match.group(1), body)
        elif PLAY_CAMPAIGN_FACTION_REPUTATION_RE.match(self.path):
            match = PLAY_CAMPAIGN_FACTION_REPUTATION_RE.match(self.path)
            self._handle_post_play_campaign_faction_reputation(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_FACTIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_FACTIONS_RE.match(self.path)
            self._handle_create_play_campaign_faction(match.group(1), body)
        elif PLAY_CAMPAIGN_RELATIONSHIPS_RE.match(self.path):
            match = PLAY_CAMPAIGN_RELATIONSHIPS_RE.match(self.path)
            self._handle_create_play_campaign_relationship(match.group(1), body)
        elif PLAY_CAMPAIGN_CLUES_RE.match(self.path):
            match = PLAY_CAMPAIGN_CLUES_RE.match(self.path)
            self._handle_create_play_campaign_clue(match.group(1), body)
        elif PLAY_CAMPAIGN_QUEST_REWARDS_AWARD_RE.match(self.path):
            match = PLAY_CAMPAIGN_QUEST_REWARDS_AWARD_RE.match(self.path)
            self._handle_award_play_campaign_quest_rewards(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_QUESTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_QUESTS_RE.match(self.path)
            self._handle_create_play_campaign_quest(match.group(1), body)
        elif PLAY_CAMPAIGN_WORLD_EVENT_RESOLVE_RE.match(self.path):
            match = PLAY_CAMPAIGN_WORLD_EVENT_RESOLVE_RE.match(self.path)
            self._handle_resolve_play_campaign_world_event(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_WORLD_EVENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_WORLD_EVENTS_RE.match(self.path)
            self._handle_create_play_campaign_world_event(match.group(1), body)
        elif PLAY_CAMPAIGN_CALENDAR_ADVANCE_RE.match(self.path):
            match = PLAY_CAMPAIGN_CALENDAR_ADVANCE_RE.match(self.path)
            self._handle_advance_play_campaign_calendar(match.group(1), body)
        elif PLAY_CAMPAIGN_CALENDAR_RE.match(self.path):
            match = PLAY_CAMPAIGN_CALENDAR_RE.match(self.path)
            self._handle_create_play_campaign_calendar(match.group(1), body)
        elif PLAY_CAMPAIGN_SETTLEMENT_DISCOVER_RE.match(self.path):
            match = PLAY_CAMPAIGN_SETTLEMENT_DISCOVER_RE.match(self.path)
            self._handle_discover_play_campaign_settlement(
                match.group(1), match.group(2)
            )
        elif PLAY_CAMPAIGN_SETTLEMENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_SETTLEMENTS_RE.match(self.path)
            self._handle_create_play_campaign_settlement(match.group(1), body)
        elif PLAY_CAMPAIGN_SETTLEMENT_SHOP_BUY_RE.match(self.path):
            match = PLAY_CAMPAIGN_SETTLEMENT_SHOP_BUY_RE.match(self.path)
            self._handle_buy_play_campaign_shop_item(
                match.group(1), match.group(2), match.group(3), body
            )
        elif PLAY_CAMPAIGN_SETTLEMENT_SHOP_SELL_RE.match(self.path):
            match = PLAY_CAMPAIGN_SETTLEMENT_SHOP_SELL_RE.match(self.path)
            self._handle_sell_play_campaign_shop_item(
                match.group(1), match.group(2), match.group(3), body
            )
        elif PLAY_CAMPAIGN_SETTLEMENT_SHOPS_RE.match(self.path):
            match = PLAY_CAMPAIGN_SETTLEMENT_SHOPS_RE.match(self.path)
            self._handle_create_play_campaign_shop(match.group(1), match.group(2), body)
        elif PLAY_CAMPAIGN_RECIPE_CRAFT_RE.match(self.path):
            match = PLAY_CAMPAIGN_RECIPE_CRAFT_RE.match(self.path)
            self._handle_craft_play_campaign_recipe(match.group(1), match.group(2), body)
        elif PLAY_CAMPAIGN_RECIPES_RE.match(self.path):
            match = PLAY_CAMPAIGN_RECIPES_RE.match(self.path)
            self._handle_create_play_campaign_recipe(match.group(1), body)
        elif PLAY_CAMPAIGN_CHARACTER_DOWNTIME_PROGRESS_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_DOWNTIME_PROGRESS_RE.match(self.path)
            self._handle_progress_play_campaign_downtime_allocation(
                match.group(1), match.group(2), match.group(3)
            )
        elif PLAY_CAMPAIGN_CHARACTER_DOWNTIME_ALLOCATIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_CHARACTER_DOWNTIME_ALLOCATIONS_RE.match(self.path)
            self._handle_create_play_campaign_downtime_allocation(
                match.group(1), match.group(2), body
            )
        elif PLAY_CAMPAIGN_DOWNTIME_ACTIVITIES_RE.match(self.path):
            match = PLAY_CAMPAIGN_DOWNTIME_ACTIVITIES_RE.match(self.path)
            self._handle_create_play_campaign_downtime_activity(match.group(1), body)
        elif PLAY_CAMPAIGN_NOTES_RE.match(self.path):
            match = PLAY_CAMPAIGN_NOTES_RE.match(self.path)
            self._handle_create_play_campaign_note(match.group(1), body)
        elif PLAY_CAMPAIGN_SEARCH_RECORDS_RE.match(self.path):
            match = PLAY_CAMPAIGN_SEARCH_RECORDS_RE.match(self.path)
            self._handle_create_play_campaign_search_record(match.group(1), body)
        elif PLAY_CAMPAIGN_WHISPERS_RE.match(self.path):
            match = PLAY_CAMPAIGN_WHISPERS_RE.match(self.path)
            self._handle_create_play_campaign_whisper(match.group(1), body)
        elif PLAY_CAMPAIGN_RATE_EVENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_RATE_EVENTS_RE.match(self.path)
            self._handle_create_play_campaign_rate_event(match.group(1), body)
        elif PLAY_CAMPAIGN_INVITATION_ACCEPT_RE.match(self.path):
            match = PLAY_CAMPAIGN_INVITATION_ACCEPT_RE.match(self.path)
            self._handle_accept_play_campaign_invitation(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_INVITATIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_INVITATIONS_RE.match(self.path)
            self._handle_create_play_campaign_invitation(match.group(1), body)
        elif PLAY_CAMPAIGN_DELEGATIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_DELEGATIONS_RE.match(self.path)
            self._handle_create_play_campaign_delegation(match.group(1), body)
        elif PLAY_CAMPAIGN_AUDIT_EVENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_AUDIT_EVENTS_RE.match(self.path)
            self._handle_create_play_campaign_audit_event(match.group(1), body)
        elif PLAY_CAMPAIGN_PROJECTION_EVENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_PROJECTION_EVENTS_RE.match(self.path)
            self._handle_create_play_campaign_projection_event(match.group(1), body)
        elif PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_IDEMPOTENT_EVENTS_RE.match(self.path)
            self._handle_create_play_campaign_idempotent_event(match.group(1), body)
        elif PLAY_CAMPAIGN_SAFE_TURNS_RE.match(self.path):
            match = PLAY_CAMPAIGN_SAFE_TURNS_RE.match(self.path)
            self._handle_create_play_campaign_safe_turn(match.group(1), body)
        elif PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE.match(self.path):
            match = PLAY_CAMPAIGN_TRANSACTIONAL_TRANSFERS_RE.match(self.path)
            self._handle_create_play_campaign_transactional_transfer(match.group(1), body)
        elif PLAY_CAMPAIGN_EXPORTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_EXPORTS_RE.match(self.path)
            self._handle_create_play_campaign_export(match.group(1))
        elif PLAY_CAMPAIGN_IMPORTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_IMPORTS_RE.match(self.path)
            self._handle_create_play_campaign_import(match.group(1), body)
        elif PLAY_CAMPAIGN_MIGRATIONS_RE.match(self.path):
            match = PLAY_CAMPAIGN_MIGRATIONS_RE.match(self.path)
            self._handle_create_play_campaign_migration(match.group(1), body)
        elif PLAY_CAMPAIGN_SERVICE_MODE_RE.match(self.path):
            match = PLAY_CAMPAIGN_SERVICE_MODE_RE.match(self.path)
            self._handle_post_play_campaign_service_mode(match.group(1), body)
        elif PLAY_CAMPAIGN_BACKUP_RESTORE_RE.match(self.path):
            match = PLAY_CAMPAIGN_BACKUP_RESTORE_RE.match(self.path)
            self._handle_restore_play_campaign_backup(match.group(1), match.group(2))
        elif PLAY_CAMPAIGN_BACKUPS_RE.match(self.path):
            match = PLAY_CAMPAIGN_BACKUPS_RE.match(self.path)
            self._handle_create_play_campaign_backup(match.group(1))
        elif PLAY_CAMPAIGN_REPLAY_EVENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_REPLAY_EVENTS_RE.match(self.path)
            self._handle_create_play_campaign_replay_event(match.group(1), body)
        elif PLAY_CAMPAIGN_RNG_ROLLS_RE.match(self.path):
            match = PLAY_CAMPAIGN_RNG_ROLLS_RE.match(self.path)
            self._handle_create_play_campaign_rng_roll(match.group(1), body)
        elif PLAY_CAMPAIGN_MODERATION_REPORTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_MODERATION_REPORTS_RE.match(self.path)
            self._handle_create_play_campaign_moderation_report(match.group(1), body)
        elif PLAY_CAMPAIGN_SAFETY_CHECKS_RE.match(self.path):
            match = PLAY_CAMPAIGN_SAFETY_CHECKS_RE.match(self.path)
            self._handle_create_play_campaign_safety_check(match.group(1), body)
        elif PLAY_CAMPAIGN_FIXTURE_SEEDS_RE.match(self.path):
            match = PLAY_CAMPAIGN_FIXTURE_SEEDS_RE.match(self.path)
            self._handle_create_play_campaign_fixture_seed(match.group(1), body)
        elif PLAY_CAMPAIGN_SPECTATORS_RE.match(self.path):
            match = PLAY_CAMPAIGN_SPECTATORS_RE.match(self.path)
            self._handle_create_play_campaign_spectator(match.group(1), body)
        elif PLAY_CAMPAIGN_MESSAGES_RE.match(self.path):
            match = PLAY_CAMPAIGN_MESSAGES_RE.match(self.path)
            self._handle_create_play_campaign_message(match.group(1), body)
        elif PLAY_CAMPAIGN_FEED_EVENTS_RE.match(self.path):
            match = PLAY_CAMPAIGN_FEED_EVENTS_RE.match(self.path)
            self._handle_create_play_campaign_feed_event(match.group(1), body)
        else:
            self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        monster_match = PLAY_CAMPAIGN_ENCOUNTER_MONSTER_RE.match(self.path)
        if monster_match:
            self._handle_remove_play_campaign_encounter_monster(
                monster_match.group(1), monster_match.group(2), monster_match.group(3)
            )
            return
        combatant_match = PLAY_CAMPAIGN_ENCOUNTER_COMBATANT_RE.match(self.path)
        if combatant_match:
            self._handle_remove_play_campaign_encounter_combatant(
                combatant_match.group(1), combatant_match.group(2), combatant_match.group(3)
            )
            return
        concentration_match = PLAY_CAMPAIGN_CHARACTER_CONCENTRATION_RE.match(self.path)
        if concentration_match:
            self._handle_delete_play_campaign_character_concentration(
                concentration_match.group(1), concentration_match.group(2)
            )
            return
        inventory_item_match = PLAY_CAMPAIGN_CHARACTER_INVENTORY_ITEM_RE.match(self.path)
        if inventory_item_match:
            try:
                body = self._read_json()
            except (json.JSONDecodeError, ValueError):
                self._send_json(400, {"error": "invalid json"})
                return
            self._handle_delete_play_campaign_character_inventory_item(
                inventory_item_match.group(1),
                inventory_item_match.group(2),
                inventory_item_match.group(3),
                body,
            )
            return
        delegation_match = PLAY_CAMPAIGN_DELEGATION_RE.match(self.path)
        if delegation_match:
            self._handle_revoke_play_campaign_delegation(
                delegation_match.group(1), delegation_match.group(2)
            )
            return
        self._send_json(404, {"error": "not found"})

    # -- storage --------------------------------------------------------

    def _handle_storage_status(self):
        self._send_json(200, {
            "driver": "sqlite",
            "schema_version": db.SCHEMA_VERSION,
            "initialized": db.is_initialized(),
        })

    def _handle_storage_reset(self, body):
        db.reset_db()
        self._send_json(200, {"ok": True, "schema_version": db.SCHEMA_VERSION})

    # -- dice / checks / encounters --------------------------------------

    def _handle_dice_stats(self, body):
        expr = body.get("expression")
        if not isinstance(expr, str):
            self._send_json(400, {"error": "invalid expression"})
            return
        match = rules.DICE_RE.match(expr.strip())
        if not match:
            self._send_json(400, {"error": "invalid expression"})
            return
        count = int(match.group(1))
        sides = int(match.group(2))
        modifier = int(match.group(3)) if match.group(3) else 0
        if count <= 0 or sides <= 0:
            self._send_json(400, {"error": "invalid expression"})
            return
        dice_min = count * 1 + modifier
        dice_max = count * sides + modifier
        average = (count * (1 + sides) / 2) + modifier
        if average == int(average):
            average = int(average)
        self._send_json(200, {
            "dice_count": count,
            "sides": sides,
            "modifier": modifier,
            "min": dice_min,
            "max": dice_max,
            "average": average,
        })

    def _handle_ability_check(self, body):
        try:
            roll = body["roll"]
            modifier = body["modifier"]
            dc = body["dc"]
        except (KeyError, TypeError):
            self._send_json(400, {"error": "missing fields"})
            return
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (roll, modifier, dc)):
            self._send_json(400, {"error": "invalid fields"})
            return
        total = roll + modifier
        success = total >= dc
        margin = total - dc
        self._send_json(200, {"total": total, "success": success, "margin": margin})

    def _compute_adjusted_xp(self, monsters):
        """Shared by /v1/encounters/adjusted-xp and the DM encounter builder.

        Returns (base_xp, monster_count, error_payload). error_payload is
        None on success, otherwise a ready-to-send {"error": ...} dict.
        """
        base_xp = 0
        monster_count = 0
        try:
            for m in monsters:
                cr = str(m["cr"])
                count = int(m["count"])
                if cr not in rules.CR_XP or count < 0:
                    return None, None, {"error": "unsupported cr"}
                base_xp += rules.CR_XP[cr] * count
                monster_count += count
        except (KeyError, TypeError, ValueError):
            return None, None, {"error": "invalid monster entry"}
        return base_xp, monster_count, None

    def _compute_party_thresholds(self, party):
        """Returns (thresholds_dict, error_payload); error_payload is None on success."""
        thresholds = {"easy": 0, "medium": 0, "hard": 0, "deadly": 0}
        try:
            for member in party:
                level = int(member["level"])
                if level not in rules.LEVEL_THRESHOLDS:
                    return None, {"error": "unsupported level"}
                for key in thresholds:
                    thresholds[key] += rules.LEVEL_THRESHOLDS[level][key]
        except (KeyError, TypeError, ValueError):
            return None, {"error": "invalid party entry"}
        return thresholds, None

    @staticmethod
    def _difficulty_for(adjusted_xp, thresholds):
        if adjusted_xp >= thresholds["deadly"]:
            return "deadly"
        if adjusted_xp >= thresholds["hard"]:
            return "hard"
        if adjusted_xp >= thresholds["medium"]:
            return "medium"
        if adjusted_xp >= thresholds["easy"]:
            return "easy"
        return "trivial"

    def _handle_adjusted_xp(self, body):
        party = body.get("party")
        monsters = body.get("monsters")
        if not isinstance(party, list) or not isinstance(monsters, list):
            self._send_json(400, {"error": "invalid fields"})
            return

        base_xp, monster_count, error = self._compute_adjusted_xp(monsters)
        if error is not None:
            self._send_json(400, error)
            return

        multiplier = rules.multiplier_for_count(monster_count)
        adjusted_xp = base_xp * multiplier
        if adjusted_xp == int(adjusted_xp):
            adjusted_xp = int(adjusted_xp)

        thresholds, error = self._compute_party_thresholds(party)
        if error is not None:
            self._send_json(400, error)
            return

        difficulty = self._difficulty_for(adjusted_xp, thresholds)

        self._send_json(200, {
            "base_xp": base_xp,
            "monster_count": monster_count,
            "multiplier": multiplier,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "thresholds": thresholds,
        })

    def _handle_initiative_order(self, body):
        combatants = body.get("combatants")
        if not isinstance(combatants, list):
            self._send_json(400, {"error": "invalid fields"})
            return

        results = []
        try:
            for c in combatants:
                name = c["name"]
                dex = c["dex"]
                roll = c["roll"]
                score = roll + dex
                results.append({"name": name, "dex": dex, "score": score})
        except (KeyError, TypeError):
            self._send_json(400, {"error": "invalid combatant entry"})
            return

        results.sort(key=lambda r: (-r["score"], -r["dex"], r["name"]))
        order = [{"name": r["name"], "score": r["score"]} for r in results]
        self._send_json(200, {"order": order})

    # -- characters -------------------------------------------------------

    def _handle_ability_modifier(self, body):
        score = body.get("score")
        if not rules.is_plain_int(score) or not (1 <= score <= 30):
            self._send_json(400, {"error": "invalid score"})
            return
        self._send_json(200, {"score": score, "modifier": rules.ability_modifier(score)})

    def _handle_proficiency(self, body):
        level = body.get("level")
        if not rules.is_plain_int(level) or not (1 <= level <= 20):
            self._send_json(400, {"error": "invalid level"})
            return
        self._send_json(200, {"level": level, "proficiency_bonus": rules.proficiency_bonus(level)})

    def _handle_derived_stats(self, body):
        level = body.get("level")
        abilities = body.get("abilities")
        armor = body.get("armor")

        if not rules.is_plain_int(level) or not (1 <= level <= 20):
            self._send_json(400, {"error": "invalid level"})
            return
        if not isinstance(abilities, dict):
            self._send_json(400, {"error": "invalid abilities"})
            return
        required = ("str", "dex", "con", "int", "wis", "cha")
        modifiers = {}
        for key in required:
            score = abilities.get(key)
            if not rules.is_plain_int(score) or not (1 <= score <= 30):
                self._send_json(400, {"error": "invalid abilities"})
                return
            modifiers[key] = rules.ability_modifier(score)

        if not isinstance(armor, dict):
            self._send_json(400, {"error": "invalid armor"})
            return
        base = armor.get("base")
        shield = armor.get("shield")
        dex_cap = armor.get("dex_cap")
        if not rules.is_plain_int(base):
            self._send_json(400, {"error": "invalid armor"})
            return
        if not isinstance(shield, bool):
            self._send_json(400, {"error": "invalid armor"})
            return
        if not rules.is_plain_int(dex_cap):
            self._send_json(400, {"error": "invalid armor"})
            return

        proficiency = rules.proficiency_bonus(level)
        hp_max = level * (6 + modifiers["con"])
        shield_bonus = 2 if shield else 0
        armor_class = base + min(modifiers["dex"], dex_cap) + shield_bonus

        self._send_json(200, {
            "level": level,
            "proficiency_bonus": proficiency,
            "hp_max": hp_max,
            "armor_class": armor_class,
            "modifiers": modifiers,
        })

    # -- PHB rules ----------------------------------------------------------

    def _handle_spell_slots(self, body):
        klass = body.get("class")
        level = body.get("level")
        if not isinstance(klass, str) or klass != "wizard":
            self._send_json(400, {"error": "unsupported class"})
            return
        if not rules.is_plain_int(level) or level not in rules.WIZARD_SPELL_SLOTS:
            self._send_json(400, {"error": "unsupported level"})
            return
        self._send_json(200, {
            "class": klass,
            "level": level,
            "slots": rules.WIZARD_SPELL_SLOTS[level],
        })

    def _handle_long_rest(self, body):
        level = body.get("level")
        hp_current = body.get("hp_current")
        hp_max = body.get("hp_max")
        hit_dice_spent = body.get("hit_dice_spent")
        exhaustion_level = body.get("exhaustion_level")

        for value in (level, hp_current, hp_max, hit_dice_spent, exhaustion_level):
            if not rules.is_plain_int(value):
                self._send_json(400, {"error": "invalid fields"})
                return
        if not (1 <= level <= 20):
            self._send_json(400, {"error": "invalid level"})
            return
        if hp_current < 0 or hp_max < 0 or hp_current > hp_max:
            self._send_json(400, {"error": "invalid hp"})
            return
        if hit_dice_spent < 0 or hit_dice_spent > level:
            self._send_json(400, {"error": "invalid hit_dice_spent"})
            return
        if exhaustion_level < 0:
            self._send_json(400, {"error": "invalid exhaustion_level"})
            return

        recovered = max(level // 2, 1)
        new_hit_dice_spent = max(hit_dice_spent - recovered, 0)
        new_exhaustion = max(exhaustion_level - 1, 0)

        self._send_json(200, {
            "hp_current": hp_max,
            "hit_dice_spent": new_hit_dice_spent,
            "exhaustion_level": new_exhaustion,
        })

    def _handle_equipment_load(self, body):
        strength = body.get("strength")
        weight = body.get("weight")
        if not rules.is_plain_int(strength) or strength < 0:
            self._send_json(400, {"error": "invalid strength"})
            return
        if not rules.is_plain_int(weight) or weight < 0:
            self._send_json(400, {"error": "invalid weight"})
            return

        capacity = strength * 15
        encumbered = weight > capacity

        self._send_json(200, {
            "capacity": capacity,
            "weight": weight,
            "encumbered": encumbered,
        })

    # -- combat sessions ------------------------------------------------------

    def _handle_create_combat_session(self, body):
        session_id = body.get("id")
        combatants = body.get("combatants")
        if not isinstance(session_id, str) or not session_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if db.combat_session_exists(session_id):
            self._send_json(400, {"error": "duplicate id"})
            return
        if not isinstance(combatants, list) or not combatants:
            self._send_json(400, {"error": "invalid combatants"})
            return

        entries = []
        try:
            for c in combatants:
                name = c["name"]
                dex = c["dex"]
                roll = c["roll"]
                if not isinstance(name, str) or not name:
                    self._send_json(400, {"error": "invalid combatant entry"})
                    return
                if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (dex, roll)):
                    self._send_json(400, {"error": "invalid combatant entry"})
                    return
                score = roll + dex
                entries.append({"name": name, "dex": dex, "score": score, "conditions": []})
        except (KeyError, TypeError):
            self._send_json(400, {"error": "invalid combatant entry"})
            return

        entries.sort(key=lambda r: (-r["score"], -r["dex"], r["name"]))

        session = {
            "id": session_id,
            "round": 1,
            "turn_index": 0,
            "order": entries,
        }
        db.save_combat_session(session)

        self._send_json(200, self._combat_session_view(session))

    def _combat_session_view(self, session):
        order = [{"name": e["name"], "score": e["score"]} for e in session["order"]]
        active_entry = session["order"][session["turn_index"]]
        return {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": {"name": active_entry["name"], "score": active_entry["score"]},
            "order": order,
        }

    def _handle_add_condition(self, session_id, body):
        session = db.get_combat_session(session_id)
        if session is None:
            self._send_json(404, {"error": "session not found"})
            return

        target = body.get("target")
        condition = body.get("condition")
        duration = body.get("duration_rounds")

        if not isinstance(target, str) or not target:
            self._send_json(400, {"error": "invalid target"})
            return
        if not isinstance(condition, str) or not condition:
            self._send_json(400, {"error": "invalid condition"})
            return
        if not rules.is_plain_int(duration) or duration <= 0:
            self._send_json(400, {"error": "invalid duration_rounds"})
            return

        entry = next((e for e in session["order"] if e["name"] == target), None)
        if entry is None:
            self._send_json(400, {"error": "unknown target"})
            return

        entry["conditions"].append({"condition": condition, "remaining_rounds": duration})
        db.save_combat_session(session)

        self._send_json(200, {
            "target": target,
            "conditions": [dict(c) for c in entry["conditions"]],
        })

    def _handle_advance_turn(self, session_id, body):
        session = db.get_combat_session(session_id)
        if session is None:
            self._send_json(404, {"error": "session not found"})
            return

        order = session["order"]
        session["turn_index"] += 1
        if session["turn_index"] >= len(order):
            session["turn_index"] = 0
            session["round"] += 1

        active_entry = order[session["turn_index"]]
        remaining = []
        for cond in active_entry["conditions"]:
            cond["remaining_rounds"] -= 1
            if cond["remaining_rounds"] > 0:
                remaining.append(cond)
        active_entry["conditions"] = remaining
        db.save_combat_session(session)

        conditions_map = {}
        for e in order:
            if e["conditions"] or e is active_entry:
                conditions_map[e["name"]] = [dict(c) for c in e["conditions"]]

        self._send_json(200, {
            "id": session["id"],
            "round": session["round"],
            "turn_index": session["turn_index"],
            "active": {"name": active_entry["name"], "score": active_entry["score"]},
            "conditions": conditions_map,
        })

    # -- compendium: monsters / items -----------------------------------------

    def _handle_create_monster(self, body):
        slug = body.get("slug")
        name = body.get("name")
        cr = body.get("cr")
        armor_class = body.get("armor_class")
        hit_points = body.get("hit_points")
        tags = body.get("tags", [])

        if not isinstance(slug, str) or not rules.SLUG_RE.match(slug):
            self._send_json(400, {"error": "invalid slug"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(cr, str) or not cr:
            self._send_json(400, {"error": "invalid cr"})
            return
        if not rules.is_plain_int(armor_class):
            self._send_json(400, {"error": "invalid armor_class"})
            return
        if not rules.is_plain_int(hit_points):
            self._send_json(400, {"error": "invalid hit_points"})
            return
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            self._send_json(400, {"error": "invalid tags"})
            return
        if db.get_monster(slug) is not None:
            self._send_json(409, {"error": "duplicate slug"})
            return

        monster = {
            "slug": slug,
            "name": name,
            "cr": cr,
            "armor_class": armor_class,
            "hit_points": hit_points,
            "tags": tags,
        }
        try:
            db.create_monster(monster)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate slug"})
            return

        self._send_json(201, {
            "slug": slug,
            "name": name,
            "cr": cr,
            "armor_class": armor_class,
            "hit_points": hit_points,
        })

    def _handle_get_monster(self, slug):
        monster = db.get_monster(slug)
        if monster is None:
            self._send_json(404, {"error": "monster not found"})
            return
        self._send_json(200, monster)

    def _handle_create_item(self, body):
        slug = body.get("slug")
        name = body.get("name")
        item_type = body.get("type")
        rarity = body.get("rarity")
        cost_gp = body.get("cost_gp")

        if not isinstance(slug, str) or not rules.SLUG_RE.match(slug):
            self._send_json(400, {"error": "invalid slug"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(item_type, str) or not item_type:
            self._send_json(400, {"error": "invalid type"})
            return
        if not isinstance(rarity, str) or not rarity:
            self._send_json(400, {"error": "invalid rarity"})
            return
        if not rules.is_plain_int(cost_gp) or cost_gp < 0:
            self._send_json(400, {"error": "invalid cost_gp"})
            return
        if db.get_item(slug) is not None:
            self._send_json(409, {"error": "duplicate slug"})
            return

        item = {
            "slug": slug,
            "name": name,
            "type": item_type,
            "rarity": rarity,
            "cost_gp": cost_gp,
        }
        try:
            db.create_item(item)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate slug"})
            return

        self._send_json(201, item)

    def _handle_get_item(self, slug):
        item = db.get_item(slug)
        if item is None:
            self._send_json(404, {"error": "item not found"})
            return
        self._send_json(200, item)

    # -- auth --------------------------------------------------------------

    def _handle_register(self, body):
        username = body.get("username")
        password = body.get("password")
        role = body.get("role")

        if not isinstance(username, str) or not rules.USERNAME_RE.match(username):
            self._send_json(400, {"error": "invalid username"})
            return
        if not isinstance(password, str) or len(password) < 8:
            self._send_json(400, {"error": "invalid password"})
            return
        if role not in ("dm", "player"):
            self._send_json(400, {"error": "invalid role"})
            return
        if db.get_user(username) is not None:
            self._send_json(409, {"error": "duplicate username"})
            return

        salt, digest_hex = rules.hash_password(password)
        try:
            db.create_user(username, role, salt, digest_hex)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate username"})
            return

        self._send_json(201, {"username": username, "role": role})

    def _handle_login(self, body):
        username = body.get("username")
        password = body.get("password")

        if not isinstance(username, str) or not isinstance(password, str):
            self._send_json(400, {"error": "invalid fields"})
            return

        user = db.get_user(username)
        if user is None or not rules.verify_password(password, user["salt"], user["hash"]):
            self._send_json(401, {"error": "invalid credentials"})
            return

        self._send_json(200, {"username": username, "token": f"session-{username}"})

    def _authenticate(self):
        """Resolve the bearer session token.

        Returns None when the Authorization header is missing or malformed
        (callers should respond 401). Returns an actor dict otherwise; if the
        username isn't a known user, role is None and callers should treat
        that as an authorization failure (403), since the token format itself
        was valid.
        """
        header = self.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        token = header[len("Bearer "):]
        if not token.startswith("session-"):
            return None
        username = token[len("session-"):]
        if not username:
            return None
        user = db.get_user(username)
        if user is None:
            return {"username": username, "role": None}
        return {"username": username, "role": user["role"]}

    def _get_actor_or_401(self):
        """`_authenticate()` plus writing the 401 response on failure.

        Callers use the `if actor is None: return` idiom; the response body
        has already been sent by the time they see None.
        """
        actor = self._authenticate()
        if actor is None:
            self._send_json(401, {"error": "unauthorized"})
        return actor

    def _get_campaign_or_404(self, campaign_id):
        """`db.get_campaign()` plus writing the 404 response on a miss.

        Shared by every campaign-scoped handler (characters, events, quests,
        factions, npcs, inventory, crafting, sessions, analytics) so the
        "campaign not found" check and response body stay identical
        everywhere it's needed.
        """
        campaign = db.get_campaign(campaign_id)
        if campaign is None:
            self._send_json(404, {"error": "campaign not found"})
        return campaign

    def _get_play_campaign_or_404(self, campaign_id):
        """`db.get_play_campaign()` plus writing the 404 response on a miss."""
        campaign = db.get_play_campaign(campaign_id)
        if campaign is None:
            self._send_json(404, {"error": "campaign not found"})
        return campaign

    def _require_owner(self, actor, campaign):
        """True if `actor` owns `campaign`; otherwise writes 403 and returns False.

        Used by DM-only live-play mutations (encounters, scenes, locations,
        turn advancement, character transfer/level-up). Callers use the
        `if not self._require_owner(actor, campaign): return` idiom.
        """
        if actor["username"] != campaign["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return False
        return True

    # -- campaigns --------------------------------------------------------------

    def _handle_create_campaign(self, body):
        campaign_id = body.get("id")
        name = body.get("name")
        dm = body.get("dm")

        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(dm, str) or not dm:
            self._send_json(400, {"error": "invalid dm"})
            return
        if db.get_campaign(campaign_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        campaign = {"id": campaign_id, "name": name, "dm": dm}
        try:
            db.create_campaign(campaign)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, campaign)

    def _handle_add_character(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        char_id = body.get("id")
        name = body.get("name")
        level = body.get("level")
        char_class = body.get("class")

        if not isinstance(char_id, str) or not char_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not rules.is_plain_int(level):
            self._send_json(400, {"error": "invalid level"})
            return
        if not isinstance(char_class, str) or not char_class:
            self._send_json(400, {"error": "invalid class"})
            return
        if db.get_campaign_character(campaign_id, char_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        character = {"id": char_id, "name": name, "level": level, "class": char_class}
        try:
            db.create_campaign_character(campaign_id, character)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, character)

    def _handle_add_event(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        event_id = body.get("id")
        kind = body.get("kind")
        summary = body.get("summary")

        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(kind, str) or not kind:
            self._send_json(400, {"error": "invalid kind"})
            return
        if summary is not None and not isinstance(summary, str):
            self._send_json(400, {"error": "invalid summary"})
            return
        if db.get_campaign_event(campaign_id, event_id):
            self._send_json(409, {"error": "duplicate id"})
            return

        event = {"id": event_id, "kind": kind, "summary": summary}
        try:
            db.create_campaign_event(campaign_id, event)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, {"id": event_id, "kind": kind})

    def _handle_campaign_state(self, campaign_id):
        campaign = self._get_campaign_or_404(campaign_id)
        if campaign is None:
            return

        characters = db.list_campaign_characters(campaign_id)
        log_count = db.count_campaign_events(campaign_id)

        self._send_json(200, {
            "id": campaign["id"],
            "name": campaign["name"],
            "dm": campaign["dm"],
            "characters": characters,
            "log_count": log_count,
        })

    def _handle_campaign_audit(self, campaign_id):
        campaign = self._get_campaign_or_404(campaign_id)
        if campaign is None:
            return

        self._send_json(200, {
            "campaign_id": campaign["id"],
            "events": db.count_campaign_events(campaign_id),
            "quests": db.count_campaign_quests(campaign_id),
            "npcs": db.count_campaign_npcs(campaign_id),
            "sessions": db.count_campaign_sessions(campaign_id),
        })

    def _handle_campaign_export(self, campaign_id):
        campaign = self._get_campaign_or_404(campaign_id)
        if campaign is None:
            return

        self._send_json(200, {
            "campaign_id": campaign["id"],
            "name": campaign["name"],
            "characters": len(db.list_campaign_characters(campaign_id)),
            "quests": db.count_campaign_quests(campaign_id),
            "npcs": db.count_campaign_npcs(campaign_id),
            "inventory_items": db.count_campaign_inventory_items_total(campaign_id),
            "sessions": db.count_campaign_sessions(campaign_id),
            "schema_version": 1,
        })

    # -- campaign analytics ---------------------------------------------

    def _analytics_signals(self, campaign_id, campaign):
        quest_counts = db.count_campaign_quests_by_status(campaign_id)
        return {
            "has_dm": bool(campaign["dm"]),
            "has_characters": len(db.list_campaign_characters(campaign_id)) > 0,
            "has_next_session": db.get_next_session(campaign_id) is not None,
            "has_active_quest": quest_counts.get("active", 0) > 0,
        }, quest_counts

    def _handle_analytics_summary(self, campaign_id):
        campaign = self._get_campaign_or_404(campaign_id)
        if campaign is None:
            return

        signals, quest_counts = self._analytics_signals(campaign_id, campaign)
        open_quests = quest_counts.get("active", 0) + quest_counts.get("blocked", 0)
        friendly_npcs = db.count_campaign_friendly_npcs(campaign_id)
        scheduled_sessions = db.count_campaign_sessions(campaign_id)
        inventory_items = db.count_campaign_inventory_items_total(campaign_id)

        readiness_score = (
            (25 if signals["has_dm"] else 0)
            + (25 if signals["has_characters"] else 0)
            + (20 if signals["has_next_session"] else 0)
            + (15 if signals["has_active_quest"] else 0)
        )

        self._send_json(200, {
            "campaign_id": campaign["id"],
            "readiness_score": readiness_score,
            "open_quests": open_quests,
            "friendly_npcs": friendly_npcs,
            "scheduled_sessions": scheduled_sessions,
            "inventory_items": inventory_items,
        })

    def _handle_analytics_risk_report(self, campaign_id, body):
        campaign = self._get_campaign_or_404(campaign_id)
        if campaign is None:
            return

        include_zeroes = body.get("include_zeroes", False)
        if not isinstance(include_zeroes, bool):
            self._send_json(400, {"error": "invalid include_zeroes"})
            return

        signals, quest_counts = self._analytics_signals(campaign_id, campaign)

        missing = []
        if not signals["has_dm"]:
            missing.append("dm")
        if not signals["has_characters"]:
            missing.append("characters")
        if not signals["has_next_session"]:
            missing.append("next_session")
        if not signals["has_active_quest"]:
            missing.append("active_quest")
        if include_zeroes:
            if db.count_campaign_npcs(campaign_id) == 0:
                missing.append("npcs")
            if db.count_campaign_inventory_items_total(campaign_id) == 0:
                missing.append("inventory")

        missing_count = len(missing)
        if missing_count == 0:
            risk_level = "low"
        elif missing_count <= 2:
            risk_level = "medium"
        else:
            risk_level = "high"

        self._send_json(200, {
            "campaign_id": campaign["id"],
            "risk_level": risk_level,
            "missing": missing,
            "signals": signals,
        })

    # -- campaign quests ----------------------------------------------------

    QUEST_STATUSES = ("active", "completed", "blocked")

    def _quest_view(self, quest):
        return {
            "id": quest["id"],
            "title": quest["title"],
            "status": quest["status"],
            "milestones_total": len(quest["milestones"]),
            "milestones_done": len(quest["completed"]),
        }

    def _handle_create_quest(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        quest_id = body.get("id")
        title = body.get("title")
        status = body.get("status")
        milestones = body.get("milestones")

        if not isinstance(quest_id, str) or not quest_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(title, str) or not title:
            self._send_json(400, {"error": "invalid title"})
            return
        if status not in self.QUEST_STATUSES:
            self._send_json(400, {"error": "invalid status"})
            return
        if not isinstance(milestones, list) or not milestones or not all(
            isinstance(m, str) and m for m in milestones
        ):
            self._send_json(400, {"error": "invalid milestones"})
            return
        if db.get_quest(campaign_id, quest_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        quest = {
            "id": quest_id,
            "title": title,
            "status": status,
            "milestones": milestones,
            "completed": [],
        }
        try:
            db.create_quest(campaign_id, quest)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, self._quest_view(quest))

    def _handle_quest_progress(self, campaign_id, quest_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return
        quest = db.get_quest(campaign_id, quest_id)
        if quest is None:
            self._send_json(404, {"error": "quest not found"})
            return

        completed_input = body.get("completed")
        if not isinstance(completed_input, list) or not all(
            isinstance(m, str) for m in completed_input
        ):
            self._send_json(400, {"error": "invalid completed"})
            return
        if not all(m in quest["milestones"] for m in completed_input):
            self._send_json(400, {"error": "unknown milestone"})
            return

        completed = list(quest["completed"])
        for m in completed_input:
            if m not in completed:
                completed.append(m)

        status = quest["status"]
        if len(completed) >= len(quest["milestones"]):
            status = "completed"

        db.save_quest_progress(campaign_id, quest_id, completed, status)

        self._send_json(200, {
            "id": quest["id"],
            "status": status,
            "milestones_total": len(quest["milestones"]),
            "milestones_done": len(completed),
        })

    def _handle_quest_summary(self, campaign_id):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        counts = db.count_campaign_quests_by_status(campaign_id)
        self._send_json(200, {
            "campaign_id": campaign_id,
            "active": counts.get("active", 0),
            "completed": counts.get("completed", 0),
            "blocked": counts.get("blocked", 0),
        })

    # -- campaign npcs / factions --------------------------------------------

    def _handle_create_faction(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        faction_id = body.get("id")
        name = body.get("name")
        stance = body.get("stance")

        if not isinstance(faction_id, str) or not faction_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(stance, str) or not stance:
            self._send_json(400, {"error": "invalid stance"})
            return
        if db.get_faction(campaign_id, faction_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        faction = {"id": faction_id, "name": name, "stance": stance}
        try:
            db.create_faction(campaign_id, faction)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, faction)

    def _handle_create_npc(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        npc_id = body.get("id")
        name = body.get("name")
        faction_id = body.get("faction_id")
        disposition = body.get("disposition")

        if not isinstance(npc_id, str) or not npc_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if faction_id is not None and not isinstance(faction_id, str):
            self._send_json(400, {"error": "invalid faction_id"})
            return
        if not rules.is_plain_int(disposition):
            self._send_json(400, {"error": "invalid disposition"})
            return
        if faction_id is not None and db.get_faction(campaign_id, faction_id) is None:
            self._send_json(400, {"error": "unknown faction_id"})
            return
        if db.get_npc(campaign_id, npc_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        npc = {
            "id": npc_id,
            "name": name,
            "faction_id": faction_id,
            "disposition": disposition,
        }
        try:
            db.create_npc(campaign_id, npc)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, npc)

    def _handle_relationships(self, campaign_id):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        self._send_json(200, {
            "campaign_id": campaign_id,
            "factions": db.count_campaign_factions(campaign_id),
            "npcs": db.count_campaign_npcs(campaign_id),
            "friendly_npcs": db.count_campaign_friendly_npcs(campaign_id),
        })

    # -- campaign inventory / equipment --------------------------------------

    def _handle_add_inventory(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        item_slug = body.get("item_slug")
        quantity = body.get("quantity")
        owner = body.get("owner")

        if not isinstance(item_slug, str) or not rules.SLUG_RE.match(item_slug):
            self._send_json(400, {"error": "invalid item_slug"})
            return
        if not rules.is_plain_int(quantity) or quantity <= 0:
            self._send_json(400, {"error": "invalid quantity"})
            return
        if not isinstance(owner, str) or not owner:
            self._send_json(400, {"error": "invalid owner"})
            return

        db.create_inventory_item(campaign_id, item_slug, quantity, owner)

        self._send_json(201, {
            "item_slug": item_slug,
            "quantity": quantity,
            "owner": owner,
        })

    def _handle_assign_equipment(self, campaign_id, character_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return
        if db.get_campaign_character(campaign_id, character_id) is None:
            self._send_json(404, {"error": "character not found"})
            return

        item_slug = body.get("item_slug")
        quantity = body.get("quantity")

        if not isinstance(item_slug, str) or not rules.SLUG_RE.match(item_slug):
            self._send_json(400, {"error": "invalid item_slug"})
            return
        if not rules.is_plain_int(quantity) or quantity <= 0:
            self._send_json(400, {"error": "invalid quantity"})
            return

        db.create_equipment_assignment(campaign_id, character_id, item_slug, quantity)

        self._send_json(200, {
            "character_id": character_id,
            "item_slug": item_slug,
            "quantity": quantity,
        })

    def _handle_inventory_summary(self, campaign_id):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        party_items = db.count_campaign_inventory_items(campaign_id, "party")
        assigned_items = db.count_campaign_equipment_assignments(campaign_id)
        party_potions = db.sum_campaign_inventory_quantity(campaign_id, "healing-potion", "party")
        assigned_potions = db.sum_campaign_equipment_quantity(campaign_id, "healing-potion")
        healing_potions_available = party_potions - assigned_potions

        self._send_json(200, {
            "campaign_id": campaign_id,
            "party_items": party_items,
            "assigned_items": assigned_items,
            "healing_potions_available": healing_potions_available,
        })

    # -- DM tools --------------------------------------------------------------

    def _handle_encounter_builder(self, body):
        campaign_id = body.get("campaign_id")
        party = body.get("party")
        monster_slugs = body.get("monster_slugs")

        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "invalid campaign_id"})
            return
        if self._get_campaign_or_404(campaign_id) is None:
            return
        if not isinstance(party, list) or not party:
            self._send_json(400, {"error": "invalid party"})
            return
        if not isinstance(monster_slugs, list) or not monster_slugs:
            self._send_json(400, {"error": "invalid monster_slugs"})
            return

        base_xp = 0
        monster_count = 0
        for slug in monster_slugs:
            if not isinstance(slug, str):
                self._send_json(400, {"error": "invalid monster_slugs"})
                return
            monster = db.get_monster(slug)
            if monster is None:
                self._send_json(400, {"error": "unknown monster slug"})
                return
            cr = monster["cr"]
            if cr not in rules.CR_XP:
                self._send_json(400, {"error": "unsupported cr"})
                return
            base_xp += rules.CR_XP[cr]
            monster_count += 1

        multiplier = rules.multiplier_for_count(monster_count)
        adjusted_xp = base_xp * multiplier
        if adjusted_xp == int(adjusted_xp):
            adjusted_xp = int(adjusted_xp)

        thresholds, error = self._compute_party_thresholds(party)
        if error is not None:
            self._send_json(400, error)
            return

        difficulty = self._difficulty_for(adjusted_xp, thresholds)

        self._send_json(200, {
            "campaign_id": campaign_id,
            "base_xp": base_xp,
            "adjusted_xp": adjusted_xp,
            "difficulty": difficulty,
            "monster_count": monster_count,
            "recommendation": rules.DIFFICULTY_RECOMMENDATIONS[difficulty],
        })

    def _handle_loot_parcel(self, body):
        campaign_id = body.get("campaign_id")
        tier = body.get("tier")
        seed = body.get("seed")

        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "invalid campaign_id"})
            return
        if self._get_campaign_or_404(campaign_id) is None:
            return
        if not rules.is_plain_int(tier) or tier not in rules.DM_LOOT_TIERS:
            self._send_json(400, {"error": "unsupported tier"})
            return
        if not rules.is_plain_int(seed):
            self._send_json(400, {"error": "invalid seed"})
            return

        # seed is accepted (and validated) for forward-compatible loot
        # rolling, but current tiers are fixed presets, so it's unused here.
        parcel = rules.DM_LOOT_TIERS[tier]
        self._send_json(200, {
            "campaign_id": campaign_id,
            "coins_gp": parcel["coins_gp"],
            "items": [dict(item) for item in parcel["items"]],
        })

    def _handle_session_recap(self, body):
        campaign_id = body.get("campaign_id")

        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "invalid campaign_id"})
            return
        campaign = self._get_campaign_or_404(campaign_id)
        if campaign is None:
            return

        event = db.latest_campaign_event(campaign_id)
        if event is None:
            self._send_json(200, {
                "campaign_id": campaign_id,
                "summary": "No sessions logged yet.",
                "open_threads": [],
            })
            return

        summary = event["summary"] or ""
        # Heuristic recap: drop the leading two words (typically "The party"
        # or similar) and any remaining "the", then treat what's left as the
        # open thread. Matches the previous implementation's behavior.
        words = summary.rstrip(".").split()
        remainder = [w for w in words[2:] if w.lower() != "the"]
        open_threads = []
        if remainder:
            open_threads.append("Resolve " + " ".join(remainder) + " ambush")

        self._send_json(200, {
            "campaign_id": campaign_id,
            "summary": summary,
            "open_threads": open_threads,
        })


    # -- downtime crafting ------------------------------------------------

    def _handle_create_crafting_project(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        project_id = body.get("id")
        character_id = body.get("character_id")
        item_slug = body.get("item_slug")
        days_required = body.get("days_required")
        cost_gp = body.get("cost_gp")

        if not isinstance(project_id, str) or not project_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(character_id, str) or not character_id:
            self._send_json(400, {"error": "invalid character_id"})
            return
        if db.get_campaign_character(campaign_id, character_id) is None:
            self._send_json(400, {"error": "unknown character_id"})
            return
        if not isinstance(item_slug, str) or not rules.SLUG_RE.match(item_slug):
            self._send_json(400, {"error": "invalid item_slug"})
            return
        if not rules.is_plain_int(days_required) or days_required <= 0:
            self._send_json(400, {"error": "invalid days_required"})
            return
        if not rules.is_plain_int(cost_gp) or cost_gp < 0:
            self._send_json(400, {"error": "invalid cost_gp"})
            return
        if db.get_crafting_project(campaign_id, project_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        project = {
            "id": project_id,
            "character_id": character_id,
            "item_slug": item_slug,
            "days_required": days_required,
            "days_completed": 0,
            "cost_gp": cost_gp,
            "status": "active",
        }
        db.create_crafting_project(campaign_id, project)

        self._send_json(201, {
            "id": project["id"],
            "character_id": project["character_id"],
            "item_slug": project["item_slug"],
            "days_required": project["days_required"],
            "days_completed": project["days_completed"],
            "status": project["status"],
        })

    def _handle_advance_crafting(self, campaign_id, project_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return
        project = db.get_crafting_project(campaign_id, project_id)
        if project is None:
            self._send_json(404, {"error": "crafting project not found"})
            return

        days = body.get("days")
        if not rules.is_plain_int(days) or days <= 0:
            self._send_json(400, {"error": "invalid days"})
            return
        if project["status"] == "complete":
            self._send_json(400, {"error": "project already complete"})
            return

        days_completed = min(project["days_completed"] + days, project["days_required"])
        status = "complete" if days_completed >= project["days_required"] else "active"

        db.save_crafting_progress(campaign_id, project_id, days_completed, status)

        if status == "complete":
            db.create_inventory_item(campaign_id, project["item_slug"], 1, "party")

        self._send_json(200, {
            "id": project["id"],
            "days_completed": days_completed,
            "status": status,
        })

    # -- campaign sessions ------------------------------------------------

    def _handle_create_session(self, campaign_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        session_id = body.get("id")
        starts_at = body.get("starts_at")
        duration_minutes = body.get("duration_minutes")
        agenda = body.get("agenda")

        if not isinstance(session_id, str) or not session_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(starts_at, str) or not ISO_TIMESTAMP_RE.match(starts_at):
            self._send_json(400, {"error": "invalid starts_at"})
            return
        if not rules.is_plain_int(duration_minutes) or duration_minutes <= 0:
            self._send_json(400, {"error": "invalid duration_minutes"})
            return
        if not isinstance(agenda, list) or not all(isinstance(a, str) and a for a in agenda):
            self._send_json(400, {"error": "invalid agenda"})
            return
        if db.get_session(campaign_id, session_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        session = {
            "id": session_id,
            "starts_at": starts_at,
            "duration_minutes": duration_minutes,
            "agenda": agenda,
            "present": [],
            "absent": [],
        }
        try:
            db.create_session(campaign_id, session)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, {
            "id": session_id,
            "starts_at": starts_at,
            "duration_minutes": duration_minutes,
            "agenda_count": len(agenda),
        })

    def _handle_session_attendance(self, campaign_id, session_id, body):
        if self._get_campaign_or_404(campaign_id) is None:
            return
        session = db.get_session(campaign_id, session_id)
        if session is None:
            self._send_json(404, {"error": "session not found"})
            return

        present = body.get("present")
        absent = body.get("absent")
        if not isinstance(present, list) or not all(isinstance(p, str) and p for p in present):
            self._send_json(400, {"error": "invalid present"})
            return
        if not isinstance(absent, list) or not all(isinstance(a, str) and a for a in absent):
            self._send_json(400, {"error": "invalid absent"})
            return

        db.save_session_attendance(campaign_id, session_id, present, absent)

        self._send_json(200, {
            "session_id": session_id,
            "present_count": len(present),
            "absent_count": len(absent),
        })

    def _handle_next_session(self, campaign_id):
        if self._get_campaign_or_404(campaign_id) is None:
            return

        session = db.get_next_session(campaign_id)
        if session is None:
            self._send_json(404, {"error": "no sessions scheduled"})
            return

        self._send_json(200, {
            "id": session["id"],
            "starts_at": session["starts_at"],
            "agenda_count": len(session["agenda"]),
        })

    # -- play campaigns ----------------------------------------------------

    def _handle_create_play_campaign(self, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return
        if actor["role"] != "dm":
            self._send_json(403, {"error": "forbidden"})
            return

        campaign_id = body.get("id")
        name = body.get("name")
        max_players = body.get("max_players")

        if not isinstance(campaign_id, str) or not campaign_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(max_players, int) or isinstance(max_players, bool) or max_players < 1:
            self._send_json(400, {"error": "invalid max_players"})
            return
        if db.get_play_campaign(campaign_id) is not None:
            self._send_json(409, {"error": "duplicate id"})
            return

        campaign = {
            "id": campaign_id,
            "name": name,
            "owner": actor["username"],
            "status": "lobby",
            "max_players": max_players,
        }
        try:
            db.create_play_campaign(campaign)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate id"})
            return

        self._send_json(201, campaign)

    def _handle_join_play_campaign(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return
        if actor["role"] != "player":
            self._send_json(403, {"error": "forbidden"})
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        character_id = body.get("character_id")
        name = body.get("name")
        char_class = body.get("class")

        if not isinstance(character_id, str) or not character_id:
            self._send_json(400, {"error": "invalid character_id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(char_class, str) or not char_class:
            self._send_json(400, {"error": "invalid class"})
            return

        if db.get_play_campaign_member(campaign_id, actor["username"]) is not None:
            self._send_json(409, {"error": "already a member"})
            return
        if db.get_play_campaign_member_by_character(campaign_id, character_id) is not None:
            self._send_json(409, {"error": "duplicate character_id"})
            return
        if db.get_play_campaign_member_count(campaign_id) >= campaign["max_players"]:
            self._send_json(409, {"error": "party full"})
            return

        member = {
            "username": actor["username"],
            "character_id": character_id,
            "name": name,
            "class": char_class,
        }
        try:
            db.create_play_campaign_member(campaign_id, member)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate member"})
            return

        self._send_json(201, member)

    def _handle_start_play_campaign(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        if campaign["status"] != "lobby":
            self._send_json(409, {"error": "campaign not in lobby"})
            return

        if db.get_play_campaign_member_count(campaign_id) < 2:
            self._send_json(409, {"error": "not enough party members"})
            return

        current_actor = db.get_first_play_campaign_member(campaign_id)
        started = db.start_play_campaign(campaign_id, current_actor)
        if not started:
            self._send_json(409, {"error": "campaign not in lobby"})
            return

        self._send_json(200, {
            "id": campaign_id,
            "status": "active",
            "current_actor": current_actor,
            "turn_number": 1,
        })

    def _handle_add_narration(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] != campaign["owner"]:
            delegation = db.get_play_campaign_delegation(campaign_id, actor["username"])
            if (
                delegation is None
                or not delegation["active"]
                or "narrate" not in delegation["powers"]
            ):
                self._send_json(403, {"error": "forbidden"})
                return

        text = body.get("text")
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        sequence = db.create_play_campaign_narration(campaign_id, actor["username"], text)

        self._send_json(201, {
            "sequence": sequence,
            "kind": "narration",
            "actor": actor["username"],
            "text": text,
        })

    def _handle_add_action(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        if is_owner or campaign["current_actor"] != actor["username"]:
            self._send_json(409, {"error": "not your turn"})
            return

        action_type = body.get("type")
        text = body.get("text")
        if not isinstance(action_type, str) or not action_type:
            self._send_json(400, {"error": "invalid type"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        sequence = db.create_play_campaign_action(
            campaign_id, actor["username"], action_type, text
        )

        self._send_json(201, {
            "sequence": sequence,
            "kind": "action",
            "actor": actor["username"],
            "type": action_type,
            "text": text,
            "next_actor": "dm",
        })

    def _handle_play_campaign_turn_travel(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        if is_owner or campaign["current_actor"] != actor["username"]:
            self._send_json(409, {"error": "not your turn"})
            return

        destination_id = body.get("destination_id")
        if not isinstance(destination_id, str) or not destination_id:
            self._send_json(400, {"error": "invalid destination_id"})
            return

        current_location_id = campaign["current_location_id"]
        connection = None
        if current_location_id is not None:
            connection = db.get_play_location_connection(
                campaign_id, current_location_id, destination_id
            )
        if connection is None:
            self._send_json(409, {"error": "invalid destination"})
            return

        sequence = db.create_play_campaign_travel(
            campaign_id, actor["username"], destination_id, campaign["owner"]
        )

        self._send_json(201, {
            "sequence": sequence,
            "kind": "travel",
            "actor": actor["username"],
            "destination_id": destination_id,
            "travel_turns": connection["travel_turns"],
            "next_actor": "dm",
        })

    def _handle_play_campaign_turn_rest(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        if is_owner or campaign["current_actor"] != actor["username"]:
            self._send_json(409, {"error": "not your turn"})
            return

        rest_type = body.get("type")
        if rest_type not in ("short", "long"):
            self._send_json(400, {"error": "invalid type"})
            return

        sequence, hp_current, hp_max = db.create_play_campaign_rest(
            campaign_id, actor["username"], rest_type, campaign["owner"]
        )

        self._send_json(201, {
            "sequence": sequence,
            "kind": "rest",
            "actor": actor["username"],
            "type": rest_type,
            "hp_current": hp_current,
            "hp_max": hp_max,
            "next_actor": "dm",
        })

    def _handle_add_resolution(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return
        if not is_owner:
            self._send_json(409, {"error": "not your turn"})
            return

        text = body.get("text")
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        members = db.get_play_campaign_members_in_join_order(campaign_id)
        if campaign["turn_number"] < 2:
            next_actor = members[1] if len(members) > 1 else members[0]
        else:
            next_actor = members[0] if members else campaign["owner"]

        sequence, turn_number = db.create_play_campaign_resolution(
            campaign_id, text, next_actor
        )

        self._send_json(201, {
            "sequence": sequence,
            "kind": "resolution",
            "actor": "dm",
            "text": text,
            "next_actor": next_actor,
            "turn_number": turn_number,
        })

    def _handle_play_campaign_turn(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        if campaign["turn_phase"]:
            phase = campaign["turn_phase"]
        else:
            phase = "dm" if campaign["current_actor"] == campaign["owner"] else "player"

        members = db.get_play_campaign_members_in_join_order(campaign_id)
        queue = []
        if len(members) >= 2:
            queue = [members[0], campaign["owner"], members[1], campaign["owner"]]

        self._send_json(200, {
            "campaign_id": campaign_id,
            "current_actor": campaign["current_actor"],
            "phase": phase,
            "turn_number": campaign["turn_number"],
            "queue": queue,
            "overdue": False,
            "logical_deadline": campaign["turn_number"] + 1,
        })

    def _handle_play_campaign_turn_nudge(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        message = body.get("message")
        if not isinstance(message, str) or not message.strip():
            self._send_json(400, {"error": "message required"})
            return

        nudge_count = db.increment_play_campaign_nudge_count(campaign_id)

        self._send_json(201, {
            "actor": actor["username"],
            "target": campaign["current_actor"],
            "message": message,
            "nudge_count": nudge_count,
        })

    def _handle_play_campaign_my_turn(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return
        if actor["role"] != "player":
            self._send_json(403, {"error": "forbidden"})
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        recent_events = db.get_recent_play_campaign_narrations(campaign_id)

        self._send_json(200, {
            "campaign_id": campaign_id,
            "is_my_turn": campaign["current_actor"] == actor["username"],
            "current_actor": campaign["current_actor"],
            "character": {
                "id": member["character_id"],
                "name": member["name"],
            },
            "recent_events": recent_events,
        })

    def _handle_play_campaign_gm_status(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        members = db.get_play_campaign_members(campaign_id)
        party = [
            {
                "username": member["username"],
                "character_id": member["character_id"],
                "name": member["name"],
                "class": member["class"],
            }
            for member in members
        ]

        recent_events = db.get_recent_play_campaign_narrations(campaign_id)

        self._send_json(200, {
            "campaign_id": campaign_id,
            "needs_attention": campaign["current_actor"] == campaign["owner"],
            "current_actor": campaign["current_actor"],
            "party": party,
            "recent_events": recent_events,
        })

    def _handle_get_play_campaign_document(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] == campaign["owner"]:
            self._send_json(200, {
                "story": campaign["story"] or "",
                "dm_notes": campaign["dm_notes"] or "",
            })
            return

        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        self._send_json(200, {"story": campaign["story"] or ""})

    def _handle_put_play_campaign_document(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        story = body.get("story")
        dm_notes = body.get("dm_notes")
        if not isinstance(story, str):
            self._send_json(400, {"error": "invalid story"})
            return
        if not isinstance(dm_notes, str):
            self._send_json(400, {"error": "invalid dm_notes"})
            return

        db.update_play_campaign_document(campaign_id, story, dm_notes)

        self._send_json(200, {"story": story, "dm_notes": dm_notes})

    def _handle_get_play_campaign_session_zero(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] != campaign["owner"]:
            member = db.get_play_campaign_member(campaign_id, actor["username"])
            if member is None:
                self._send_json(403, {"error": "forbidden"})
                return

        settings = db.get_play_session_zero(campaign_id)
        if settings is None:
            self._send_json(404, {"error": "session-zero settings not found"})
            return

        self._send_json(200, settings)

    def _handle_put_play_campaign_session_zero(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        if campaign["status"] != "lobby":
            self._send_json(409, {"error": "campaign already started"})
            return

        rules = body.get("rules")
        tone = body.get("tone")
        consent = body.get("consent")

        if not isinstance(rules, str) or not rules:
            self._send_json(400, {"error": "invalid rules"})
            return
        if not isinstance(tone, str) or not tone:
            self._send_json(400, {"error": "invalid tone"})
            return
        if not isinstance(consent, list) or not consent:
            self._send_json(400, {"error": "invalid consent"})
            return
        for entry in consent:
            if not isinstance(entry, str) or not entry:
                self._send_json(400, {"error": "invalid consent"})
                return
        if len(set(consent)) != len(consent):
            self._send_json(400, {"error": "invalid consent"})
            return

        db.set_play_session_zero(campaign_id, rules, tone, consent)

        self._send_json(200, {"rules": rules, "tone": tone, "consent": consent})

    # -- play: content ------------------------------------------------------

    def _validate_content_tags(self, tags):
        if not isinstance(tags, list):
            return False
        for tag in tags:
            if not isinstance(tag, str) or not tag:
                return False
        if len(set(tags)) != len(tags):
            return False
        return True

    def _handle_create_play_campaign_content(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        content_id = body.get("content_id")
        kind = body.get("kind")
        text = body.get("text")
        tags = body.get("tags")

        if not isinstance(content_id, str) or not content_id:
            self._send_json(400, {"error": "invalid content_id"})
            return
        if not isinstance(kind, str) or not kind:
            self._send_json(400, {"error": "invalid kind"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        if not tags or not self._validate_content_tags(tags):
            self._send_json(400, {"error": "invalid tags"})
            return

        try:
            created = db.create_play_campaign_content(
                campaign_id, content_id, kind, text, tags
            )
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate content_id"})
            return
        if not created:
            self._send_json(409, {"error": "duplicate content_id"})
            return

        self._send_json(201, {
            "content_id": content_id,
            "kind": kind,
            "text": text,
            "tags": tags,
        })

    def _handle_put_play_campaign_content_tags(self, campaign_id, content_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        if db.get_play_campaign_content(campaign_id, content_id) is None:
            self._send_json(404, {"error": "content not found"})
            return

        tags = body.get("tags")
        if not self._validate_content_tags(tags):
            self._send_json(400, {"error": "invalid tags"})
            return

        updated = db.update_play_campaign_content_tags(campaign_id, content_id, tags)
        self._send_json(200, updated)

    def _handle_get_play_campaign_content(self, campaign_id, query):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        exclude_tag_values = query.get("exclude_tag")
        exclude_tag = None
        if exclude_tag_values is not None:
            exclude_tag = exclude_tag_values[0]
            if not isinstance(exclude_tag, str) or not exclude_tag:
                self._send_json(400, {"error": "invalid exclude_tag"})
                return

        content_list = db.get_play_campaign_content_list(campaign_id)
        if not is_owner and exclude_tag:
            content_list = [
                item for item in content_list if exclude_tag not in item["tags"]
            ]

        self._send_json(200, {"content": content_list})

    # -- play: notes ----------------------------------------------------------

    def _handle_create_play_campaign_note(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        note_id = body.get("note_id")
        text = body.get("text")
        visibility = body.get("visibility")

        if not isinstance(note_id, str) or not note_id:
            self._send_json(400, {"error": "invalid note_id"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        if visibility not in ("private", "party"):
            self._send_json(400, {"error": "invalid visibility"})
            return

        created = db.create_play_campaign_note(
            campaign_id, note_id, text, visibility, actor["username"]
        )
        if not created:
            self._send_json(409, {"error": "duplicate note_id"})
            return

        self._send_json(201, {
            "note_id": note_id,
            "text": text,
            "visibility": visibility,
            "owner": actor["username"],
        })

    def _handle_create_play_campaign_search_record(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        record_id = body.get("record_id")
        text = body.get("text")

        if not isinstance(record_id, str) or not record_id:
            self._send_json(400, {"error": "invalid record_id"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        created = db.create_play_campaign_search_record(campaign_id, record_id, text)
        if not created:
            self._send_json(400, {"error": "duplicate record_id"})
            return

        self._send_json(201, {"record_id": record_id, "text": text})

    def _handle_get_play_campaign_search_records(self, campaign_id, query):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        q_values = query.get("q")
        q = q_values[0] if q_values else None

        limit_values = query.get("limit")
        if limit_values:
            try:
                limit = int(limit_values[0])
            except ValueError:
                self._send_json(400, {"error": "invalid limit"})
                return
            if limit < 1 or limit > 3:
                self._send_json(400, {"error": "invalid limit"})
                return
        else:
            limit = 2

        cursor_values = query.get("cursor")
        if cursor_values:
            try:
                cursor = int(cursor_values[0])
            except ValueError:
                self._send_json(400, {"error": "invalid cursor"})
                return
            if cursor < 0:
                self._send_json(400, {"error": "invalid cursor"})
                return
        else:
            cursor = 0

        records = db.get_play_campaign_search_records(campaign_id)
        if q:
            q_lower = q.lower()
            records = [r for r in records if q_lower in r["text"].lower()]

        page = records[cursor:cursor + limit]
        next_offset = cursor + limit
        next_cursor = next_offset if next_offset < len(records) else None

        self._send_json(200, {"records": page, "next_cursor": next_cursor})

    def _handle_get_play_campaign_notes(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        notes = db.get_play_campaign_notes(campaign_id)
        if not is_dm:
            username = actor["username"]
            notes = [
                note for note in notes
                if note["visibility"] == "party" or note["owner"] == username
            ]

        self._send_json(200, {"notes": notes})

    def _handle_get_play_campaign_note(self, campaign_id, note_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        note = db.get_play_campaign_note(campaign_id, note_id)
        if note is None:
            self._send_json(404, {"error": "note not found"})
            return

        if not is_dm and note["visibility"] == "private" and note["owner"] != actor["username"]:
            self._send_json(403, {"error": "forbidden"})
            return

        self._send_json(200, note)

    def _handle_put_play_campaign_note(self, campaign_id, note_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        note = db.get_play_campaign_note(campaign_id, note_id)
        if note is None:
            self._send_json(404, {"error": "note not found"})
            return

        if note["owner"] != actor["username"]:
            self._send_json(403, {"error": "forbidden"})
            return

        text = body.get("text")
        visibility = body.get("visibility")
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        if visibility not in ("private", "party"):
            self._send_json(400, {"error": "invalid visibility"})
            return

        updated = db.update_play_campaign_note(campaign_id, note_id, text, visibility)
        self._send_json(200, updated)

    # -- play: whispers ---------------------------------------------------------

    def _handle_create_play_campaign_whisper(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if member is None or not member.get("character_id"):
            self._send_json(403, {"error": "forbidden"})
            return

        from_character_id = member["character_id"]

        whisper_id = body.get("whisper_id")
        to_character_id = body.get("to_character_id")
        text = body.get("text")

        if not isinstance(whisper_id, str) or not whisper_id:
            self._send_json(400, {"error": "invalid whisper_id"})
            return
        if not isinstance(to_character_id, str) or not to_character_id:
            self._send_json(400, {"error": "invalid to_character_id"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        recipient = db.get_play_campaign_member_by_character(campaign_id, to_character_id)
        if recipient is None:
            self._send_json(400, {"error": "invalid to_character_id"})
            return

        created = db.create_play_campaign_whisper(
            campaign_id, whisper_id, from_character_id, to_character_id, text
        )
        if not created:
            self._send_json(409, {"error": "duplicate whisper_id"})
            return

        self._send_json(201, {
            "whisper_id": whisper_id,
            "from_character_id": from_character_id,
            "to_character_id": to_character_id,
            "text": text,
        })

    def _handle_get_play_campaign_whispers(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_dm and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        whispers = db.get_play_campaign_whispers(campaign_id)
        if not is_dm:
            character_id = member.get("character_id") if member else None
            whispers = [
                w for w in whispers
                if w["from_character_id"] == character_id
                or w["to_character_id"] == character_id
            ]

        self._send_json(200, {"whispers": whispers})

    # -- play: rate events --------------------------------------------------

    def _handle_create_play_campaign_rate_event(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        event_id = body.get("event_id")
        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid event_id"})
            return

        result = db.create_play_campaign_rate_event(
            campaign_id, event_id, actor["username"], RATE_EVENT_LIMIT
        )
        if result["status"] == "duplicate":
            self._send_json(400, {"error": "duplicate event_id"})
            return
        if result["status"] == "limited":
            self._send_json(429, {"limit": RATE_EVENT_LIMIT, "remaining": 0})
            return

        self._send_json(
            201,
            {
                "event_id": event_id,
                "actor": actor["username"],
                "remaining": result["remaining"],
            },
        )

    def _handle_get_play_campaign_rate_events(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        events = db.get_play_campaign_rate_events(campaign_id)
        remaining = db.get_play_campaign_rate_event_remaining(
            campaign_id, actor["username"], RATE_EVENT_LIMIT
        )
        self._send_json(200, {"events": events, "remaining": remaining})

    # -- play: metrics --------------------------------------------------------

    def _handle_get_play_campaign_metrics(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] != campaign["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        metrics = db.get_play_campaign_metrics(campaign_id)
        self._send_json(200, metrics)

    # -- play: rng ledger -----------------------------------------------------

    def _handle_put_play_campaign_rng_seed(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        seed = body.get("seed")
        if not isinstance(seed, str) or not seed:
            self._send_json(400, {"error": "invalid seed"})
            return

        result = db.create_play_campaign_rng_seed(campaign_id, seed)
        if result is None:
            self._send_json(409, {"error": "seed already configured"})
            return

        self._send_json(200, {"seed": seed, "rolls": []})

    def _handle_create_play_campaign_rng_roll(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        roll_id = body.get("roll_id")
        if not isinstance(roll_id, str) or not roll_id:
            self._send_json(400, {"error": "invalid roll_id"})
            return

        sides = body.get("sides")
        if not isinstance(sides, int) or isinstance(sides, bool) or sides < 2 or sides > 100:
            self._send_json(400, {"error": "invalid sides"})
            return

        result = db.create_play_campaign_rng_roll(campaign_id, roll_id, sides)
        if result is None:
            self._send_json(409, {"error": "no seed configured"})
            return
        if result == "duplicate":
            self._send_json(409, {"error": "duplicate roll_id"})
            return

        self._send_json(201, result)

    def _handle_get_play_campaign_rng_ledger(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        ledger = db.get_play_campaign_rng_ledger(campaign_id)
        self._send_json(200, ledger)

    # -- play: moderation workflow --------------------------------------------

    def _handle_create_play_campaign_moderation_report(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        report_id = body.get("report_id")
        target_id = body.get("target_id")
        reason = body.get("reason")
        if not isinstance(report_id, str) or not report_id:
            self._send_json(400, {"error": "invalid report_id"})
            return
        if not isinstance(target_id, str) or not target_id:
            self._send_json(400, {"error": "invalid target_id"})
            return
        if not isinstance(reason, str) or not reason:
            self._send_json(400, {"error": "invalid reason"})
            return

        result = db.create_play_campaign_moderation_report(
            campaign_id, report_id, target_id, reason, actor["username"]
        )
        if result == "duplicate":
            self._send_json(409, {"error": "duplicate report_id"})
            return

        self._send_json(201, result)

    def _handle_get_play_campaign_moderation_reports(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        reports = db.get_play_campaign_moderation_reports(campaign_id)
        self._send_json(200, {"reports": reports})

    def _handle_put_play_campaign_moderation_resolution(self, campaign_id, report_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        action = body.get("action")
        note = body.get("note")
        if action not in ("allow", "remove"):
            self._send_json(400, {"error": "invalid action"})
            return
        if not isinstance(note, str) or not note:
            self._send_json(400, {"error": "invalid note"})
            return

        result = db.resolve_play_campaign_moderation_report(
            campaign_id, report_id, action, note, actor["username"]
        )
        if result is None:
            self._send_json(404, {"error": "report not found"})
            return
        if result == "resolved":
            self._send_json(409, {"error": "report already resolved"})
            return

        self._send_json(200, result)

    # -- play: safety boundaries ----------------------------------------------

    def _handle_put_play_campaign_safety_boundaries(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid request"})
            return

        blocked_tags = body.get("blocked_tags")
        if (
            not isinstance(blocked_tags, list)
            or not blocked_tags
            or not all(isinstance(tag, str) and tag for tag in blocked_tags)
            or len(set(blocked_tags)) != len(blocked_tags)
        ):
            self._send_json(400, {"error": "invalid blocked_tags"})
            return

        sorted_tags = db.replace_play_campaign_safety_boundaries(campaign_id, blocked_tags)
        self._send_json(200, {"blocked_tags": sorted_tags})

    def _handle_get_play_campaign_safety_boundaries(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        blocked_tags = db.get_play_campaign_safety_boundaries(campaign_id)
        self._send_json(200, {"blocked_tags": blocked_tags})

    def _handle_create_play_campaign_safety_check(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid request"})
            return

        event_id = body.get("event_id")
        kind = body.get("kind")
        text = body.get("text")
        tags = body.get("tags")

        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid event_id"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        if kind not in ("narration", "chat"):
            self._send_json(400, {"error": "invalid kind"})
            return
        if (
            not isinstance(tags, list)
            or not tags
            or not all(isinstance(tag, str) and tag for tag in tags)
            or len(set(tags)) != len(tags)
        ):
            self._send_json(400, {"error": "invalid tags"})
            return

        result = db.create_play_campaign_safety_check(campaign_id, event_id, kind, text, tags)
        if result == "duplicate":
            self._send_json(409, {"error": "duplicate event_id"})
            return
        if result == "blocked":
            self._send_json(409, {"error": "blocked tag"})
            return

        self._send_json(201, result)

    def _handle_get_play_campaign_safety_events(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        events = db.get_play_campaign_safety_events(campaign_id)
        self._send_json(200, {"events": events})

    # -- play: fixture seeding ---------------------------------------------

    def _handle_create_play_campaign_fixture_seed(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid request"})
            return

        fixture_id = body.get("fixture_id")
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id != "canonical-v1":
            self._send_json(400, {"error": "invalid fixture_id"})
            return

        existed = db.get_play_campaign_fixture_state(campaign_id) is not None
        state = db.seed_play_campaign_fixture(campaign_id, fixture_id)
        self._send_json(200 if existed else 201, state)

    def _handle_get_play_campaign_fixture_state(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        state = db.get_play_campaign_fixture_state(campaign_id)
        if state is None:
            self._send_json(404, {"error": "fixture not seeded"})
            return

        self._send_json(200, state)

    # -- play: service mode -------------------------------------------------

    def _handle_post_play_campaign_service_mode(self, campaign_id, body):
        global _MAINTENANCE_MODE

        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] != campaign["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        if not isinstance(body, dict) or not isinstance(body.get("maintenance"), bool):
            self._send_json(400, {"error": "invalid request"})
            return

        _MAINTENANCE_MODE = body["maintenance"]
        self._send_json(200, {"maintenance": _MAINTENANCE_MODE})

    # -- play: character sheet ---------------------------------------------------

    def _handle_get_play_campaign_character_sheet(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_dm = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_dm and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        sheet = db.get_play_campaign_character_sheet(campaign_id, character_id)
        if sheet is None:
            self._send_json(404, {"error": "character not found"})
            return

        if not is_dm and sheet["owner"] != actor["username"]:
            self._send_json(403, {"error": "forbidden"})
            return

        self._send_json(200, {
            "character_id": character_id,
            "owner": sheet["owner"],
            "name": sheet["name"],
            "class": sheet["class"],
            "level": 1,
            "proficiency_bonus": 2,
            "hp_max": 10,
            "armor_class": 10,
        })

    # -- play: scenes -----------------------------------------------------

    def _handle_create_play_campaign_scene(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        scene_id = body.get("id")
        name = body.get("name")
        if not isinstance(scene_id, str) or not scene_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return

        if db.get_play_scene(campaign_id, scene_id) is not None:
            self._send_json(409, {"error": "duplicate scene id"})
            return

        scene = {"id": scene_id, "name": name, "status": "open"}
        try:
            db.create_play_scene(campaign_id, scene)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate scene id"})
            return

        self._send_json(201, scene)

    def _handle_create_play_campaign_encounter(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter_id = body.get("id")
        name = body.get("name")
        if not isinstance(encounter_id, str) or not encounter_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return

        if db.get_play_encounter(campaign_id, encounter_id) is not None:
            self._send_json(409, {"error": "duplicate encounter id"})
            return

        if db.get_active_play_encounter(campaign_id) is not None:
            self._send_json(409, {"error": "campaign already in combat"})
            return

        encounter = {
            "id": encounter_id,
            "name": name,
            "status": "active",
            "combatants": [],
        }
        try:
            db.create_play_encounter(campaign_id, encounter)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate encounter id"})
            return

        self._send_json(201, encounter)

    def _handle_award_play_campaign_encounter_rewards(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        if encounter["rewards"] is not None:
            self._send_json(409, {"error": "rewards already awarded"})
            return

        xp = body.get("xp")
        loot = body.get("loot", [])
        if not isinstance(xp, int) or isinstance(xp, bool) or xp < 0:
            self._send_json(400, {"error": "invalid xp"})
            return
        if not isinstance(loot, list):
            self._send_json(400, {"error": "invalid loot"})
            return
        for entry in loot:
            if not isinstance(entry, dict):
                self._send_json(400, {"error": "invalid loot entry"})
                return
            slug = entry.get("slug")
            quantity = entry.get("quantity")
            if not isinstance(slug, str) or not slug:
                self._send_json(400, {"error": "invalid loot slug"})
                return
            if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity <= 0:
                self._send_json(400, {"error": "invalid loot quantity"})
                return

        rewards = {"xp": xp, "loot": loot}
        db.award_play_encounter_rewards(campaign_id, encounter_id, rewards)

        self._send_json(200, {"encounter_id": encounter_id, "xp": xp, "loot": loot})

    def _handle_close_play_campaign_encounter(self, campaign_id, encounter_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        db.close_play_encounter(campaign_id, encounter_id)

        self._send_json(200, {
            "id": encounter_id,
            "status": "closed",
            "xp_awarded": encounter["xp_awarded"],
        })

    def _handle_end_play_campaign_encounter(self, campaign_id, encounter_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        if campaign["pre_combat_actor"] is None:
            self._send_json(409, {"error": "campaign not in combat"})
            return

        restored_actor = db.end_play_encounter(campaign_id, encounter_id)
        current_actor = restored_actor if restored_actor is not None else campaign["current_actor"]

        self._send_json(200, {
            "campaign_id": campaign_id,
            "status": campaign["status"],
            "phase": "exploration",
            "current_actor": current_actor,
        })

    def _handle_add_play_campaign_encounter_monster(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        monster_id = body.get("monster_id")
        name = body.get("name")
        hp_max = body.get("hp_max")
        initiative = body.get("initiative")
        if not isinstance(monster_id, str) or not monster_id:
            self._send_json(400, {"error": "invalid monster_id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(hp_max, int) or isinstance(hp_max, bool) or hp_max <= 0:
            self._send_json(400, {"error": "invalid hp_max"})
            return
        if not isinstance(initiative, int) or isinstance(initiative, bool):
            self._send_json(400, {"error": "invalid initiative"})
            return

        combatants = encounter["combatants"]
        if any(c.get("monster_id") == monster_id for c in combatants):
            self._send_json(409, {"error": "duplicate monster id"})
            return

        monster = {
            "monster_id": monster_id,
            "name": name,
            "hp_max": hp_max,
            "initiative": initiative,
            "hp_current": hp_max,
        }
        combatants.append(monster)
        db.update_play_encounter_combatants(campaign_id, encounter_id, combatants)

        self._send_json(201, monster)

    def _handle_remove_play_campaign_encounter_monster(
        self, campaign_id, encounter_id, monster_id
    ):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        remaining = [c for c in combatants if c.get("monster_id") != monster_id]
        if len(remaining) == len(combatants):
            self._send_json(404, {"error": "monster not found"})
            return

        db.update_play_encounter_combatants(campaign_id, encounter_id, remaining)

        self._send_json(200, {"removed": monster_id})

    def _handle_add_play_campaign_encounter_combatant(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        member_username = body.get("member")
        initiative = body.get("initiative")
        if not isinstance(member_username, str) or not member_username:
            self._send_json(400, {"error": "invalid member"})
            return
        if not isinstance(initiative, int) or isinstance(initiative, bool):
            self._send_json(400, {"error": "invalid initiative"})
            return

        member = db.get_play_campaign_member(campaign_id, member_username)
        if member is None:
            self._send_json(400, {"error": "member not found"})
            return

        combatants = encounter["combatants"]
        if any(c.get("member") == member_username for c in combatants):
            self._send_json(409, {"error": "duplicate member"})
            return

        combatant = {
            "member": member_username,
            "character_id": member["character_id"],
            "name": member["name"],
            "initiative": initiative,
        }
        combatants.append(combatant)
        db.update_play_encounter_combatants(campaign_id, encounter_id, combatants)

        self._send_json(201, combatant)

    def _handle_remove_play_campaign_encounter_combatant(
        self, campaign_id, encounter_id, member_username
    ):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        remaining = [c for c in combatants if c.get("member") != member_username]
        if len(remaining) == len(combatants):
            self._send_json(404, {"error": "member not found"})
            return

        db.update_play_encounter_combatants(campaign_id, encounter_id, remaining)

        self._send_json(200, {"removed": member_username})

    @staticmethod
    def _encounter_initiative_order(combatants):
        return sorted(
            range(len(combatants)),
            key=lambda i: -combatants[i]["initiative"],
        )

    @staticmethod
    def _encounter_active_combatant(combatants, turn_index):
        order = Handler._encounter_initiative_order(combatants)
        position = order[turn_index]
        combatant = combatants[position]
        kind = "monster" if "monster_id" in combatant else "player"
        return {
            "name": combatant["name"],
            "kind": kind,
            "initiative": combatant["initiative"],
        }, combatant

    @staticmethod
    def _encounter_target_key(combatant):
        return combatant.get("monster_id") or combatant.get("member")

    def _handle_get_play_campaign_encounter_turn(self, campaign_id, encounter_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        if not combatants:
            self._send_json(404, {"error": "no combatants"})
            return

        active, _ = self._encounter_active_combatant(combatants, encounter["turn_index"])
        self._send_json(200, {
            "round": encounter["round"],
            "turn_index": encounter["turn_index"],
            "active": active,
        })

    def _handle_advance_play_campaign_encounter_turn(self, campaign_id, encounter_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        if not combatants:
            self._send_json(404, {"error": "no combatants"})
            return

        turn_index = encounter["turn_index"]
        _, current_combatant = self._encounter_active_combatant(combatants, turn_index)
        is_current_combatant = current_combatant.get("member") == actor["username"]
        if not is_owner and not is_current_combatant:
            self._send_json(409, {"error": "not your turn"})
            return

        round_number = encounter["round"]
        next_index = turn_index + 1
        if next_index >= len(combatants):
            next_index = 0
            round_number += 1

        active, next_combatant = self._encounter_active_combatant(combatants, next_index)
        target_key = self._encounter_target_key(next_combatant)

        conditions = encounter["conditions"]
        target_conditions = conditions.get(target_key, [])
        remaining = []
        for entry in target_conditions:
            entry["remaining_rounds"] -= 1
            if entry["remaining_rounds"] > 0:
                remaining.append(entry)
        if remaining:
            conditions[target_key] = remaining
        elif target_key in conditions:
            del conditions[target_key]

        db.update_play_encounter_turn_and_conditions(
            campaign_id, encounter_id, round_number, next_index, conditions
        )

        self._send_json(200, {
            "round": round_number,
            "turn_index": next_index,
            "active": active,
        })

    def _handle_delay_play_campaign_encounter_turn(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        if not combatants:
            self._send_json(404, {"error": "no combatants"})
            return

        turn_index = encounter["turn_index"]
        order = self._encounter_initiative_order(combatants)
        _, current_combatant = self._encounter_active_combatant(combatants, turn_index)
        is_current_combatant = current_combatant.get("member") == actor["username"]
        if not is_owner and not is_current_combatant:
            self._send_json(409, {"error": "not your turn"})
            return

        to_index = body.get("new_index")
        if not rules.is_plain_int(to_index) or isinstance(to_index, bool):
            self._send_json(400, {"error": "invalid index"})
            return
        if to_index <= turn_index or to_index >= len(combatants):
            self._send_json(400, {"error": "illegal index"})
            return

        actor_position = order[turn_index]
        new_order = order[:turn_index] + order[turn_index + 1:]
        new_order.insert(to_index, actor_position)

        base = 10000
        for position, combatant_index in enumerate(new_order):
            combatants[combatant_index]["initiative"] = base - position

        db.update_play_encounter_combatants(campaign_id, encounter_id, combatants)
        db.update_play_encounter_turn(campaign_id, encounter_id, encounter["round"], to_index)

        response_order = [
            {
                "name": combatants[combatant_index]["name"],
                "initiative": combatants[combatant_index]["initiative"],
            }
            for combatant_index in new_order
        ]

        self._send_json(200, {
            "round": encounter["round"],
            "turn_index": to_index,
            "order": response_order,
        })

    def _handle_ready_play_campaign_encounter_turn(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        if not combatants:
            self._send_json(404, {"error": "no combatants"})
            return

        turn_index = encounter["turn_index"]
        _, current_combatant = self._encounter_active_combatant(combatants, turn_index)
        if current_combatant.get("member") != actor["username"]:
            self._send_json(409, {"error": "not your turn"})
            return

        trigger = body.get("trigger")
        if not isinstance(trigger, str) or not trigger:
            self._send_json(400, {"error": "invalid trigger"})
            return

        db.create_play_campaign_encounter_action(
            campaign_id, actor["username"], "ready", None, trigger
        )

        self._send_json(201, {
            "actor": actor["username"],
            "trigger": trigger,
        })

    def _handle_add_play_campaign_encounter_action(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        if not combatants:
            self._send_json(404, {"error": "no combatants"})
            return

        turn_index = encounter["turn_index"]
        _, current_combatant = self._encounter_active_combatant(combatants, turn_index)
        if current_combatant.get("member") != actor["username"]:
            self._send_json(409, {"error": "not your turn"})
            return

        action_type = body.get("type")
        if action_type not in ("attack", "help", "dodge", "ready"):
            self._send_json(400, {"error": "invalid type"})
            return

        target = body.get("target")
        if target is not None and not isinstance(target, str):
            self._send_json(400, {"error": "invalid target"})
            return

        text = body.get("text")
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        sequence = db.create_play_campaign_encounter_action(
            campaign_id, actor["username"], action_type, target, text
        )

        self._send_json(201, {
            "sequence": sequence,
            "kind": "combat_action",
            "actor": actor["username"],
            "type": action_type,
            "target": target,
            "text": text,
        })

    def _apply_play_campaign_encounter_hp_delta(
        self, campaign_id, encounter_id, target, delta
    ):
        """Locate target among encounter combatants and apply a clamped HP
        delta. Returns (hp_before, hp_after) or None if target not found.
        """
        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            return None

        combatants = encounter["combatants"]
        for combatant in combatants:
            if combatant.get("monster_id") == target:
                hp_before = combatant["hp_current"]
                hp_max = combatant["hp_max"]
                hp_after = max(0, min(hp_max, hp_before + delta))
                combatant["hp_current"] = hp_after
                db.update_play_encounter_combatants(campaign_id, encounter_id, combatants)
                return hp_before, hp_after

        for combatant in combatants:
            if combatant.get("member") == target:
                hp = db.get_play_campaign_member_hp(campaign_id, target)
                if hp is None:
                    return None
                hp_before, hp_max = hp
                hp_after = max(0, min(hp_max, hp_before + delta))
                db.set_play_campaign_member_hp(campaign_id, target, hp_after)
                return hp_before, hp_after

        return None

    def _handle_damage_play_campaign_encounter(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        target = body.get("target")
        amount = body.get("amount")
        if not isinstance(target, str) or not target:
            self._send_json(400, {"error": "invalid target"})
            return
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            self._send_json(400, {"error": "invalid amount"})
            return

        if db.get_play_encounter(campaign_id, encounter_id) is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        result = self._apply_play_campaign_encounter_hp_delta(
            campaign_id, encounter_id, target, -amount
        )
        if result is None:
            self._send_json(404, {"error": "target not found"})
            return

        hp_before, hp_after = result
        self._send_json(200, {
            "target": target,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "damage": amount,
        })

    def _handle_heal_play_campaign_encounter(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        target = body.get("target")
        amount = body.get("amount")
        if not isinstance(target, str) or not target:
            self._send_json(400, {"error": "invalid target"})
            return
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            self._send_json(400, {"error": "invalid amount"})
            return

        if db.get_play_encounter(campaign_id, encounter_id) is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        result = self._apply_play_campaign_encounter_hp_delta(
            campaign_id, encounter_id, target, amount
        )
        if result is None:
            self._send_json(404, {"error": "target not found"})
            return

        hp_before, hp_after = result
        self._send_json(200, {
            "target": target,
            "hp_before": hp_before,
            "hp_after": hp_after,
            "healing": amount,
        })

    def _handle_add_play_campaign_encounter_condition(self, campaign_id, encounter_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        target = body.get("target")
        condition = body.get("condition")
        duration_rounds = body.get("duration_rounds")
        if not isinstance(target, str) or not target:
            self._send_json(400, {"error": "invalid target"})
            return
        if not isinstance(condition, str) or not condition:
            self._send_json(400, {"error": "invalid condition"})
            return
        if (
            not isinstance(duration_rounds, int)
            or isinstance(duration_rounds, bool)
            or duration_rounds <= 0
        ):
            self._send_json(400, {"error": "invalid duration_rounds"})
            return

        combatants = encounter["combatants"]
        target_exists = any(
            self._encounter_target_key(c) == target for c in combatants
        )
        if not target_exists:
            self._send_json(404, {"error": "target not found"})
            return

        conditions = encounter["conditions"]
        target_conditions = conditions.get(target, [])
        target_conditions = [
            entry for entry in target_conditions if entry["condition"] != condition
        ]
        target_conditions.append(
            {"condition": condition, "remaining_rounds": duration_rounds}
        )
        conditions[target] = target_conditions
        db.update_play_encounter_conditions(campaign_id, encounter_id, conditions)

        self._send_json(201, {"target": target, "conditions": target_conditions})

    def _handle_get_play_campaign_encounter_status(self, campaign_id, encounter_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        encounter = db.get_play_encounter(campaign_id, encounter_id)
        if encounter is None:
            self._send_json(404, {"error": "encounter not found"})
            return

        combatants = encounter["combatants"]
        order = []
        active = None
        if combatants:
            order_positions = self._encounter_initiative_order(combatants)
            order = [
                {
                    "name": combatants[i]["name"],
                    "initiative": combatants[i]["initiative"],
                }
                for i in order_positions
            ]
            active, _ = self._encounter_active_combatant(combatants, encounter["turn_index"])

        self._send_json(200, {
            "round": encounter["round"],
            "turn_index": encounter["turn_index"],
            "active": active,
            "order": order,
            "conditions": encounter["conditions"],
        })

    def _handle_damage_play_campaign_character(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        amount = body.get("amount")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            self._send_json(400, {"error": "invalid amount"})
            return

        member = db.get_play_campaign_member_by_character(campaign_id, character_id)
        if member is None:
            self._send_json(404, {"error": "character not found"})
            return

        result = db.apply_play_campaign_character_damage(
            campaign_id, character_id, amount
        )

        self._send_json(200, {
            "character_id": character_id,
            "target": character_id,
            "hp_before": result["hp_before"],
            "hp_after": result["hp_after"],
            "hp_max": result["hp_max"],
            "status": result["status"],
            "damage": amount,
        })

    def _handle_play_campaign_character_death_save(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        member = db.get_play_campaign_member_by_character(campaign_id, character_id)
        if member is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != member["username"]:
            self._send_json(403, {"error": "forbidden"})
            return

        outcome = body.get("outcome")
        if outcome not in ("success", "failure"):
            self._send_json(400, {"error": "invalid outcome"})
            return

        result = db.record_play_campaign_death_save(campaign_id, character_id, outcome)
        if result.get("error") == "not_unconscious":
            self._send_json(409, {"error": "character is not unconscious"})
            return

        self._send_json(201, {
            "character_id": character_id,
            "successes": result["successes"],
            "failures": result["failures"],
            "status": result["status"],
        })

    def _handle_get_play_campaign_character_status(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        status = db.get_play_campaign_character_status(campaign_id, character_id)
        if status is None:
            self._send_json(404, {"error": "character not found"})
            return

        self._send_json(200, {
            "character_id": character_id,
            "hp_current": status["hp_current"],
            "hp_max": status["hp_max"],
            "status": status["status"],
        })

    def _handle_get_play_campaign_character_owner(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        self._send_json(200, {
            "character_id": character_id,
            "owner": owner_info["owner"],
        })

    def _handle_claim_play_campaign_character(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if db.get_play_campaign_member(campaign_id, actor["username"]) is None:
            self._send_json(403, {"error": "forbidden"})
            return

        result = db.claim_play_campaign_character(
            campaign_id, character_id, actor["username"]
        )
        if result.get("error") == "not_found":
            self._send_json(404, {"error": "character not found"})
            return
        if result.get("error") == "conflict":
            self._send_json(409, {"error": "character already owned"})
            return

        self._send_json(201, {
            "character_id": character_id,
            "owner": result["owner"],
        })

    def _handle_transfer_play_campaign_character(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        new_owner = body.get("new_owner")
        if not isinstance(new_owner, str) or not new_owner:
            self._send_json(400, {"error": "invalid new_owner"})
            return

        if db.get_play_campaign_member(campaign_id, new_owner) is None:
            self._send_json(400, {"error": "new_owner not a campaign member"})
            return

        db.transfer_play_campaign_character(campaign_id, character_id, new_owner)

        self._send_json(200, {
            "character_id": character_id,
            "owner": new_owner,
        })

    def _handle_build_play_campaign_character(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        race = body.get("race")
        klass = body.get("class")
        background = body.get("background")
        abilities = body.get("abilities")

        if not isinstance(race, str) or race not in rules.VALID_RACES:
            self._send_json(400, {"error": "invalid race"})
            return
        if not isinstance(klass, str) or klass not in rules.CLASS_HIT_DIE:
            self._send_json(400, {"error": "invalid class"})
            return
        if not isinstance(background, str) or background not in rules.VALID_BACKGROUNDS:
            self._send_json(400, {"error": "invalid background"})
            return
        if not isinstance(abilities, dict):
            self._send_json(400, {"error": "invalid abilities"})
            return

        required = ("str", "dex", "con", "int", "wis", "cha")
        for key in required:
            score = abilities.get(key)
            if not rules.is_plain_int(score) or not (1 <= score <= 30):
                self._send_json(400, {"error": "invalid abilities"})
                return

        con_modifier = rules.ability_modifier(abilities["con"])
        str_modifier = rules.ability_modifier(abilities["str"])
        dex_modifier = rules.ability_modifier(abilities["dex"])
        int_modifier = rules.ability_modifier(abilities["int"])
        wis_modifier = rules.ability_modifier(abilities["wis"])
        cha_modifier = rules.ability_modifier(abilities["cha"])
        level = 1
        hp_max = rules.level_one_hp_max(klass, con_modifier)
        proficiency = rules.proficiency_bonus(level)

        db.build_play_campaign_character(
            campaign_id, character_id, race, klass, background, level, hp_max,
            con_modifier, str_modifier, dex_modifier, int_modifier, wis_modifier,
            cha_modifier,
        )

        self._send_json(200, {
            "character_id": character_id,
            "race": race,
            "class": klass,
            "background": background,
            "level": level,
            "hp_max": hp_max,
            "proficiency_bonus": proficiency,
        })

    def _handle_level_up_play_campaign_character(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        character = db.get_play_campaign_character_for_level_up(campaign_id, character_id)
        if character is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != character["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        new_level = body.get("level")
        if not rules.is_plain_int(new_level):
            self._send_json(400, {"error": "invalid level"})
            return
        if new_level != character["level"] + 1:
            self._send_json(400, {"error": "level must be exactly one higher"})
            return

        gain = rules.hp_gain_per_level(character["class"], character["con_modifier"])
        hp_max = character["hp_max"] + gain
        hp_current = min(character["hp_current"] + gain, hp_max)
        proficiency = rules.proficiency_bonus(new_level)
        hit_die = rules.CLASS_HIT_DIE[character["class"]]

        db.level_up_play_campaign_character(
            campaign_id, character_id, new_level, hp_max, hp_current
        )

        self._send_json(200, {
            "character_id": character_id,
            "level": new_level,
            "hp_max": hp_max,
            "hit_dice": "1d%d" % hit_die,
            "proficiency_bonus": proficiency,
        })

    def _handle_skill_check_play_campaign_character(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        character = db.get_play_campaign_character_for_skill_check(campaign_id, character_id)
        if character is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != character["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        skill = body.get("skill")
        ability = body.get("ability")
        proficient = body.get("proficient")
        roll = body.get("roll")

        if not isinstance(skill, str) or skill not in rules.SKILL_ABILITY:
            self._send_json(400, {"error": "unsupported skill"})
            return
        valid_abilities = ("str", "dex", "con", "int", "wis", "cha")
        if not isinstance(ability, str) or ability not in valid_abilities:
            self._send_json(400, {"error": "unsupported ability"})
            return
        if ability != rules.SKILL_ABILITY[skill]:
            self._send_json(400, {"error": "ability does not match skill"})
            return
        if not isinstance(proficient, bool):
            self._send_json(400, {"error": "invalid proficient"})
            return
        if not rules.is_plain_int(roll):
            self._send_json(400, {"error": "invalid roll"})
            return

        proficiency = rules.proficiency_bonus(character["level"]) or 0
        modifier = character[ability] + (proficiency if proficient else 0)
        total = roll + modifier

        self._send_json(200, {
            "character_id": character_id,
            "skill": skill,
            "ability": ability,
            "modifier": modifier,
            "total": total,
        })

    def _handle_add_play_campaign_character_spell(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        spell_id = body.get("spell_id")
        name = body.get("name")
        level = body.get("level")

        if not isinstance(spell_id, str) or not spell_id:
            self._send_json(400, {"error": "invalid spell_id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not rules.is_plain_int(level):
            self._send_json(400, {"error": "invalid level"})
            return

        member = db.get_play_campaign_member_by_character(campaign_id, character_id)
        char_class = member["class"] if member else None
        class_spells = rules.CLASS_SPELL_LIST.get(char_class, {})
        known_spell = class_spells.get(spell_id)
        if known_spell is None or known_spell[0] != name or known_spell[1] != level:
            self._send_json(400, {"error": "invalid class/spell combination"})
            return

        try:
            db.create_play_campaign_character_spell(campaign_id, character_id, spell_id, name, level)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "spell already known"})
            return

        self._send_json(201, {"spell_id": spell_id, "name": name, "level": level})

    def _handle_get_play_campaign_character_spells(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        spells = db.list_play_campaign_character_spells(campaign_id, character_id)
        self._send_json(200, {"spells": spells})

    def _handle_put_play_campaign_character_prepared_spells(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        info = db.get_play_campaign_character_for_prepared_spells(campaign_id, character_id)
        if info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        char_class = info["class"]
        if char_class not in rules.CLASS_SPELL_LIST:
            self._send_json(400, {"error": "not a spellcasting class"})
            return

        spell_ids = body.get("spell_ids")
        if not isinstance(spell_ids, list) or not all(isinstance(s, str) and s for s in spell_ids):
            self._send_json(400, {"error": "invalid spell_ids"})
            return

        max_prepared = rules.max_prepared_spells(char_class, info["level"])

        known_spell_ids = {
            spell["spell_id"]
            for spell in db.list_play_campaign_character_spells(campaign_id, character_id)
        }
        for spell_id in spell_ids:
            if spell_id not in known_spell_ids:
                self._send_json(400, {"error": "unknown spell"})
                return

        if len(spell_ids) > max_prepared:
            self._send_json(400, {"error": "exceeds max prepared spells"})
            return

        db.set_play_campaign_character_prepared_spells(campaign_id, character_id, spell_ids)

        self._send_json(200, {
            "character_id": character_id,
            "prepared_spells": spell_ids,
            "max_prepared": max_prepared,
        })

    def _handle_get_play_campaign_character_prepared_spells(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        info = db.get_play_campaign_character_for_prepared_spells(campaign_id, character_id)
        if info is None:
            self._send_json(404, {"error": "character not found"})
            return

        max_prepared = rules.max_prepared_spells(info["class"], info["level"])
        prepared_spells = db.list_play_campaign_character_prepared_spells(campaign_id, character_id)

        self._send_json(200, {
            "character_id": character_id,
            "prepared_spells": prepared_spells,
            "max_prepared": max_prepared,
        })

    def _handle_post_play_campaign_character_cast(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        info = db.get_play_campaign_character_for_cast(campaign_id, character_id)
        if info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        spell_id = body.get("spell_id")
        target = body.get("target")
        if not isinstance(spell_id, str) or not spell_id:
            self._send_json(400, {"error": "invalid spell_id"})
            return
        if not isinstance(target, str) or not target:
            self._send_json(400, {"error": "invalid target"})
            return

        char_class = info["class"]
        class_spells = rules.CLASS_SPELL_LIST.get(char_class)
        if not class_spells:
            self._send_json(400, {"error": "not a spellcasting class"})
            return

        prepared_spell_ids = set(
            db.list_play_campaign_character_prepared_spells(campaign_id, character_id)
        )
        spell_info = class_spells.get(spell_id)
        if spell_info is None or spell_id not in prepared_spell_ids:
            self._send_json(400, {"error": "spell not prepared"})
            return

        slot_level = spell_info[1]
        max_slots = rules.casting_spell_slots(char_class, info["level"], slot_level)

        result = db.attempt_play_campaign_character_cast(
            campaign_id, character_id, spell_id, target, slot_level, max_slots
        )
        if result is None:
            self._send_json(409, {"error": "no remaining spell slots"})
            return

        sequence, slots_remaining = result

        self._send_json(201, {
            "character_id": character_id,
            "spell_id": spell_id,
            "target": target,
            "slot_level": slot_level,
            "slots_remaining": slots_remaining,
            "sequence": sequence,
        })

    def _handle_get_play_campaign_character_casts(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        casts = db.list_play_campaign_character_casts(campaign_id, character_id)
        self._send_json(200, {"casts": casts})

    def _handle_put_play_campaign_character_concentration(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        info = db.get_play_campaign_character_for_concentration(campaign_id, character_id)
        if info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        spell_id = body.get("spell_id")
        target = body.get("target")
        duration_turns = body.get("duration_turns")
        if not isinstance(spell_id, str) or not spell_id:
            self._send_json(400, {"error": "invalid spell_id"})
            return
        if not isinstance(target, str) or not target:
            self._send_json(400, {"error": "invalid target"})
            return
        if not rules.is_plain_int(duration_turns) or duration_turns < 1:
            self._send_json(400, {"error": "invalid duration_turns"})
            return

        char_class = info["class"]
        if char_class not in rules.CLASS_SPELL_LIST:
            self._send_json(400, {"error": "not a spellcasting class"})
            return

        known_spell_ids = {
            spell["spell_id"]
            for spell in db.list_play_campaign_character_spells(campaign_id, character_id)
        }
        if spell_id not in known_spell_ids:
            self._send_json(400, {"error": "spell not known"})
            return

        prepared_spell_ids = set(
            db.list_play_campaign_character_prepared_spells(campaign_id, character_id)
        )
        if spell_id not in prepared_spell_ids:
            self._send_json(400, {"error": "spell not prepared"})
            return

        db.set_play_campaign_character_concentration(
            campaign_id, character_id, spell_id, target, duration_turns
        )

        self._send_json(200, {
            "character_id": character_id,
            "concentration": {
                "spell_id": spell_id,
                "target": target,
                "remaining_turns": duration_turns,
            },
        })

    def _handle_get_play_campaign_character_concentration(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        concentration = db.get_play_campaign_character_concentration(campaign_id, character_id)
        self._send_json(200, {"character_id": character_id, "concentration": concentration})

    def _handle_advance_play_campaign_character_concentration(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        concentration = db.advance_play_campaign_character_concentration(campaign_id, character_id)
        self._send_json(200, {"character_id": character_id, "concentration": concentration})

    def _handle_delete_play_campaign_character_concentration(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        info = db.get_play_campaign_character_for_concentration(campaign_id, character_id)
        if info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        db.clear_play_campaign_character_concentration(campaign_id, character_id)
        self._send_json(200, {"character_id": character_id, "concentration": None})

    def _handle_add_play_campaign_character_inventory_item(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        item_id = body.get("item_id")
        quantity = body.get("quantity")
        if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
            self._send_json(400, {"error": "invalid item_id"})
            return
        if not rules.is_plain_int(quantity) or quantity < 1:
            self._send_json(400, {"error": "invalid quantity"})
            return

        total_quantity = db.add_play_campaign_character_inventory_item(
            campaign_id, character_id, item_id, quantity
        )

        self._send_json(201, {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": total_quantity,
        })

    def _handle_get_play_campaign_character_inventory_items(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        items = db.list_play_campaign_character_inventory_items(campaign_id, character_id)
        self._send_json(200, {"character_id": character_id, "items": items})

    def _handle_delete_play_campaign_character_inventory_item(
        self, campaign_id, character_id, item_id, body
    ):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        quantity = body.get("quantity")
        if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
            self._send_json(400, {"error": "invalid item_id"})
            return
        if not rules.is_plain_int(quantity) or quantity < 1:
            self._send_json(400, {"error": "invalid quantity"})
            return

        total_quantity = db.remove_play_campaign_character_inventory_item(
            campaign_id, character_id, item_id, quantity
        )
        if total_quantity is None:
            self._send_json(409, {"error": "insufficient quantity"})
            return

        self._send_json(200, {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "total_quantity": total_quantity,
        })

    def _handle_put_play_campaign_character_equipment(self, campaign_id, character_id, slot, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        if slot not in rules.VALID_EQUIPMENT_SLOTS:
            self._send_json(400, {"error": "invalid slot"})
            return

        item_id = body.get("item_id")
        if item_id not in rules.ITEM_EQUIPMENT_SLOT:
            self._send_json(400, {"error": "invalid item_id"})
            return

        if rules.ITEM_EQUIPMENT_SLOT[item_id] != slot:
            self._send_json(400, {"error": "item does not fit slot"})
            return

        held = db.get_play_campaign_character_inventory_item_quantity(
            campaign_id, character_id, item_id
        )
        if held < 1:
            self._send_json(400, {"error": "item not held"})
            return

        db.set_play_campaign_character_equipment_slot(campaign_id, character_id, slot, item_id)

        self._send_json(200, {
            "character_id": character_id,
            "slot": slot,
            "item_id": item_id,
            "attuned": False,
        })

    def _handle_get_play_campaign_character_equipment(self, campaign_id, character_id, slot):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if slot not in rules.VALID_EQUIPMENT_SLOTS:
            self._send_json(400, {"error": "invalid slot"})
            return

        equipped = db.get_play_campaign_character_equipment_slot(campaign_id, character_id, slot)
        if equipped is None:
            self._send_json(200, {
                "character_id": character_id,
                "slot": slot,
                "item_id": "",
                "attuned": False,
            })
            return

        self._send_json(200, {
            "character_id": character_id,
            "slot": slot,
            "item_id": equipped["item_id"],
            "attuned": equipped["attuned"],
        })

    def _handle_attune_play_campaign_character_equipment(self, campaign_id, character_id, slot):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        if slot not in rules.VALID_EQUIPMENT_SLOTS:
            self._send_json(400, {"error": "invalid slot"})
            return

        equipped = db.get_play_campaign_character_equipment_slot(campaign_id, character_id, slot)
        if equipped is None or equipped["item_id"] not in rules.ATTUNABLE_ITEM_IDS:
            self._send_json(400, {"error": "slot is not an attunable item"})
            return

        if equipped["attuned"]:
            self._send_json(409, {"error": "already attuned"})
            return

        attunement_count = db.count_play_campaign_character_attunements(campaign_id, character_id)
        if attunement_count >= rules.MAX_ATTUNEMENTS:
            self._send_json(409, {"error": "max attunements reached"})
            return

        db.attune_play_campaign_character_equipment_slot(campaign_id, character_id, slot)
        attunement_count += 1

        self._send_json(200, {
            "character_id": character_id,
            "slot": slot,
            "item_id": equipped["item_id"],
            "attuned": True,
            "attunement_count": attunement_count,
            "max_attunements": rules.MAX_ATTUNEMENTS,
        })

    def _handle_consume_play_campaign_character_inventory_item(
        self, campaign_id, character_id, item_id
    ):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
            self._send_json(400, {"error": "invalid item_id"})
            return

        if item_id not in rules.CONSUMABLE_ITEM_EFFECTS:
            self._send_json(400, {"error": "item is not consumable"})
            return

        total_quantity = db.remove_play_campaign_character_inventory_item(
            campaign_id, character_id, item_id, 1
        )
        if total_quantity is None:
            self._send_json(409, {"error": "no held quantity"})
            return

        self._send_json(200, {
            "character_id": character_id,
            "item_id": item_id,
            "quantity_consumed": 1,
            "total_quantity": total_quantity,
            "effect": rules.CONSUMABLE_ITEM_EFFECTS[item_id],
        })

    def _handle_enter_play_campaign_scene(self, campaign_id, scene_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        scene = db.get_play_scene(campaign_id, scene_id)
        if scene is None:
            self._send_json(404, {"error": "scene not found"})
            return

        if scene["status"] != "open":
            self._send_json(409, {"error": "scene closed"})
            return

        db.set_play_campaign_current_scene(campaign_id, scene_id)

        self._send_json(200, {"current_scene_id": scene_id, "name": scene["name"]})

    def _handle_close_play_campaign_scene(self, campaign_id, scene_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        scene = db.get_play_scene(campaign_id, scene_id)
        if scene is None:
            self._send_json(404, {"error": "scene not found"})
            return

        db.close_play_scene(campaign_id, scene_id)

        self._send_json(200, {"id": scene_id, "status": "closed"})

    def _handle_get_play_campaign_current_scene(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        scene_id = campaign["current_scene_id"]
        scene = db.get_play_scene(campaign_id, scene_id) if scene_id else None
        if scene is None or scene["status"] != "open":
            self._send_json(404, {"error": "no current scene"})
            return

        self._send_json(200, {
            "id": scene["id"],
            "name": scene["name"],
            "status": scene["status"],
        })

    # -- play: locations --------------------------------------------------

    def _handle_create_play_campaign_location(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        location_id = body.get("id")
        name = body.get("name")
        if not isinstance(location_id, str) or not location_id:
            self._send_json(400, {"error": "invalid id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return

        if db.get_play_location(campaign_id, location_id) is not None:
            self._send_json(409, {"error": "duplicate location id"})
            return

        location = {"id": location_id, "name": name}
        try:
            db.create_play_location(campaign_id, location)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate location id"})
            return

        self._send_json(201, location)

    def _handle_create_play_campaign_location_connection(self, campaign_id, from_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        to_id = body.get("to_id")
        travel_turns = body.get("travel_turns")
        if not isinstance(to_id, str) or not to_id:
            self._send_json(400, {"error": "invalid to_id"})
            return
        if not isinstance(travel_turns, int) or isinstance(travel_turns, bool) or travel_turns < 0:
            self._send_json(400, {"error": "invalid travel_turns"})
            return

        if db.get_play_location(campaign_id, from_id) is None:
            self._send_json(400, {"error": "unknown source location"})
            return
        if db.get_play_location(campaign_id, to_id) is None:
            self._send_json(400, {"error": "unknown destination location"})
            return

        if db.get_play_location_connection(campaign_id, from_id, to_id) is not None:
            self._send_json(400, {"error": "already connected"})
            return

        connection = {"from_id": from_id, "to_id": to_id, "travel_turns": travel_turns}
        try:
            db.create_play_location_connection(campaign_id, connection)
        except sqlite3.IntegrityError:
            self._send_json(400, {"error": "already connected"})
            return

        self._send_json(201, connection)

    def _handle_get_play_campaign_location_travel(self, campaign_id, loc_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        destinations = db.get_play_location_destinations(campaign_id, loc_id)
        self._send_json(200, {"destinations": destinations})

    def _handle_get_play_campaign_character_currency(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        gold = db.get_play_campaign_character_gold(campaign_id, character_id)
        self._send_json(200, {"character_id": character_id, "gold": gold})

    def _handle_post_play_campaign_character_currency_transfer(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        to_character_id = body.get("to_character_id")
        gold = body.get("gold")

        if not isinstance(to_character_id, str) or not to_character_id:
            self._send_json(400, {"error": "invalid to_character_id"})
            return
        if to_character_id == character_id:
            self._send_json(400, {"error": "invalid to_character_id"})
            return
        dest_info = db.get_play_campaign_character_owner(campaign_id, to_character_id)
        if dest_info is None:
            self._send_json(400, {"error": "invalid to_character_id"})
            return
        if not rules.is_plain_int(gold) or gold <= 0:
            self._send_json(400, {"error": "invalid gold"})
            return

        result = db.transfer_play_campaign_character_gold(
            campaign_id, character_id, to_character_id, gold
        )
        if result is None:
            self._send_json(409, {"error": "insufficient gold"})
            return

        transfer_id, from_gold, to_gold = result
        self._send_json(201, {
            "from_character_id": character_id,
            "to_character_id": to_character_id,
            "gold": gold,
            "from_gold": from_gold,
            "to_gold": to_gold,
            "transfer_id": transfer_id,
        })

    # -- play campaign loot --------------------------------------------------

    def _handle_create_play_campaign_loot(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        loot_id = body.get("loot_id")
        item_id = body.get("item_id")
        quantity = body.get("quantity")

        if not isinstance(loot_id, str) or not loot_id:
            self._send_json(400, {"error": "invalid loot_id"})
            return
        if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
            self._send_json(400, {"error": "invalid item_id"})
            return
        if not rules.is_plain_int(quantity) or quantity < 1:
            self._send_json(400, {"error": "invalid quantity"})
            return

        created = db.create_play_campaign_loot(campaign_id, loot_id, item_id, quantity)
        if not created:
            self._send_json(409, {"error": "duplicate loot_id"})
            return

        self._send_json(201, {
            "loot_id": loot_id,
            "item_id": item_id,
            "quantity": quantity,
            "status": "open",
        })

    def _handle_get_play_campaign_loot(self, campaign_id, loot_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        loot = db.get_play_campaign_loot(campaign_id, loot_id)
        if loot is None:
            self._send_json(404, {"error": "loot not found"})
            return

        votes = db.get_play_campaign_loot_votes_tally(campaign_id, loot_id)

        self._send_json(200, {
            "loot_id": loot["loot_id"],
            "item_id": loot["item_id"],
            "quantity": loot["quantity"],
            "status": loot["status"],
            "recipient_character_id": loot["recipient_character_id"],
            "votes": votes,
        })

    def _handle_post_play_campaign_loot_vote(self, campaign_id, loot_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        loot = db.get_play_campaign_loot(campaign_id, loot_id)
        if loot is None:
            self._send_json(404, {"error": "loot not found"})
            return

        recipient_character_id = body.get("recipient_character_id")
        if not isinstance(recipient_character_id, str) or not recipient_character_id:
            self._send_json(400, {"error": "invalid recipient_character_id"})
            return
        recipient_info = db.get_play_campaign_character_owner(campaign_id, recipient_character_id)
        if recipient_info is None:
            self._send_json(400, {"error": "invalid recipient_character_id"})
            return

        votes_for_recipient = db.cast_play_campaign_loot_vote(
            campaign_id, loot_id, actor["username"], recipient_character_id
        )
        if votes_for_recipient is None:
            self._send_json(409, {"error": "already voted"})
            return

        self._send_json(201, {
            "loot_id": loot_id,
            "voter": actor["username"],
            "recipient_character_id": recipient_character_id,
            "votes_for_recipient": votes_for_recipient,
        })

    def _handle_post_play_campaign_loot_assign(self, campaign_id, loot_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        result = db.assign_play_campaign_loot(campaign_id, loot_id)
        error = result.get("error")
        if error == "not_found":
            self._send_json(404, {"error": "loot not found"})
            return
        if error is not None:
            self._send_json(409, {"error": error})
            return

        self._send_json(200, result)

    # -- play campaign npcs ---------------------------------------------------

    def _handle_create_play_campaign_npc(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        npc_id = body.get("npc_id")
        name = body.get("name")
        agenda = body.get("agenda")
        public_status = body.get("public_status")

        if not isinstance(npc_id, str) or not npc_id:
            self._send_json(400, {"error": "invalid npc_id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not isinstance(agenda, str) or not agenda:
            self._send_json(400, {"error": "invalid agenda"})
            return
        if not isinstance(public_status, str) or not public_status:
            self._send_json(400, {"error": "invalid public_status"})
            return

        created = db.create_play_campaign_npc(campaign_id, npc_id, name, agenda, public_status)
        if not created:
            self._send_json(409, {"error": "duplicate npc_id"})
            return

        self._send_json(201, {
            "npc_id": npc_id,
            "name": name,
            "agenda": agenda,
            "public_status": public_status,
        })

    def _handle_put_play_campaign_npc_agenda(self, campaign_id, npc_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        agenda = body.get("agenda")
        public_status = body.get("public_status")

        if not isinstance(agenda, str) or not agenda:
            self._send_json(400, {"error": "invalid agenda"})
            return
        if not isinstance(public_status, str) or not public_status:
            self._send_json(400, {"error": "invalid public_status"})
            return

        updated = db.update_play_campaign_npc_agenda(campaign_id, npc_id, agenda, public_status)
        if updated is None:
            self._send_json(404, {"error": "npc not found"})
            return

        self._send_json(200, updated)

    def _handle_get_play_campaign_npc(self, campaign_id, npc_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        npc = db.get_play_campaign_npc(campaign_id, npc_id)
        if npc is None:
            self._send_json(404, {"error": "npc not found"})
            return

        if is_owner:
            self._send_json(200, npc)
            return

        self._send_json(200, {
            "npc_id": npc["npc_id"],
            "name": npc["name"],
            "public_status": npc["public_status"],
        })

    def _handle_post_play_campaign_npc_dialogue(self, campaign_id, npc_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        npc = db.get_play_campaign_npc(campaign_id, npc_id)
        if npc is None:
            self._send_json(404, {"error": "npc not found"})
            return

        dialogue_id = body.get("dialogue_id")
        speaker = body.get("speaker")
        text = body.get("text")
        visibility = body.get("visibility")

        if not isinstance(dialogue_id, str) or not dialogue_id:
            self._send_json(400, {"error": "invalid dialogue_id"})
            return
        if not isinstance(speaker, str) or not speaker:
            self._send_json(400, {"error": "invalid speaker"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        if visibility not in ("public", "private"):
            self._send_json(400, {"error": "invalid visibility"})
            return

        created = db.create_play_campaign_npc_dialogue(
            campaign_id, npc_id, dialogue_id, speaker, text, visibility
        )
        if not created:
            self._send_json(409, {"error": "duplicate dialogue_id"})
            return

        self._send_json(201, {
            "dialogue_id": dialogue_id,
            "speaker": speaker,
            "text": text,
            "visibility": visibility,
        })

    def _handle_get_play_campaign_npc_dialogue(self, campaign_id, npc_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        npc = db.get_play_campaign_npc(campaign_id, npc_id)
        if npc is None:
            self._send_json(404, {"error": "npc not found"})
            return

        entries = db.get_play_campaign_npc_dialogue_history(
            campaign_id, npc_id, public_only=not is_owner
        )

        self._send_json(200, {"npc_id": npc_id, "entries": entries})

    # -- campaign relationships -------------------------------------------

    def _handle_create_play_campaign_relationship(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        source_id = body.get("source_id")
        target_id = body.get("target_id")
        kind = body.get("kind")
        score = body.get("score")

        if not isinstance(source_id, str) or not source_id:
            self._send_json(400, {"error": "invalid source_id"})
            return
        if not isinstance(target_id, str) or not target_id:
            self._send_json(400, {"error": "invalid target_id"})
            return
        if not isinstance(kind, str) or not kind:
            self._send_json(400, {"error": "invalid kind"})
            return
        if not rules.is_plain_int(score) or score < -100 or score > 100:
            self._send_json(400, {"error": "invalid score"})
            return
        if source_id == target_id:
            self._send_json(400, {"error": "source_id and target_id must differ"})
            return

        if not db.play_campaign_entity_exists(campaign_id, source_id):
            self._send_json(404, {"error": "source_id not found"})
            return
        if not db.play_campaign_entity_exists(campaign_id, target_id):
            self._send_json(404, {"error": "target_id not found"})
            return

        created = db.create_play_campaign_relationship(campaign_id, source_id, target_id, kind, score)
        if not created:
            self._send_json(409, {"error": "duplicate relationship"})
            return

        self._send_json(201, {
            "source_id": source_id,
            "target_id": target_id,
            "kind": kind,
            "score": score,
        })

    def _handle_put_play_campaign_relationship(self, campaign_id, source_id, target_id, kind, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        score = body.get("score")
        if not rules.is_plain_int(score) or score < -100 or score > 100:
            self._send_json(400, {"error": "invalid score"})
            return

        updated = db.update_play_campaign_relationship_score(campaign_id, source_id, target_id, kind, score)
        if updated is None:
            self._send_json(404, {"error": "relationship not found"})
            return

        self._send_json(200, updated)

    def _handle_get_play_campaign_relationships(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        edges = db.get_play_campaign_relationships(campaign_id)
        self._send_json(200, {"edges": edges})

    # -- campaign clues -----------------------------------------------------

    def _clue_response(self, clue):
        result = {
            "clue_id": clue["clue_id"],
            "text": clue["text"],
            "audience": clue["audience"],
        }
        if clue["audience"] == "character":
            result["character_id"] = clue["character_id"]
        return result

    def _handle_create_play_campaign_clue(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        clue_id = body.get("clue_id")
        text = body.get("text")
        audience = body.get("audience")
        character_id = body.get("character_id")

        if not isinstance(clue_id, str) or not clue_id:
            self._send_json(400, {"error": "invalid clue_id"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        if audience not in ("character", "party", "hidden"):
            self._send_json(400, {"error": "invalid audience"})
            return

        if audience == "character":
            if not isinstance(character_id, str) or not character_id:
                self._send_json(400, {"error": "invalid character_id"})
                return
            if db.get_play_campaign_member_by_character(campaign_id, character_id) is None:
                self._send_json(400, {"error": "unknown character_id"})
                return
        else:
            if character_id is not None:
                self._send_json(400, {"error": "character_id must be omitted"})
                return
            character_id = None

        if db.get_play_campaign_clue(campaign_id, clue_id) is not None:
            self._send_json(409, {"error": "duplicate clue_id"})
            return

        db.create_play_campaign_clue(campaign_id, clue_id, text, audience, character_id)

        clue = {
            "clue_id": clue_id,
            "text": text,
            "audience": audience,
            "character_id": character_id,
        }
        self._send_json(201, self._clue_response(clue))

    def _handle_get_play_campaign_clues(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        clues = db.get_play_campaign_clues(campaign_id)
        if not is_owner:
            own_character_id = member["character_id"]
            clues = [
                c for c in clues
                if c["audience"] == "party"
                or (c["audience"] == "character" and c["character_id"] == own_character_id)
            ]

        self._send_json(200, {"clues": [self._clue_response(c) for c in clues]})

    # -- campaign quests ----------------------------------------------------

    def _quest_response(self, campaign_id, quest):
        response = {
            "quest_id": quest["quest_id"],
            "title": quest["title"],
            "depends_on": quest["depends_on"],
            "state": quest["state"],
        }
        rewards = db.get_play_campaign_quest_rewards(campaign_id, quest["quest_id"])
        if rewards is not None:
            response["rewards"] = {"xp": rewards["xp"], "items": rewards["items"]}
        return response

    def _handle_create_play_campaign_quest(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        quest_id = body.get("quest_id")
        title = body.get("title")
        depends_on = body.get("depends_on", [])

        if not isinstance(quest_id, str) or not quest_id:
            self._send_json(400, {"error": "invalid quest_id"})
            return
        if not isinstance(title, str) or not title:
            self._send_json(400, {"error": "invalid title"})
            return
        if not isinstance(depends_on, list) or any(
            not isinstance(d, str) for d in depends_on
        ):
            self._send_json(400, {"error": "invalid depends_on"})
            return
        if len(set(depends_on)) != len(depends_on):
            self._send_json(400, {"error": "duplicate dependency"})
            return
        if quest_id in depends_on:
            self._send_json(400, {"error": "quest cannot depend on itself"})
            return
        for dep_id in depends_on:
            if db.get_play_campaign_quest(campaign_id, dep_id) is None:
                self._send_json(400, {"error": "unknown dependency"})
                return

        if db.get_play_campaign_quest(campaign_id, quest_id) is not None:
            self._send_json(409, {"error": "duplicate quest_id"})
            return

        db.create_play_campaign_quest(campaign_id, quest_id, title, depends_on)

        quest = {
            "quest_id": quest_id,
            "title": title,
            "depends_on": depends_on,
            "state": "locked",
        }
        self._send_json(201, self._quest_response(campaign_id, quest))

    def _world_event_response(self, event):
        response = {
            "event_id": event["event_id"],
            "turn_number": event["turn_number"],
            "title": event["title"],
            "text": event["text"],
            "status": event["status"],
        }
        if event["resolution"] is not None:
            response["resolution"] = event["resolution"]
        return response

    def _handle_create_play_campaign_world_event(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        event_id = body.get("event_id")
        turn_number = body.get("turn_number")
        title = body.get("title")
        text = body.get("text")

        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid event_id"})
            return
        if not isinstance(title, str) or not title:
            self._send_json(400, {"error": "invalid title"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        current_turn_number = campaign["turn_number"] if campaign["turn_number"] is not None else 1
        if not rules.is_plain_int(turn_number) or turn_number < current_turn_number:
            self._send_json(400, {"error": "invalid turn_number"})
            return

        if db.get_play_campaign_world_event(campaign_id, event_id) is not None:
            self._send_json(409, {"error": "duplicate event_id"})
            return

        db.create_play_campaign_world_event(campaign_id, event_id, turn_number, title, text)

        event = {
            "event_id": event_id,
            "turn_number": turn_number,
            "title": title,
            "text": text,
            "status": "scheduled",
            "resolution": None,
        }
        self._send_json(201, self._world_event_response(event))

    def _handle_resolve_play_campaign_world_event(self, campaign_id, event_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        event = db.get_play_campaign_world_event(campaign_id, event_id)
        if event is None:
            self._send_json(404, {"error": "event not found"})
            return

        text = body.get("text")
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        if campaign["turn_number"] != event["turn_number"]:
            self._send_json(409, {"error": "turn mismatch"})
            return

        if event["status"] == "resolved":
            self._send_json(409, {"error": "event already resolved"})
            return

        resolved = db.resolve_play_campaign_world_event(campaign_id, event_id, text)
        if not resolved:
            self._send_json(409, {"error": "event already resolved"})
            return

        event = db.get_play_campaign_world_event(campaign_id, event_id)
        self._send_json(201, self._world_event_response(event))

    def _handle_get_play_campaign_world_events(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        events = db.get_play_campaign_world_events(campaign_id)
        self._send_json(200, {"events": [self._world_event_response(e) for e in events]})

    def _calendar_response(self, calendar):
        return {
            "day": calendar["day"],
            "season": calendar["season"],
            "weather": rules.weather_for(calendar["day"], calendar["season"]),
        }

    def _handle_create_play_campaign_calendar(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        day = body.get("day")
        season = body.get("season")

        if not rules.is_plain_int(day) or day < 1:
            self._send_json(400, {"error": "invalid day"})
            return
        if season not in ("spring", "summer", "autumn", "winter"):
            self._send_json(400, {"error": "invalid season"})
            return

        created = db.create_play_campaign_calendar(campaign_id, day, season)
        if not created:
            self._send_json(409, {"error": "calendar already initialized"})
            return

        calendar = db.get_play_campaign_calendar(campaign_id)
        self._send_json(201, self._calendar_response(calendar))

    def _handle_get_play_campaign_calendar(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        calendar = db.get_play_campaign_calendar(campaign_id)
        if calendar is None:
            self._send_json(404, {"error": "calendar not found"})
            return

        self._send_json(200, self._calendar_response(calendar))

    def _handle_advance_play_campaign_calendar(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        days = body.get("days")
        if not rules.is_plain_int(days) or days < 1 or days > 30:
            self._send_json(400, {"error": "invalid days"})
            return

        calendar = db.advance_play_campaign_calendar(campaign_id, days)
        if calendar is None:
            self._send_json(404, {"error": "calendar not found"})
            return

        self._send_json(200, self._calendar_response(calendar))

    def _settlement_response(self, settlement, discovered_by):
        return {
            "settlement_id": settlement["settlement_id"],
            "name": settlement["name"],
            "services": settlement["services"],
            "availability": settlement["availability"],
            "discovered_by": discovered_by,
        }

    def _validate_settlement_payload(self, body):
        """Returns (name, services, availability) or None after sending a 400."""
        name = body.get("name")
        services = body.get("services")
        availability = body.get("availability")

        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return None
        if not isinstance(services, list) or not services:
            self._send_json(400, {"error": "invalid services"})
            return None

        normalized_services = []
        seen = set()
        for service in services:
            if not isinstance(service, str):
                self._send_json(400, {"error": "invalid services"})
                return None
            trimmed = service.strip()
            if not trimmed or trimmed in seen:
                self._send_json(400, {"error": "invalid services"})
                return None
            seen.add(trimmed)
            normalized_services.append(trimmed)

        if availability not in ("open", "limited", "closed"):
            self._send_json(400, {"error": "invalid availability"})
            return None

        return name, normalized_services, availability

    def _handle_create_play_campaign_settlement(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        settlement_id = body.get("settlement_id")
        if not isinstance(settlement_id, str) or not settlement_id:
            self._send_json(400, {"error": "invalid settlement_id"})
            return

        validated = self._validate_settlement_payload(body)
        if validated is None:
            return
        name, services, availability = validated

        created = db.create_play_campaign_settlement(
            campaign_id, settlement_id, name, services, availability
        )
        if not created:
            self._send_json(409, {"error": "duplicate settlement_id"})
            return

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        self._send_json(201, self._settlement_response(settlement, settlement["discovered_by"]))

    def _handle_put_play_campaign_settlement(self, campaign_id, settlement_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        if settlement is None:
            self._send_json(404, {"error": "settlement not found"})
            return

        validated = self._validate_settlement_payload(body)
        if validated is None:
            return
        name, services, availability = validated

        db.update_play_campaign_settlement(campaign_id, settlement_id, name, services, availability)

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        self._send_json(200, self._settlement_response(settlement, settlement["discovered_by"]))

    def _handle_discover_play_campaign_settlement(self, campaign_id, settlement_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        if settlement is None:
            self._send_json(404, {"error": "settlement not found"})
            return

        character_id = member["character_id"]
        newly_discovered = db.discover_play_campaign_settlement(
            campaign_id, settlement_id, character_id
        )

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        discovered_by = [cid for cid in settlement["discovered_by"] if cid == character_id]
        status = 201 if newly_discovered else 200
        self._send_json(status, self._settlement_response(settlement, discovered_by))

    def _handle_get_play_campaign_settlements(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        settlements = db.get_play_campaign_settlements(campaign_id)

        if is_owner:
            response = [
                self._settlement_response(s, s["discovered_by"]) for s in settlements
            ]
        else:
            character_id = member["character_id"]
            response = []
            for s in settlements:
                if character_id in s["discovered_by"]:
                    response.append(self._settlement_response(s, [character_id]))

        self._send_json(200, {"settlements": response})

    def _shop_response(self, shop):
        return {
            "shop_id": shop["shop_id"],
            "name": shop["name"],
            "stock": shop["stock"],
            "buy_price": shop["buy_price"],
            "sell_price": shop["sell_price"],
        }

    def _validate_shop_payload(self, body):
        """Returns (shop_id, name, stock, buy_price, sell_price) or None after a 400."""
        shop_id = body.get("shop_id")
        name = body.get("name")
        stock = body.get("stock")
        buy_price = body.get("buy_price")
        sell_price = body.get("sell_price")

        if not isinstance(shop_id, str) or not shop_id:
            self._send_json(400, {"error": "invalid shop_id"})
            return None
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return None
        if not isinstance(stock, dict) or not stock:
            self._send_json(400, {"error": "invalid stock"})
            return None
        for item_id, quantity in stock.items():
            if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
                self._send_json(400, {"error": "invalid stock"})
                return None
            if not rules.is_plain_int(quantity) or quantity < 1:
                self._send_json(400, {"error": "invalid stock"})
                return None
        if not rules.is_plain_int(buy_price) or buy_price < 1:
            self._send_json(400, {"error": "invalid buy_price"})
            return None
        if not rules.is_plain_int(sell_price) or sell_price < 0:
            self._send_json(400, {"error": "invalid sell_price"})
            return None

        return shop_id, name, stock, buy_price, sell_price

    def _handle_create_play_campaign_shop(self, campaign_id, settlement_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        if settlement is None:
            self._send_json(404, {"error": "settlement not found"})
            return

        if not self._require_owner(actor, campaign):
            return

        validated = self._validate_shop_payload(body)
        if validated is None:
            return
        shop_id, name, stock, buy_price, sell_price = validated

        created = db.create_play_campaign_shop(
            campaign_id, settlement_id, shop_id, name, stock, buy_price, sell_price
        )
        if not created:
            self._send_json(409, {"error": "duplicate shop_id"})
            return

        shop = db.get_play_campaign_shop(campaign_id, settlement_id, shop_id)
        self._send_json(201, self._shop_response(shop))

    def _handle_get_play_campaign_shop(self, campaign_id, settlement_id, shop_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        if settlement is None:
            self._send_json(404, {"error": "settlement not found"})
            return

        shop = db.get_play_campaign_shop(campaign_id, settlement_id, shop_id)
        if shop is None:
            self._send_json(404, {"error": "shop not found"})
            return

        is_owner = actor["username"] == campaign["owner"]
        if not is_owner:
            member = db.get_play_campaign_member(campaign_id, actor["username"])
            if member is None:
                self._send_json(403, {"error": "forbidden"})
                return
            if member["character_id"] not in settlement["discovered_by"]:
                self._send_json(404, {"error": "shop not found"})
                return

        self._send_json(200, self._shop_response(shop))

    def _validate_shop_trade_payload(self, body):
        """Returns (character_id, item_id, quantity) or None after a 400."""
        character_id = body.get("character_id")
        item_id = body.get("item_id")
        quantity = body.get("quantity")

        if not isinstance(character_id, str) or not character_id:
            self._send_json(400, {"error": "invalid character_id"})
            return None
        if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
            self._send_json(400, {"error": "invalid item_id"})
            return None
        if not rules.is_plain_int(quantity) or quantity < 1:
            self._send_json(400, {"error": "invalid quantity"})
            return None

        return character_id, item_id, quantity

    def _handle_buy_play_campaign_shop_item(self, campaign_id, settlement_id, shop_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        if settlement is None:
            self._send_json(404, {"error": "settlement not found"})
            return

        shop = db.get_play_campaign_shop(campaign_id, settlement_id, shop_id)
        if shop is None:
            self._send_json(404, {"error": "shop not found"})
            return

        validated = self._validate_shop_trade_payload(body)
        if validated is None:
            return
        character_id, item_id, quantity = validated

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        result = db.buy_play_campaign_shop_item(
            campaign_id, settlement_id, shop_id, character_id, item_id, quantity
        )
        if result is None:
            self._send_json(409, {"error": "insufficient stock or funds"})
            return

        gold, stock = result
        self._send_json(200, {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": gold,
            "stock": stock,
        })

    def _handle_sell_play_campaign_shop_item(self, campaign_id, settlement_id, shop_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        settlement = db.get_play_campaign_settlement(campaign_id, settlement_id)
        if settlement is None:
            self._send_json(404, {"error": "settlement not found"})
            return

        shop = db.get_play_campaign_shop(campaign_id, settlement_id, shop_id)
        if shop is None:
            self._send_json(404, {"error": "shop not found"})
            return

        validated = self._validate_shop_trade_payload(body)
        if validated is None:
            return
        character_id, item_id, quantity = validated

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        result = db.sell_play_campaign_shop_item(
            campaign_id, settlement_id, shop_id, character_id, item_id, quantity
        )
        if result is None:
            self._send_json(409, {"error": "insufficient inventory"})
            return

        gold, stock = result
        self._send_json(200, {
            "character_id": character_id,
            "item_id": item_id,
            "quantity": quantity,
            "gold": gold,
            "stock": stock,
        })

    def _recipe_response(self, recipe):
        return {
            "recipe_id": recipe["recipe_id"],
            "name": recipe["name"],
            "ingredients": recipe["ingredients"],
            "output_item": recipe["output_item"],
            "output_quantity": recipe["output_quantity"],
        }

    def _validate_recipe_payload(self, body):
        """Returns (recipe_id, name, ingredients, output_item, output_quantity) or None after a 400."""
        recipe_id = body.get("recipe_id")
        name = body.get("name")
        ingredients = body.get("ingredients")
        output_item = body.get("output_item")
        output_quantity = body.get("output_quantity")

        if not isinstance(recipe_id, str) or not recipe_id:
            self._send_json(400, {"error": "invalid recipe_id"})
            return None
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return None
        if not isinstance(ingredients, dict) or not ingredients:
            self._send_json(400, {"error": "invalid ingredients"})
            return None
        for item_id, quantity in ingredients.items():
            if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
                self._send_json(400, {"error": "invalid ingredients"})
                return None
            if not rules.is_plain_int(quantity) or quantity < 1:
                self._send_json(400, {"error": "invalid ingredients"})
                return None
        if output_item not in rules.VALID_INVENTORY_ITEM_IDS:
            self._send_json(400, {"error": "invalid output_item"})
            return None
        if not rules.is_plain_int(output_quantity) or output_quantity < 1:
            self._send_json(400, {"error": "invalid output_quantity"})
            return None

        return recipe_id, name, ingredients, output_item, output_quantity

    def _handle_create_play_campaign_recipe(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        validated = self._validate_recipe_payload(body)
        if validated is None:
            return
        recipe_id, name, ingredients, output_item, output_quantity = validated

        created = db.create_play_campaign_recipe(
            campaign_id, recipe_id, name, ingredients, output_item, output_quantity
        )
        if not created:
            self._send_json(409, {"error": "duplicate recipe_id"})
            return

        recipe = db.get_play_campaign_recipe(campaign_id, recipe_id)
        self._send_json(201, self._recipe_response(recipe))

    def _handle_get_play_campaign_recipes(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        recipes = db.get_play_campaign_recipes(campaign_id)
        self._send_json(200, {"recipes": [self._recipe_response(r) for r in recipes]})

    def _handle_craft_play_campaign_recipe(self, campaign_id, recipe_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        character_id = body.get("character_id")
        if not isinstance(character_id, str) or not character_id:
            self._send_json(400, {"error": "invalid character_id"})
            return

        recipe = db.get_play_campaign_recipe(campaign_id, recipe_id)
        if recipe is None:
            self._send_json(404, {"error": "recipe not found"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        result = db.craft_play_campaign_recipe(campaign_id, character_id, recipe_id)
        if result is None:
            self._send_json(409, {"error": "insufficient ingredients"})
            return

        self._send_json(201, {
            "character_id": character_id,
            "recipe_id": recipe_id,
            "output_item": recipe["output_item"],
            "output_quantity": recipe["output_quantity"],
        })

    def _downtime_activity_response(self, activity):
        return {
            "activity_id": activity["activity_id"],
            "name": activity["name"],
            "cycles_required": activity["cycles_required"],
        }

    def _downtime_allocation_response(self, allocation):
        return {
            "character_id": allocation["character_id"],
            "activity_id": allocation["activity_id"],
            "cycles_completed": allocation["cycles_completed"],
            "completions": allocation["completions"],
        }

    def _handle_create_play_campaign_downtime_activity(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        activity_id = body.get("activity_id")
        name = body.get("name")
        cycles_required = body.get("cycles_required")

        if not isinstance(activity_id, str) or not activity_id:
            self._send_json(400, {"error": "invalid activity_id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return
        if not rules.is_plain_int(cycles_required) or not (1 <= cycles_required <= 10):
            self._send_json(400, {"error": "invalid cycles_required"})
            return

        created = db.create_play_campaign_downtime_activity(
            campaign_id, activity_id, name, cycles_required
        )
        if not created:
            self._send_json(409, {"error": "duplicate activity_id"})
            return

        activity = db.get_play_campaign_downtime_activity(campaign_id, activity_id)
        self._send_json(201, self._downtime_activity_response(activity))

    def _handle_create_play_campaign_downtime_allocation(self, campaign_id, character_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        activity_id = body.get("activity_id")
        if not isinstance(activity_id, str) or not activity_id:
            self._send_json(400, {"error": "invalid activity_id"})
            return

        activity = db.get_play_campaign_downtime_activity(campaign_id, activity_id)
        if activity is None:
            self._send_json(404, {"error": "activity not found"})
            return

        created = db.create_play_campaign_downtime_allocation(
            campaign_id, character_id, activity_id
        )
        if not created:
            self._send_json(409, {"error": "duplicate allocation"})
            return

        allocation = db.get_play_campaign_downtime_allocation(
            campaign_id, character_id, activity_id
        )
        self._send_json(201, self._downtime_allocation_response(allocation))

    def _handle_progress_play_campaign_downtime_allocation(
        self, campaign_id, character_id, activity_id
    ):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        if actor["username"] != owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        activity = db.get_play_campaign_downtime_activity(campaign_id, activity_id)
        if activity is None:
            self._send_json(404, {"error": "activity not found"})
            return

        allocation = db.get_play_campaign_downtime_allocation(
            campaign_id, character_id, activity_id
        )
        if allocation is None:
            self._send_json(404, {"error": "allocation not found"})
            return

        updated = db.progress_play_campaign_downtime_allocation(
            campaign_id, character_id, activity_id
        )
        self._send_json(200, self._downtime_allocation_response(updated))

    def _handle_get_play_campaign_downtime_allocation(
        self, campaign_id, character_id, activity_id
    ):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        activity = db.get_play_campaign_downtime_activity(campaign_id, activity_id)
        if activity is None:
            self._send_json(404, {"error": "activity not found"})
            return

        allocation = db.get_play_campaign_downtime_allocation(
            campaign_id, character_id, activity_id
        )
        if allocation is None:
            self._send_json(404, {"error": "allocation not found"})
            return

        self._send_json(200, self._downtime_allocation_response(allocation))

    def _handle_put_play_campaign_quest_state(self, campaign_id, quest_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        quest = db.get_play_campaign_quest(campaign_id, quest_id)
        if quest is None:
            self._send_json(404, {"error": "quest not found"})
            return

        new_state = body.get("state")
        if new_state not in ("active", "completed"):
            self._send_json(400, {"error": "invalid state"})
            return

        current_state = quest["state"]
        if current_state == "locked" and new_state == "active":
            deps = quest["depends_on"]
            for dep_id in deps:
                dep = db.get_play_campaign_quest(campaign_id, dep_id)
                if dep is None or dep["state"] != "completed":
                    self._send_json(409, {"error": "unmet dependencies"})
                    return
        elif current_state == "active" and new_state == "completed":
            pass
        else:
            self._send_json(409, {"error": "invalid transition"})
            return

        db.set_play_campaign_quest_state(campaign_id, quest_id, new_state)
        quest["state"] = new_state
        self._send_json(200, self._quest_response(campaign_id, quest))

    def _handle_get_play_campaign_quests(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        quests = db.get_play_campaign_quests(campaign_id)
        self._send_json(200, {"quests": [self._quest_response(campaign_id, q) for q in quests]})

    def _handle_put_play_campaign_quest_rewards(self, campaign_id, quest_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        quest = db.get_play_campaign_quest(campaign_id, quest_id)
        if quest is None:
            self._send_json(404, {"error": "quest not found"})
            return

        if quest["state"] not in ("locked", "active"):
            self._send_json(409, {"error": "quest already completed"})
            return

        xp = body.get("xp")
        items = body.get("items", {})

        if not rules.is_plain_int(xp) or xp < 0:
            self._send_json(400, {"error": "invalid xp"})
            return
        if not isinstance(items, dict):
            self._send_json(400, {"error": "invalid items"})
            return
        for item_id, quantity in items.items():
            if item_id not in rules.VALID_INVENTORY_ITEM_IDS:
                self._send_json(400, {"error": "invalid item_id"})
                return
            if not rules.is_plain_int(quantity) or quantity <= 0:
                self._send_json(400, {"error": "invalid item quantity"})
                return

        db.set_play_campaign_quest_rewards(campaign_id, quest_id, xp, items)

        self._send_json(200, self._quest_response(campaign_id, quest))

    def _handle_award_play_campaign_quest_rewards(self, campaign_id, quest_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        quest = db.get_play_campaign_quest(campaign_id, quest_id)
        if quest is None:
            self._send_json(404, {"error": "quest not found"})
            return

        if quest["state"] != "completed":
            self._send_json(409, {"error": "quest not completed"})
            return

        rewards = db.get_play_campaign_quest_rewards(campaign_id, quest_id)
        if rewards is None or rewards["awarded"]:
            self._send_json(409, {"error": "rewards not available"})
            return

        members = db.get_play_campaign_members(campaign_id)
        character_ids = [m["character_id"] for m in members if m["character_id"]]

        awarded = db.award_play_campaign_quest_rewards(campaign_id, quest_id, character_ids)
        if awarded is None:
            self._send_json(409, {"error": "rewards not available"})
            return

        self._send_json(201, {
            "quest_id": quest_id,
            "awarded": True,
            "xp": awarded["xp"],
            "items": awarded["items"],
        })

    def _handle_get_play_campaign_character_quest_rewards(self, campaign_id, character_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        owner_info = db.get_play_campaign_character_owner(campaign_id, character_id)
        if owner_info is None:
            self._send_json(404, {"error": "character not found"})
            return

        rewards = db.get_play_campaign_character_quest_rewards(campaign_id, character_id)
        self._send_json(200, {
            "character_id": character_id,
            "xp": rewards["xp"],
            "items": rewards["items"],
        })

    # -- campaign factions / reputation ----------------------------------

    def _handle_create_play_campaign_faction(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        faction_id = body.get("faction_id")
        name = body.get("name")

        if not isinstance(faction_id, str) or not faction_id:
            self._send_json(400, {"error": "invalid faction_id"})
            return
        if not isinstance(name, str) or not name:
            self._send_json(400, {"error": "invalid name"})
            return

        created = db.create_play_campaign_faction(campaign_id, faction_id, name)
        if not created:
            self._send_json(409, {"error": "duplicate faction_id"})
            return

        self._send_json(201, {"faction_id": faction_id, "name": name})

    def _handle_post_play_campaign_faction_reputation(self, campaign_id, faction_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        faction = db.get_play_campaign_faction(campaign_id, faction_id)
        if faction is None:
            self._send_json(404, {"error": "faction not found"})
            return

        character_id = body.get("character_id")
        delta = body.get("delta")
        reason = body.get("reason")

        if not isinstance(character_id, str) or not character_id:
            self._send_json(400, {"error": "invalid character_id"})
            return
        if db.get_play_campaign_character_owner(campaign_id, character_id) is None:
            self._send_json(400, {"error": "unknown character_id"})
            return
        if not isinstance(delta, int) or isinstance(delta, bool) or delta == 0 or delta < -25 or delta > 25:
            self._send_json(400, {"error": "invalid delta"})
            return
        if not isinstance(reason, str) or not reason:
            self._send_json(400, {"error": "invalid reason"})
            return

        entry = db.add_play_campaign_reputation_entry(
            campaign_id, faction_id, character_id, delta, reason
        )

        self._send_json(201, entry)

    def _handle_get_play_campaign_faction_reputation(self, campaign_id, faction_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return

        faction = db.get_play_campaign_faction(campaign_id, faction_id)
        if faction is None:
            self._send_json(404, {"error": "faction not found"})
            return

        if is_owner:
            entries = db.get_play_campaign_faction_reputation_history(campaign_id, faction_id)
        else:
            entries = db.get_play_campaign_faction_reputation_history(
                campaign_id, faction_id, member["character_id"]
            )

        self._send_json(200, {"faction_id": faction_id, "entries": entries})

    # -- play: invitations -------------------------------------------------------

    def _handle_create_play_campaign_invitation(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        invitation_id = body.get("invitation_id")
        username = body.get("username")
        character_id = body.get("character_id")

        if not isinstance(invitation_id, str) or not invitation_id:
            self._send_json(400, {"error": "invalid invitation_id"})
            return
        if not isinstance(username, str) or not username:
            self._send_json(400, {"error": "invalid username"})
            return
        if not isinstance(character_id, str) or not character_id:
            self._send_json(400, {"error": "invalid character_id"})
            return

        target = db.get_user(username)
        if target is None or target["role"] != "player":
            self._send_json(400, {"error": "invalid username"})
            return

        if db.get_play_campaign_invitation(campaign_id, invitation_id) is not None:
            self._send_json(409, {"error": "duplicate invitation_id"})
            return

        if db.get_play_campaign_pending_invitation_for_user(campaign_id, username) is not None:
            self._send_json(409, {"error": "duplicate active invitation"})
            return

        db.create_play_campaign_invitation(campaign_id, invitation_id, username, character_id)

        self._send_json(201, {
            "invitation_id": invitation_id,
            "username": username,
            "character_id": character_id,
            "status": "pending",
        })

    def _handle_accept_play_campaign_invitation(self, campaign_id, invitation_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        invitation = db.get_play_campaign_invitation(campaign_id, invitation_id)
        if invitation is None:
            self._send_json(404, {"error": "invitation not found"})
            return

        if actor["username"] != invitation["username"]:
            self._send_json(403, {"error": "forbidden"})
            return

        if invitation["status"] != "pending":
            self._send_json(409, {"error": "invitation not pending"})
            return

        member = {
            "username": invitation["username"],
            "character_id": invitation["character_id"],
            "name": "",
            "class": "",
        }
        try:
            db.create_play_campaign_member(campaign_id, member)
        except sqlite3.IntegrityError:
            self._send_json(409, {"error": "duplicate member"})
            return

        updated = db.update_play_campaign_invitation_status(
            campaign_id, invitation_id, "accepted"
        )

        self._send_json(200, updated)

    def _handle_get_play_campaign_invitations(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        invitations = db.get_play_campaign_invitations(campaign_id)
        if actor["username"] != campaign["owner"]:
            username = actor["username"]
            invitations = [inv for inv in invitations if inv["username"] == username]

        self._send_json(200, {"invitations": invitations})

    # -- play: delegations --------------------------------------------------------

    VALID_DELEGATION_POWERS = {"narrate"}

    def _handle_create_play_campaign_delegation(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        username = body.get("username")
        powers = body.get("powers")

        if not isinstance(username, str) or not username:
            self._send_json(400, {"error": "invalid username"})
            return
        if (
            not isinstance(powers, list)
            or not powers
            or not all(isinstance(power, str) for power in powers)
            or len(set(powers)) != len(powers)
            or not set(powers).issubset(self.VALID_DELEGATION_POWERS)
        ):
            self._send_json(400, {"error": "invalid powers"})
            return

        member = db.get_play_campaign_member(campaign_id, username)
        if member is None:
            self._send_json(400, {"error": "invalid username"})
            return

        existing = db.get_play_campaign_delegation(campaign_id, username)
        if existing is not None and existing["active"]:
            self._send_json(409, {"error": "duplicate active delegate"})
            return

        record = db.upsert_play_campaign_delegation(campaign_id, username, powers)
        db.add_play_campaign_delegation_audit_entry(
            campaign_id, username, "granted", powers
        )

        self._send_json(201, record)

    def _handle_revoke_play_campaign_delegation(self, campaign_id, username):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        existing = db.get_play_campaign_delegation(campaign_id, username)
        if existing is None:
            self._send_json(404, {"error": "delegation not found"})
            return

        record = db.revoke_play_campaign_delegation(campaign_id, username)
        db.add_play_campaign_delegation_audit_entry(
            campaign_id, username, "revoked", record["powers"]
        )

        self._send_json(200, record)

    def _handle_get_play_campaign_delegation_audit(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        entries = db.get_play_campaign_delegation_audit(campaign_id)
        self._send_json(200, {"entries": entries})

    # -- play: actor audit trail --------------------------------------------------

    def _handle_create_play_campaign_audit_event(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        kind = body.get("kind")
        correlation_id = body.get("correlation_id")

        if not isinstance(kind, str) or not kind:
            self._send_json(400, {"error": "invalid kind"})
            return
        if not isinstance(correlation_id, str) or not correlation_id:
            self._send_json(400, {"error": "invalid correlation_id"})
            return

        role = "DM" if is_owner else "player"
        record = db.add_play_campaign_audit_event(
            campaign_id, kind, actor["username"], role, correlation_id
        )
        if record is None:
            self._send_json(409, {"error": "duplicate correlation_id"})
            return

        self._send_json(201, record)

    def _handle_get_play_campaign_audit_events(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        entries = db.get_play_campaign_audit_events(campaign_id)
        self._send_json(200, {"entries": entries})

    # -- play: event projections ---------------------------------------------------

    VALID_PROJECTION_EVENT_KINDS = {"set-story", "increment-danger"}

    def _handle_create_play_campaign_projection_event(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if is_owner:
            self._send_json(403, {"error": "forbidden"})
            return
        if not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        event_id = body.get("event_id")
        kind = body.get("kind")

        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid event_id"})
            return
        if kind not in self.VALID_PROJECTION_EVENT_KINDS:
            self._send_json(400, {"error": "invalid kind"})
            return

        if kind == "set-story":
            value = body.get("value")
            if not isinstance(value, str) or not value:
                self._send_json(400, {"error": "invalid value"})
                return
        else:
            if "value" in body:
                self._send_json(400, {"error": "invalid value"})
                return
            value = None

        record = db.add_play_campaign_projection_event(campaign_id, event_id, kind, value)
        if record is None:
            self._send_json(409, {"error": "duplicate event_id"})
            return

        db.compute_play_campaign_projection(campaign_id)

        response = {
            "sequence": record["sequence"],
            "event_id": record["event_id"],
            "kind": record["kind"],
        }
        if kind == "set-story":
            response["value"] = record["value"]

        self._send_json(201, response)

    def _handle_get_play_campaign_projection(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        projection = db.compute_play_campaign_projection(campaign_id)
        self._send_json(200, projection)

    # -- play: idempotent events ---------------------------------------------------

    def _handle_create_play_campaign_idempotent_event(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        idempotency_key = self.headers.get("Idempotency-Key", "")
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            self._send_json(400, {"error": "missing idempotency key"})
            return
        idempotency_key = idempotency_key.strip()

        event_id = body.get("event_id")
        value = body.get("value")

        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid event_id"})
            return
        if not isinstance(value, str) or not value:
            self._send_json(400, {"error": "invalid value"})
            return

        status, record = db.add_play_campaign_idempotent_event(
            campaign_id, idempotency_key, event_id, value
        )

        if status == "created":
            self._send_json(201, record)
        elif status == "duplicate":
            self._send_json(200, record)
        else:
            self._send_json(409, {"error": "idempotency conflict"})

    def _handle_get_play_campaign_idempotent_events(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        events = db.get_play_campaign_idempotent_events(campaign_id)
        self._send_json(200, {"events": events})

    # -- play: safe turns ---------------------------------------------------------

    def _handle_create_play_campaign_safe_turn(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        submission_id = body.get("submission_id")
        expected_turn = body.get("expected_turn")
        action = body.get("action")

        if not isinstance(submission_id, str) or not submission_id:
            self._send_json(400, {"error": "invalid submission_id"})
            return
        if not isinstance(action, str) or not action:
            self._send_json(400, {"error": "invalid action"})
            return
        if (
            not isinstance(expected_turn, int)
            or isinstance(expected_turn, bool)
            or expected_turn < 1
        ):
            self._send_json(400, {"error": "invalid expected_turn"})
            return

        status, record = db.submit_play_campaign_safe_turn(
            campaign_id, submission_id, expected_turn, action
        )

        if status == "accepted":
            self._send_json(201, record)
        elif status == "stale":
            self._send_json(409, record)
        else:
            self._send_json(409, {"error": "duplicate submission"})

    def _handle_get_play_campaign_safe_turns(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        result = db.get_play_campaign_safe_turns(campaign_id)
        self._send_json(200, result)

    # -- play: transactional transfers --------------------------------------

    def _handle_create_play_campaign_transactional_transfer(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        from_character_id = body.get("from_character_id")
        to_character_id = body.get("to_character_id")
        amount = body.get("amount")
        simulate_failure = body.get("simulate_failure", False)

        if not isinstance(from_character_id, str) or not from_character_id:
            self._send_json(400, {"error": "invalid from_character_id"})
            return
        if not isinstance(to_character_id, str) or not to_character_id:
            self._send_json(400, {"error": "invalid to_character_id"})
            return
        if from_character_id == to_character_id:
            self._send_json(400, {"error": "invalid to_character_id"})
            return
        if not isinstance(simulate_failure, bool):
            self._send_json(400, {"error": "invalid simulate_failure"})
            return

        from_owner_info = db.get_play_campaign_character_owner(campaign_id, from_character_id)
        if from_owner_info is None:
            self._send_json(400, {"error": "invalid from_character_id"})
            return
        to_owner_info = db.get_play_campaign_character_owner(campaign_id, to_character_id)
        if to_owner_info is None:
            self._send_json(400, {"error": "invalid to_character_id"})
            return

        if actor["username"] != from_owner_info["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        if not rules.is_plain_int(amount) or amount <= 0:
            self._send_json(400, {"error": "invalid amount"})
            return

        result = db.create_play_campaign_transactional_transfer(
            campaign_id, from_character_id, to_character_id, amount, simulate_failure
        )

        if result == "insufficient":
            self._send_json(409, {"error": "insufficient gold"})
            return
        if result == "simulated_failure":
            self._send_json(500, {"error": "simulated failure"})
            return

        sequence, from_gold, to_gold = result
        self._send_json(201, {
            "from_character_id": from_character_id,
            "to_character_id": to_character_id,
            "amount": amount,
            "from_gold": from_gold,
            "to_gold": to_gold,
            "sequence": sequence,
        })

    def _handle_get_play_campaign_transactional_transfers(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        is_owner = actor["username"] == campaign["owner"]
        is_member = db.get_play_campaign_member(campaign_id, actor["username"]) is not None
        if not is_owner and not is_member:
            self._send_json(403, {"error": "forbidden"})
            return

        transfers = db.get_play_campaign_transactional_transfers(campaign_id)
        self._send_json(200, {"transfers": transfers})

    def _handle_create_play_campaign_export(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        export = db.create_play_campaign_export(campaign_id)
        self._send_json(201, export)

    def _handle_get_play_campaign_exports(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        exports = db.get_play_campaign_exports(campaign_id)
        self._send_json(200, {"exports": exports})

    def _handle_get_play_campaign_export(self, campaign_id, version_str):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        if not version_str.isdigit():
            self._send_json(404, {"error": "not found"})
            return

        export = db.get_play_campaign_export(campaign_id, int(version_str))
        if export is None:
            self._send_json(404, {"error": "not found"})
            return

        self._send_json(200, export)

    def _handle_create_play_campaign_backup(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        backup = db.create_play_campaign_backup(campaign_id)
        self._send_json(201, backup)

    def _handle_list_play_campaign_backups(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        backups = db.get_play_campaign_backups(campaign_id)
        self._send_json(200, {"backups": backups})

    def _handle_restore_play_campaign_backup(self, campaign_id, backup_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        backup = db.restore_play_campaign_backup(campaign_id, backup_id)
        if backup is None:
            self._send_json(404, {"error": "not found"})
            return

        self._send_json(200, backup)

    def _require_play_campaign_member(self, actor, campaign):
        """True if `actor` is the campaign owner or a member; otherwise writes 403."""
        campaign_id = campaign["id"]
        is_owner = actor["username"] == campaign["owner"]
        member = db.get_play_campaign_member(campaign_id, actor["username"])
        if not is_owner and member is None:
            self._send_json(403, {"error": "forbidden"})
            return False
        return True

    def _handle_get_play_campaign_onboarding(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_play_campaign_member(actor, campaign):
            return

        if actor["username"] == campaign["owner"]:
            self._send_json(200, {
                "role": "dm",
                "next_steps": [
                    "configure-safety",
                    "invite-players",
                    "start-campaign",
                ],
                "can_mutate": True,
            })
            return

        self._send_json(200, {
            "role": "player",
            "next_steps": [
                "review-party",
                "take-turn",
                "submit-action",
            ],
            "can_mutate": True,
        })

    # -- play: spectators --------------------------------------------------------

    def _handle_create_play_campaign_spectator(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] != campaign["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        spectator_id = body.get("spectator_id")
        if not isinstance(spectator_id, str) or not spectator_id:
            self._send_json(400, {"error": "invalid spectator_id"})
            return

        created = db.create_play_campaign_spectator(campaign_id, spectator_id)
        if not created:
            self._send_json(409, {"error": "duplicate spectator_id"})
            return

        self._send_json(201, {
            "spectator_id": spectator_id,
            "token": f"spectator-{spectator_id}",
        })

    def _handle_get_play_campaign_spectator_view(self, campaign_id):
        header = self.headers.get("Authorization", "")
        if not header:
            self._send_json(401, {"error": "unauthorized"})
            return
        if header.startswith("Bearer session-"):
            self._send_json(403, {"error": "forbidden"})
            return
        if not header.startswith("Bearer spectator-"):
            self._send_json(401, {"error": "unauthorized"})
            return
        spectator_id = header[len("Bearer spectator-"):]
        if not spectator_id:
            self._send_json(401, {"error": "unauthorized"})
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        ticket = db.get_play_campaign_spectator(spectator_id)
        if ticket is None:
            self._send_json(401, {"error": "unauthorized"})
            return
        if ticket["campaign_id"] != campaign_id:
            self._send_json(403, {"error": "forbidden"})
            return

        party_size = db.get_play_campaign_member_count(campaign_id)
        self._send_json(200, {
            "campaign_id": campaign["id"],
            "name": campaign["name"],
            "status": campaign["status"],
            "party_size": party_size,
            "story": campaign["story"],
        })

    # -- play: chat messages -----------------------------------------------------

    def _handle_create_play_campaign_message(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_play_campaign_member(actor, campaign):
            return

        text = body.get("text")
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        sequence = db.create_play_campaign_message(campaign_id, actor["username"], text)

        self._send_json(201, {
            "sequence": sequence,
            "kind": "chat",
            "actor": actor["username"],
            "text": text,
        })

    # -- play: load-safe event feed ----------------------------------------------

    def _handle_create_play_campaign_feed_event(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_play_campaign_member(actor, campaign):
            return

        event_id = body.get("event_id")
        text = body.get("text")
        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid event_id"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return

        sequence = db.create_play_campaign_feed_event(campaign_id, event_id, text)
        if sequence is None:
            self._send_json(409, {"error": "duplicate event_id"})
            return

        self._send_json(201, {
            "event_id": event_id,
            "text": text,
            "sequence": sequence,
        })

    def _handle_get_play_campaign_event_feed(self, campaign_id, query):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_play_campaign_member(actor, campaign):
            return

        cursor_values = query.get("cursor")
        if cursor_values:
            try:
                cursor = int(cursor_values[0])
            except ValueError:
                self._send_json(400, {"error": "invalid cursor"})
                return
            if cursor < 0:
                self._send_json(400, {"error": "invalid cursor"})
                return
        else:
            cursor = 0

        limit_values = query.get("limit")
        if limit_values:
            try:
                limit = int(limit_values[0])
            except ValueError:
                self._send_json(400, {"error": "invalid limit"})
                return
            if limit < 1 or limit > 3:
                self._send_json(400, {"error": "invalid limit"})
                return
        else:
            limit = 2

        events = db.get_play_campaign_feed_events(campaign_id, cursor, limit)
        next_cursor = cursor + len(events)

        self._send_json(200, {"events": events, "next_cursor": next_cursor})

    def _handle_create_play_campaign_replay_event(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_play_campaign_member(actor, campaign):
            return

        event_id = body.get("event_id")
        kind = body.get("kind")
        text = body.get("text")

        if not isinstance(event_id, str) or not event_id:
            self._send_json(400, {"error": "invalid event_id"})
            return
        if not isinstance(text, str) or not text:
            self._send_json(400, {"error": "invalid text"})
            return
        if kind != "append":
            self._send_json(400, {"error": "invalid kind"})
            return

        sequence = db.create_play_campaign_replay_event(campaign_id, event_id, kind, text)
        if sequence is None:
            self._send_json(409, {"error": "duplicate event_id"})
            return

        self._send_json(201, {
            "event_id": event_id,
            "kind": kind,
            "text": text,
            "sequence": sequence,
        })

    def _handle_get_play_campaign_replay(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_play_campaign_member(actor, campaign):
            return

        state = db.get_play_campaign_replay_state(campaign_id)
        self._send_json(200, state)

    def _handle_create_play_campaign_import(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid import"})
            return

        version = body.get("version")
        story = body.get("story")
        status = body.get("status")

        if version != 1:
            self._send_json(400, {"error": "invalid import"})
            return
        if not isinstance(story, str) or not story:
            self._send_json(400, {"error": "invalid import"})
            return
        if status not in ("lobby", "started"):
            self._send_json(400, {"error": "invalid import"})
            return

        result = db.import_play_campaign_snapshot(campaign_id, version, story, status)
        self._send_json(200, result)

    def _handle_get_play_campaign_import_state(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if not self._require_owner(actor, campaign):
            return

        state = db.get_play_campaign_import_state(campaign_id)
        if state is None:
            self._send_json(404, {"error": "not found"})
            return

        self._send_json(200, state)

    def _handle_create_play_campaign_migration(self, campaign_id, body):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] != campaign["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        if not isinstance(body, dict):
            self._send_json(400, {"error": "invalid migration"})
            return

        schema_version = body.get("schema_version")
        story = body.get("story")

        if schema_version != 1:
            self._send_json(400, {"error": "invalid migration"})
            return
        if not isinstance(story, str) or not story:
            self._send_json(400, {"error": "invalid migration"})
            return

        state, created = db.migrate_play_campaign_snapshot(campaign_id, story, campaign["name"])
        self._send_json(201 if created else 200, state)

    def _handle_get_play_campaign_migration_state(self, campaign_id):
        actor = self._get_actor_or_401()
        if actor is None:
            return

        campaign = self._get_play_campaign_or_404(campaign_id)
        if campaign is None:
            return

        if actor["username"] != campaign["owner"]:
            self._send_json(403, {"error": "forbidden"})
            return

        state = db.get_play_campaign_migration_state(campaign_id)
        if state is None:
            self._send_json(404, {"error": "not found"})
            return

        self._send_json(200, state)


def main():
    if os.path.exists(db.DB_PATH):
        os.remove(db.DB_PATH)
    db.init_db()
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.serve_forever()


if __name__ == "__main__":
    main()

<?php
declare(strict_types=1);

// Entry point: wires up the request bootstrap, shared helper libraries, and
// route modules in dependency order, then falls through to a 404 if nothing
// matched. Every required file below is plain top-level code (no
// autoloading, no namespaces) that executes in this same global scope, so
// functions/constants/variables defined in an earlier require are available
// to every later one -- that ordering is what makes the split safe.

require __DIR__ . '/lib/bootstrap.php';           // request line ($method/$path), SCHEMA_VERSION/TURN_TIMEOUT_WINDOW consts, $dbFile
require __DIR__ . '/lib/db.php';                  // SQLite schema init + $db handle (init_schema, get_db)
require __DIR__ . '/lib/http.php';                 // JSON request/response helpers + field validation helpers
require __DIR__ . '/lib/rules.php';                 // ability/dice/XP/threshold tables + combat/initiative helpers
require __DIR__ . '/lib/auth.php';                  // user load/save, password hashing, session actor resolution
require __DIR__ . '/lib/delegations.php';           // gm delegation helpers (has_delegated_power), used by play_campaign narration route

require __DIR__ . '/lib/routes_core.php';           // health, dice & ability checks, encounter XP/initiative, characters, combat sessions, auth, storage admin
require __DIR__ . '/lib/routes_compendium.php';     // monsters and items
require __DIR__ . '/lib/routes_campaigns.php';      // campaign roster/events, NPCs & factions, inventory & equipment
require __DIR__ . '/lib/routes_tools.php';          // PHB rules, DM tools, downtime crafting, session scheduling, audit/export, analytics

require __DIR__ . '/lib/play_campaign.php';         // play campaign lifecycle: create/join/start, narration, turn context, document
require __DIR__ . '/lib/play_scenes_travel.php';    // play scenes, locations/connections, travel turns, rest turns
require __DIR__ . '/lib/play_characters.php';       // play character damage/death-saves/status, ownership, build, level-up, skill checks
require __DIR__ . '/lib/play_combat.php';           // play encounters: combatants/monsters, turn order, actions, conditions, rewards
require __DIR__ . '/lib/play_loot.php';             // campaign-scoped loot: dm-created loot, player votes, dm assignment
require __DIR__ . '/lib/play_npcs.php';             // campaign-scoped npc agendas: dm-managed private agenda, player-visible status
require __DIR__ . '/lib/play_factions.php';         // campaign-scoped factions: dm-created factions, bounded character reputation history
require __DIR__ . '/lib/play_relationships.php';    // campaign-scoped directed relationship graph among characters & npcs
require __DIR__ . '/lib/play_clues.php';            // campaign-scoped dm clues revealed to a character, the party, or nobody
require __DIR__ . '/lib/play_quests.php';           // campaign-scoped quests gated by completed prerequisite quests
require __DIR__ . '/lib/play_world_events.php';     // campaign-scoped world events scheduled by turn and resolved once
require __DIR__ . '/lib/play_calendar.php';         // campaign-scoped calendar the dm initializes/advances with deterministic weather
require __DIR__ . '/lib/play_settlements.php';      // campaign-scoped dm-managed settlements with services, availability, and player discovery
require __DIR__ . '/lib/play_shops.php';            // settlement-scoped dm-managed shops with deterministic stock/prices and player buy/sell
require __DIR__ . '/lib/play_recipes.php';          // campaign-scoped crafting recipes with deterministic ingredient requirements
require __DIR__ . '/lib/play_downtime.php';         // campaign-scoped recurring downtime activities and character allocations
require __DIR__ . '/lib/play_privacy.php';          // campaign-scoped privacy controls: notes, whispers, basic character sheets
require __DIR__ . '/lib/play_invitations.php';      // campaign-scoped dm invitations of registered players, target-only acceptance
require __DIR__ . '/lib/play_delegations.php';      // campaign-scoped gm delegation: grant/revoke narrate power, audit log
require __DIR__ . '/lib/play_audit.php';            // campaign-scoped actor audit trail: member-created audit events, owner-only read
require __DIR__ . '/lib/play_projections.php';      // campaign-scoped projection event log and deterministic rebuilt projection
require __DIR__ . '/lib/play_idempotent_events.php'; // campaign-scoped idempotent event creation keyed by Idempotency-Key
require __DIR__ . '/lib/play_safe_turns.php';       // campaign-scoped concurrent-safe turn submission rejecting stale turns
require __DIR__ . '/lib/play_transactional_transfers.php'; // campaign-scoped transactional currency transfers with all-or-nothing recovery
require __DIR__ . '/lib/play_versioned_exports.php'; // campaign-scoped dm-only immutable versioned story/status exports

require __DIR__ . '/lib/routes_fallback.php';       // 404 for anything not matched above

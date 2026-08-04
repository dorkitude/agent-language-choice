/**
 * Protected campaign-play surface (`/v1/play/*`). Requests authenticate with
 * `Authorization: Bearer session-<username>`; role checks gate DM-only
 * actions. Handlers are grouped by concern across sibling modules:
 *
 *  - shared.ts          row lookups, auth, and turn/combat helpers reused everywhere below
 *  - campaign-turns.ts  campaign lifecycle, whose-turn-is-it, actions/resolutions, document
 *  - scenes.ts          scene create/enter/close
 *  - locations.ts       location graph, travel, rest
 *  - combat.ts           encounter/initiative/turn machinery, monster HP, rewards
 *  - characters.ts      character HP/death, ownership, build, leveling, skill checks
 *
 * This file just re-exports the public handler functions so callers (e.g.
 * api-plugin.ts) have a single stable import path.
 */

export * from './campaign-turns.ts';
export * from './scenes.ts';
export * from './locations.ts';
export * from './combat.ts';
export * from './characters.ts';
export * from './spells.ts';
export * from './inventory.ts';
export * from './currency.ts';
export * from './loot.ts';
export * from './npcs.ts';
export * from './factions.ts';
export * from './relationships.ts';
export * from './clues.ts';
export * from './quests.ts';
export * from './world-events.ts';
export * from './calendar.ts';
export * from './settlements.ts';
export * from './shops.ts';
export * from './recipes.ts';
export * from './downtime.ts';
export * from './session-zero.ts';
export * from './content.ts';
export * from './notes.ts';
export * from './whispers.ts';
export * from './invitations.ts';
export * from './delegations.ts';
export * from './audit-events.ts';
export * from './projections.ts';
export * from './idempotency.ts';
export * from './safe-turns.ts';
export * from './transactional-transfers.ts';
export * from './exports.ts';
export * from './imports.ts';
export * from './migrations.ts';
export * from './search-records.ts';
export * from './rate-events.ts';
export * from './metrics.ts';
export * from './service-mode.ts';
export * from './backups.ts';
export * from './replay.ts';
export * from './rng.ts';
export * from './moderation.ts';
export * from './safety.ts';
export * from './fixtures.ts';
export * from './spectators.ts';
export * from './feed-events.ts';

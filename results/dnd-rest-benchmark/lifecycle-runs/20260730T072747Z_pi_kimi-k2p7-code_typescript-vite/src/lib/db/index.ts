// Barrel export for the SQLite persistence layer. The previous single-file
// db.ts has been split by domain; imports from '../db.js' continue to work
// through the compatibility shim at src/lib/db.ts.

export { db, initializeSchema, isDbInitialized, resetSchema } from './connection.js';
export { SCHEMA_VERSION } from '../constants.js';

export * from './users.js';
export * from './combat.js';
export * from './compendium.js';
export * from './campaigns.js';
export * from './play.js';
export * from './quests.js';
export * from './factions.js';
export * from './npcs.js';
export * from './inventory.js';
export * from './sessions.js';
export * from './crafting.js';

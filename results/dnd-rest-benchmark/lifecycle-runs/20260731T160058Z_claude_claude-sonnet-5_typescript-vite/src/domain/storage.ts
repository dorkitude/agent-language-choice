/**
 * Storage lifecycle: opens the SQLite database and rehydrates the in-memory
 * caches owned by the auth and combat modules, and exposes the status/reset
 * endpoints used by tests to inspect or wipe persisted state.
 */

import { getDb, isInitialized, resetStorage, SCHEMA_VERSION } from '../db.ts';
import type { ApiResult } from '../types.ts';
import { clearUsers, loadUsersFromDb } from './auth.ts';
import { clearCombatSessions, loadCombatSessionsFromDb } from './combat.ts';

export function initStorage(): void {
  getDb();
  loadUsersFromDb();
  loadCombatSessionsFromDb();
}

export function storageStatus(): ApiResult {
  return {
    status: 200,
    body: { driver: 'sqlite', schema_version: SCHEMA_VERSION, initialized: isInitialized() },
  };
}

export function resetStorageHandler(): ApiResult {
  resetStorage();
  clearUsers();
  clearCombatSessions();
  return { status: 200, body: { ok: true, schema_version: SCHEMA_VERSION } };
}
